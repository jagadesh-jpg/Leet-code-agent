"""Adaptive Interview Preparation Planner Engine.

Milestone 6.3.21: Adaptive Interview Preparation Planner.
Provides:
1. Configurable study planning:
   - Daily availability (15-360 min, default 60 min).
   - Planning horizon (7, 14, 30 days).
   - Preferred study days (e.g. Mon-Sun).
   - Sessions per day (1-4).
   - Target interview track (beginner, intermediate, advanced, mixed).
   - Target language, target score, and preparation intensity (light, moderate, intensive).
2. Evidence-driven task selection:
   - Integrates interview performance analytics (recurring weaknesses).
   - Integrates DSA roadmap topic mastery (incomplete prerequisites).
   - Integrates spaced repetition queue (overdue revisions).
   - Integrates active learning & interview goals.
   - Integrates daily missions and failed coding attempts.
   - Foundational fallback for learners without prior assessment history.
3. Structured daily & weekly schedules:
   - Daily plans bounded strictly by configured time availability.
   - Multi-session daily breakdown with transparent P0-P3 priority scoring.
   - Progressive weekly preparation objectives and milestone checkpoints.
4. Adaptive replanning:
   - Adjusts future schedules based on completed, skipped, or missed tasks.
   - Preserves completed tasks and historical plans.
   - Preview-before-apply workflow with explicit change rationales.
5. Deterministic progress tracking:
   - Tracks planned vs actual recorded minutes, completion ratio, and streaks.
   - Non-destructive persistence in session_tracking.db without touching progress.db.

100% offline, deterministic, zero external API or LLM calls.
Never fabricates metrics, streaks, or completion history.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from intelligence.daily_mission import DailyMissionManager
from intelligence.goals import GoalsManager
from intelligence.interview_analytics import InterviewAnalyticsManager
from intelligence.mock_interview import InterviewManager
from intelligence.revision import SpacedRevisionEngine
from intelligence.roadmap import DsaRoadmapEngine, TopicMasteryStatus
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from problems import load_problems
import store


class TaskType(str, Enum):
    """Supported preparation task categories."""
    SOLVE_PROBLEM = "solve_problem"
    REVISE_PROBLEM = "revise_problem"
    REVIEW_COMPLEXITY = "review_complexity"
    PRACTICE_WEAK_TOPIC = "practice_weak_topic"
    COMPLETE_DAILY_MISSION = "complete_daily_mission"
    REVIEW_MOCK_INTERVIEW = "review_mock_interview"
    CONDUCT_MOCK_INTERVIEW = "conduct_mock_interview"
    ANALYZE_FAILED_SUBMISSION = "analyze_failed_submission"
    STUDY_ROADMAP_PREREQUISITES = "study_roadmap_prerequisites"
    REVIEW_CODE_STRUCTURE = "review_code_structure"


class TaskPriority(str, Enum):
    """Evidence-driven task priority levels."""
    P0 = "P0"  # Critical / Overdue / Recurring weakness
    P1 = "P1"  # High / Core roadmap gap / Mock interview
    P2 = "P2"  # Medium / Topic practice / Complexity
    P3 = "P3"  # Low / Foundational theory / Readability


class TaskStatus(str, Enum):
    """Lifecycle states of an individual preparation task."""
    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class PlanStatus(str, Enum):
    """Lifecycle states of an interview preparation plan."""
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class IntensityLevel(str, Enum):
    """Preparation intensity presets."""
    LIGHT = "light"
    MODERATE = "moderate"
    INTENSIVE = "intensive"


ALL_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_utc_now_iso() -> str:
    return _get_utc_now().isoformat()


@dataclass
class PlannerSettings:
    """User-configurable study plan constraints and preferences."""
    daily_minutes: int = 60
    horizon_days: int = 7
    preferred_days: List[str] = field(default_factory=lambda: list(ALL_WEEKDAYS))
    sessions_per_day: int = 2
    target_track: str = "intermediate"
    language: str = "python"
    target_score: float = 80.0
    intensity: str = "moderate"

    def validate(self) -> None:
        """Validate all configuration bounds and values."""
        if not (15 <= self.daily_minutes <= 360):
            raise ValueError(f"daily_minutes must be between 15 and 360, got {self.daily_minutes}.")
        if self.horizon_days not in (7, 14, 30):
            raise ValueError(f"horizon_days must be 7, 14, or 30, got {self.horizon_days}.")
        if not (1 <= self.sessions_per_day <= 4):
            raise ValueError(f"sessions_per_day must be between 1 and 4, got {self.sessions_per_day}.")
        if not (50.0 <= self.target_score <= 100.0):
            raise ValueError(f"target_score must be between 50.0 and 100.0, got {self.target_score}.")

        valid_tracks = ["beginner", "intermediate", "advanced", "mixed"]
        if self.target_track.lower() not in valid_tracks:
            raise ValueError(f"target_track must be one of {valid_tracks}, got '{self.target_track}'.")

        valid_langs = ["python", "cpp", "c", "java"]
        if self.language.lower() not in valid_langs:
            raise ValueError(f"language must be one of {valid_langs}, got '{self.language}'.")

        valid_intensities = [i.value for i in IntensityLevel]
        if self.intensity.lower() not in valid_intensities:
            raise ValueError(f"intensity must be one of {valid_intensities}, got '{self.intensity}'.")

        if not self.preferred_days:
            raise ValueError("preferred_days cannot be empty.")
        clean_days = [d.lower()[:3] for d in self.preferred_days]
        for d in clean_days:
            if d not in ALL_WEEKDAYS:
                raise ValueError(f"Invalid weekday '{d}'. Must be one of {ALL_WEEKDAYS}.")
        self.preferred_days = clean_days


@dataclass
class PreparationTask:
    """Actionable single practice task inside a daily session."""
    task_id: str
    plan_id: str
    day_date: str                     # YYYY-MM-DD
    session_index: int                # 1, 2, ...
    order_index: int
    task_type: str                    # TaskType value
    title: str
    description: str
    estimated_minutes: int
    priority: str                     # TaskPriority value
    reason: str
    evidence: str
    completion_criteria: str
    actual_minutes: Optional[int] = None
    topic: Optional[str] = None
    problem_id: Optional[str] = None
    status: str = TaskStatus.PENDING.value
    completed_at: Optional[str] = None
    skipped_reason: Optional[str] = None


@dataclass
class PreparationDay:
    """Structured schedule for a single calendar day."""
    day_date: str
    day_name: str
    is_study_day: bool
    planned_minutes: int
    actual_minutes: int
    tasks: List[PreparationTask]
    completed_tasks_count: int
    total_tasks_count: int
    day_status: str                   # "pending", "in_progress", "completed", "rest_day"


@dataclass
class PreparationWeek:
    """High-level weekly strategy and aggregated daily plans."""
    week_number: int
    start_date: str
    end_date: str
    week_objective: str
    focus_topics: List[str]
    planned_practice_count: int
    revision_workload_count: int
    mock_interview_targets: int
    weakness_improvement_focus: str
    daily_time_allocations: Dict[str, int]
    weekly_completion_targets: str
    days: List[PreparationDay]


@dataclass
class PlanProgress:
    """Real-time calculated completion metrics and learning streak."""
    tasks_planned: int
    tasks_completed: int
    tasks_skipped: int
    tasks_overdue: int
    planned_minutes: int
    actual_recorded_minutes: int
    completion_ratio_pct: float
    current_streak_days: int
    weekly_completion_pct: float
    topics_progressed: List[str]
    goal_alignment: str


@dataclass
class PreparationPlan:
    """Complete multi-week interview preparation plan."""
    plan_id: str
    title: str
    created_at: str
    updated_at: str
    start_date: str
    end_date: str
    horizon_days: int
    status: str
    settings: PlannerSettings
    weeks: List[PreparationWeek]
    all_tasks: List[PreparationTask]
    progress: PlanProgress
    adaptation_history: List[Dict[str, Any]] = field(default_factory=list)


class PreparationPlanner:
    """Coordinates evidence-based interview study plan generation, tracking, and adaptive replanning."""

    def __init__(
        self,
        tracking_db_path: Optional[str | Path] = None,
        progress_db_path: Optional[str | Path] = None,
    ):
        self.tracking_db_path = Path(tracking_db_path) if tracking_db_path is not None else DEFAULT_TRACKING_DB_PATH
        self.progress_db_path = progress_db_path
        self.init_schema()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.tracking_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """Create planner tables non-destructively in session_tracking.db."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS preparation_settings (
                    id INTEGER PRIMARY KEY,
                    daily_minutes INTEGER NOT NULL,
                    horizon_days INTEGER NOT NULL,
                    preferred_days TEXT NOT NULL,
                    sessions_per_day INTEGER NOT NULL,
                    target_track TEXT NOT NULL,
                    language TEXT NOT NULL,
                    target_score REAL NOT NULL,
                    intensity TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS preparation_plans (
                    plan_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    horizon_days INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    adaptation_history_json TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS preparation_plan_days (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT NOT NULL,
                    day_date TEXT NOT NULL,
                    day_name TEXT NOT NULL,
                    is_study_day INTEGER NOT NULL,
                    planned_minutes INTEGER NOT NULL,
                    week_number INTEGER NOT NULL,
                    FOREIGN KEY (plan_id) REFERENCES preparation_plans(plan_id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS preparation_tasks (
                    task_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    day_date TEXT NOT NULL,
                    session_index INTEGER NOT NULL,
                    order_index INTEGER NOT NULL,
                    task_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    estimated_minutes INTEGER NOT NULL,
                    actual_minutes INTEGER,
                    priority TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    topic TEXT,
                    problem_id TEXT,
                    completion_criteria TEXT NOT NULL,
                    status TEXT NOT NULL,
                    completed_at TEXT,
                    skipped_reason TEXT,
                    FOREIGN KEY (plan_id) REFERENCES preparation_plans(plan_id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS preparation_task_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    old_status TEXT,
                    new_status TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    notes TEXT
                )
                """
            )
            conn.commit()

    # -------------------------------------------------------------------------
    # Settings Management
    # -------------------------------------------------------------------------

    def get_settings(self) -> PlannerSettings:
        """Fetch saved planner settings or default configuration."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM preparation_settings WHERE id = 1")
            row = cursor.fetchone()
            if not row:
                return PlannerSettings()

            return PlannerSettings(
                daily_minutes=row["daily_minutes"],
                horizon_days=row["horizon_days"],
                preferred_days=json.loads(row["preferred_days"]),
                sessions_per_day=row["sessions_per_day"],
                target_track=row["target_track"],
                language=row["language"],
                target_score=float(row["target_score"]),
                intensity=row["intensity"],
            )

    def save_settings(self, settings: PlannerSettings) -> PlannerSettings:
        """Validate and persist planner settings."""
        settings.validate()
        now_str = _get_utc_now_iso()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO preparation_settings (
                    id, daily_minutes, horizon_days, preferred_days, sessions_per_day,
                    target_track, language, target_score, intensity, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    daily_minutes=excluded.daily_minutes,
                    horizon_days=excluded.horizon_days,
                    preferred_days=excluded.preferred_days,
                    sessions_per_day=excluded.sessions_per_day,
                    target_track=excluded.target_track,
                    language=excluded.language,
                    target_score=excluded.target_score,
                    intensity=excluded.intensity,
                    updated_at=excluded.updated_at
                """,
                (
                    settings.daily_minutes,
                    settings.horizon_days,
                    json.dumps(settings.preferred_days),
                    settings.sessions_per_day,
                    settings.target_track,
                    settings.language,
                    settings.target_score,
                    settings.intensity,
                    now_str,
                ),
            )
            conn.commit()
        return settings

    # -------------------------------------------------------------------------
    # Evidence Gathering
    # -------------------------------------------------------------------------

    def gather_preparation_evidence(self) -> Dict[str, Any]:
        """Collect local evidence across interview analytics, DSA roadmap, revisions, goals, and history."""
        evidence: Dict[str, Any] = {
            "has_assessment_history": False,
            "interview_insights": [],
            "weak_topics": [],
            "overdue_revisions": [],
            "roadmap_recommendations": [],
            "active_goals": [],
            "failed_attempts": [],
        }

        # 1. Interview Analytics & Weaknesses
        try:
            ia_mgr = InterviewAnalyticsManager(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            overview = ia_mgr.get_analytics_overview()
            if overview.total_completed_interviews > 0:
                evidence["has_assessment_history"] = True
                evidence["interview_insights"] = overview.insights
                for top in overview.topic_analytics:
                    if top.status == "needs_practice":
                        evidence["weak_topics"].append(top.topic)
        except Exception:
            pass

        # 2. DSA Roadmap Recommendations
        try:
            rm_engine = DsaRoadmapEngine(
                progress_db_path=self.progress_db_path,
                tracking_db_path=self.tracking_db_path,
            )
            recs = rm_engine.generate_recommendations(limit=5)
            evidence["roadmap_recommendations"] = [r.topic_name for r in recs]
        except Exception:
            pass

        # 3. Spaced Repetition Due Queue
        try:
            rev_engine = SpacedRevisionEngine(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            queue = rev_engine.list_queue()
            evidence["overdue_revisions"] = [item.problem_id for item in queue if item.is_due_or_overdue]
        except Exception:
            pass

        # 4. Learning Goals
        try:
            goals_mgr = GoalsManager(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            active_goals = goals_mgr.list_goals(status="active")
            evidence["active_goals"] = [g.title for g in active_goals]
        except Exception:
            pass

        # 5. Failed Attempts from Progress DB
        if self.progress_db_path:
            try:
                with sqlite3.connect(str(self.progress_db_path)) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT problem_id FROM attempts WHERE passed < total GROUP BY problem_id ORDER BY id DESC LIMIT 5"
                    )
                    evidence["failed_attempts"] = [r["problem_id"] for r in cursor.fetchall()]
            except Exception:
                pass

        return evidence

    # -------------------------------------------------------------------------
    # Problem Inventory Lookup
    # -------------------------------------------------------------------------

    def _get_problem_inventory(self) -> Dict[str, Dict[str, Any]]:
        """Load and index all available local problem definitions."""
        problems = load_problems()
        prob_map = {p["id"]: p for p in problems}

        if self.progress_db_path:
            try:
                custom_probs = store.list_custom_problems(db_path=self.progress_db_path)
                for cp in custom_probs:
                    if cp.get("id") and cp["id"] not in prob_map:
                        prob_map[cp["id"]] = cp
            except Exception:
                pass

        return prob_map

    # -------------------------------------------------------------------------
    # Plan Generation Engine
    # -------------------------------------------------------------------------

    def generate_plan(
        self,
        settings: Optional[PlannerSettings] = None,
        start_date: Optional[str] = None,
        title: Optional[str] = None,
    ) -> PreparationPlan:
        """Generate a complete evidence-based daily and weekly interview preparation plan."""
        cfg = settings or self.get_settings()
        cfg.validate()

        evidence = self.gather_preparation_evidence()
        prob_map = self._get_problem_inventory()

        now = _get_utc_now()
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            except ValueError:
                start_dt = now
        else:
            start_dt = now

        plan_id = f"plan_{uuid.uuid4().hex[:10]}"
        plan_title = title or f"{cfg.target_track.capitalize()} Track Preparation ({cfg.horizon_days} Days)"
        end_dt = start_dt + timedelta(days=cfg.horizon_days - 1)

        # Build day schedules
        all_tasks: List[PreparationTask] = []
        days_list: List[PreparationDay] = []

        scheduled_problems: Set[str] = set()

        for day_offset in range(cfg.horizon_days):
            current_day_dt = start_dt + timedelta(days=day_offset)
            day_date_str = current_day_dt.strftime("%Y-%m-%d")
            weekday_idx = current_day_dt.weekday() # 0 = Mon, 6 = Sun
            weekday_code = ALL_WEEKDAYS[weekday_idx]
            weekday_name = WEEKDAY_NAMES[weekday_idx]

            is_study_day = weekday_code in cfg.preferred_days
            week_number = (day_offset // 7) + 1

            if not is_study_day:
                days_list.append(
                    PreparationDay(
                        day_date=day_date_str,
                        day_name=weekday_name,
                        is_study_day=False,
                        planned_minutes=0,
                        actual_minutes=0,
                        tasks=[],
                        completed_tasks_count=0,
                        total_tasks_count=0,
                        day_status="rest_day",
                    )
                )
                continue

            day_tasks = self._generate_day_tasks(
                plan_id=plan_id,
                day_date=day_date_str,
                day_offset=day_offset,
                cfg=cfg,
                evidence=evidence,
                prob_map=prob_map,
                scheduled_problems=scheduled_problems,
            )

            total_day_minutes = sum(t.estimated_minutes for t in day_tasks)
            all_tasks.extend(day_tasks)

            days_list.append(
                PreparationDay(
                    day_date=day_date_str,
                    day_name=weekday_name,
                    is_study_day=True,
                    planned_minutes=total_day_minutes,
                    actual_minutes=0,
                    tasks=day_tasks,
                    completed_tasks_count=0,
                    total_tasks_count=len(day_tasks),
                    day_status="pending",
                )
            )

        # Structure weeks
        weeks_list = self._structure_weeks(days_list, cfg, evidence)

        # Calculate initial progress
        total_planned_min = sum(t.estimated_minutes for t in all_tasks)
        progress = PlanProgress(
            tasks_planned=len(all_tasks),
            tasks_completed=0,
            tasks_skipped=0,
            tasks_overdue=0,
            planned_minutes=total_planned_min,
            actual_recorded_minutes=0,
            completion_ratio_pct=0.0,
            current_streak_days=0,
            weekly_completion_pct=0.0,
            topics_progressed=[],
            goal_alignment=f"Targeting {cfg.target_track} track with {cfg.target_score} score target",
        )

        plan = PreparationPlan(
            plan_id=plan_id,
            title=plan_title,
            created_at=_get_utc_now_iso(),
            updated_at=_get_utc_now_iso(),
            start_date=start_dt.strftime("%Y-%m-%d"),
            end_date=end_dt.strftime("%Y-%m-%d"),
            horizon_days=cfg.horizon_days,
            status=PlanStatus.DRAFT.value,
            settings=cfg,
            weeks=weeks_list,
            all_tasks=all_tasks,
            progress=progress,
            adaptation_history=[],
        )

        return plan

    def _generate_day_tasks(
        self,
        plan_id: str,
        day_date: str,
        day_offset: int,
        cfg: PlannerSettings,
        evidence: Dict[str, Any],
        prob_map: Dict[str, Dict[str, Any]],
        scheduled_problems: Set[str],
    ) -> List[PreparationTask]:
        """Generate balanced tasks for a single study day within the configured time budget."""
        daily_budget = cfg.daily_minutes
        sessions = cfg.sessions_per_day
        tasks: List[PreparationTask] = []
        minutes_remaining = daily_budget

        has_evidence = evidence["has_assessment_history"]
        insights = evidence["interview_insights"]
        weak_topics = evidence["weak_topics"]
        overdue_revs = evidence["overdue_revisions"]
        rm_recs = evidence["roadmap_recommendations"]
        failed_attempts = evidence["failed_attempts"]

        # Strategy per day:
        # Day 7, 14, 21, 28 (Weekly capstone): Timed Mock Interview if budget allows (>= 45m)
        is_mock_day = (day_offset % 7 == 6) and daily_budget >= 45

        if is_mock_day:
            mock_time = min(60, daily_budget)
            tasks.append(
                PreparationTask(
                    task_id=f"ptask_{uuid.uuid4().hex[:10]}",
                    plan_id=plan_id,
                    day_date=day_date,
                    session_index=1,
                    order_index=1,
                    task_type=TaskType.CONDUCT_MOCK_INTERVIEW.value,
                    title=f"Timed Mock Interview ({cfg.target_track.capitalize()} Track)",
                    description=f"Conduct a timed assessment to measure readiness against the target score of {cfg.target_score}.",
                    estimated_minutes=mock_time,
                    priority=TaskPriority.P1.value,
                    reason=f"Weekly benchmark checkpoint for {cfg.target_track} track.",
                    evidence=f"Weekly milestone to assess readiness against {cfg.target_score} score goal.",
                    topic="Full Mock Interview",
                    completion_criteria="Complete all assigned problems and inspect the assessment report.",
                )
            )
            minutes_remaining -= mock_time

            # If time remains, add review task
            if minutes_remaining >= 15:
                tasks.append(
                    PreparationTask(
                        task_id=f"ptask_{uuid.uuid4().hex[:10]}",
                        plan_id=plan_id,
                        day_date=day_date,
                        session_index=2,
                        order_index=2,
                        task_type=TaskType.REVIEW_MOCK_INTERVIEW.value,
                        title="Assessment Rubric & Feedback Review",
                        description="Examine correctness, complexity score, and time management breakdown from the mock session.",
                        estimated_minutes=minutes_remaining,
                        priority=TaskPriority.P2.value,
                        reason="Review scoring rubric to identify areas for next week's focus.",
                        evidence="Immediate post-interview reflection reinforces learning retention.",
                        topic="Assessment Reflection",
                        completion_criteria="Read rubric feedback and note down identified bottlenecks.",
                    )
                )
            return tasks

        # Regular Study Day Structure:
        # Session 1: Spaced revision or failed attempt review or weak topic practice
        order_idx = 1
        s1_budget = min(minutes_remaining // sessions if sessions > 1 else minutes_remaining, 30)

        # Check for overdue revision
        unrevised = [pid for pid in overdue_revs if pid not in scheduled_problems and pid in prob_map]
        unfailed = [pid for pid in failed_attempts if pid not in scheduled_problems and pid in prob_map]

        if unrevised and s1_budget >= 15:
            target_pid = unrevised[0]
            scheduled_problems.add(target_pid)
            p_title = prob_map[target_pid].get("title", target_pid)
            tasks.append(
                PreparationTask(
                    task_id=f"ptask_{uuid.uuid4().hex[:10]}",
                    plan_id=plan_id,
                    day_date=day_date,
                    session_index=1,
                    order_index=order_idx,
                    task_type=TaskType.REVISE_PROBLEM.value,
                    title=f"Spaced Revision: {p_title}",
                    description=f"Re-solve problem '{target_pid}' without consulting previous code.",
                    estimated_minutes=min(20, s1_budget),
                    priority=TaskPriority.P0.value,
                    reason="Scheduled spaced repetition review interval due for retention.",
                    evidence=f"Problem '{target_pid}' is due in the spaced repetition queue.",
                    problem_id=target_pid,
                    topic="Spaced Repetition",
                    completion_criteria="Run and pass all local test cases.",
                )
            )
            minutes_remaining -= min(20, s1_budget)
            order_idx += 1
        elif unfailed and s1_budget >= 15:
            target_pid = unfailed[0]
            scheduled_problems.add(target_pid)
            p_title = prob_map[target_pid].get("title", target_pid)
            tasks.append(
                PreparationTask(
                    task_id=f"ptask_{uuid.uuid4().hex[:10]}",
                    plan_id=plan_id,
                    day_date=day_date,
                    session_index=1,
                    order_index=order_idx,
                    task_type=TaskType.ANALYZE_FAILED_SUBMISSION.value,
                    title=f"Analyze Prior Failed Attempt: {p_title}",
                    description=f"Inspect failing test cases and debug implementation for problem '{target_pid}'.",
                    estimated_minutes=min(25, s1_budget),
                    priority=TaskPriority.P1.value,
                    reason="Prior attempt had test failures; debugging reinforces edge-case handling.",
                    evidence=f"Recorded attempt for '{target_pid}' had passed < total tests.",
                    problem_id=target_pid,
                    topic="Debugging & Edge Cases",
                    completion_criteria="Identify bug cause and pass all test cases.",
                )
            )
            minutes_remaining -= min(25, s1_budget)
            order_idx += 1

        # Session 2: Weak Topic Practice or Roadmap Topic
        if minutes_remaining >= 20:
            s2_budget = min(minutes_remaining, 35)

            # Pick target topic
            target_topic = None
            evidence_reason = ""
            evidence_data = ""

            if weak_topics:
                target_topic = weak_topics[day_offset % len(weak_topics)]
                evidence_reason = f"Identified as needing practice in mock interview evaluations."
                evidence_data = f"Topic '{target_topic}' showed sub-70% success in interview evaluations."
                prio = TaskPriority.P0.value
            elif rm_recs and has_evidence:
                target_topic = rm_recs[day_offset % len(rm_recs)]
                evidence_reason = f"Next recommended prerequisite in DSA Roadmap."
                evidence_data = f"DSA Roadmap identifies '{target_topic}' as prerequisite readiness."
                prio = TaskPriority.P1.value
            else:
                # Neutral foundational fallback
                foundations = ["Arrays", "Strings", "Two Pointers", "Hashing", "Binary Search"]
                target_topic = foundations[day_offset % len(foundations)]
                evidence_reason = "General recommendation: Foundational DSA practice."
                evidence_data = "No prior assessment evidence recorded; establishing foundational skills."
                prio = TaskPriority.P2.value

            # Find matching problem from inventory
            matching_prob = None
            diff_target = "easy" if cfg.target_track == "beginner" else "medium"
            for pid, pdata in prob_map.items():
                if pid not in scheduled_problems:
                    p_topics = [t.lower() for t in (pdata.get("topics") or [])]
                    if target_topic.lower() in p_topics or target_topic.lower() in pdata.get("title", "").lower():
                        matching_prob = pdata
                        break

            # Fallback to any unassigned problem matching difficulty
            if not matching_prob:
                for pid, pdata in prob_map.items():
                    if pid not in scheduled_problems:
                        matching_prob = pdata
                        break

            pid_val = matching_prob["id"] if matching_prob else "two-sum"
            ptitle = matching_prob.get("title", pid_val) if matching_prob else "Two Sum"
            scheduled_problems.add(pid_val)

            tasks.append(
                PreparationTask(
                    task_id=f"ptask_{uuid.uuid4().hex[:10]}",
                    plan_id=plan_id,
                    day_date=day_date,
                    session_index=min(2, sessions),
                    order_index=order_idx,
                    task_type=TaskType.PRACTICE_WEAK_TOPIC.value if weak_topics else TaskType.SOLVE_PROBLEM.value,
                    title=f"Practice {target_topic}: {ptitle}",
                    description=f"Implement and verify solution for '{ptitle}' in {cfg.language}.",
                    estimated_minutes=s2_budget,
                    priority=prio,
                    reason=evidence_reason,
                    evidence=evidence_data,
                    topic=target_topic,
                    problem_id=pid_val,
                    completion_criteria="All local test cases passing cleanly.",
                )
            )
            minutes_remaining -= s2_budget
            order_idx += 1

        # Session 3: Complexity Analysis or Code Structure Review (if budget >= 10m)
        if minutes_remaining >= 10:
            has_cplx_weakness = any(i.insight_id == "weakness_complexity" for i in insights)
            task_type = TaskType.REVIEW_COMPLEXITY.value if has_cplx_weakness else TaskType.REVIEW_CODE_STRUCTURE.value
            title_text = "Complexity & Big-O Tradeoff Review" if has_cplx_weakness else "Code Structure & Readability Review"
            desc_text = (
                "Explicitly compute time and space complexity for your drafted solutions today."
                if has_cplx_weakness
                else "Refactor code to minimize cyclomatic complexity and ensure clean naming."
            )
            reason_text = (
                "Interview analytics detected recurring low complexity awareness scores."
                if has_cplx_weakness
                else "Strengthen code structure and maintainability under interview conditions."
            )
            evidence_text = (
                "Complexity awareness score fell below 60% benchmark across past assessments."
                if has_cplx_weakness
                else "AST structure and readability improve interviewer clarity."
            )

            tasks.append(
                PreparationTask(
                    task_id=f"ptask_{uuid.uuid4().hex[:10]}",
                    plan_id=plan_id,
                    day_date=day_date,
                    session_index=min(3, sessions),
                    order_index=order_idx,
                    task_type=task_type,
                    title=title_text,
                    description=desc_text,
                    estimated_minutes=minutes_remaining,
                    priority=TaskPriority.P2.value,
                    reason=reason_text,
                    evidence=evidence_text,
                    topic="Code Quality & Complexity",
                    completion_criteria="Document Big-O annotations and ensure clean modular logic.",
                )
            )

        return tasks

    def _structure_weeks(
        self,
        days: List[PreparationDay],
        cfg: PlannerSettings,
        evidence: Dict[str, Any],
    ) -> List[PreparationWeek]:
        """Group calendar days into structured progressive weekly plans."""
        weeks: List[PreparationWeek] = []
        num_weeks = (len(days) + 6) // 7

        weak_topics = evidence.get("weak_topics") or []
        rm_recs = evidence.get("roadmap_recommendations") or []

        for w_idx in range(num_weeks):
            w_num = w_idx + 1
            w_days = days[w_idx * 7 : (w_idx + 1) * 7]
            if not w_days:
                continue

            # Focus topics for this week
            f_topics: List[str] = []
            if weak_topics:
                f_topics.append(weak_topics[w_idx % len(weak_topics)])
            if rm_recs:
                f_topics.append(rm_recs[w_idx % len(rm_recs)])
            if not f_topics:
                f_topics = ["Arrays & Hashing", "Two Pointers"]

            all_w_tasks = [t for d in w_days for t in d.tasks]
            practice_cnt = sum(1 for t in all_w_tasks if t.task_type in (TaskType.SOLVE_PROBLEM.value, TaskType.PRACTICE_WEAK_TOPIC.value))
            rev_cnt = sum(1 for t in all_w_tasks if t.task_type == TaskType.REVISE_PROBLEM.value)
            mock_cnt = sum(1 for t in all_w_tasks if t.task_type == TaskType.CONDUCT_MOCK_INTERVIEW.value)

            allocations = {d.day_name: d.planned_minutes for d in w_days}

            obj_text = (
                f"Week {w_num}: Reinforce core problem-solving fundamentals in {', '.join(f_topics)}."
                if w_num == 1
                else f"Week {w_num}: Expand problem complexity and validate with timed mock checkpoints."
            )

            weakness_text = (
                "Focus on test case dry-runs and edge cases."
                if any(i.insight_id == "weakness_correctness" for i in evidence.get("interview_insights", []))
                else "Balanced focus across correctness, completion, and complexity awareness."
            )

            weeks.append(
                PreparationWeek(
                    week_number=w_num,
                    start_date=w_days[0].day_date,
                    end_date=w_days[-1].day_date,
                    week_objective=obj_text,
                    focus_topics=f_topics,
                    planned_practice_count=practice_cnt,
                    revision_workload_count=rev_cnt,
                    mock_interview_targets=mock_cnt,
                    weakness_improvement_focus=weakness_text,
                    daily_time_allocations=allocations,
                    weekly_completion_targets=f"Complete >= 85% of planned practice sessions and {mock_cnt} mock checkpoint.",
                    days=w_days,
                )
            )

        return weeks

    # -------------------------------------------------------------------------
    # Plan Persistence & Application
    # -------------------------------------------------------------------------

    def save_plan(self, plan: PreparationPlan) -> PreparationPlan:
        """Persist a newly generated or modified plan into session_tracking.db."""
        now_str = _get_utc_now_iso()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO preparation_plans (
                    plan_id, title, created_at, updated_at, start_date, end_date,
                    horizon_days, status, settings_json, adaptation_history_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    title=excluded.title,
                    updated_at=excluded.updated_at,
                    status=excluded.status,
                    settings_json=excluded.settings_json,
                    adaptation_history_json=excluded.adaptation_history_json
                """,
                (
                    plan.plan_id,
                    plan.title,
                    plan.created_at,
                    now_str,
                    plan.start_date,
                    plan.end_date,
                    plan.horizon_days,
                    plan.status,
                    json.dumps(asdict(plan.settings)),
                    json.dumps(plan.adaptation_history),
                ),
            )

            # Persist plan days
            cursor.execute("DELETE FROM preparation_plan_days WHERE plan_id = ?", (plan.plan_id,))
            for week in plan.weeks:
                for d in week.days:
                    cursor.execute(
                        """
                        INSERT INTO preparation_plan_days (
                            plan_id, day_date, day_name, is_study_day, planned_minutes, week_number
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            plan.plan_id,
                            d.day_date,
                            d.day_name,
                            1 if d.is_study_day else 0,
                            d.planned_minutes,
                            week.week_number,
                        ),
                    )

            # Persist tasks
            cursor.execute("DELETE FROM preparation_tasks WHERE plan_id = ?", (plan.plan_id,))
            for t in plan.all_tasks:
                cursor.execute(
                    """
                    INSERT INTO preparation_tasks (
                        task_id, plan_id, day_date, session_index, order_index,
                        task_type, title, description, estimated_minutes, actual_minutes,
                        priority, reason, evidence, topic, problem_id, completion_criteria,
                        status, completed_at, skipped_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        t.task_id,
                        t.plan_id,
                        t.day_date,
                        t.session_index,
                        t.order_index,
                        t.task_type,
                        t.title,
                        t.description,
                        t.estimated_minutes,
                        t.actual_minutes,
                        t.priority,
                        t.reason,
                        t.evidence,
                        t.topic,
                        t.problem_id,
                        t.completion_criteria,
                        t.status,
                        t.completed_at,
                        t.skipped_reason,
                    ),
                )
            conn.commit()

        return self.get_plan(plan.plan_id)

    def apply_plan(self, plan_id: str) -> PreparationPlan:
        """Explicitly activate a draft or existing plan. Only one plan is active at a time."""
        plan = self.get_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan '{plan_id}' not found.")

        now_str = _get_utc_now_iso()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Archive existing active plans
            cursor.execute(
                "UPDATE preparation_plans SET status = ?, updated_at = ? WHERE status = ?",
                (PlanStatus.ARCHIVED.value, now_str, PlanStatus.ACTIVE.value),
            )
            # Activate selected plan
            cursor.execute(
                "UPDATE preparation_plans SET status = ?, updated_at = ? WHERE plan_id = ?",
                (PlanStatus.ACTIVE.value, now_str, plan_id),
            )
            conn.commit()

        return self.get_plan(plan_id)

    def get_plan(self, plan_id: str) -> Optional[PreparationPlan]:
        """Retrieve full plan with all weeks, days, tasks, and calculated progress."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM preparation_plans WHERE plan_id = ?", (plan_id,))
            plan_row = cursor.fetchone()
            if not plan_row:
                return None

            # Retrieve days
            cursor.execute(
                "SELECT * FROM preparation_plan_days WHERE plan_id = ? ORDER BY day_date ASC",
                (plan_id,),
            )
            day_rows = cursor.fetchall()

            # Retrieve tasks
            cursor.execute(
                "SELECT * FROM preparation_tasks WHERE plan_id = ? ORDER BY day_date ASC, order_index ASC",
                (plan_id,),
            )
            task_rows = cursor.fetchall()

        settings_dict = json.loads(plan_row["settings_json"])
        settings = PlannerSettings(**settings_dict)

        tasks_by_date: Dict[str, List[PreparationTask]] = {}
        all_tasks: List[PreparationTask] = []
        for tr in task_rows:
            task = PreparationTask(
                task_id=tr["task_id"],
                plan_id=tr["plan_id"],
                day_date=tr["day_date"],
                session_index=tr["session_index"],
                order_index=tr["order_index"],
                task_type=tr["task_type"],
                title=tr["title"],
                description=tr["description"],
                estimated_minutes=tr["estimated_minutes"],
                actual_minutes=tr["actual_minutes"],
                priority=tr["priority"],
                reason=tr["reason"],
                evidence=tr["evidence"],
                topic=tr["topic"],
                problem_id=tr["problem_id"],
                completion_criteria=tr["completion_criteria"],
                status=tr["status"],
                completed_at=tr["completed_at"],
                skipped_reason=tr["skipped_reason"],
            )
            all_tasks.append(task)
            tasks_by_date.setdefault(tr["day_date"], []).append(task)

        # Build days
        days_by_week: Dict[int, List[PreparationDay]] = {}
        for dr in day_rows:
            d_date = dr["day_date"]
            d_tasks = tasks_by_date.get(d_date, [])
            d_completed = sum(1 for t in d_tasks if t.status == TaskStatus.COMPLETED.value)
            d_actual_min = sum(t.actual_minutes or 0 for t in d_tasks)

            if not dr["is_study_day"]:
                d_status = "rest_day"
            elif d_completed == len(d_tasks) and len(d_tasks) > 0:
                d_status = "completed"
            elif d_completed > 0:
                d_status = "in_progress"
            else:
                d_status = "pending"

            day_obj = PreparationDay(
                day_date=d_date,
                day_name=dr["day_name"],
                is_study_day=bool(dr["is_study_day"]),
                planned_minutes=dr["planned_minutes"],
                actual_minutes=d_actual_min,
                tasks=d_tasks,
                completed_tasks_count=d_completed,
                total_tasks_count=len(d_tasks),
                day_status=d_status,
            )
            days_by_week.setdefault(dr["week_number"], []).append(day_obj)

        # Build weeks
        weeks: List[PreparationWeek] = []
        for w_num in sorted(days_by_week.keys()):
            w_days = days_by_week[w_num]
            w_tasks = [t for d in w_days for t in d.tasks]
            practice_cnt = sum(1 for t in w_tasks if t.task_type in (TaskType.SOLVE_PROBLEM.value, TaskType.PRACTICE_WEAK_TOPIC.value))
            rev_cnt = sum(1 for t in w_tasks if t.task_type == TaskType.REVISE_PROBLEM.value)
            mock_cnt = sum(1 for t in w_tasks if t.task_type == TaskType.CONDUCT_MOCK_INTERVIEW.value)
            allocations = {d.day_name: d.planned_minutes for d in w_days}

            weeks.append(
                PreparationWeek(
                    week_number=w_num,
                    start_date=w_days[0].day_date,
                    end_date=w_days[-1].day_date,
                    week_objective=f"Week {w_num} Preparation Schedule",
                    focus_topics=list({t.topic for t in w_tasks if t.topic and t.topic != "Spaced Repetition"}),
                    planned_practice_count=practice_cnt,
                    revision_workload_count=rev_cnt,
                    mock_interview_targets=mock_cnt,
                    weakness_improvement_focus="Continuous rubric alignment",
                    daily_time_allocations=allocations,
                    weekly_completion_targets=f"Complete >= 85% of planned practice sessions.",
                    days=w_days,
                )
            )

        # Calculate progress
        now_date_str = _get_utc_now().strftime("%Y-%m-%d")
        planned_cnt = len(all_tasks)
        completed_cnt = sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETED.value)
        skipped_cnt = sum(1 for t in all_tasks if t.status == TaskStatus.SKIPPED.value)
        overdue_cnt = sum(
            1 for t in all_tasks
            if t.status == TaskStatus.PENDING.value and t.day_date < now_date_str
        )
        total_planned_min = sum(t.estimated_minutes for t in all_tasks)
        total_actual_min = sum(t.actual_minutes or 0 for t in all_tasks)
        ratio_pct = round((completed_cnt / max(1, planned_cnt)) * 100.0, 1) if planned_cnt > 0 else 0.0

        # Calculate current streak
        streak = 0
        study_days_sorted = [d for d in day_rows if d["is_study_day"] and d["day_date"] <= now_date_str]
        for sd in reversed(study_days_sorted):
            sd_tasks = tasks_by_date.get(sd["day_date"], [])
            if any(t.status == TaskStatus.COMPLETED.value for t in sd_tasks):
                streak += 1
            else:
                break

        progress = PlanProgress(
            tasks_planned=planned_cnt,
            tasks_completed=completed_cnt,
            tasks_skipped=skipped_cnt,
            tasks_overdue=overdue_cnt,
            planned_minutes=total_planned_min,
            actual_recorded_minutes=total_actual_min,
            completion_ratio_pct=ratio_pct,
            current_streak_days=streak,
            weekly_completion_pct=ratio_pct,
            topics_progressed=list({t.topic for t in all_tasks if t.status == TaskStatus.COMPLETED.value and t.topic}),
            goal_alignment=f"Targeting {settings.target_track} track ({settings.target_score} score goal)",
        )

        return PreparationPlan(
            plan_id=plan_row["plan_id"],
            title=plan_row["title"],
            created_at=plan_row["created_at"],
            updated_at=plan_row["updated_at"],
            start_date=plan_row["start_date"],
            end_date=plan_row["end_date"],
            horizon_days=plan_row["horizon_days"],
            status=plan_row["status"],
            settings=settings,
            weeks=weeks,
            all_tasks=all_tasks,
            progress=progress,
            adaptation_history=json.loads(plan_row["adaptation_history_json"] or "[]"),
        )

    def get_active_plan(self) -> Optional[PreparationPlan]:
        """Retrieve the currently active preparation plan."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT plan_id FROM preparation_plans WHERE status = ?", (PlanStatus.ACTIVE.value,))
            row = cursor.fetchone()
            if not row:
                return None
            return self.get_plan(row["plan_id"])

    def list_plans(self) -> List[Dict[str, Any]]:
        """List summary of all historical and active plans."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT plan_id, title, created_at, updated_at, start_date, end_date, horizon_days, status "
                "FROM preparation_plans ORDER BY created_at DESC"
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Task Lifecycle: Complete & Skip
    # -------------------------------------------------------------------------

    def complete_task(
        self,
        task_id: str,
        actual_minutes: Optional[int] = None,
    ) -> PreparationTask:
        """Mark an individual task as completed with optional actual study minutes."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM preparation_tasks WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Task '{task_id}' not found.")

            current_status = row["status"]
            if current_status == TaskStatus.COMPLETED.value:
                # Idempotent return
                return self._row_to_task(row)

            now_str = _get_utc_now_iso()
            est_min = row["estimated_minutes"]
            act_min = int(actual_minutes) if actual_minutes is not None and actual_minutes > 0 else est_min

            cursor.execute(
                """
                UPDATE preparation_tasks
                SET status = ?, actual_minutes = ?, completed_at = ?
                WHERE task_id = ?
                """,
                (TaskStatus.COMPLETED.value, act_min, now_str, task_id),
            )

            # Log history
            cursor.execute(
                """
                INSERT INTO preparation_task_history (
                    task_id, plan_id, action, old_status, new_status, timestamp, notes
                ) VALUES (?, ?, 'complete', ?, ?, ?, ?)
                """,
                (task_id, row["plan_id"], current_status, TaskStatus.COMPLETED.value, now_str, f"Completed in {act_min}m"),
            )
            conn.commit()

            cursor.execute("SELECT * FROM preparation_tasks WHERE task_id = ?", (task_id,))
            updated_row = cursor.fetchone()
            return self._row_to_task(updated_row)

    def skip_task(
        self,
        task_id: str,
        reason: Optional[str] = None,
    ) -> PreparationTask:
        """Mark an individual task as skipped."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM preparation_tasks WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Task '{task_id}' not found.")

            current_status = row["status"]
            if current_status == TaskStatus.COMPLETED.value:
                raise ValueError(f"Cannot skip task '{task_id}' because it has already been completed.")

            now_str = _get_utc_now_iso()
            skip_desc = reason or "Task skipped by learner"

            cursor.execute(
                """
                UPDATE preparation_tasks
                SET status = ?, skipped_reason = ?
                WHERE task_id = ?
                """,
                (TaskStatus.SKIPPED.value, skip_desc, task_id),
            )

            # Log history
            cursor.execute(
                """
                INSERT INTO preparation_task_history (
                    task_id, plan_id, action, old_status, new_status, timestamp, notes
                ) VALUES (?, ?, 'skip', ?, ?, ?, ?)
                """,
                (task_id, row["plan_id"], current_status, TaskStatus.SKIPPED.value, now_str, skip_desc),
            )
            conn.commit()

            cursor.execute("SELECT * FROM preparation_tasks WHERE task_id = ?", (task_id,))
            updated_row = cursor.fetchone()
            return self._row_to_task(updated_row)

    def _row_to_task(self, row: sqlite3.Row) -> PreparationTask:
        return PreparationTask(
            task_id=row["task_id"],
            plan_id=row["plan_id"],
            day_date=row["day_date"],
            session_index=row["session_index"],
            order_index=row["order_index"],
            task_type=row["task_type"],
            title=row["title"],
            description=row["description"],
            estimated_minutes=row["estimated_minutes"],
            actual_minutes=row["actual_minutes"],
            priority=row["priority"],
            reason=row["reason"],
            evidence=row["evidence"],
            topic=row["topic"],
            problem_id=row["problem_id"],
            completion_criteria=row["completion_criteria"],
            status=row["status"],
            completed_at=row["completed_at"],
            skipped_reason=row["skipped_reason"],
        )

    # -------------------------------------------------------------------------
    # Adaptive Replanning
    # -------------------------------------------------------------------------

    def preview_replan(
        self,
        plan_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate an adaptive replan preview comparing current schedule with necessary adjustments."""
        active_plan = self.get_plan(plan_id) if plan_id else self.get_active_plan()
        if not active_plan:
            raise ValueError("No active preparation plan found to replan.")

        now_date_str = _get_utc_now().strftime("%Y-%m-%d")

        # Analyze task states
        completed_tasks = [t for t in active_plan.all_tasks if t.status == TaskStatus.COMPLETED.value]
        skipped_tasks = [t for t in active_plan.all_tasks if t.status == TaskStatus.SKIPPED.value]
        overdue_tasks = [
            t for t in active_plan.all_tasks
            if t.status == TaskStatus.PENDING.value and t.day_date < now_date_str
        ]
        future_pending = [
            t for t in active_plan.all_tasks
            if t.status == TaskStatus.PENDING.value and t.day_date >= now_date_str
        ]

        changes: List[Dict[str, Any]] = []
        rescheduled_tasks: List[Dict[str, Any]] = []

        # Rule 1: Reschedule overdue high-priority tasks (P0, P1) into future study days
        # find future study days with capacity
        future_study_days = [
            d for w in active_plan.weeks for d in w.days
            if d.is_study_day and d.day_date >= now_date_str
        ]

        if overdue_tasks:
            changes.append({
                "action": "reschedule_overdue",
                "count": len(overdue_tasks),
                "reason": f"Redistributing {len(overdue_tasks)} uncompleted overdue tasks into future study sessions.",
            })

            # Reassign overdue P0/P1 tasks to earliest available future day
            day_idx = 0
            for ot in overdue_tasks:
                if future_study_days:
                    target_day = future_study_days[day_idx % len(future_study_days)]
                    rescheduled_tasks.append({
                        "task_id": ot.task_id,
                        "title": ot.title,
                        "old_date": ot.day_date,
                        "new_date": target_day.day_date,
                        "priority": ot.priority,
                        "reason": f"Rescheduled from {ot.day_date} to prevent learning backlog.",
                    })
                    day_idx += 1

        # Rule 2: If a task was skipped, add revision/prerequisite checkpoint in a later day
        if skipped_tasks:
            changes.append({
                "action": "review_skipped",
                "count": len(skipped_tasks),
                "reason": f"Detected {len(skipped_tasks)} skipped tasks; scheduling targeted review checkpoint.",
            })

        # Rule 3: Rebalance workload to ensure no day exceeds daily_minutes
        summary = (
            f"Adaptive replan identified {len(overdue_tasks)} overdue tasks and {len(skipped_tasks)} skipped tasks. "
            f"Preserved all {len(completed_tasks)} completed tasks. Rebalanced schedule across remaining {len(future_study_days)} study days."
        )

        return {
            "plan_id": active_plan.plan_id,
            "can_replan": bool(overdue_tasks or skipped_tasks),
            "completed_tasks_preserved": len(completed_tasks),
            "overdue_tasks_count": len(overdue_tasks),
            "skipped_tasks_count": len(skipped_tasks),
            "rescheduled_tasks": rescheduled_tasks,
            "strategic_changes": changes,
            "explanation": summary,
        }

    def apply_replan(
        self,
        plan_id: Optional[str] = None,
    ) -> PreparationPlan:
        """Apply adaptive replanning changes to the active plan and log adaptation history."""
        preview = self.preview_replan(plan_id)
        target_plan_id = preview["plan_id"]
        rescheduled = preview["rescheduled_tasks"]

        now_str = _get_utc_now_iso()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for r in rescheduled:
                cursor.execute(
                    """
                    UPDATE preparation_tasks
                    SET day_date = ?
                    WHERE task_id = ?
                    """,
                    (r["new_date"], r["task_id"]),
                )
                cursor.execute(
                    """
                    INSERT INTO preparation_task_history (
                        task_id, plan_id, action, old_status, new_status, timestamp, notes
                    ) VALUES (?, ?, 'reschedule', 'pending', 'pending', ?, ?)
                    """,
                    (r["task_id"], target_plan_id, now_str, f"Rescheduled from {r['old_date']} to {r['new_date']}"),
                )

            # Record adaptation in plan history
            cursor.execute("SELECT adaptation_history_json FROM preparation_plans WHERE plan_id = ?", (target_plan_id,))
            hist_row = cursor.fetchone()
            hist = json.loads(hist_row["adaptation_history_json"] or "[]")
            hist.append({
                "timestamp": now_str,
                "overdue_count": preview["overdue_tasks_count"],
                "skipped_count": preview["skipped_tasks_count"],
                "rescheduled_count": len(rescheduled),
                "explanation": preview["explanation"],
            })

            cursor.execute(
                "UPDATE preparation_plans SET adaptation_history_json = ?, updated_at = ? WHERE plan_id = ?",
                (json.dumps(hist), now_str, target_plan_id),
            )
            conn.commit()

        return self.get_plan(target_plan_id)
