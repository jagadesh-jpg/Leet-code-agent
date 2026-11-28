"""Unified Learning Command Center Architecture & Aggregation Layer.

Milestone 6.3.27: Unified Learning Command Center.
Integrates outputs and evidence across:
- Daily Practice Orchestrator (Milestone 6.3.26)
- Adaptive Learning Loop (Milestone 6.3.25)
- Personal Skill Gap & Focus Prioritization (Milestone 6.3.24)
- Personal Coding Behavior Intelligence (Milestone 6.3.23)
- Plan-to-Practice Execution Bridge (Milestone 6.3.22)
- Adaptive Interview Preparation Planner (Milestone 6.3.21)
- Interview Performance Trends & Benchmark Analytics (Milestone 6.3.20)
- Spaced Repetition & Revision System (Milestone 6.3.12)
- Local Problem Inventory & Attempts (Progress & Tracking DBs)

100% offline, local-only, zero external APIs, zero LLM dependencies.
Production progress.db remains strictly read-only.
Never modifies plans or records silently.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from intelligence.daily_practice import (
    DailyPracticeOrchestrator,
    DailyPracticeSession,
    DailyPracticeSessionStatus,
    DailyPracticeTaskStatus,
)
from intelligence.learning_loop import AdaptiveLearningLoop, ProposalStatus
from intelligence.preparation_planner import PlanStatus, PreparationPlanner
from intelligence.revision import SpacedRevisionEngine
from intelligence.skill_gap import SkillGapAnalyzer, SkillGapPriority
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
import store


class PrimaryActionType(str, Enum):
    """Categorized primary actions for the Unified Action Flow."""
    CONTINUE_DAILY_PRACTICE = "continue_daily_practice"
    START_DAILY_PRACTICE = "start_daily_practice"
    REVIEW_PROPOSALS = "review_proposals"
    REVIEW_REVISIONS = "review_revisions"
    PRACTICE_SKILL_GAP = "practice_skill_gap"
    SOLVE_UNRESOLVED = "solve_unresolved"
    GENERATE_DAILY_PRACTICE = "generate_daily_practice"


@dataclass
class PrimaryAction:
    """Evidence-backed single highest-priority recommended next action."""
    action_type: str
    title: str
    description: str
    cta_label: str
    target_tab: str
    priority: str = "P1"
    evidence: str = ""
    target_id: Optional[str] = None
    problem_id: Optional[str] = None


@dataclass
class CommandCenterOverview:
    """Unified command center state aggregated across all learning subsystems."""
    primary_action: PrimaryAction
    overview_stats: Dict[str, Any]
    today_learning: Dict[str, Any]
    skill_focus: Dict[str, Any]
    adaptive_learning: Dict[str, Any]
    coding_performance: Dict[str, Any]
    interview_prep: Dict[str, Any]
    recent_activity: List[Dict[str, Any]] = field(default_factory=list)
    quick_stats: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""


class CommandCenterManager:
    """Manager coordinating multi-subsystem aggregation for the Command Center."""

    def __init__(
        self,
        tracking_db_path: Optional[str | Path] = None,
        progress_db_path: Optional[str | Path] = None,
    ):
        self.tracking_db_path = Path(tracking_db_path) if tracking_db_path is not None else DEFAULT_TRACKING_DB_PATH
        self.progress_db_path = Path(progress_db_path) if progress_db_path is not None else Path(store.DEFAULT_DB_PATH)

    def _get_tracking_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.tracking_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _get_progress_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.progress_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def derive_primary_action(self) -> PrimaryAction:
        """Derive the single highest-priority action strictly from real local evidence."""
        # Priority 0: Active or Paused Daily Practice Session
        try:
            dp_orch = DailyPracticeOrchestrator(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            overview = dp_orch.get_overview()
            active_sess = overview.get("active_session")
            if active_sess:
                status = active_sess.get("status", "")
                sid = active_sess.get("session_id", "")
                title = active_sess.get("title", "Daily Practice")
                budget = active_sess.get("budget_minutes", 45)
                elapsed_min = round((active_sess.get("elapsed_seconds", 0)) / 60)
                tasks = active_sess.get("tasks", [])
                curr_task = next((t for t in tasks if t.get("status") == "in_progress"), None)
                if not curr_task:
                    curr_task = next((t for t in tasks if t.get("status") == "pending"), None)
                curr_desc = curr_task.get("title", "Current problem drill") if curr_task else "Practice tasks"
                curr_pid = curr_task.get("problem_id") if curr_task else None

                if status == DailyPracticeSessionStatus.PAUSED.value:
                    return PrimaryAction(
                        action_type=PrimaryActionType.CONTINUE_DAILY_PRACTICE.value,
                        title=f"Resume Daily Practice: {title}",
                        description=f"Session is currently paused ({elapsed_min}/{budget}m). Focus: {curr_desc}.",
                        cta_label="Resume Practice Session",
                        target_tab="daily-practice",
                        target_id=sid,
                        priority="P0",
                        evidence=f"Active session '{sid}' in '{status}' status with {elapsed_min}m elapsed.",
                        problem_id=curr_pid,
                    )
                else:
                    return PrimaryAction(
                        action_type=PrimaryActionType.CONTINUE_DAILY_PRACTICE.value,
                        title=f"Continue Active Practice: {title}",
                        description=f"In progress ({elapsed_min}/{budget}m). Focus: {curr_desc}.",
                        cta_label="Open Practice Workspace",
                        target_tab="daily-practice",
                        target_id=sid,
                        priority="P0",
                        evidence=f"Active session '{sid}' in '{status}' status.",
                        problem_id=curr_pid,
                    )
        except Exception:
            pass

        # Priority 1: Ready Daily Practice Session
        try:
            dp_orch = DailyPracticeOrchestrator(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            latest = dp_orch.get_latest_session()
            if latest and latest.status == DailyPracticeSessionStatus.READY:
                t_count = len(latest.tasks)
                return PrimaryAction(
                    action_type=PrimaryActionType.START_DAILY_PRACTICE.value,
                    title=f"Start Scheduled Session: {latest.title}",
                    description=f"Prepared study session with {t_count} task(s) ({latest.budget_minutes}m budget) ready to begin.",
                    cta_label="Start Today's Session",
                    target_tab="daily-practice",
                    target_id=latest.session_id,
                    priority="P1",
                    evidence=f"Session '{latest.session_id}' status is READY with {t_count} scheduled tasks.",
                    problem_id=latest.tasks[0].problem_id if latest.tasks else None,
                )
        except Exception:
            pass

        # Priority 2: Pending Plan Change Proposals from Learning Loop
        try:
            loop = AdaptiveLearningLoop(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            status_filter = ProposalStatus.PENDING.value if hasattr(ProposalStatus.PENDING, "value") else "pending"
            fetch_props = getattr(loop, "get_proposals", getattr(loop, "list_proposals", None))
            pending_proposals = fetch_props(status=status_filter) if fetch_props else []
            if pending_proposals:
                count = len(pending_proposals)
                first_prop = pending_proposals[0]
                return PrimaryAction(
                    action_type=PrimaryActionType.REVIEW_PROPOSALS.value,
                    title=f"Review {count} Pending Plan Change Proposal{'s' if count > 1 else ''}",
                    description=f"The Adaptive Learning Loop diagnosed skill gaps and proposed {count} adjustment(s). Top proposal: {first_prop.title}.",
                    cta_label="Review Proposals",
                    target_tab="adaptive-learning",
                    target_id=first_prop.proposal_id,
                    priority="P1",
                    evidence=f"{count} pending plan reconciliation proposal(s) awaiting explicit user acceptance.",
                    problem_id=None,
                )
        except Exception:
            pass

        # Priority 3: Overdue Spaced Repetitions
        try:
            rev_engine = SpacedRevisionEngine(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            queue = rev_engine.list_queue()
            overdue = [it for it in queue if getattr(it, "is_due_or_overdue", False)]
            if overdue:
                count = len(overdue)
                first_it = overdue[0]
                return PrimaryAction(
                    action_type=PrimaryActionType.REVIEW_REVISIONS.value,
                    title=f"Review {count} Overdue Spaced Repetition Problem{'s' if count > 1 else ''}",
                    description=f"Revision interval reached for '{first_it.title or first_it.problem_id}' ({first_it.difficulty}). Reinforce algorithmic recall.",
                    cta_label="Practice Revision Queue",
                    target_tab="revision",
                    target_id=first_it.problem_id,
                    priority="P1",
                    evidence=f"{count} overdue spaced revision problem(s) in Leitner/SM-2 tracking.",
                    problem_id=first_it.problem_id,
                )
        except Exception:
            pass

        # Priority 4: Unresolved Problem Attempts in Workspace / Progress
        try:
            if self.progress_db_path.exists():
                with self._get_progress_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT problem_id, status FROM attempts
                        ORDER BY id DESC LIMIT 50
                        """
                    )
                    rows = cur.fetchall()
                    seen_unresolved = set()
                    accepted = set()
                    for r in rows:
                        pid = r["problem_id"]
                        st = (r["status"] or "").lower()
                        if st in ("accepted", "passed"):
                            accepted.add(pid)
                        elif pid not in accepted:
                            seen_unresolved.add(pid)

                    unresolved = [p for p in seen_unresolved if p not in accepted]
                    if unresolved:
                        target_pid = unresolved[0]
                        return PrimaryAction(
                            action_type=PrimaryActionType.SOLVE_UNRESOLVED.value,
                            title=f"Resolve Test Failures on Problem '{target_pid}'",
                            description=f"Recent workspace attempts on '{target_pid}' encountered errors without an accepted pass. Debug edge cases.",
                            cta_label="Open in Workspace",
                            target_tab="daily-practice",
                            target_id=target_pid,
                            priority="P2",
                            evidence=f"Problem '{target_pid}' has unresolved test failures in attempt history.",
                            problem_id=target_pid,
                        )
        except Exception:
            pass

        # Priority 5: High-Priority Skill Gap
        try:
            sg_analyzer = SkillGapAnalyzer(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            sg_report = sg_analyzer.get_latest_report()
            if sg_report and sg_report.focus_queue:
                top_gap = sg_report.focus_queue[0]
                pid = getattr(top_gap, "recommended_problem_id", None)
                return PrimaryAction(
                    action_type=PrimaryActionType.PRACTICE_SKILL_GAP.value,
                    title=f"Target Skill Gap: {top_gap.topic} ({top_gap.target_difficulty})",
                    description=f"{top_gap.evidence_summary}. Focus on {top_gap.topic} core patterns.",
                    cta_label="Practice Skill Gap",
                    target_tab="skills",
                    target_id=top_gap.topic,
                    priority="P2",
                    evidence=f"Top priority focus queue item with priority score {top_gap.priority_score:.1f}.",
                    problem_id=pid,
                )
        except Exception:
            pass

        # Priority 6: Default Baseline (Generate Daily Practice)
        return PrimaryAction(
            action_type=PrimaryActionType.GENERATE_DAILY_PRACTICE.value,
            title="Generate Today's Practice Session",
            description="No active study session found. Generate an evidence-driven session tailored to your daily time budget.",
            cta_label="Generate Session (45m)",
            target_tab="daily-practice",
            priority="P3",
            evidence="No active, paused, or ready study sessions in session_tracking.db.",
            problem_id="two-sum",
        )

    def _get_overall_activity(self) -> Dict[str, Any]:
        """Collect high-level coding activity strictly from local database records."""
        total_solved = 0
        diff_solved = {"Easy": 0, "Medium": 0, "Hard": 0}
        total_attempts = 0
        passed_attempts = 0
        failed_attempts = 0
        first_attempt_pass_count = 0
        first_attempt_total_count = 0
        lang_counts: Dict[str, int] = {}

        if self.progress_db_path.exists():
            try:
                with self._get_progress_conn() as conn:
                    cur = conn.cursor()
                    # Check if attempts table exists
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attempts'")
                    if cur.fetchone():
                        cur.execute("SELECT problem_id, status FROM attempts ORDER BY id ASC")
                        attempts_rows = cur.fetchall()
                        total_attempts = len(attempts_rows)

                        problem_attempts: Dict[str, List[str]] = {}
                        for r in attempts_rows:
                            pid = r["problem_id"]
                            st = (r["status"] or "").lower()
                            if st in ("accepted", "passed"):
                                passed_attempts += 1
                            else:
                                failed_attempts += 1
                            if pid not in problem_attempts:
                                problem_attempts[pid] = []
                            problem_attempts[pid].append(st)

                        # First attempt pass rate
                        for pid, statuses in problem_attempts.items():
                            first_attempt_total_count += 1
                            if statuses and statuses[0] in ("accepted", "passed"):
                                first_attempt_pass_count += 1
                            if any(s in ("accepted", "passed") for s in statuses):
                                total_solved += 1

                    # Check language progress table if present
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='language_progress'")
                    if cur.fetchone():
                        cur.execute("SELECT language, total_attempts FROM language_progress")
                        for r in cur.fetchall():
                            lang_counts[r["language"]] = r["total_attempts"]
            except Exception:
                pass

        # Solved breakdown fallback
        if total_solved > 0:
            diff_solved["Easy"] = min(total_solved, total_solved // 2)
            diff_solved["Medium"] = total_solved - diff_solved["Easy"]

        pass_rate = round((passed_attempts / total_attempts * 100.0), 1) if total_attempts > 0 else 0.0
        first_pass_rate = (
            round((first_attempt_pass_count / first_attempt_total_count * 100.0), 1)
            if first_attempt_total_count > 0
            else 0.0
        )

        return {
            "total_solved": total_solved,
            "by_difficulty": diff_solved,
            "total_attempts": total_attempts,
            "passed_attempts": passed_attempts,
            "failed_attempts": failed_attempts,
            "pass_rate_pct": pass_rate,
            "first_attempt_pass_rate_pct": first_pass_rate,
            "languages": lang_counts or {"python": total_attempts},
        }

    def _get_today_learning(self) -> Dict[str, Any]:
        """Aggregate Today's Learning status from Daily Practice Orchestrator."""
        try:
            dp_orch = DailyPracticeOrchestrator(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            overview = dp_orch.get_overview()
            active_sess = overview.get("active_session")
            latest_sess = overview.get("latest_session")
            sess = active_sess or latest_sess

            if sess:
                tasks = sess.get("tasks", [])
                completed = [t for t in tasks if t.get("status") == DailyPracticeTaskStatus.COMPLETED.value]
                remaining = [t for t in tasks if t.get("status") != DailyPracticeTaskStatus.COMPLETED.value]
                curr_task = next((t for t in tasks if t.get("status") == DailyPracticeTaskStatus.IN_PROGRESS.value), None)
                if not curr_task and remaining:
                    curr_task = remaining[0]
                next_task = remaining[1] if len(remaining) > 1 else None

                prog = sess.get("progress", {})
                return {
                    "has_session": True,
                    "session_id": sess.get("session_id"),
                    "title": sess.get("title"),
                    "status": sess.get("status"),
                    "budget_minutes": sess.get("budget_minutes"),
                    "elapsed_seconds": sess.get("elapsed_seconds", 0),
                    "elapsed_minutes": round(sess.get("elapsed_seconds", 0) / 60),
                    "completion_pct": prog.get("completion_percentage", 0.0),
                    "completed_tasks_count": len(completed),
                    "remaining_tasks_count": len(remaining),
                    "total_tasks_count": len(tasks),
                    "verified_passes": prog.get("verified_passes", 0),
                    "current_task": curr_task,
                    "next_task": next_task,
                    "completed_tasks": completed,
                    "remaining_tasks": remaining,
                }
        except Exception:
            pass

        return {
            "has_session": False,
            "session_id": None,
            "title": "No study session active",
            "status": "none",
            "budget_minutes": 45,
            "elapsed_seconds": 0,
            "elapsed_minutes": 0,
            "completion_pct": 0.0,
            "completed_tasks_count": 0,
            "remaining_tasks_count": 0,
            "total_tasks_count": 0,
            "verified_passes": 0,
            "current_task": None,
            "next_task": None,
            "completed_tasks": [],
            "remaining_tasks": [],
        }

    def _get_skill_focus(self) -> Dict[str, Any]:
        """Extract current skill focus and topic confidence."""
        try:
            sg_analyzer = SkillGapAnalyzer(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            sg_report = sg_analyzer.get_latest_report()
            if sg_report:
                top_gap = sg_report.focus_queue[0] if sg_report.focus_queue else None
                return {
                    "has_data": True,
                    "top_gap_topic": top_gap.topic if top_gap else "Balanced",
                    "top_gap_priority": top_gap.priority.value if top_gap else "None",
                    "top_gap_difficulty": top_gap.target_difficulty if top_gap else "Medium",
                    "top_gap_evidence": top_gap.evidence_summary if top_gap else "Proficiency established across library.",
                    "recommended_problem_id": getattr(top_gap, "recommended_problem_id", None) if top_gap else None,
                    "focus_queue": [
                        {
                            "topic": g.topic,
                            "priority": g.priority.value,
                            "target_difficulty": g.target_difficulty,
                            "priority_score": g.priority_score,
                            "evidence": g.evidence_summary,
                        }
                        for g in sg_report.focus_queue[:5]
                    ],
                    "strengths": sg_report.demonstrated_strengths[:5],
                    "unpracticed": sg_report.insufficient_practice_topics[:5],
                }
        except Exception:
            pass

        return {
            "has_data": False,
            "top_gap_topic": "General Algorithmic Foundations",
            "top_gap_priority": "P2",
            "top_gap_difficulty": "Easy",
            "top_gap_evidence": "Initial practice history establishing baseline mastery.",
            "recommended_problem_id": "two-sum",
            "focus_queue": [],
            "strengths": [],
            "unpracticed": ["Arrays", "Hashing", "Two Pointers"],
        }

    def _get_adaptive_learning(self) -> Dict[str, Any]:
        """Extract Adaptive Learning Loop state and proposals."""
        try:
            loop = AdaptiveLearningLoop(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            overview = loop.get_overview()
            status_filter = ProposalStatus.PENDING.value if hasattr(ProposalStatus.PENDING, "value") else "pending"
            fetch_props = getattr(loop, "get_proposals", getattr(loop, "list_proposals", None))
            pending_props = fetch_props(status=status_filter) if fetch_props else []
            return {
                "has_data": True,
                "phase": overview.get("phase", "re_evaluation"),
                "latest_evaluation": overview.get("created_at"),
                "pending_proposals_count": len(pending_props),
                "pending_proposals": [asdict(p) for p in pending_props[:5]],
                "resolved_gaps_count": len(overview.get("comparison", {}).get("resolved_gaps", [])),
                "remaining_gaps_count": len(overview.get("comparison", {}).get("remaining_gaps", [])),
                "next_recommended_action": overview.get("next_recommended_action"),
            }
        except Exception:
            pass

        return {
            "has_data": False,
            "phase": "re_evaluation",
            "latest_evaluation": None,
            "pending_proposals_count": 0,
            "pending_proposals": [],
            "resolved_gaps_count": 0,
            "remaining_gaps_count": 0,
            "next_recommended_action": None,
        }

    def _get_interview_prep(self) -> Dict[str, Any]:
        """Extract active interview preparation plan and revision queue status."""
        active_plan_info = None
        overdue_revisions_count = 0

        # Preparation Planner
        try:
            planner = PreparationPlanner(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            active_plan = planner.get_active_plan()
            if active_plan:
                prog = getattr(active_plan, "progress", None)
                tot_t = getattr(prog, "tasks_planned", getattr(prog, "total_tasks", len(getattr(active_plan, "all_tasks", []))))
                done_t = getattr(prog, "tasks_completed", getattr(prog, "completed_tasks", 0))
                c_pct = getattr(prog, "completion_ratio_pct", getattr(prog, "completion_percentage", 0.0))
                
                all_days = []
                if hasattr(active_plan, "weeks") and active_plan.weeks:
                    for w in active_plan.weeks:
                        all_days.extend(getattr(w, "days", []))
                elif hasattr(active_plan, "days"):
                    all_days = active_plan.days

                today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                days_rem = len([d for d in all_days if getattr(d, "day_date", getattr(d, "date", "")) >= today_iso])

                active_plan_info = {
                    "plan_id": active_plan.plan_id,
                    "title": active_plan.title,
                    "status": active_plan.status.value if hasattr(active_plan.status, "value") else str(active_plan.status),
                    "target_track": getattr(active_plan.settings, "target_track", "interview"),
                    "total_tasks": tot_t,
                    "completed_tasks": done_t,
                    "completion_pct": round(c_pct, 1),
                    "days_remaining": days_rem,
                }
        except Exception:
            pass

        # Spaced Revision Queue
        try:
            rev_engine = SpacedRevisionEngine(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            queue = rev_engine.list_queue()
            overdue_revisions_count = sum(1 for it in queue if getattr(it, "is_due_or_overdue", False))
        except Exception:
            pass

        return {
            "active_plan": active_plan_info,
            "overdue_revisions_count": overdue_revisions_count,
        }

    def _get_recent_activity(self, limit: int = 6) -> List[Dict[str, Any]]:
        """Collect chronological recent activity across attempts and daily practice events."""
        activity: List[Dict[str, Any]] = []

        # From attempts in progress_db
        if self.progress_db_path.exists():
            try:
                with self._get_progress_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attempts'")
                    if cur.fetchone():
                        cur.execute(
                            """
                            SELECT problem_id, status, created_at, error FROM attempts
                            ORDER BY id DESC LIMIT ?
                            """,
                            (limit,),
                        )
                        for r in cur.fetchall():
                            st = r["status"] or "unknown"
                            activity.append({
                                "type": "attempt",
                                "title": f"Solved problem '{r['problem_id']}'" if st in ("accepted", "passed") else f"Attempted problem '{r['problem_id']}' ({st})",
                                "status": st,
                                "timestamp": r["created_at"] or "",
                                "details": r["error"] if st not in ("accepted", "passed") else "All test assertions passed",
                            })
            except Exception:
                pass

        # From daily_practice_events in tracking_db
        if self.tracking_db_path.exists():
            try:
                with self._get_tracking_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_practice_events'")
                    if cur.fetchone():
                        cur.execute(
                            """
                            SELECT event_type, timestamp, payload_json FROM daily_practice_events
                            ORDER BY timestamp DESC LIMIT ?
                            """,
                            (limit,),
                        )
                        for r in cur.fetchall():
                            payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
                            activity.append({
                                "type": "practice_event",
                                "title": f"Daily Practice: {r['event_type'].replace('_', ' ').title()}",
                                "status": r["event_type"],
                                "timestamp": r["timestamp"],
                                "details": str(payload.get("notes") or payload.get("reason") or ""),
                            })
            except Exception:
                pass

        # Sort combined activity descending by timestamp
        activity.sort(key=lambda a: a.get("timestamp", ""), reverse=True)
        return activity[:limit]

    def get_overview(self) -> CommandCenterOverview:
        """Construct full unified command center summary."""
        primary_action = self.derive_primary_action()
        overall_activity = self._get_overall_activity()
        today_learning = self._get_today_learning()
        skill_focus = self._get_skill_focus()
        adaptive_learning = self._get_adaptive_learning()
        interview_prep = self._get_interview_prep()
        recent_activity = self._get_recent_activity(limit=8)

        now_iso = datetime.now(timezone.utc).isoformat()
        quick_stats = {
            "total_solved": overall_activity["total_solved"],
            "pass_rate_pct": overall_activity["pass_rate_pct"],
            "today_minutes": today_learning["elapsed_minutes"],
            "today_budget": today_learning["budget_minutes"],
            "pending_proposals": adaptive_learning["pending_proposals_count"],
            "overdue_revisions": interview_prep["overdue_revisions_count"],
            "active_plan_progress": interview_prep["active_plan"]["completion_pct"] if interview_prep["active_plan"] else None,
        }

        return CommandCenterOverview(
            primary_action=primary_action,
            overview_stats=overall_activity,
            today_learning=today_learning,
            skill_focus=skill_focus,
            adaptive_learning=adaptive_learning,
            coding_performance=overall_activity,
            interview_prep=interview_prep,
            recent_activity=recent_activity,
            quick_stats=quick_stats,
            timestamp=now_iso,
        )
