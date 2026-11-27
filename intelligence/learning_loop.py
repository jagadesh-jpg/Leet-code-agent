"""Adaptive Learning Loop Orchestrator & Evidence-Based Plan Reconciliation.

Milestone 6.3.25: Adaptive Learning Loop & Evidence-Based Plan Reconciliation.
Provides:
1. Unified 5-Phase Learning Cycle:
   - Phase 1 (Evidence Collection): Aggregates coding attempts, judge executions, coding behavior profiles,
     skill gaps, preparation plans, practice sessions, spaced repetition queue, and mock interview assessments.
   - Phase 2 (Learning Diagnosis): Diagnoses verified weaknesses, strengths, unpracticed topics, unresolved
     failures, overdue revision backlog, and subsystem recommendation conflicts.
   - Phase 3 (Plan Reconciliation): Reconciles active preparation plans against real-time evidence; generates
     explicit proposed plan modifications (ADD_TASK, REVISE_TASK, ADJUST_DIFFICULTY, REORDER_TASK, REMOVE_OUTDATED_TASK)
     without automatically altering plans.
   - Phase 4 (Practice Actions): Bridges learning actions to the Practice Session Bridge with verified problem IDs
     from inventory, estimated difficulty, and clear pedagogical rationales.
   - Phase 5 (Re-Evaluation & Snapshot Comparison): Compares snapshots across learning cycles to detect resolved gaps,
     progression, regressions, and plan alignment deltas.
2. Explicit Plan-Change Approval:
   - All proposed adjustments remain PENDING until explicitly accepted or rejected by the learner.
   - Prevents duplicate applications and guarantees completed tasks are never deleted or altered.
3. Persistent Snapshots & Reports:
   - Non-destructive SQLite persistence in session_tracking.db (learning_loop_snapshots, learning_loop_reports,
     learning_loop_proposals, learning_loop_events).
   - Production progress.db remains strictly read-only.

100% offline, deterministic, zero external API or LLM calls.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from intelligence.coding_behavior import CodingBehaviorAnalyzer
from intelligence.mock_interview import InterviewManager
from intelligence.practice_session import PracticeSessionManager
from intelligence.preparation_planner import (
    PlanStatus,
    PreparationPlan,
    PreparationPlanner,
    PreparationTask,
    TaskPriority,
    TaskStatus,
    TaskType,
)
from intelligence.revision import SpacedRevisionEngine
from intelligence.skill_gap import SkillGapAnalyzer, SkillGapPriority, SkillGapType
from intelligence.topics import get_problem_topics
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from problems import load_problems
import store


class LearningLoopPhase(str, Enum):
    """Phases of the unified adaptive learning cycle."""
    EVIDENCE_COLLECTION = "evidence_collection"
    DIAGNOSIS = "diagnosis"
    PLAN_RECONCILIATION = "plan_reconciliation"
    PRACTICE_ACTION = "practice_action"
    RE_EVALUATION = "re_evaluation"


class ProposalStatus(str, Enum):
    """Lifecycle state of a proposed plan modification."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    APPLIED = "applied"


class ProposalActionType(str, Enum):
    """Action categories for plan reconciliation proposals."""
    ADD_TASK = "add_task"
    REVISE_TASK = "revise_task"
    REORDER_TASK = "reorder_task"
    ADJUST_DIFFICULTY = "adjust_difficulty"
    REMOVE_OUTDATED_TASK = "remove_outdated_task"


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_utc_now_iso() -> str:
    return _get_utc_now().isoformat()


@dataclass
class LearningLoopEvidence:
    """Atomic evidence summary item from a specific subsystem."""
    source: str
    metric_name: str
    summary: str
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LearningLoopAction:
    """Concrete practice action mapped to an existing problem and practice session bridge."""
    action_id: str
    topic: str
    problem_id: Optional[str]
    difficulty: str                       # "Easy", "Medium", "Hard"
    reason: str
    supporting_evidence: str
    learning_objective: str
    planner_task_id: Optional[str] = None
    priority: str = "P1"                  # "P0", "P1", "P2", "P3"
    confidence: str = "medium"            # "high", "medium", "low", "insufficient_data"


@dataclass
class LearningLoopChangeProposal:
    """Explicit, user-confirmable proposal to adjust an active preparation plan."""
    proposal_id: str
    snapshot_id: str
    action_type: ProposalActionType
    status: ProposalStatus
    plan_id: Optional[str]
    task_id: Optional[str]
    topic: str
    problem_id: Optional[str]
    target_difficulty: str
    title: str
    description: str
    rationale: str
    supporting_evidence: str
    created_at: str
    resolved_at: Optional[str] = None
    resolution_notes: Optional[str] = None


@dataclass
class LearningLoopRecommendation:
    """High-level pedagogical recommendation derived from multi-system diagnosis."""
    recommendation_id: str
    title: str
    category: str
    suggested_action: str
    priority: str
    evidence: str
    is_actionable: bool = True


@dataclass
class LearningLoopSnapshot:
    """Comprehensive point-in-time snapshot of learner state across all intelligence subsystems."""
    snapshot_id: str
    created_at: str
    phase: LearningLoopPhase
    evidence_summary: Dict[str, Any]
    skill_gap_summary: Dict[str, Any]
    planner_summary: Dict[str, Any]
    practice_session_summary: Dict[str, Any]
    revision_summary: Dict[str, Any]
    behavior_summary: Dict[str, Any]
    interview_summary: Dict[str, Any]
    recommendations: List[LearningLoopRecommendation] = field(default_factory=list)
    proposals: List[LearningLoopChangeProposal] = field(default_factory=list)
    actions: List[LearningLoopAction] = field(default_factory=list)
    confidence: str = "medium"
    limitations: List[str] = field(default_factory=list)


@dataclass
class LearningLoopReport:
    """Comprehensive, exportable report synthesizing learning loop cycle results."""
    report_id: str
    created_at: str
    snapshot: LearningLoopSnapshot
    executive_summary: str
    comparison_with_previous: Optional[Dict[str, Any]] = None
    proposals: List[LearningLoopChangeProposal] = field(default_factory=list)
    recommended_next_action: Optional[LearningLoopAction] = None
    limitations: List[str] = field(default_factory=list)


class AdaptiveLearningLoop:
    """Orchestrates multi-subsystem intelligence, evidence reconciliation, and plan evolution."""

    def __init__(
        self,
        tracking_db_path: Optional[str | Path] = None,
        progress_db_path: Optional[str | Path] = None,
    ):
        self.tracking_db_path = Path(tracking_db_path) if tracking_db_path is not None else DEFAULT_TRACKING_DB_PATH
        self.progress_db_path = Path(progress_db_path) if progress_db_path is not None else store.DEFAULT_DB_PATH
        self.init_schema()

    def get_tracking_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.tracking_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_progress_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.progress_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """Create learning loop persistence tables non-destructively in session_tracking.db."""
        with self.get_tracking_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_loop_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_loop_reports (
                    report_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    executive_summary TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    FOREIGN KEY (snapshot_id) REFERENCES learning_loop_snapshots(snapshot_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_loop_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_id TEXT,
                    task_id TEXT,
                    topic TEXT,
                    problem_id TEXT,
                    target_difficulty TEXT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    supporting_evidence TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolution_notes TEXT,
                    FOREIGN KEY (snapshot_id) REFERENCES learning_loop_snapshots(snapshot_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_loop_events (
                    event_id TEXT PRIMARY KEY,
                    snapshot_id TEXT,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    details_json TEXT NOT NULL
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ll_snapshots_created ON learning_loop_snapshots(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ll_proposals_status ON learning_loop_proposals(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ll_proposals_snap ON learning_loop_proposals(snapshot_id)")
            conn.commit()

    # -------------------------------------------------------------------------
    # PHASE 1: EVIDENCE COLLECTION
    # -------------------------------------------------------------------------

    def collect_evidence(self) -> Dict[str, Any]:
        """Aggregate observational evidence safely across all existing intelligence subsystems."""
        evidence: Dict[str, Any] = {
            "skill_gap": {},
            "behavior": {},
            "planner": {},
            "practice_sessions": {},
            "revisions": {},
            "interviews": {},
            "attempts": [],
        }

        # 1. Skill Gaps (from SkillGapAnalyzer)
        try:
            sg_analyzer = SkillGapAnalyzer(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            sg_report = sg_analyzer.get_latest_report()
            if not sg_report:
                sg_report = sg_analyzer.analyze(save=False)
            evidence["skill_gap"] = asdict(sg_report)
        except Exception:
            pass

        # 2. Coding Behavior (from CodingBehaviorAnalyzer)
        try:
            cb_analyzer = CodingBehaviorAnalyzer(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            cb_profile = cb_analyzer.get_latest_profile()
            if not cb_profile:
                cb_rep = cb_analyzer.analyze(save=False)
                cb_profile = cb_rep.profile
            evidence["behavior"] = asdict(cb_profile)
        except Exception:
            pass

        # 3. Preparation Planner Active Plan (from PreparationPlanner)
        try:
            planner = PreparationPlanner(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            active_plan = planner.get_active_plan()
            if active_plan:
                evidence["planner"] = asdict(active_plan)
        except Exception:
            pass

        # 4. Practice Sessions (from PracticeSessionManager)
        try:
            ps_mgr = PracticeSessionManager(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            recent_sessions = ps_mgr.list_sessions(limit=10)
            active_sess = ps_mgr.get_active_session()
            evidence["practice_sessions"] = {
                "recent_sessions": recent_sessions,
                "active_session": asdict(active_sess) if active_sess else None,
            }
        except Exception:
            pass

        # 5. Spaced Repetition (from SpacedRevisionEngine)
        try:
            rev_engine = SpacedRevisionEngine(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            queue = rev_engine.list_queue()
            analytics = rev_engine.get_analytics()
            evidence["revisions"] = {
                "overdue_count": analytics.reviews_overdue,
                "due_today_count": analytics.reviews_due_today,
                "total_tracked": analytics.total_tracked_for_revision,
                "overdue_problems": [item.problem_id for item in queue if item.is_due_or_overdue],
            }
        except Exception:
            pass

        # 6. Mock Interviews (from InterviewManager)
        try:
            int_mgr = InterviewManager(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            history = int_mgr.list_interviews(limit=5)
            evidence["interviews"] = {
                "total_interviews": len(history),
                "history": history,
            }
        except Exception:
            pass

        # 7. Raw Attempts from progress.db (read-only)
        if self.progress_db_path.exists():
            try:
                with self.get_progress_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attempts'")
                    if cur.fetchone():
                        cur.execute("SELECT id, problem_id, status, error, created_at FROM attempts ORDER BY id DESC LIMIT 50")
                        evidence["attempts"] = [dict(r) for r in cur.fetchall()]
            except Exception:
                pass

        return evidence

    # -------------------------------------------------------------------------
    # PHASE 2: LEARNING DIAGNOSIS
    # -------------------------------------------------------------------------

    def diagnose(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """Diagnose learner state, identifying gaps, strengths, conflicts, and blockers."""
        sg_data = evidence.get("skill_gap", {})
        high_gaps = sg_data.get("highest_priority_gaps", [])
        strengths = sg_data.get("demonstrated_strengths", [])
        unpracticed = sg_data.get("insufficient_evidence_topics", [])
        queue = sg_data.get("focus_queue", [])

        # Extract unresolved problem IDs
        unresolved_pids: List[str] = []
        for g in high_gaps:
            ev = g.get("evidence", {})
            unresolved_pids.extend(ev.get("unresolved_problem_ids", []))
        unresolved_pids = sorted(list(set(unresolved_pids)))

        # Revision needs
        rev_data = evidence.get("revisions", {})
        overdue_pids = rev_data.get("overdue_problems", [])

        # Planner tasks state
        planner_data = evidence.get("planner", {})
        all_tasks = planner_data.get("all_tasks", [])
        pending_tasks = [t for t in all_tasks if t.get("status") == TaskStatus.PENDING.value]
        completed_tasks = [t for t in all_tasks if t.get("status") == TaskStatus.COMPLETED.value]

        # Behavior friction points
        behavior_data = evidence.get("behavior", {})
        debugging_patterns = behavior_data.get("debugging_patterns", {})
        session_behavior = behavior_data.get("session_behavior", {})
        dom_error = debugging_patterns.get("dominant_error")
        abandonment_rate = session_behavior.get("abandonment_rate", 0.0)

        # Detect conflicts between planner and skill gaps:
        # e.g. Planner has tasks on a topic with difficulty "Hard", but skill gap analyzer shows failure rate > 60%
        conflicts: List[Dict[str, Any]] = []
        high_gap_topics = {g.get("topic") for g in high_gaps}
        for pt in pending_tasks:
            t_topic = pt.get("topic")
            if t_topic in high_gap_topics:
                gap_obj = next((g for g in high_gaps if g.get("topic") == t_topic), None)
                if gap_obj and gap_obj.get("suggested_difficulty") == "Easy" and pt.get("estimated_minutes", 0) > 40:
                    conflicts.append({
                        "task_id": pt.get("task_id"),
                        "topic": t_topic,
                        "conflict_type": "difficulty_mismatch",
                        "description": f"Planner task '{pt.get('title')}' is intensive, but {t_topic} has active failure evidence suggesting foundational practice.",
                    })

        return {
            "highest_priority_topics": [g.get("topic") for g in high_gaps],
            "strengths_topics": [s.get("topic") for s in strengths],
            "unpracticed_topics": [u.get("topic") for u in unpracticed],
            "unresolved_problem_ids": unresolved_pids,
            "overdue_problem_ids": overdue_pids,
            "pending_tasks_count": len(pending_tasks),
            "completed_tasks_count": len(completed_tasks),
            "dominant_error": dom_error,
            "abandonment_rate": abandonment_rate,
            "conflicts": conflicts,
            "focus_queue": queue,
        }

    # -------------------------------------------------------------------------
    # PHASE 3: PLAN RECONCILIATION
    # -------------------------------------------------------------------------

    def reconcile_plan(
        self, evidence: Dict[str, Any], diagnosis: Dict[str, Any], snapshot_id: str
    ) -> List[LearningLoopChangeProposal]:
        """Compare active plan with diagnosis and generate previewable change proposals.

        Crucially: does NOT modify any database records or plans automatically.
        """
        proposals: List[LearningLoopChangeProposal] = []
        planner_data = evidence.get("planner", {})
        plan_id = planner_data.get("plan_id")
        all_tasks = planner_data.get("all_tasks", [])
        pending_tasks = [t for t in all_tasks if t.get("status") == TaskStatus.PENDING.value]
        pending_topics = {t.get("topic") for t in pending_tasks if t.get("topic")}

        # 1. Check for missing coverage on critical P0/P1 gaps
        high_gaps = diagnosis.get("highest_priority_topics", [])
        focus_queue = diagnosis.get("focus_queue", [])
        for top_topic in high_gaps[:2]:
            if top_topic and top_topic not in pending_topics:
                # Find recommended problem from focus queue
                q_item = next((it for it in focus_queue if it.get("topic") == top_topic), {})
                rel_pids = q_item.get("related_problem_ids", [])
                rec_pid = rel_pids[0] if rel_pids else None
                sugg_diff = q_item.get("suggested_difficulty", "Easy")

                proposals.append(
                    LearningLoopChangeProposal(
                        proposal_id=f"prop_{uuid.uuid4().hex[:10]}",
                        snapshot_id=snapshot_id,
                        action_type=ProposalActionType.ADD_TASK,
                        status=ProposalStatus.PENDING,
                        plan_id=plan_id,
                        task_id=None,
                        topic=top_topic,
                        problem_id=rec_pid,
                        target_difficulty=sugg_diff,
                        title=f"Add targeted practice for {top_topic}",
                        description=f"Add a new preparation task for {top_topic} ({sugg_diff}) to address high-priority skill gap.",
                        rationale=q_item.get("reason", f"High priority skill gap with 0 pending tasks in current plan."),
                        supporting_evidence=f"Skill gap analysis identified {top_topic} as a critical focus area.",
                        created_at=_get_utc_now_iso(),
                    )
                )

        # 2. Check for overdue revision problems not represented in pending tasks
        overdue_pids = diagnosis.get("overdue_problem_ids", [])
        pending_pids = {t.get("problem_id") for t in pending_tasks if t.get("problem_id")}
        for opid in overdue_pids[:2]:
            if opid not in pending_pids:
                proposals.append(
                    LearningLoopChangeProposal(
                        proposal_id=f"prop_{uuid.uuid4().hex[:10]}",
                        snapshot_id=snapshot_id,
                        action_type=ProposalActionType.REVISE_TASK,
                        status=ProposalStatus.PENDING,
                        plan_id=plan_id,
                        task_id=None,
                        topic="Revision",
                        problem_id=opid,
                        target_difficulty="Medium",
                        title=f"Schedule Spaced Revision: {opid}",
                        description=f"Include overdue revision problem '{opid}' into preparation schedule.",
                        rationale=f"Problem '{opid}' is currently overdue in the Spaced Repetition queue.",
                        supporting_evidence="Spaced repetition engine flagged item as overdue.",
                        created_at=_get_utc_now_iso(),
                    )
                )

        # 3. Check for difficulty adjustment conflicts
        for conf in diagnosis.get("conflicts", []):
            task_id = conf.get("task_id")
            topic = conf.get("topic")
            proposals.append(
                LearningLoopChangeProposal(
                    proposal_id=f"prop_{uuid.uuid4().hex[:10]}",
                    snapshot_id=snapshot_id,
                    action_type=ProposalActionType.ADJUST_DIFFICULTY,
                    status=ProposalStatus.PENDING,
                    plan_id=plan_id,
                    task_id=task_id,
                    topic=topic,
                    problem_id=None,
                    target_difficulty="Easy",
                    title=f"Calibrate task difficulty for {topic}",
                    description=f"Adjust task '{task_id}' difficulty from intensive to foundational Easy practice.",
                    rationale=conf.get("description", "Demonstrated weakness requires foundational consolidation before advanced sets."),
                    supporting_evidence="Recent local test runs exhibited high failure frequency.",
                    created_at=_get_utc_now_iso(),
                )
            )

        return proposals

    # -------------------------------------------------------------------------
    # PHASE 4: PRACTICE ACTIONS
    # -------------------------------------------------------------------------

    def derive_practice_actions(
        self,
        evidence: Dict[str, Any],
        diagnosis: Dict[str, Any],
        proposals: List[LearningLoopChangeProposal],
    ) -> List[LearningLoopAction]:
        """Formulate practice actions linked to real problem inventory and practice bridge."""
        actions: List[LearningLoopAction] = []
        all_problems = list(load_problems())
        if self.progress_db_path.exists():
            try:
                all_problems.extend(store.get_custom_problems(db_path=self.progress_db_path))
            except Exception:
                pass

        # 1. Actions from unresolved problems (highest priority)
        unres = diagnosis.get("unresolved_problem_ids", [])
        for pid in unres[:2]:
            prob = next((p for p in all_problems if p.get("id") == pid), None)
            topics = get_problem_topics(prob) if prob else ["Algorithmic Problem"]
            diff = (prob.get("difficulty") or "Medium").capitalize() if prob else "Medium"
            actions.append(
                LearningLoopAction(
                    action_id=f"act_{uuid.uuid4().hex[:8]}",
                    topic=topics[0] if topics else "General",
                    problem_id=pid,
                    difficulty=diff,
                    reason=f"Problem '{pid}' has failed test runs without an accepted resolution.",
                    supporting_evidence="Unresolved failure recorded in local judge executions.",
                    learning_objective="Debug edge cases and implement an accepted passing solution.",
                    priority="P0",
                    confidence="high",
                )
            )

        # 2. Actions from overdue revisions
        overdue = diagnosis.get("overdue_problem_ids", [])
        for pid in overdue[:1]:
            if pid not in [a.problem_id for a in actions]:
                prob = next((p for p in all_problems if p.get("id") == pid), None)
                diff = (prob.get("difficulty") or "Medium").capitalize() if prob else "Medium"
                actions.append(
                    LearningLoopAction(
                        action_id=f"act_{uuid.uuid4().hex[:8]}",
                        topic="Spaced Repetition",
                        problem_id=pid,
                        difficulty=diff,
                        reason=f"Scheduled spaced repetition review for '{pid}' is overdue.",
                        supporting_evidence="Flagged by SpacedRevisionEngine Leitner/SM-2 schedule.",
                        learning_objective="Reconstruct and reinforce solution recall without hints.",
                        priority="P1",
                        confidence="high",
                    )
                )

        # 3. Actions from focus queue if under 3 actions
        focus_queue = diagnosis.get("focus_queue", [])
        for item in focus_queue:
            if len(actions) >= 3:
                break
            rel_pids = item.get("related_problem_ids", [])
            cand_pid = rel_pids[0] if rel_pids else None
            if cand_pid and cand_pid not in [a.problem_id for a in actions]:
                actions.append(
                    LearningLoopAction(
                        action_id=f"act_{uuid.uuid4().hex[:8]}",
                        topic=item.get("topic", "General"),
                        problem_id=cand_pid,
                        difficulty=item.get("suggested_difficulty", "Easy"),
                        reason=item.get("reason", "Top prioritized focus topic."),
                        supporting_evidence=f"Priority score {item.get('priority_score')} in skill gap intelligence.",
                        learning_objective=f"Practice {item.get('topic')} core pattern and establish proficiency.",
                        priority=item.get("priority_tier", "P1"),
                        confidence=item.get("confidence", "medium"),
                    )
                )

        return actions

    # -------------------------------------------------------------------------
    # PHASE 5: RE-EVALUATION & SNAPSHOT COMPARISON
    # -------------------------------------------------------------------------

    def compare_snapshots(
        self, current: LearningLoopSnapshot, previous: Optional[LearningLoopSnapshot]
    ) -> Dict[str, Any]:
        """Compare metrics deterministically across snapshots to detect progression or regressions."""
        if not previous:
            return {
                "has_previous": False,
                "summary": "Initial baseline learning loop snapshot established. Historical progression will track from here.",
                "resolved_gaps": [],
                "remaining_gaps": current.skill_gap_summary.get("highest_priority_topics", []),
                "task_completion_delta": 0,
            }

        curr_gaps = set(current.skill_gap_summary.get("highest_priority_topics", []))
        prev_gaps = set(previous.skill_gap_summary.get("highest_priority_topics", []))

        resolved_gaps = sorted(list(prev_gaps - curr_gaps))
        new_gaps = sorted(list(curr_gaps - prev_gaps))
        remaining_gaps = sorted(list(curr_gaps & prev_gaps))

        curr_completed = current.planner_summary.get("completed_tasks_count", 0)
        prev_completed = previous.planner_summary.get("completed_tasks_count", 0)
        task_delta = curr_completed - prev_completed

        progression_notes = []
        if resolved_gaps:
            progression_notes.append(f"Resolved {len(resolved_gaps)} priority gap(s): {', '.join(resolved_gaps)}")
        if task_delta > 0:
            progression_notes.append(f"Completed {task_delta} additional preparation task(s)")
        if new_gaps:
            progression_notes.append(f"Newly flagged gap(s): {', '.join(new_gaps)}")

        summary = (
            "; ".join(progression_notes)
            if progression_notes
            else "Metrics remain stable across evaluation cycles."
        )

        return {
            "has_previous": True,
            "previous_snapshot_id": previous.snapshot_id,
            "previous_timestamp": previous.created_at,
            "resolved_gaps": resolved_gaps,
            "new_gaps": new_gaps,
            "remaining_gaps": remaining_gaps,
            "task_completion_delta": task_delta,
            "summary": summary,
        }

    # -------------------------------------------------------------------------
    # FULL LOOP ORCHESTRATION & PERSISTENCE
    # -------------------------------------------------------------------------

    def run_learning_cycle(self, save: bool = True) -> LearningLoopReport:
        """Execute the complete 5-phase adaptive learning loop cycle."""
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        created_at = _get_utc_now_iso()

        # Phase 1: Evidence Collection
        evidence = self.collect_evidence()

        # Phase 2: Diagnosis
        diagnosis = self.diagnose(evidence)

        # Phase 3: Plan Reconciliation (Generates PENDING proposals)
        proposals = self.reconcile_plan(evidence, diagnosis, snapshot_id)

        # Phase 4: Practice Actions
        actions = self.derive_practice_actions(evidence, diagnosis, proposals)

        # Recommendations summary
        recommendations: List[LearningLoopRecommendation] = []
        for a in actions:
            recommendations.append(
                LearningLoopRecommendation(
                    recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
                    title=f"Practice {a.topic}: {a.problem_id or 'Problem'}",
                    category=a.topic,
                    suggested_action=a.learning_objective,
                    priority=a.priority,
                    evidence=a.supporting_evidence,
                    is_actionable=True,
                )
            )

        limitations = [
            "All loop diagnostics are derived purely from offline local logs and test outcomes.",
            "Proposed plan modifications are preview-only and strictly require explicit user acceptance.",
            "Historical progress and completed planner tasks are permanently preserved.",
        ]

        # Assemble Snapshot
        snapshot = LearningLoopSnapshot(
            snapshot_id=snapshot_id,
            created_at=created_at,
            phase=LearningLoopPhase.RE_EVALUATION,
            evidence_summary={
                "attempts_count": len(evidence.get("attempts", [])),
                "has_active_plan": bool(evidence.get("planner")),
                "active_plan_id": evidence.get("planner", {}).get("plan_id"),
                "overdue_revisions": len(evidence.get("revisions", {}).get("overdue_problems", [])),
            },
            skill_gap_summary={
                "highest_priority_topics": diagnosis.get("highest_priority_topics", []),
                "strengths_topics": diagnosis.get("strengths_topics", []),
                "unpracticed_topics": diagnosis.get("unpracticed_topics", []),
                "unresolved_problems": diagnosis.get("unresolved_problem_ids", []),
            },
            planner_summary={
                "plan_id": evidence.get("planner", {}).get("plan_id"),
                "pending_tasks_count": diagnosis.get("pending_tasks_count", 0),
                "completed_tasks_count": diagnosis.get("completed_tasks_count", 0),
            },
            practice_session_summary={
                "active_session": bool(evidence.get("practice_sessions", {}).get("active_session")),
            },
            revision_summary=evidence.get("revisions", {}),
            behavior_summary={
                "dominant_error": diagnosis.get("dominant_error"),
                "abandonment_rate": diagnosis.get("abandonment_rate"),
            },
            interview_summary=evidence.get("interviews", {}),
            recommendations=recommendations,
            proposals=proposals,
            actions=actions,
            confidence="high" if len(evidence.get("attempts", [])) >= 10 else "medium",
            limitations=limitations,
        )

        # Phase 5: Re-evaluation & Comparison with previous snapshot
        previous_snapshot = self.get_latest_snapshot()
        comparison = self.compare_snapshots(snapshot, previous_snapshot)

        # Executive summary
        exec_summary = (
            f"Adaptive Learning Loop orchestrated evidence across all intelligence subsystems. "
            f"Identified {len(diagnosis.get('highest_priority_topics', []))} priority focus area(s) "
            f"and generated {len(proposals)} proposed plan adjustment(s). "
            f"Comparison with prior cycle: {comparison.get('summary')}"
        )

        report_id = f"llr_{uuid.uuid4().hex[:12]}"
        report = LearningLoopReport(
            report_id=report_id,
            created_at=created_at,
            snapshot=snapshot,
            executive_summary=exec_summary,
            comparison_with_previous=comparison,
            proposals=proposals,
            recommended_next_action=actions[0] if actions else None,
            limitations=limitations,
        )

        if save:
            self._save_report(report)

        return report

    def _save_report(self, report: LearningLoopReport) -> None:
        """Persist snapshot, report, proposals, and audit events non-destructively in session_tracking.db."""
        snapshot = report.snapshot
        snapshot_json = json.dumps(asdict(snapshot))
        report_json = json.dumps(asdict(report))

        with self.get_tracking_connection() as conn:
            cur = conn.cursor()

            # Insert snapshot
            cur.execute(
                """
                INSERT OR REPLACE INTO learning_loop_snapshots
                (snapshot_id, created_at, phase, confidence, snapshot_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.created_at,
                    snapshot.phase.value,
                    snapshot.confidence,
                    snapshot_json,
                ),
            )

            # Insert report
            cur.execute(
                """
                INSERT OR REPLACE INTO learning_loop_reports
                (report_id, snapshot_id, created_at, executive_summary, report_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    snapshot.snapshot_id,
                    report.created_at,
                    report.executive_summary,
                    report_json,
                ),
            )

            # Insert proposals
            for prop in report.proposals:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO learning_loop_proposals
                    (proposal_id, snapshot_id, action_type, status, plan_id, task_id, topic, problem_id, target_difficulty, title, description, rationale, supporting_evidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prop.proposal_id,
                        snapshot.snapshot_id,
                        prop.action_type.value,
                        prop.status.value,
                        prop.plan_id,
                        prop.task_id,
                        prop.topic,
                        prop.problem_id,
                        prop.target_difficulty,
                        prop.title,
                        prop.description,
                        prop.rationale,
                        prop.supporting_evidence,
                        prop.created_at,
                    ),
                )

            # Insert event
            cur.execute(
                """
                INSERT INTO learning_loop_events
                (event_id, snapshot_id, event_type, timestamp, details_json)
                VALUES (?, ?, 'cycle_run', ?, ?)
                """,
                (
                    f"ev_{uuid.uuid4().hex[:10]}",
                    snapshot.snapshot_id,
                    report.created_at,
                    json.dumps({"proposals_count": len(report.proposals), "actions_count": len(snapshot.actions)}),
                ),
            )

            conn.commit()

    # -------------------------------------------------------------------------
    # PROPOSAL APPROVAL WORKFLOW
    # -------------------------------------------------------------------------

    def get_proposals(
        self, snapshot_id: Optional[str] = None, status: Optional[str] = None, limit: int = 20
    ) -> List[LearningLoopChangeProposal]:
        """Fetch plan reconciliation proposals with optional filters."""
        query = "SELECT * FROM learning_loop_proposals WHERE 1=1"
        params: List[Any] = []
        if snapshot_id:
            query += " AND snapshot_id = ?"
            params.append(snapshot_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
            return [
                LearningLoopChangeProposal(
                    proposal_id=r["proposal_id"],
                    snapshot_id=r["snapshot_id"],
                    action_type=ProposalActionType(r["action_type"]),
                    status=ProposalStatus(r["status"]),
                    plan_id=r["plan_id"],
                    task_id=r["task_id"],
                    topic=r["topic"] or "",
                    problem_id=r["problem_id"],
                    target_difficulty=r["target_difficulty"] or "Medium",
                    title=r["title"],
                    description=r["description"],
                    rationale=r["rationale"],
                    supporting_evidence=r["supporting_evidence"],
                    created_at=r["created_at"],
                    resolved_at=r["resolved_at"],
                    resolution_notes=r["resolution_notes"],
                )
                for r in rows
            ]

    def accept_proposal(
        self, proposal_id: str, apply_to_plan: bool = True
    ) -> LearningLoopChangeProposal:
        """Accept an explicit proposal and optionally apply it non-destructively to the active plan."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM learning_loop_proposals WHERE proposal_id = ?", (proposal_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Proposal '{proposal_id}' not found.")

            current_status = row["status"]
            if current_status in (ProposalStatus.ACCEPTED.value, ProposalStatus.APPLIED.value):
                # Idempotent return without duplicate application
                return self._row_to_proposal(row)

            now_str = _get_utc_now_iso()
            target_status = ProposalStatus.ACCEPTED.value

            # If apply_to_plan is True and plan exists, apply non-destructively
            plan_id = row["plan_id"]
            if apply_to_plan and plan_id:
                try:
                    planner = PreparationPlanner(
                        tracking_db_path=self.tracking_db_path,
                        progress_db_path=self.progress_db_path,
                    )
                    action_type = row["action_type"]

                    if action_type == ProposalActionType.ADD_TASK.value:
                        # Append a new task to the earliest incomplete day
                        new_task_id = f"task_{uuid.uuid4().hex[:10]}"
                        cur.execute(
                            """
                            INSERT INTO preparation_tasks
                            (task_id, plan_id, day_date, session_index, order_index, task_type, title, description, estimated_minutes, priority, reason, evidence, topic, problem_id, completion_criteria, status)
                            VALUES (?, ?, ?, 1, 99, ?, ?, ?, 30, 'P1', ?, ?, ?, ?, 'Solve with local judge', 'pending')
                            """,
                            (
                                new_task_id,
                                plan_id,
                                now_str[:10],
                                TaskType.SOLVE_PROBLEM.value,
                                row["title"],
                                row["description"],
                                row["rationale"],
                                row["supporting_evidence"],
                                row["topic"],
                                row["problem_id"],
                            ),
                        )
                        target_status = ProposalStatus.APPLIED.value

                    elif action_type == ProposalActionType.ADJUST_DIFFICULTY.value and row["task_id"]:
                        # Update task title / description to reflect adjusted difficulty
                        cur.execute(
                            """
                            UPDATE preparation_tasks
                            SET title = title || ' [Calibrated to ' || ? || ']',
                                estimated_minutes = 25
                            WHERE task_id = ? AND status = 'pending'
                            """,
                            (row["target_difficulty"], row["task_id"]),
                        )
                        target_status = ProposalStatus.APPLIED.value

                    elif action_type == ProposalActionType.REVISE_TASK.value and row["problem_id"]:
                        # Add revision task
                        new_task_id = f"task_{uuid.uuid4().hex[:10]}"
                        cur.execute(
                            """
                            INSERT INTO preparation_tasks
                            (task_id, plan_id, day_date, session_index, order_index, task_type, title, description, estimated_minutes, priority, reason, evidence, topic, problem_id, completion_criteria, status)
                            VALUES (?, ?, ?, 1, 98, ?, ?, ?, 20, 'P0', ?, ?, 'Revision', ?, 'Complete spaced revision', 'pending')
                            """,
                            (
                                new_task_id,
                                plan_id,
                                now_str[:10],
                                TaskType.REVISE_PROBLEM.value,
                                row["title"],
                                row["description"],
                                row["rationale"],
                                row["supporting_evidence"],
                                row["problem_id"],
                            ),
                        )
                        target_status = ProposalStatus.APPLIED.value

                except Exception as e:
                    # If plan application encounters issues, proposal is still accepted
                    target_status = ProposalStatus.ACCEPTED.value

            # Update proposal status
            cur.execute(
                """
                UPDATE learning_loop_proposals
                SET status = ?, resolved_at = ?, resolution_notes = ?
                WHERE proposal_id = ?
                """,
                (target_status, now_str, "Explicitly accepted by user", proposal_id),
            )

            # Record event
            cur.execute(
                """
                INSERT INTO learning_loop_events
                (event_id, snapshot_id, event_type, timestamp, details_json)
                VALUES (?, ?, 'proposal_accepted', ?, ?)
                """,
                (
                    f"ev_{uuid.uuid4().hex[:10]}",
                    row["snapshot_id"],
                    now_str,
                    json.dumps({"proposal_id": proposal_id, "new_status": target_status}),
                ),
            )
            conn.commit()

            cur.execute("SELECT * FROM learning_loop_proposals WHERE proposal_id = ?", (proposal_id,))
            updated_row = cur.fetchone()
            return self._row_to_proposal(updated_row)

    def reject_proposal(
        self, proposal_id: str, reason: str = ""
    ) -> LearningLoopChangeProposal:
        """Reject an explicit proposal."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM learning_loop_proposals WHERE proposal_id = ?", (proposal_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Proposal '{proposal_id}' not found.")

            now_str = _get_utc_now_iso()
            notes = reason or "Rejected by user"

            cur.execute(
                """
                UPDATE learning_loop_proposals
                SET status = ?, resolved_at = ?, resolution_notes = ?
                WHERE proposal_id = ?
                """,
                (ProposalStatus.REJECTED.value, now_str, notes, proposal_id),
            )

            cur.execute(
                """
                INSERT INTO learning_loop_events
                (event_id, snapshot_id, event_type, timestamp, details_json)
                VALUES (?, ?, 'proposal_rejected', ?, ?)
                """,
                (
                    f"ev_{uuid.uuid4().hex[:10]}",
                    row["snapshot_id"],
                    now_str,
                    json.dumps({"proposal_id": proposal_id, "reason": notes}),
                ),
            )
            conn.commit()

            cur.execute("SELECT * FROM learning_loop_proposals WHERE proposal_id = ?", (proposal_id,))
            updated_row = cur.fetchone()
            return self._row_to_proposal(updated_row)

    def _row_to_proposal(self, row: sqlite3.Row) -> LearningLoopChangeProposal:
        return LearningLoopChangeProposal(
            proposal_id=row["proposal_id"],
            snapshot_id=row["snapshot_id"],
            action_type=ProposalActionType(row["action_type"]),
            status=ProposalStatus(row["status"]),
            plan_id=row["plan_id"],
            task_id=row["task_id"],
            topic=row["topic"] or "",
            problem_id=row["problem_id"],
            target_difficulty=row["target_difficulty"] or "Medium",
            title=row["title"],
            description=row["description"],
            rationale=row["rationale"],
            supporting_evidence=row["supporting_evidence"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            resolution_notes=row["resolution_notes"],
        )

    # -------------------------------------------------------------------------
    # QUERIES & RETRIEVAL
    # -------------------------------------------------------------------------

    def get_latest_snapshot(self) -> Optional[LearningLoopSnapshot]:
        """Fetch most recent LearningLoopSnapshot."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT snapshot_json FROM learning_loop_snapshots ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            return self._deserialize_snapshot(json.loads(row["snapshot_json"]))

    def get_snapshot(self, snapshot_id: str) -> Optional[LearningLoopSnapshot]:
        """Fetch specific LearningLoopSnapshot by its ID."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT snapshot_json FROM learning_loop_snapshots WHERE snapshot_id = ?", (snapshot_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._deserialize_snapshot(json.loads(row["snapshot_json"]))

    def get_latest_report(self) -> Optional[LearningLoopReport]:
        """Fetch most recent LearningLoopReport."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT report_json FROM learning_loop_reports ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            return self._deserialize_report(json.loads(row["report_json"]))

    def get_report(self, report_id: str) -> Optional[LearningLoopReport]:
        """Fetch specific LearningLoopReport by report ID."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT report_json FROM learning_loop_reports WHERE report_id = ?", (report_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._deserialize_report(json.loads(row["report_json"]))

    def list_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List historical reports and snapshots."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT report_id, snapshot_id, created_at, executive_summary
                FROM learning_loop_reports
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_overview(self) -> Dict[str, Any]:
        """Overview dictionary for interactive dashboard panel."""
        latest_report = self.get_latest_report()
        if not latest_report:
            latest_report = self.run_learning_cycle(save=False)

        snapshot = latest_report.snapshot
        pending_props = self.get_proposals(snapshot_id=snapshot.snapshot_id, status=ProposalStatus.PENDING.value)
        if not pending_props:
            pending_props = [p for p in snapshot.proposals if p.status == ProposalStatus.PENDING]

        return {
            "report_id": latest_report.report_id,
            "snapshot_id": snapshot.snapshot_id,
            "created_at": latest_report.created_at,
            "phase": snapshot.phase.value,
            "confidence": snapshot.confidence,
            "executive_summary": latest_report.executive_summary,
            "comparison": latest_report.comparison_with_previous,
            "pending_proposals": [asdict(p) for p in pending_props],
            "highest_priority_focus": snapshot.skill_gap_summary.get("highest_priority_topics", []),
            "demonstrated_strengths": snapshot.skill_gap_summary.get("strengths_topics", []),
            "next_recommended_action": asdict(latest_report.recommended_next_action) if latest_report.recommended_next_action else None,
            "actions": [asdict(a) for a in snapshot.actions],
            "limitations": latest_report.limitations,
        }

    def _deserialize_snapshot(self, d: Dict[str, Any]) -> LearningLoopSnapshot:
        actions = [LearningLoopAction(**a) for a in d.get("actions", [])]
        recommendations = [LearningLoopRecommendation(**r) for r in d.get("recommendations", [])]
        proposals = [
            LearningLoopChangeProposal(
                proposal_id=p["proposal_id"],
                snapshot_id=p["snapshot_id"],
                action_type=ProposalActionType(p["action_type"]),
                status=ProposalStatus(p["status"]),
                plan_id=p.get("plan_id"),
                task_id=p.get("task_id"),
                topic=p.get("topic", ""),
                problem_id=p.get("problem_id"),
                target_difficulty=p.get("target_difficulty", "Medium"),
                title=p["title"],
                description=p["description"],
                rationale=p["rationale"],
                supporting_evidence=p["supporting_evidence"],
                created_at=p["created_at"],
                resolved_at=p.get("resolved_at"),
                resolution_notes=p.get("resolution_notes"),
            )
            for p in d.get("proposals", [])
        ]

        return LearningLoopSnapshot(
            snapshot_id=d["snapshot_id"],
            created_at=d["created_at"],
            phase=LearningLoopPhase(d["phase"]),
            evidence_summary=d.get("evidence_summary", {}),
            skill_gap_summary=d.get("skill_gap_summary", {}),
            planner_summary=d.get("planner_summary", {}),
            practice_session_summary=d.get("practice_session_summary", {}),
            revision_summary=d.get("revision_summary", {}),
            behavior_summary=d.get("behavior_summary", {}),
            interview_summary=d.get("interview_summary", {}),
            recommendations=recommendations,
            proposals=proposals,
            actions=actions,
            confidence=d.get("confidence", "medium"),
            limitations=d.get("limitations", []),
        )

    def _deserialize_report(self, d: Dict[str, Any]) -> LearningLoopReport:
        snapshot = self._deserialize_snapshot(d["snapshot"])
        proposals = [
            LearningLoopChangeProposal(
                proposal_id=p["proposal_id"],
                snapshot_id=p["snapshot_id"],
                action_type=ProposalActionType(p["action_type"]),
                status=ProposalStatus(p["status"]),
                plan_id=p.get("plan_id"),
                task_id=p.get("task_id"),
                topic=p.get("topic", ""),
                problem_id=p.get("problem_id"),
                target_difficulty=p.get("target_difficulty", "Medium"),
                title=p["title"],
                description=p["description"],
                rationale=p["rationale"],
                supporting_evidence=p["supporting_evidence"],
                created_at=p["created_at"],
                resolved_at=p.get("resolved_at"),
                resolution_notes=p.get("resolution_notes"),
            )
            for p in d.get("proposals", [])
        ]
        next_act = LearningLoopAction(**d["recommended_next_action"]) if d.get("recommended_next_action") else None

        return LearningLoopReport(
            report_id=d["report_id"],
            created_at=d["created_at"],
            snapshot=snapshot,
            executive_summary=d["executive_summary"],
            comparison_with_previous=d.get("comparison_with_previous"),
            proposals=proposals,
            recommended_next_action=next_act,
            limitations=d.get("limitations", []),
        )
