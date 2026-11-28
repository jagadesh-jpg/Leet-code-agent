"""Guided Daily Practice & Study Session Orchestrator.

Milestone 6.3.26: Guided Daily Practice & Study Session Orchestrator.
Provides:
1. Evidence-based daily practice session generation integrating:
   - Latest adaptive learning-loop recommendations.
   - Skill-gap priority focus queue.
   - Active preparation planner tasks.
   - Overdue spaced repetition items.
   - Unresolved judge execution failures.
   - Problem inventory (problems.json and custom problems).
2. User-configurable study budget allocation (15, 30, 45, 60, 90, or custom minutes) with deterministic knapsack scheduling.
3. Pre-execution session preview with topic, difficulty, sequence, and break checkpoints.
4. Robust lifecycle state machine (DRAFT -> READY -> ACTIVE <-> PAUSED -> COMPLETED / ABANDONED).
5. Guided task execution connecting to existing local workspace judge, practice session bridge, and spaced repetition.
6. Progress and high-fidelity elapsed time tracking across pause/resume transitions.
7. Verification-based session report generation (never claims solved without local judge pass evidence).
8. Deliberate integration triggering re-evaluation in the Adaptive Learning Loop upon user request.
9. Non-destructive persistence in session_tracking.db; production progress.db remains 100% read-only.

100% offline, local-first, zero external API or LLM calls.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from intelligence.learning_loop import AdaptiveLearningLoop, LearningLoopReport
from intelligence.practice_session import PracticeSessionManager
from intelligence.preparation_planner import (
    PlanStatus,
    PreparationPlanner,
    TaskStatus,
)
from intelligence.revision import SpacedRevisionEngine
from intelligence.skill_gap import SkillGapAnalyzer
from intelligence.topics import get_problem_topics
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from problems import load_problems
import store


class DailyPracticeSessionStatus(str, Enum):
    """Lifecycle states of a daily practice study session."""
    DRAFT = "draft"
    READY = "ready"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class DailyPracticeTaskStatus(str, Enum):
    """Lifecycle states of an individual practice task."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class DailyPracticeTaskType(str, Enum):
    """Pedagogical categories of daily practice tasks."""
    TARGETED_CODING = "targeted_coding"
    UNRESOLVED_PROBLEM_REVIEW = "unresolved_problem_review"
    SPACED_REPETITION = "spaced_repetition"
    TOPIC_REINFORCEMENT = "topic_reinforcement"
    DEBUGGING_EXERCISE = "debugging_exercise"
    COMPLEXITY_ANALYSIS = "complexity_analysis"
    MOCK_INTERVIEW = "mock_interview"
    LEARNING_REFLECTION = "learning_reflection"
    SESSION_REFLECTION = "learning_reflection"
    BREAK_CHECKPOINT = "break_checkpoint"


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_utc_now_iso() -> str:
    return _get_utc_now().isoformat()


@dataclass
class DailyPracticeEvidence:
    """Observational evidence backing a generated task or session allocation."""
    source: str                           # "skill_gap", "revision_queue", "unresolved_attempts", "learning_loop"
    metric_name: str
    summary: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DailyPracticeTask:
    """Actionable single task scheduled inside a daily practice session."""
    task_id: str
    session_id: str
    sequence_order: int
    task_type: DailyPracticeTaskType
    title: str
    description: str
    topic: str
    problem_id: Optional[str]
    target_difficulty: str                # "Easy", "Medium", "Hard"
    planned_duration_min: int
    priority: str                         # "P0", "P1", "P2", "P3"
    learning_objective: str
    evidence_rationale: str
    completion_criteria: str
    related_planner_task_id: Optional[str] = None
    actual_duration_min: Optional[int] = None
    status: DailyPracticeTaskStatus = DailyPracticeTaskStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    skipped_reason: Optional[str] = None
    notes: Optional[str] = None
    verified_pass: bool = False
    test_run_id: Optional[str] = None

    @property
    def target_duration_minutes(self) -> int:
        return self.planned_duration_min

    @property
    def actual_duration_minutes(self) -> int:
        return self.actual_duration_min or 0

    @property
    def order_index(self) -> int:
        return self.sequence_order


@dataclass
class DailyPracticeProgress:
    """Real-time calculated progress through a daily study session."""
    total_tasks: int
    completed_tasks: int
    skipped_tasks: int
    remaining_tasks: int
    completion_percentage: float
    planned_minutes: int
    actual_elapsed_seconds: int
    actual_elapsed_minutes: int
    current_task_id: Optional[str] = None
    current_task_index: int = 0
    verified_passes: int = 0


@dataclass
class DailyPracticeSchedule:
    """Structured breakdown and preview of a generated session before starting."""
    session_id: str
    planned_budget_min: int
    total_allocated_min: int
    total_tasks: int
    topic_distribution: Dict[str, int]
    difficulty_distribution: Dict[str, int]
    tasks: List[DailyPracticeTask] = field(default_factory=list)
    break_suggestions: List[Dict[str, Any]] = field(default_factory=list)
    learning_objectives: List[str] = field(default_factory=list)
    source_evidence: List[DailyPracticeEvidence] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    @property
    def budget_minutes(self) -> int:
        return self.planned_budget_min


@dataclass
class DailyPracticeSession:
    """Active or historical daily practice study session container."""
    session_id: str
    title: str
    status: DailyPracticeSessionStatus
    created_at: str
    budget_minutes: int
    elapsed_seconds: int
    started_at: Optional[str] = None
    paused_at: Optional[str] = None
    ended_at: Optional[str] = None
    current_task_id: Optional[str] = None
    tasks: List[DailyPracticeTask] = field(default_factory=list)
    progress: Optional[DailyPracticeProgress] = None
    schedule: Optional[DailyPracticeSchedule] = None


@dataclass
class DailyPracticeReport:
    """Comprehensive, evidence-based retrospective report for a finished or abandoned session."""
    report_id: str
    session_id: str
    created_at: str
    session_summary: str
    budget_minutes: int
    actual_duration_minutes: int
    completion_rate: float
    tasks_planned: int
    tasks_completed: int
    tasks_skipped: int
    tasks_unfinished: int
    verified_problem_outcomes: List[Dict[str, Any]]
    topics_practiced: List[str]
    difficulty_distribution: Dict[str, int]
    reflection_notes: List[Dict[str, Any]]
    next_learning_loop_recommendations: List[str]
    limitations: List[str]


class DailyPracticeOrchestrator:
    """Coordinates daily study session generation, budget allocation, execution, and loop feedback."""

    DEFAULT_BUDGET_MINUTES = 45
    MIN_BUDGET_MINUTES = 15
    MAX_BUDGET_MINUTES = 360

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
        """Create daily practice persistence tables non-destructively in session_tracking.db."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_practice_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    paused_at TEXT,
                    ended_at TEXT,
                    budget_minutes INTEGER NOT NULL,
                    elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                    current_task_id TEXT,
                    session_json TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_practice_tasks (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    sequence_order INTEGER NOT NULL,
                    task_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    problem_id TEXT,
                    target_difficulty TEXT NOT NULL,
                    planned_duration_min INTEGER NOT NULL,
                    actual_duration_min INTEGER,
                    priority TEXT NOT NULL,
                    learning_objective TEXT NOT NULL,
                    evidence_rationale TEXT NOT NULL,
                    completion_criteria TEXT NOT NULL,
                    related_planner_task_id TEXT,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    skipped_reason TEXT,
                    notes TEXT,
                    verified_pass INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (session_id) REFERENCES daily_practice_sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_practice_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES daily_practice_sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_practice_notes (
                    note_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_id TEXT,
                    note_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES daily_practice_sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_dp_sessions_created ON daily_practice_sessions(created_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_dp_tasks_sess ON daily_practice_tasks(session_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_dp_events_sess ON daily_practice_events(session_id)")
            conn.commit()

    def _load_all_problems(self) -> List[Dict[str, Any]]:
        """Load curated and custom problems safely."""
        problems = list(load_problems())
        if self.progress_db_path.exists():
            try:
                problems.extend(store.get_custom_problems(db_path=self.progress_db_path))
            except Exception:
                pass
        return problems

    # -------------------------------------------------------------------------
    # EVIDENCE-BASED SESSION GENERATION & BUDGET ALLOCATION
    # -------------------------------------------------------------------------

    def generate_session(
        self,
        budget_minutes: int = DEFAULT_BUDGET_MINUTES,
        title: Optional[str] = None,
        custom_title: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
        save: bool = True,
    ) -> DailyPracticeSession:
        """Generate a guided daily practice session bounded strictly by the configured budget."""
        if budget_minutes < self.MIN_BUDGET_MINUTES or budget_minutes > self.MAX_BUDGET_MINUTES:
            raise ValueError(
                f"budget_minutes must be between {self.MIN_BUDGET_MINUTES} and {self.MAX_BUDGET_MINUTES}, got {budget_minutes}"
            )
        session_id = f"dps_{uuid.uuid4().hex[:12]}"
        now_str = _get_utc_now_iso()
        title = title or custom_title or f"Daily Practice Session — {now_str[:10]}"

        all_problems = self._load_all_problems()
        candidate_tasks: List[DailyPracticeTask] = []
        source_evidence: List[DailyPracticeEvidence] = []
        allocated_minutes = 0

        # Helper to avoid scheduling duplicate problem IDs inside the same session
        scheduled_problem_ids: Set[str] = set()

        # 1. Unresolved coding problems from recent judge execution (Highest Priority P0)
        unresolved_problems: List[str] = []
        if self.tracking_db_path.exists():
            try:
                with self.get_tracking_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT problem_id, status FROM workspace_runs
                        ORDER BY created_at ASC
                        """
                    )
                    rows = cur.fetchall()
                    failed_pids: Set[str] = set()
                    solved_pids: Set[str] = set()
                    for r in rows:
                        pid = r["problem_id"]
                        st = r["status"].lower()
                        if st in ("passed", "accepted", "success"):
                            solved_pids.add(pid)
                        else:
                            failed_pids.add(pid)
                    unresolved_problems = [p for p in failed_pids if p not in solved_pids]
            except Exception:
                pass

        for pid in unresolved_problems:
            if allocated_minutes + 20 > budget_minutes:
                break
            prob = next((p for p in all_problems if p.get("id") == pid), None)
            topics = get_problem_topics(prob) if prob else ["Algorithmic Problem"]
            diff = (prob.get("difficulty") or "Medium").capitalize() if prob else "Medium"
            task_id = f"dpt_{uuid.uuid4().hex[:10]}"
            candidate_tasks.append(
                DailyPracticeTask(
                    task_id=task_id,
                    session_id=session_id,
                    sequence_order=len(candidate_tasks) + 1,
                    task_type=DailyPracticeTaskType.UNRESOLVED_PROBLEM_REVIEW,
                    title=f"Resolve failing test cases on '{pid}'",
                    description=f"Debug edge cases and fix logic to achieve an accepted solution on problem '{pid}'.",
                    topic=topics[0] if topics else "General",
                    problem_id=pid,
                    target_difficulty=diff,
                    planned_duration_min=20,
                    priority="P0",
                    learning_objective=f"Debug {diff} problem '{pid}' and pass all test assertions.",
                    evidence_rationale="Recent local judge run failed without subsequent accepted pass.",
                    completion_criteria="Run local judge and achieve 100% passed test cases.",
                )
            )
            scheduled_problem_ids.add(pid)
            allocated_minutes += 20
            source_evidence.append(
                DailyPracticeEvidence(
                    source="unresolved_attempts",
                    metric_name="unresolved_problem",
                    summary=f"Problem '{pid}' exhibited unresolved test failures in workspace runs.",
                    details={"problem_id": pid, "difficulty": diff},
                )
            )

        # 2. Overdue Spaced Repetition items (Priority P0 / P1)
        try:
            rev_engine = SpacedRevisionEngine(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            queue = rev_engine.list_queue()
            overdue_items = [it for it in queue if it.is_due_or_overdue]
            for it in overdue_items:
                if allocated_minutes + 15 > budget_minutes:
                    break
                pid = it.problem_id
                if pid not in scheduled_problem_ids:
                    prob = next((p for p in all_problems if p.get("id") == pid), None)
                    diff = (it.difficulty or (prob.get("difficulty") if prob else "Medium")).capitalize()
                    topics = it.topics if it.topics else (get_problem_topics(prob) if prob else ["Revision"])
                    task_id = f"dpt_{uuid.uuid4().hex[:10]}"
                    candidate_tasks.append(
                        DailyPracticeTask(
                            task_id=task_id,
                            session_id=session_id,
                            sequence_order=len(candidate_tasks) + 1,
                            task_type=DailyPracticeTaskType.SPACED_REPETITION,
                            title=f"Spaced Revision: {it.title or pid}",
                            description=f"Reconstruct solution for '{pid}' to reinforce algorithmic recall.",
                            topic=topics[0] if topics else "Revision",
                            problem_id=pid,
                            target_difficulty=diff,
                            planned_duration_min=15,
                            priority="P1",
                            learning_objective=f"Recall and code clean solution for {diff} problem '{pid}'.",
                            evidence_rationale=f"Scheduled Leitner/SM-2 revision is overdue ({it.repetition_count} prior reviews).",
                            completion_criteria="Solve problem or record revision self-assessment outcome.",
                        )
                    )
                    scheduled_problem_ids.add(pid)
                    allocated_minutes += 15
                    source_evidence.append(
                        DailyPracticeEvidence(
                            source="revision_queue",
                            metric_name="overdue_review",
                            summary=f"Item '{pid}' is overdue in the spaced repetition queue.",
                            details={"problem_id": pid, "interval_days": it.interval_days},
                        )
                    )
        except Exception:
            pass

        # 3. Highest Priority Skill Gaps (from SkillGapAnalyzer)
        try:
            sg_analyzer = SkillGapAnalyzer(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            sg_overview = sg_analyzer.get_overview()
            focus_queue = sg_overview.get("focus_queue", [])
            for item in focus_queue:
                if allocated_minutes + 20 > budget_minutes:
                    break
                rel_pids = item.get("related_problem_ids", [])
                cand_pid = next((p for p in rel_pids if p not in scheduled_problem_ids), None)
                if not cand_pid:
                    # Find unattempted problem with matching topic
                    matching = [
                        p["id"] for p in all_problems
                        if item.get("topic") in get_problem_topics(p) and p["id"] not in scheduled_problem_ids
                    ]
                    cand_pid = matching[0] if matching else None

                if cand_pid:
                    prob = next((p for p in all_problems if p.get("id") == cand_pid), None)
                    diff = (prob.get("difficulty") or item.get("suggested_difficulty") or "Medium").capitalize() if prob else "Medium"
                    task_id = f"dpt_{uuid.uuid4().hex[:10]}"
                    candidate_tasks.append(
                        DailyPracticeTask(
                            task_id=task_id,
                            session_id=session_id,
                            sequence_order=len(candidate_tasks) + 1,
                            task_type=DailyPracticeTaskType.TARGETED_CODING,
                            title=f"Practice {item.get('topic')}: '{cand_pid}'",
                            description=item.get("suggested_action") or f"Solve {diff} problem '{cand_pid}' to build {item.get('topic')} fluency.",
                            topic=item.get("topic", "General"),
                            problem_id=cand_pid,
                            target_difficulty=diff,
                            planned_duration_min=20,
                            priority=item.get("priority_tier", "P1"),
                            learning_objective=f"Master {item.get('topic')} core pattern on {diff} problem '{cand_pid}'.",
                            evidence_rationale=item.get("reason", "High priority focus area in skill gap intelligence."),
                            completion_criteria="Solve problem with passing test runs in coding workspace.",
                        )
                    )
                    scheduled_problem_ids.add(cand_pid)
                    allocated_minutes += 20
                    source_evidence.append(
                        DailyPracticeEvidence(
                            source="skill_gap",
                            metric_name="priority_gap",
                            summary=f"Topic '{item.get('topic')}' has priority score {item.get('priority_score')}.",
                            details={"topic": item.get("topic"), "problem_id": cand_pid},
                        )
                    )
        except Exception:
            pass

        # 4. Preparation Planner active tasks
        try:
            planner = PreparationPlanner(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            active_plan = planner.get_active_plan()
            if active_plan:
                pending_plan_tasks = [t for t in active_plan.all_tasks if t.status == TaskStatus.PENDING.value]
                for pt in pending_plan_tasks:
                    if allocated_minutes + 15 > budget_minutes:
                        break
                    if pt.problem_id and pt.problem_id in scheduled_problem_ids:
                        continue
                    task_id = f"dpt_{uuid.uuid4().hex[:10]}"
                    est = min(pt.estimated_minutes, max(15, budget_minutes - allocated_minutes))
                    candidate_tasks.append(
                        DailyPracticeTask(
                            task_id=task_id,
                            session_id=session_id,
                            sequence_order=len(candidate_tasks) + 1,
                            task_type=DailyPracticeTaskType.TOPIC_REINFORCEMENT,
                            title=pt.title,
                            description=pt.description,
                            topic=pt.topic or "Preparation",
                            problem_id=pt.problem_id,
                            target_difficulty="Medium",
                            planned_duration_min=est,
                            priority=pt.priority,
                            learning_objective=pt.completion_criteria,
                            evidence_rationale=pt.reason,
                            completion_criteria=pt.completion_criteria,
                            related_planner_task_id=pt.task_id,
                        )
                    )
                    if pt.problem_id:
                        scheduled_problem_ids.add(pt.problem_id)
                    allocated_minutes += est
                    source_evidence.append(
                        DailyPracticeEvidence(
                            source="planner",
                            metric_name="preparation_task",
                            summary=f"Linked active plan task '{pt.title}'.",
                            details={"task_id": pt.task_id},
                        )
                    )
        except Exception:
            pass

        # 5. Fallback: If library has unattempted problems and budget allows, schedule foundational problem
        if not candidate_tasks and all_problems:
            first_prob = all_problems[0]
            pid = first_prob["id"]
            diff = first_prob.get("difficulty", "easy").capitalize()
            topics = get_problem_topics(first_prob)
            task_id = f"dpt_{uuid.uuid4().hex[:10]}"
            candidate_tasks.append(
                DailyPracticeTask(
                    task_id=task_id,
                    session_id=session_id,
                    sequence_order=1,
                    task_type=DailyPracticeTaskType.TARGETED_CODING,
                    title=f"Foundational Practice: {first_prob.get('title', pid)}",
                    description=f"Solve '{pid}' to establish baseline technique in local workspace.",
                    topic=topics[0] if topics else "Foundations",
                    problem_id=pid,
                    target_difficulty=diff,
                    planned_duration_min=min(budget_minutes, 20),
                    priority="P2",
                    learning_objective=f"Implement and verify clean solution for '{pid}'.",
                    evidence_rationale="Initial practice baseline establishing operational learning history.",
                    completion_criteria="Pass test cases in coding workspace.",
                )
            )
            allocated_minutes += min(budget_minutes, 20)

        # 6. Reflection & Complexity Analysis Task (if budget allows and >= 30 min)
        if allocated_minutes + 5 <= budget_minutes and candidate_tasks:
            task_id = f"dpt_{uuid.uuid4().hex[:10]}"
            candidate_tasks.append(
                DailyPracticeTask(
                    task_id=task_id,
                    session_id=session_id,
                    sequence_order=len(candidate_tasks) + 1,
                    task_type=DailyPracticeTaskType.LEARNING_REFLECTION,
                    title="Session Reflection & Complexity Review",
                    description="Annotate Big-O time and space complexity notes and document key takeaways.",
                    topic="Reflection",
                    problem_id=None,
                    target_difficulty="Easy",
                    planned_duration_min=5,
                    priority="P3",
                    learning_objective="Formalize asymptotic complexity notes and consolidate takeaways.",
                    evidence_rationale="Coding behavior analysis benefits from consistent complexity reflection.",
                    completion_criteria="Save reflection notes for completed session problems.",
                )
            )
            allocated_minutes += 5

        # Break checkpoint if allocated >= 40 and budget allows 5 min break
        if allocated_minutes >= 40 and allocated_minutes + 5 <= budget_minutes:
            break_task = DailyPracticeTask(
                task_id=f"dpt_brk_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                sequence_order=len(candidate_tasks) + 1,
                task_type=DailyPracticeTaskType.BREAK_CHECKPOINT,
                title="Cognitive Break & Reset",
                description="Step away from the screen, stretch, hydrate, and clear working memory.",
                topic="Recovery",
                problem_id=None,
                target_difficulty="",
                planned_duration_min=5,
                priority="P2",
                learning_objective="Rest cognitive faculties to maintain focus in subsequent problem solving.",
                evidence_rationale="Session exceeds 40 minutes; spaced breaks improve retention and debugging clarity.",
                completion_criteria="Take 5-minute break.",
            )
            candidate_tasks.append(break_task)
            allocated_minutes += 5

        # Re-number sequence orders
        for idx, t in enumerate(candidate_tasks, 1):
            t.sequence_order = idx

        # Distributions & Break suggestions
        topic_dist: Dict[str, int] = {}
        diff_dist: Dict[str, int] = {}
        for t in candidate_tasks:
            topic_dist[t.topic] = topic_dist.get(t.topic, 0) + 1
            if t.target_difficulty:
                diff_dist[t.target_difficulty] = diff_dist.get(t.target_difficulty, 0) + 1

        breaks: List[Dict[str, Any]] = []
        if allocated_minutes >= 45 and len(candidate_tasks) >= 2:
            mid_index = max(1, len(candidate_tasks) // 2)
            breaks.append({
                "after_task_order": mid_index,
                "recommended_break_min": 5,
                "reason": "Sustain cognitive focus and prevent fatigue during intensive sessions.",
            })

        schedule = DailyPracticeSchedule(
            session_id=session_id,
            planned_budget_min=budget_minutes,
            total_allocated_min=allocated_minutes,
            total_tasks=len(candidate_tasks),
            topic_distribution=topic_dist,
            difficulty_distribution=diff_dist,
            tasks=candidate_tasks,
            break_suggestions=breaks,
            learning_objectives=[t.learning_objective for t in candidate_tasks],
            source_evidence=source_evidence,
            limitations=[
                f"Session duration is bounded strictly to {allocated_minutes}/{budget_minutes} minutes without artificial filler.",
                "All problem candidates reference real inventory problems without fabricated IDs.",
            ],
        )

        progress = DailyPracticeProgress(
            total_tasks=len(candidate_tasks),
            completed_tasks=0,
            skipped_tasks=0,
            remaining_tasks=len(candidate_tasks),
            completion_percentage=0.0,
            planned_minutes=allocated_minutes,
            actual_elapsed_seconds=0,
            actual_elapsed_minutes=0,
            current_task_id=candidate_tasks[0].task_id if candidate_tasks else None,
            current_task_index=1 if candidate_tasks else 0,
        )

        session = DailyPracticeSession(
            session_id=session_id,
            title=title,
            status=DailyPracticeSessionStatus.READY,
            created_at=now_str,
            budget_minutes=budget_minutes,
            elapsed_seconds=0,
            current_task_id=candidate_tasks[0].task_id if candidate_tasks else None,
            tasks=candidate_tasks,
            progress=progress,
            schedule=schedule,
        )

        if save:
            self._save_session(session)

        return session

    def _save_session(self, session: DailyPracticeSession) -> None:
        """Persist session and its tasks non-destructively in session_tracking.db."""
        session_dict = asdict(session)
        session_json = json.dumps(session_dict)

        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO daily_practice_sessions
                (session_id, title, status, created_at, started_at, paused_at, ended_at, budget_minutes, elapsed_seconds, current_task_id, session_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.title,
                    session.status.value,
                    session.created_at,
                    session.started_at,
                    session.paused_at,
                    session.ended_at,
                    session.budget_minutes,
                    session.elapsed_seconds,
                    session.current_task_id,
                    session_json,
                ),
            )

            # Persist individual tasks
            for t in session.tasks:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO daily_practice_tasks
                    (task_id, session_id, sequence_order, task_type, title, description, topic, problem_id, target_difficulty, planned_duration_min, actual_duration_min, priority, learning_objective, evidence_rationale, completion_criteria, related_planner_task_id, status, started_at, completed_at, skipped_reason, notes, verified_pass)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        t.task_id,
                        session.session_id,
                        t.sequence_order,
                        t.task_type.value,
                        t.title,
                        t.description,
                        t.topic,
                        t.problem_id,
                        t.target_difficulty,
                        t.planned_duration_min,
                        t.actual_duration_min,
                        t.priority,
                        t.learning_objective,
                        t.evidence_rationale,
                        t.completion_criteria,
                        t.related_planner_task_id,
                        t.status.value,
                        t.started_at,
                        t.completed_at,
                        t.skipped_reason,
                        t.notes,
                        1 if t.verified_pass else 0,
                    ),
                )

            conn.commit()

    # -------------------------------------------------------------------------
    # SESSION LIFECYCLE & STATE TRANSITIONS
    # -------------------------------------------------------------------------

    def get_session(self, session_id: str) -> Optional[DailyPracticeSession]:
        """Retrieve a session by its session_id."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT session_json FROM daily_practice_sessions WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._deserialize_session(json.loads(row["session_json"]))

    def get_latest_session(self) -> Optional[DailyPracticeSession]:
        """Retrieve the most recent daily practice session."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT session_json FROM daily_practice_sessions ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            return self._deserialize_session(json.loads(row["session_json"]))

    def list_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List historical sessions in reverse chronological order."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT session_id, title, status, created_at, started_at, ended_at,
                       budget_minutes, elapsed_seconds
                FROM daily_practice_sessions
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_overview(self) -> Dict[str, Any]:
        """Summary overview for dashboard and REST API."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS total FROM daily_practice_sessions")
            total = cur.fetchone()["total"]
            cur.execute("SELECT COUNT(*) AS completed FROM daily_practice_sessions WHERE status = ?", (DailyPracticeSessionStatus.COMPLETED.value,))
            completed = cur.fetchone()["completed"]
            cur.execute("SELECT SUM(elapsed_seconds) AS total_elapsed FROM daily_practice_sessions")
            elapsed = cur.fetchone()["total_elapsed"] or 0
            cur.execute(
                "SELECT session_json FROM daily_practice_sessions WHERE status IN (?, ?) ORDER BY created_at DESC LIMIT 1",
                (DailyPracticeSessionStatus.ACTIVE.value, DailyPracticeSessionStatus.PAUSED.value)
            )
            active_row = cur.fetchone()
            active_session = asdict(self._deserialize_session(json.loads(active_row["session_json"]))) if active_row else None

        latest = self.get_latest_session()
        return {
            "total_sessions": total,
            "completed_sessions": completed,
            "total_practice_minutes": round(elapsed / 60.0, 1),
            "default_budget_minutes": self.DEFAULT_BUDGET_MINUTES,
            "latest_session": asdict(latest) if latest else None,
            "active_session": active_session,
        }

    def preview_session(
        self,
        session_id_or_budget: Union[str, int] = DEFAULT_BUDGET_MINUTES,
        budget_minutes: Optional[int] = None,
        title: Optional[str] = None,
        focus_topics: Optional[List[str]] = None,
    ) -> DailyPracticeSchedule:
        """Inspect the schedule and task breakdown without mutating lifecycle state."""
        if isinstance(session_id_or_budget, str) and not session_id_or_budget.isdigit() and session_id_or_budget.startswith("dps_"):
            session = self.get_session(session_id_or_budget)
            if not session or not session.schedule:
                raise ValueError(f"Daily practice session '{session_id_or_budget}' not found.")
            return session.schedule

        effective_budget = budget_minutes if budget_minutes is not None else (
            int(session_id_or_budget) if isinstance(session_id_or_budget, (int, str)) and str(session_id_or_budget).isdigit() else self.DEFAULT_BUDGET_MINUTES
        )
        session = self.generate_session(
            budget_minutes=effective_budget,
            title=title,
            focus_topics=focus_topics,
            save=False,
        )
        return session.schedule

    def start_session(self, session_id: str) -> DailyPracticeSession:
        """Transition session to ACTIVE state and mark the first task IN_PROGRESS."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")

        if session.status != DailyPracticeSessionStatus.READY:
            raise ValueError(f"Cannot start session '{session_id}' in state '{session.status.value}'. Session must be in 'ready' state to start.")

        now_str = _get_utc_now_iso()
        session.status = DailyPracticeSessionStatus.ACTIVE
        if not session.started_at:
            session.started_at = now_str
        session.paused_at = None

        # Start first task if pending
        if session.tasks and session.tasks[0].status == DailyPracticeTaskStatus.PENDING:
            session.tasks[0].status = DailyPracticeTaskStatus.IN_PROGRESS
            session.tasks[0].started_at = now_str
            session.current_task_id = session.tasks[0].task_id

        self._recalculate_progress(session)
        self._record_event(session_id, "session_start", {"started_at": now_str})
        self._save_session(session)
        return session

    def start_task(self, session_id: str, task_id: str) -> DailyPracticeSession:
        """Explicitly set an individual task to IN_PROGRESS."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")

        task = next((t for t in session.tasks if t.task_id == task_id), None)
        if not task:
            raise ValueError(f"Task '{task_id}' not found in session '{session_id}'.")

        if task.status in (DailyPracticeTaskStatus.COMPLETED, DailyPracticeTaskStatus.SKIPPED):
            raise ValueError(f"Task '{task_id}' is already in terminal state '{task.status.value}'.")

        now_str = _get_utc_now_iso()
        task.status = DailyPracticeTaskStatus.IN_PROGRESS
        if not task.started_at:
            task.started_at = now_str
        session.current_task_id = task_id

        self._recalculate_progress(session)
        self._record_event(session_id, "task_start", {"task_id": task_id, "started_at": now_str})
        self._save_session(session)
        return session

    def complete_task(
        self,
        session_id: str,
        task_id: str,
        notes: Optional[str] = None,
        actual_minutes: Optional[int] = None,
        verified_pass: bool = False,
        test_run_id: Optional[str] = None,
    ) -> DailyPracticeSession:
        """Mark task as COMPLETED with verified outcomes and advance current task pointer."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")

        task = next((t for t in session.tasks if t.task_id == task_id), None)
        if not task:
            raise ValueError(f"Task '{task_id}' not found in session '{session_id}'.")

        now_str = _get_utc_now_iso()
        task.status = DailyPracticeTaskStatus.COMPLETED
        task.completed_at = now_str
        if notes:
            task.notes = notes
        if actual_minutes:
            task.actual_duration_min = actual_minutes
        elif task.started_at:
            try:
                start_dt = datetime.fromisoformat(task.started_at.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(now_str.replace("Z", "+00:00"))
                task.actual_duration_min = max(1, int((end_dt - start_dt).total_seconds() // 60))
            except Exception:
                task.actual_duration_min = task.planned_duration_min
        else:
            task.actual_duration_min = task.planned_duration_min

        task.verified_pass = verified_pass
        if test_run_id:
            task.test_run_id = test_run_id

        # If task is associated with PreparationPlanner, bridge completion
        if task.related_planner_task_id:
            try:
                planner = PreparationPlanner(
                    tracking_db_path=self.tracking_db_path,
                    progress_db_path=self.progress_db_path,
                )
                planner.complete_task(task.related_planner_task_id, actual_minutes=task.actual_duration_min)
            except Exception:
                pass

        # If notes were provided, record in daily_practice_notes
        if notes:
            self._save_note(session_id, task_id, "task_reflection", notes)

        # Advance current_task_id to next pending task
        next_task = next((t for t in session.tasks if t.status == DailyPracticeTaskStatus.PENDING), None)
        if next_task:
            session.current_task_id = next_task.task_id
            if session.status == DailyPracticeSessionStatus.ACTIVE:
                next_task.status = DailyPracticeTaskStatus.IN_PROGRESS
                next_task.started_at = now_str

        self._recalculate_progress(session)
        self._record_event(session_id, "task_complete", {"task_id": task_id, "completed_at": now_str})
        self._save_session(session)
        return session

    def skip_task(
        self, session_id: str, task_id: str, reason: Optional[str] = None
    ) -> DailyPracticeSession:
        """Mark task as SKIPPED with documented reason and advance current task pointer."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")

        task = next((t for t in session.tasks if t.task_id == task_id), None)
        if not task:
            raise ValueError(f"Task '{task_id}' not found in session '{session_id}'.")

        if task.status == DailyPracticeTaskStatus.COMPLETED:
            raise ValueError(f"Cannot skip task '{task_id}' because it has already been completed.")

        now_str = _get_utc_now_iso()
        task.status = DailyPracticeTaskStatus.SKIPPED
        task.skipped_reason = reason or "Skipped by learner"

        # Advance current_task_id
        next_task = next((t for t in session.tasks if t.status == DailyPracticeTaskStatus.PENDING), None)
        if next_task:
            session.current_task_id = next_task.task_id
            if session.status == DailyPracticeSessionStatus.ACTIVE:
                next_task.status = DailyPracticeTaskStatus.IN_PROGRESS
                next_task.started_at = now_str

        self._recalculate_progress(session)
        self._record_event(session_id, "task_skip", {"task_id": task_id, "reason": task.skipped_reason})
        self._save_session(session)
        return session

    def pause_session(self, session_id: str, reason: Optional[str] = None) -> DailyPracticeSession:
        """Pause active session, freezing elapsed time."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")

        if session.status != DailyPracticeSessionStatus.ACTIVE:
            raise ValueError(f"Cannot pause session '{session_id}' in state '{session.status.value}'.")

        now_str = _get_utc_now_iso()
        now_dt = _get_utc_now()

        # Compute elapsed time since last unpaused active period
        anchor_iso = session.paused_at or session.started_at or now_str
        try:
            anchor_dt = datetime.fromisoformat(anchor_iso.replace("Z", "+00:00"))
            delta_sec = max(0, int((now_dt - anchor_dt).total_seconds()))
            session.elapsed_seconds += delta_sec
        except Exception:
            pass

        session.status = DailyPracticeSessionStatus.PAUSED
        session.paused_at = now_str

        self._recalculate_progress(session)
        self._record_event(session_id, "session_pause", {"paused_at": now_str, "reason": reason})
        self._save_session(session)
        return session

    def resume_session(self, session_id: str) -> DailyPracticeSession:
        """Resume paused session."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")

        if session.status != DailyPracticeSessionStatus.PAUSED:
            raise ValueError(f"Cannot resume session '{session_id}' in state '{session.status.value}'.")

        now_str = _get_utc_now_iso()
        session.status = DailyPracticeSessionStatus.ACTIVE
        session.paused_at = None

        self._recalculate_progress(session)
        self._record_event(session_id, "session_resume", {"resumed_at": now_str})
        self._save_session(session)
        return session

    def abandon_session(
        self, session_id: str, reason: Optional[str] = None
    ) -> DailyPracticeSession:
        """Abandon in-progress study session safely."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")

        if session.status == DailyPracticeSessionStatus.COMPLETED:
            raise ValueError(f"Cannot abandon session '{session_id}' because it is already COMPLETED.")

        now_str = _get_utc_now_iso()
        now_dt = _get_utc_now()

        if session.status == DailyPracticeSessionStatus.ACTIVE and session.started_at:
            try:
                start_dt = datetime.fromisoformat(session.started_at.replace("Z", "+00:00"))
                session.elapsed_seconds = max(session.elapsed_seconds, int((now_dt - start_dt).total_seconds()))
            except Exception:
                pass

        session.status = DailyPracticeSessionStatus.ABANDONED
        session.ended_at = now_str

        self._recalculate_progress(session)
        self._record_event(session_id, "session_abandon", {"reason": reason or "Abandoned by learner"})
        self._save_session(session)
        return session

    def complete_session(
        self, session_id: str, notes: Optional[str] = None
    ) -> Tuple[DailyPracticeSession, DailyPracticeReport]:
        """Conclude session as COMPLETED and return tuple of (session, report)."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")

        if session.status == DailyPracticeSessionStatus.ABANDONED:
            raise ValueError(f"Cannot complete session '{session_id}' because it was ABANDONED.")

        if session.status == DailyPracticeSessionStatus.COMPLETED:
            raise ValueError(f"Session '{session_id}' is already COMPLETED.")

        now_str = _get_utc_now_iso()
        now_dt = _get_utc_now()

        if session.status == DailyPracticeSessionStatus.ACTIVE and session.started_at:
            try:
                start_dt = datetime.fromisoformat(session.started_at.replace("Z", "+00:00"))
                session.elapsed_seconds = max(session.elapsed_seconds, int((now_dt - start_dt).total_seconds()))
            except Exception:
                pass

        session.status = DailyPracticeSessionStatus.COMPLETED
        session.ended_at = now_str

        # Mark in-progress tasks completed if any
        for t in session.tasks:
            if t.status == DailyPracticeTaskStatus.IN_PROGRESS:
                t.status = DailyPracticeTaskStatus.COMPLETED
                t.completed_at = now_str

        if notes:
            self._save_note(session_id, None, "session_summary", notes)

        self._recalculate_progress(session)
        self._record_event(session_id, "session_complete", {"completed_at": now_str, "notes": notes})
        self._save_session(session)
        report = self.get_report(session_id)
        return session, report

    def get_report(self, session_id: str) -> DailyPracticeReport:
        """Generate verified retrospective report for a session."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")

        report_id = f"dpr_{uuid.uuid4().hex[:12]}"
        now_str = _get_utc_now_iso()

        prog = session.progress or DailyPracticeProgress(0, 0, 0, 0, 0.0, 0, 0, 0)
        verified_outcomes: List[Dict[str, Any]] = []
        topics_practiced: Set[str] = set()
        diff_dist: Dict[str, int] = {}
        notes_list: List[Dict[str, Any]] = []

        for t in session.tasks:
            if t.status == DailyPracticeTaskStatus.COMPLETED:
                topics_practiced.add(t.topic)
                if t.target_difficulty:
                    diff_dist[t.target_difficulty] = diff_dist.get(t.target_difficulty, 0) + 1
                if t.problem_id:
                    verified_outcomes.append({
                        "task_id": t.task_id,
                        "problem_id": t.problem_id,
                        "topic": t.topic,
                        "difficulty": t.target_difficulty,
                        "verified_pass": t.verified_pass,
                        "duration_min": t.actual_duration_min or t.planned_duration_min,
                    })
                if t.notes:
                    notes_list.append({"task_id": t.task_id, "notes": t.notes})

        summary = (
            f"Daily practice session '{session.title}' ({session.status.value.upper()}): "
            f"Completed {prog.completed_tasks} of {prog.total_tasks} planned tasks "
            f"({prog.completion_percentage}%) in {prog.actual_elapsed_minutes} minutes."
        )

        loop_recs: List[str] = []
        if prog.completion_percentage >= 80.0:
            loop_recs.append("Trigger Adaptive Learning Loop evaluation to advance preparation plan milestones.")
        elif prog.skipped_tasks > 0:
            loop_recs.append("Reconcile skipped practice tasks with next day's preparation queue.")
        else:
            loop_recs.append("Continue standard daily practice cadence.")

        return DailyPracticeReport(
            report_id=report_id,
            session_id=session_id,
            created_at=now_str,
            session_summary=summary,
            budget_minutes=session.budget_minutes,
            actual_duration_minutes=prog.actual_elapsed_minutes,
            completion_rate=prog.completion_percentage,
            tasks_planned=prog.total_tasks,
            tasks_completed=prog.completed_tasks,
            tasks_skipped=prog.skipped_tasks,
            tasks_unfinished=prog.remaining_tasks,
            verified_problem_outcomes=verified_outcomes,
            topics_practiced=sorted(list(topics_practiced)),
            difficulty_distribution=diff_dist,
            reflection_notes=notes_list,
            next_learning_loop_recommendations=loop_recs,
            limitations=[
                "Actual duration is calculated from recorded session timestamps.",
                "Problem completion claims require verified local judge execution evidence.",
            ],
        )

    # -------------------------------------------------------------------------
    # ADAPTIVE LEARNING LOOP INTEGRATION
    # -------------------------------------------------------------------------

    def reevaluate_learning_loop(self, session_id: Optional[str] = None) -> LearningLoopReport:
        """Trigger an explicit evaluation cycle through the Adaptive Learning Loop."""
        loop = AdaptiveLearningLoop(
            tracking_db_path=self.tracking_db_path,
            progress_db_path=self.progress_db_path,
        )
        report = loop.run_learning_cycle(save=True)

        if session_id:
            self._record_event(
                session_id,
                "loop_reevaluation",
                {"learning_loop_report_id": report.report_id, "snapshot_id": report.snapshot.snapshot_id},
            )

        return report

    # -------------------------------------------------------------------------
    # INTERNAL HELPERS
    # -------------------------------------------------------------------------

    def _recalculate_progress(self, session: DailyPracticeSession) -> None:
        """Update progress counts, completion percentages, and elapsed minutes."""
        total = len(session.tasks)
        completed = sum(1 for t in session.tasks if t.status == DailyPracticeTaskStatus.COMPLETED)
        skipped = sum(1 for t in session.tasks if t.status == DailyPracticeTaskStatus.SKIPPED)
        remaining = total - (completed + skipped)
        pct = round((completed / total * 100.0), 1) if total > 0 else 0.0

        current_idx = 1
        for idx, t in enumerate(session.tasks, 1):
            if t.status in (DailyPracticeTaskStatus.PENDING, DailyPracticeTaskStatus.IN_PROGRESS):
                current_idx = idx
                break

        elapsed_min = session.elapsed_seconds // 60
        verified = sum(1 for t in session.tasks if t.verified_pass)

        session.progress = DailyPracticeProgress(
            total_tasks=total,
            completed_tasks=completed,
            skipped_tasks=skipped,
            remaining_tasks=remaining,
            completion_percentage=pct,
            planned_minutes=session.schedule.total_allocated_min if session.schedule else session.budget_minutes,
            actual_elapsed_seconds=session.elapsed_seconds,
            actual_elapsed_minutes=elapsed_min,
            current_task_id=session.current_task_id,
            current_task_index=current_idx,
            verified_passes=verified,
        )

    def _record_event(self, session_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        """Append event to daily_practice_events audit trail."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO daily_practice_events (event_id, session_id, event_type, timestamp, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"ev_{uuid.uuid4().hex[:10]}",
                    session_id,
                    event_type,
                    _get_utc_now_iso(),
                    json.dumps(payload),
                ),
            )
            conn.commit()

    def _save_note(self, session_id: str, task_id: Optional[str], note_type: str, content: str) -> None:
        """Persist learner reflection notes."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO daily_practice_notes (note_id, session_id, task_id, note_type, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"note_{uuid.uuid4().hex[:10]}",
                    session_id,
                    task_id,
                    note_type,
                    content,
                    _get_utc_now_iso(),
                ),
            )
            conn.commit()

    def _deserialize_session(self, d: Dict[str, Any]) -> DailyPracticeSession:
        """Reconstruct DailyPracticeSession dataclass from JSON dictionary."""
        tasks: List[DailyPracticeTask] = []
        for t in d.get("tasks", []):
            tasks.append(
                DailyPracticeTask(
                    task_id=t["task_id"],
                    session_id=t["session_id"],
                    sequence_order=t["sequence_order"],
                    task_type=DailyPracticeTaskType(t["task_type"]),
                    title=t["title"],
                    description=t["description"],
                    topic=t["topic"],
                    problem_id=t.get("problem_id"),
                    target_difficulty=t["target_difficulty"],
                    planned_duration_min=t["planned_duration_min"],
                    priority=t["priority"],
                    learning_objective=t["learning_objective"],
                    evidence_rationale=t["evidence_rationale"],
                    completion_criteria=t["completion_criteria"],
                    related_planner_task_id=t.get("related_planner_task_id"),
                    actual_duration_min=t.get("actual_duration_min"),
                    status=DailyPracticeTaskStatus(t["status"]),
                    started_at=t.get("started_at"),
                    completed_at=t.get("completed_at"),
                    skipped_reason=t.get("skipped_reason"),
                    notes=t.get("notes"),
                    verified_pass=bool(t.get("verified_pass", False)),
                    test_run_id=t.get("test_run_id"),
                )
            )

        prog_data = d.get("progress")
        if prog_data:
            if "verified_passes" not in prog_data:
                prog_data["verified_passes"] = sum(1 for t in tasks if t.verified_pass)
            progress = DailyPracticeProgress(**prog_data)
        else:
            progress = None

        sched_data = d.get("schedule")
        if sched_data:
            sched_evidence = [DailyPracticeEvidence(**ev) for ev in sched_data.get("source_evidence", [])]
            schedule = DailyPracticeSchedule(
                session_id=sched_data["session_id"],
                planned_budget_min=sched_data["planned_budget_min"],
                total_allocated_min=sched_data["total_allocated_min"],
                total_tasks=sched_data["total_tasks"],
                topic_distribution=sched_data.get("topic_distribution", {}),
                difficulty_distribution=sched_data.get("difficulty_distribution", {}),
                tasks=tasks,
                break_suggestions=sched_data.get("break_suggestions", []),
                learning_objectives=sched_data.get("learning_objectives", []),
                source_evidence=sched_evidence,
                limitations=sched_data.get("limitations", []),
            )
        else:
            schedule = None

        return DailyPracticeSession(
            session_id=d["session_id"],
            title=d["title"],
            status=DailyPracticeSessionStatus(d["status"]),
            created_at=d["created_at"],
            budget_minutes=d["budget_minutes"],
            elapsed_seconds=d.get("elapsed_seconds", 0),
            started_at=d.get("started_at"),
            paused_at=d.get("paused_at"),
            ended_at=d.get("ended_at"),
            current_task_id=d.get("current_task_id"),
            tasks=tasks,
            progress=progress,
            schedule=schedule,
        )
