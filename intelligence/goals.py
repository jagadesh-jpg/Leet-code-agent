"""Personal Learning Goals & Achievement Tracker Engine.

Milestone 6.3.13: Personal Learning Goals & Achievement Tracker.
Provides offline goal management, progress computation based on verifiable local records,
actionable goal planning, and evidence-based milestone achievements.

100% offline, local-first, database-safe (uses tracking DB tables), zero API calls.
Never fabricates progress or retroactively claims unearned achievements.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Tuple

from intelligence.tracker import DEFAULT_TRACKING_DB_PATH, SessionStatus, SessionTracker
from problems import load_problems
import store


class GoalType(str, Enum):
    """Categorized learning goal types."""
    SOLVE_PROBLEMS = "solve_problems"          # Target total solved problems
    SOLVE_DIFFICULTY = "solve_difficulty"      # Target solved problems of specific difficulty (easy/med/hard)
    PRACTICE_TOPIC = "practice_topic"          # Target attempts or solved problems in an algorithm topic
    COMPLETE_SESSIONS = "complete_sessions"    # Target completed learning sessions
    COMPLETE_REVISIONS = "complete_revisions"  # Target spaced repetition reviews
    WEEKLY_TARGET = "weekly_target"            # Target weekly problem solutions or sessions


class GoalStatus(str, Enum):
    """Lifecycle states of a personal learning goal."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass
class LearningGoal:
    """A user-defined measurable coding practice goal."""
    goal_id: str
    title: str
    goal_type: GoalType
    target_metric: int
    current_progress: int
    target_parameter: Optional[str]            # e.g., "easy", "medium", "hard", or topic "Arrays"
    deadline: Optional[str]                    # YYYY-MM-DD
    status: GoalStatus
    created_at: str
    updated_at: str
    completed_at: Optional[str]
    notes: Optional[str]

    @property
    def target_value(self) -> int:
        return self.target_metric

    @property
    def current_value(self) -> int:
        return self.current_progress

    @property
    def percent_completed(self) -> float:
        if self.target_metric <= 0:
            return 100.0
        return min(100.0, round((self.current_progress / self.target_metric) * 100.0, 1))

    @property
    def remaining_workload(self) -> int:
        return max(0, self.target_metric - self.current_progress)

    @property
    def days_remaining(self) -> Optional[int]:
        if not self.deadline:
            return None
        try:
            deadline_date = datetime.strptime(self.deadline, "%Y-%m-%d").date()
            today_date = datetime.now(timezone.utc).date()
            return (deadline_date - today_date).days
        except Exception:
            return None

    @property
    def is_overdue(self) -> bool:
        dr = self.days_remaining
        return dr is not None and dr < 0 and self.status == GoalStatus.ACTIVE


@dataclass
class MilestoneAchievement:
    """An evidence-based milestone unlocked strictly through local data."""
    achievement_id: str
    title: str
    category: str
    description: str
    unlocked: bool
    unlocked_at: Optional[str]
    evidence: str

    @property
    def milestone_id(self) -> str:
        return self.achievement_id

    @property
    def is_unlocked(self) -> bool:
        return self.unlocked


@dataclass
class GoalPlanRecommendation:
    """Manageable daily/weekly practice schedule recommended for active goals."""
    goal_id: str
    goal_title: str
    target_remaining: int
    days_remaining: Optional[int]
    recommended_daily_pace: float
    recommended_session_size: int
    rationale: str

    @property
    def daily_pacing(self) -> float:
        return self.recommended_daily_pace

    @property
    def sessions_per_week(self) -> int:
        return 7 if self.recommended_daily_pace >= 1.0 else 3


@dataclass
class GoalsAnalyticsReport:
    """Aggregate offline goals and milestone achievement metrics."""
    total_goals_created: int
    active_goals_count: int
    completed_goals_count: int
    paused_goals_count: int
    archived_goals_count: int
    overall_completion_rate: float
    achievements_unlocked_count: int
    total_achievements_count: int
    active_goals: List[LearningGoal] = field(default_factory=list)
    milestones: List[MilestoneAchievement] = field(default_factory=list)
    plan_recommendations: List[GoalPlanRecommendation] = field(default_factory=list)
    summary: str = ""

    @property
    def total_goals(self) -> int:
        return self.total_goals_created

    @property
    def active_goals_total(self) -> int:
        return self.active_goals_count

    @property
    def completed_goals(self) -> int:
        return self.completed_goals_count

    @property
    def completion_rate_pct(self) -> float:
        return round(self.overall_completion_rate * 100.0, 1)

    @property
    def milestones_unlocked(self) -> int:
        return self.achievements_unlocked_count

    @property
    def total_milestones(self) -> int:
        return self.total_achievements_count


def _get_utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GoalsManager:
    """Manages personal learning goals, progress calculations, and achievements."""

    def __init__(
        self,
        tracking_db_path: Optional[str | Path] = None,
        progress_db_path: Optional[str | Path] = None,
        language: str = "python",
    ):
        self.tracking_db_path = Path(tracking_db_path) if tracking_db_path is not None else DEFAULT_TRACKING_DB_PATH
        self.progress_db_path = progress_db_path
        self.language = (language or "python").strip().lower()
        self.init_schema()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.tracking_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """Create goals and achievement tables in tracking DB without touching progress.db."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_goals (
                    goal_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    goal_type TEXT NOT NULL,
                    target_metric INTEGER NOT NULL,
                    current_progress INTEGER NOT NULL,
                    target_parameter TEXT,
                    deadline TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    notes TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS achievement_unlocks (
                    achievement_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    unlocked_at TEXT NOT NULL,
                    evidence TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_goals_status ON learning_goals(status)"
            )
            conn.commit()

    def create_goal(
        self,
        title: str,
        goal_type: GoalType,
        target_metric: Optional[int] = None,
        target_parameter: Optional[str] = None,
        deadline: Optional[str] = None,
        notes: Optional[str] = None,
        goal_id: Optional[str] = None,
        target_value: Optional[int] = None,
        target_difficulty: Optional[str] = None,
        target_topic: Optional[str] = None,
        days_to_complete: Optional[int] = None,
        description: Optional[str] = None,
    ) -> LearningGoal:
        """Create and persist a new measurable learning goal."""
        title = title.strip()
        if not title:
            raise ValueError("Goal title cannot be empty.")

        # Harmonize target_metric and target_value
        effective_target = target_value if target_value is not None else target_metric
        if effective_target is None or effective_target <= 0:
            raise ValueError("Target value must be a positive integer.")

        # Harmonize target_parameter
        effective_param = target_parameter
        if target_difficulty is not None:
            effective_param = target_difficulty
        elif target_topic is not None:
            effective_param = target_topic

        if goal_type == GoalType.SOLVE_DIFFICULTY and not effective_param:
            raise ValueError("GoalType.SOLVE_DIFFICULTY requires a valid target_difficulty.")
        if goal_type == GoalType.PRACTICE_TOPIC and not effective_param:
            raise ValueError("GoalType.PRACTICE_TOPIC requires a valid target_topic.")

        # Harmonize deadline
        effective_deadline = deadline
        if days_to_complete is not None:
            target_date = datetime.now(timezone.utc).date() + timedelta(days=days_to_complete)
            effective_deadline = target_date.strftime("%Y-%m-%d")

        if effective_deadline:
            try:
                datetime.strptime(effective_deadline.strip(), "%Y-%m-%d")
                effective_deadline = effective_deadline.strip()
            except ValueError:
                raise ValueError("Deadline must be in YYYY-MM-DD format.")

        effective_notes = description if description is not None else notes

        now_str = _get_utc_now_iso()
        gid = goal_id or f"goal_{uuid.uuid4().hex[:10]}"

        # Prevent duplicate identical active goal
        existing = self.list_goals(status_filter=GoalStatus.ACTIVE.value)
        for g in existing:
            if g.title.lower() == title.lower() and g.goal_type == goal_type:
                return g

        # Initial progress check based on current DB state
        initial_progress = self._compute_live_metric(goal_type, effective_param)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO learning_goals (
                    goal_id, title, goal_type, target_metric, current_progress,
                    target_parameter, deadline, status, created_at, updated_at,
                    completed_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    gid,
                    title,
                    goal_type.value,
                    effective_target,
                    initial_progress,
                    effective_param.strip() if effective_param else None,
                    effective_deadline,
                    GoalStatus.ACTIVE.value,
                    now_str,
                    now_str,
                    effective_notes.strip() if effective_notes else None,
                ),
            )
            conn.commit()

        # Check for auto-completion if initial progress already meets target
        item = self.get_goal(gid)
        assert item is not None
        if item.current_progress >= item.target_metric:
            item = self.complete_goal(gid)
        return item

    def get_goal(self, goal_id: str) -> Optional[LearningGoal]:
        """Retrieve a specific learning goal by ID, updating its progress dynamically."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM learning_goals WHERE goal_id = ?", (goal_id,))
            row = cursor.fetchone()
            if not row:
                return None

        goal = self._row_to_goal(row)
        # Update progress dynamically if goal is active
        if goal.status == GoalStatus.ACTIVE:
            live_val = self._compute_live_metric(goal.goal_type, goal.target_parameter)
            if live_val != goal.current_progress:
                now_str = _get_utc_now_iso()
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE learning_goals SET current_progress = ?, updated_at = ? WHERE goal_id = ?",
                        (live_val, now_str, goal_id),
                    )
                    conn.commit()
                goal.current_progress = live_val
                # Check for auto-completion
                if goal.current_progress >= goal.target_metric:
                    return self.complete_goal(goal_id)

        return goal

    def _row_to_goal(self, row: sqlite3.Row) -> LearningGoal:
        return LearningGoal(
            goal_id=row["goal_id"],
            title=row["title"],
            goal_type=GoalType(row["goal_type"]),
            target_metric=row["target_metric"],
            current_progress=row["current_progress"],
            target_parameter=row["target_parameter"],
            deadline=row["deadline"],
            status=GoalStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            notes=row["notes"],
        )

    def list_goals(self, status_filter: Optional[str] = None) -> List[LearningGoal]:
        """List learning goals optionally filtered by status."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if status_filter:
                cursor.execute(
                    "SELECT goal_id FROM learning_goals WHERE status = ? ORDER BY created_at DESC",
                    (status_filter.strip().lower(),),
                )
            else:
                cursor.execute("SELECT goal_id FROM learning_goals ORDER BY created_at DESC")
            rows = cursor.fetchall()

        result = []
        for r in rows:
            g = self.get_goal(r["goal_id"])
            if g:
                result.append(g)
        return result

    def update_goal(
        self,
        goal_id: str,
        title: Optional[str] = None,
        target_metric: Optional[int] = None,
        deadline: Optional[str] = None,
        notes: Optional[str] = None,
        target_value: Optional[int] = None,
        description: Optional[str] = None,
        deadline_at: Optional[str] = None,
    ) -> LearningGoal:
        """Update metadata, target metric, or deadline of an existing goal."""
        goal = self.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal '{goal_id}' not found.")
        if goal.status in (GoalStatus.COMPLETED, GoalStatus.ARCHIVED):
            raise ValueError(f"Cannot edit {goal.status.value} goal '{goal_id}'.")

        new_title = title.strip() if title is not None else goal.title
        if not new_title:
            raise ValueError("Goal title cannot be empty.")

        effective_target = target_value if target_value is not None else target_metric
        new_target = effective_target if effective_target is not None else goal.target_metric
        if new_target <= 0:
            raise ValueError("Target metric must be positive.")

        effective_deadline = deadline_at if deadline_at is not None else deadline
        new_deadline = goal.deadline
        if effective_deadline is not None:
            if effective_deadline.strip():
                try:
                    datetime.strptime(effective_deadline.strip(), "%Y-%m-%d")
                    new_deadline = effective_deadline.strip()
                except ValueError:
                    raise ValueError("Deadline must be in YYYY-MM-DD format.")
            else:
                new_deadline = None

        effective_notes = description if description is not None else notes
        new_notes = effective_notes.strip() if effective_notes is not None else goal.notes
        now_str = _get_utc_now_iso()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE learning_goals
                SET title = ?, target_metric = ?, deadline = ?, notes = ?, updated_at = ?
                WHERE goal_id = ?
                """,
                (new_title, new_target, new_deadline, new_notes, now_str, goal_id),
            )
            conn.commit()

        updated = self.get_goal(goal_id)
        assert updated is not None
        if updated.current_progress >= updated.target_metric:
            return self.complete_goal(goal_id)
        return updated

    def set_goal_status(self, goal_id: str, new_status: GoalStatus) -> LearningGoal:
        """Transition goal lifecycle status (pause, resume, archive)."""
        goal = self.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal '{goal_id}' not found.")

        now_str = _get_utc_now_iso()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE learning_goals SET status = ?, updated_at = ? WHERE goal_id = ?",
                (new_status.value, now_str, goal_id),
            )
            conn.commit()

        updated = self.get_goal(goal_id)
        assert updated is not None
        return updated

    def complete_goal(self, goal_id: str) -> LearningGoal:
        """Mark goal as completed."""
        goal = self.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal '{goal_id}' not found.")
        if goal.status == GoalStatus.COMPLETED:
            return goal

        now_str = _get_utc_now_iso()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE learning_goals SET status = ?, completed_at = ?, updated_at = ? WHERE goal_id = ?",
                (GoalStatus.COMPLETED.value, now_str, now_str, goal_id),
            )
            conn.commit()

        # Trigger achievement verification
        self._evaluate_and_unlock_achievements()

        updated = self.get_goal(goal_id)
        assert updated is not None
        return updated

    def _get_solved_problem_ids(self) -> set:
        """Helper to get set of solved problem IDs across attempts, language_progress, or progress table."""
        solved = set()
        if not self.progress_db_path:
            return solved
        try:
            with sqlite3.connect(str(self.progress_db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if "attempts" in tables:
                    cur.execute("SELECT DISTINCT problem_id FROM attempts WHERE passed = total AND total > 0")
                    for r in cur.fetchall():
                        solved.add(r["problem_id"])
                if "language_progress" in tables:
                    cur.execute("SELECT DISTINCT problem_id FROM language_progress WHERE status = 'solved'")
                    for r in cur.fetchall():
                        solved.add(r["problem_id"])
                if "progress" in tables:
                    cur.execute("SELECT DISTINCT problem_id FROM progress WHERE status = 'solved'")
                    for r in cur.fetchall():
                        solved.add(r["problem_id"])
        except Exception:
            pass
        return solved

    def _compute_live_metric(self, goal_type: GoalType, parameter: Optional[str]) -> int:
        """Calculate actual metric count from existing SQLite database records."""
        # 1. Total Problems Solved
        if goal_type == GoalType.SOLVE_PROBLEMS:
            return len(self._get_solved_problem_ids())

        # 2. Solved Problems by Specific Difficulty
        elif goal_type == GoalType.SOLVE_DIFFICULTY:
            target_diff = (parameter or "easy").strip().lower()
            all_problems = load_problems()
            diff_pids = {p["id"] for p in all_problems if p.get("difficulty", "").lower() == target_diff}
            solved_ids = self._get_solved_problem_ids()
            return len(solved_ids.intersection(diff_pids))

        # 3. Topic Practice / Solutions
        elif goal_type == GoalType.PRACTICE_TOPIC:
            target_topic = (parameter or "Arrays").strip()
            all_problems = load_problems()
            from intelligence.topics import get_problem_topics
            topic_pids = {p["id"] for p in all_problems if target_topic.lower() in [t.lower() for t in get_problem_topics(p)]}
            solved_ids = self._get_solved_problem_ids()
            return len(solved_ids.intersection(topic_pids))

        # 4. Completed Learning Sessions
        elif goal_type == GoalType.COMPLETE_SESSIONS:
            try:
                with self.get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) as cnt FROM learning_sessions WHERE status = 'completed'")
                    row = cur.fetchone()
                    return int(row["cnt"]) if row and row["cnt"] else 0
            except Exception:
                return 0

        # 5. Completed Spaced Repetitions
        elif goal_type == GoalType.COMPLETE_REVISIONS:
            try:
                with self.get_connection() as conn:
                    cur = conn.cursor()
                    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                    if "revision_history" in tables:
                        cur.execute("SELECT COUNT(*) as cnt FROM revision_history")
                        row = cur.fetchone()
                        if row and row["cnt"]:
                            return int(row["cnt"])
                    if "spaced_revisions" in tables:
                        cur.execute("SELECT SUM(review_count) as total_rev FROM spaced_revisions")
                        row = cur.fetchone()
                        if row and row["total_rev"]:
                            return int(row["total_rev"])
            except Exception:
                return 0
            return 0

        # 6. Weekly Target
        elif goal_type == GoalType.WEEKLY_TARGET:
            # Solved problems within last 7 days
            seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            try:
                with sqlite3.connect(str(self.progress_db_path)) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                    if "attempts" in tables:
                        cur.execute(
                            "SELECT COUNT(DISTINCT problem_id) as cnt FROM attempts WHERE passed = total AND total > 0 AND timestamp >= ?",
                            (seven_days_ago,),
                        )
                        row = cur.fetchone()
                        if row and row["cnt"]:
                            return int(row["cnt"])
                    if "progress" in tables:
                        cur.execute(
                            "SELECT COUNT(*) as cnt FROM progress WHERE status = 'solved' AND solved_at >= ?",
                            (seven_days_ago,),
                        )
                        row = cur.fetchone()
                        return int(row["cnt"]) if row and row["cnt"] else 0
            except Exception:
                return 0

        return 0

    def get_goal_plan_recommendations(self) -> List[GoalPlanRecommendation]:
        """Generate manageable schedule pacing for all active goals."""
        active = self.list_goals(status_filter=GoalStatus.ACTIVE.value)
        recs: List[GoalPlanRecommendation] = []

        for g in active:
            rem = g.remaining_workload
            days = g.days_remaining

            if days is not None and days > 0:
                daily_pace = round(rem / max(1, days), 2)
            else:
                daily_pace = float(rem)

            # Recommend manageable session size
            if daily_pace <= 1.0:
                sess_size = 2
            elif daily_pace <= 3.0:
                sess_size = 3
            else:
                sess_size = 4

            if days is not None and days < 0:
                rationale = f"Goal is overdue by {abs(days)} day(s). Recommended {sess_size} problem(s)/session to recover pace."
            elif days is not None and days == 0:
                rationale = f"Due today! Complete remaining {rem} item(s) to finalize goal."
            elif days is not None:
                rationale = f"{rem} item(s) remaining over {days} day(s) (~{daily_pace}/day). Recommended session size: {sess_size} problem(s)."
            else:
                rationale = f"{rem} item(s) remaining with open deadline. Steady practice pace recommended."

            recs.append(
                GoalPlanRecommendation(
                    goal_id=g.goal_id,
                    goal_title=g.title,
                    target_remaining=rem,
                    days_remaining=days,
                    recommended_daily_pace=daily_pace,
                    recommended_session_size=sess_size,
                    rationale=rationale,
                )
            )

        return recs

    def check_and_unlock_milestones(self) -> List[MilestoneAchievement]:
        """Evaluate local records and return milestones."""
        return self.get_milestones()

    def get_goals_analytics(self) -> GoalsAnalyticsReport:
        """Alias for get_analytics()."""
        return self.get_analytics()

    def recommend_goal_schedule(
        self,
        target_problems: int,
        target_days: int,
    ) -> GoalPlanRecommendation:
        """Provide a pacing recommendation for a hypothetical or target schedule."""
        if target_days <= 0:
            target_days = 1
        daily_pace = round(target_problems / max(1, target_days), 2)
        if daily_pace <= 1.0:
            sess_size = 2
        elif daily_pace <= 3.0:
            sess_size = 2 if target_problems <= 14 else 3
        else:
            sess_size = 4

        return GoalPlanRecommendation(
            goal_id="schedule_rec",
            goal_title="Pacing Recommendation",
            target_remaining=target_problems,
            days_remaining=target_days,
            recommended_daily_pace=daily_pace,
            recommended_session_size=sess_size,
            rationale=f"Recommended daily pace of {daily_pace} problem(s) over {target_days} day(s).",
        )

    def _evaluate_and_unlock_achievements(self) -> None:
        """Evaluate local records and unlock milestones supported by evidence."""
        # Achievement definitions
        achievements = [
            {
                "id": "ach_first_solve",
                "title": "First Problem Solved",
                "category": "solving",
                "description": "Successfully solved your first algorithm problem locally.",
                "condition": lambda: self._compute_live_metric(GoalType.SOLVE_PROBLEMS, None) >= 1,
                "evidence": lambda: f"Verified {self._compute_live_metric(GoalType.SOLVE_PROBLEMS, None)} solved problem(s).",
            },
            {
                "id": "ach_first_session",
                "title": "First Session Completed",
                "category": "sessions",
                "description": "Completed your first structured practice session.",
                "condition": lambda: self._compute_live_metric(GoalType.COMPLETE_SESSIONS, None) >= 1,
                "evidence": lambda: f"Verified {self._compute_live_metric(GoalType.COMPLETE_SESSIONS, None)} completed session(s).",
            },
            {
                "id": "ach_first_goal",
                "title": "Goal Achieved",
                "category": "goals",
                "description": "Achieved and completed your first learning goal.",
                "condition": lambda: len(self.list_goals(status_filter=GoalStatus.COMPLETED.value)) >= 1,
                "evidence": lambda: f"Verified {len(self.list_goals(status_filter=GoalStatus.COMPLETED.value))} completed goal(s).",
            },
            {
                "id": "ach_first_revision",
                "title": "Smart Recall Pioneer",
                "category": "revision",
                "description": "Logged your first spaced repetition revision outcome.",
                "condition": lambda: self._compute_live_metric(GoalType.COMPLETE_REVISIONS, None) >= 1,
                "evidence": lambda: f"Verified {self._compute_live_metric(GoalType.COMPLETE_REVISIONS, None)} revision review(s).",
            },
            {
                "id": "ach_five_solves",
                "title": "DSA Foundation Milestone",
                "category": "solving",
                "description": "Solved 5 distinct algorithmic problems.",
                "condition": lambda: self._compute_live_metric(GoalType.SOLVE_PROBLEMS, None) >= 5,
                "evidence": lambda: f"Verified {self._compute_live_metric(GoalType.SOLVE_PROBLEMS, None)} solved problems.",
            },
        ]

        now_str = _get_utc_now_iso()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for ach in achievements:
                aid = ach["id"]
                cursor.execute("SELECT achievement_id FROM achievement_unlocks WHERE achievement_id = ?", (aid,))
                if not cursor.fetchone():
                    try:
                        if ach["condition"]():
                            cursor.execute(
                                """
                                INSERT INTO achievement_unlocks (
                                    achievement_id, title, category, description, unlocked_at, evidence
                                ) VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (aid, ach["title"], ach["category"], ach["description"], now_str, ach["evidence"]()),
                            )
                    except Exception:
                        pass
            conn.commit()

    def get_milestones(self) -> List[MilestoneAchievement]:
        """Fetch all evidence-based milestones and their unlocked status."""
        self._evaluate_and_unlock_achievements()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM achievement_unlocks")
            unlocked_rows = {r["achievement_id"]: r for r in cursor.fetchall()}

        standard_milestones = [
            ("ach_first_solve", "First Problem Solved", "solving", "Successfully solved your first algorithm problem locally."),
            ("ach_first_session", "First Session Completed", "sessions", "Completed your first structured practice session."),
            ("ach_first_goal", "Goal Achieved", "goals", "Achieved and completed your first learning goal."),
            ("ach_first_revision", "Smart Recall Pioneer", "revision", "Logged your first spaced repetition revision outcome."),
            ("ach_five_solves", "DSA Foundation Milestone", "solving", "Solved 5 distinct algorithmic problems."),
        ]

        result: List[MilestoneAchievement] = []
        for aid, title, cat, desc in standard_milestones:
            if aid in unlocked_rows:
                u_row = unlocked_rows[aid]
                result.append(
                    MilestoneAchievement(
                        achievement_id=aid,
                        title=title,
                        category=cat,
                        description=desc,
                        unlocked=True,
                        unlocked_at=u_row["unlocked_at"],
                        evidence=u_row["evidence"],
                    )
                )
            else:
                result.append(
                    MilestoneAchievement(
                        achievement_id=aid,
                        title=title,
                        category=cat,
                        description=desc,
                        unlocked=False,
                        unlocked_at=None,
                        evidence="Pending achievement completion.",
                    )
                )

        return result

    def get_analytics(self) -> GoalsAnalyticsReport:
        """Compile complete analytics across personal goals and milestones."""
        all_goals = self.list_goals()
        active = [g for g in all_goals if g.status == GoalStatus.ACTIVE]
        completed = [g for g in all_goals if g.status == GoalStatus.COMPLETED]
        paused = [g for g in all_goals if g.status == GoalStatus.PAUSED]
        archived = [g for g in all_goals if g.status == GoalStatus.ARCHIVED]

        tot = len(all_goals)
        comp_rate = (len(completed) / tot) if tot > 0 else 0.0

        milestones = self.get_milestones()
        unlocked_count = sum(1 for m in milestones if m.unlocked)
        plan_recs = self.get_goal_plan_recommendations()

        summary_parts = []
        if active:
            summary_parts.append(f"{len(active)} active goal(s) in progress.")
        if completed:
            summary_parts.append(f"{len(completed)} goal(s) completed.")
        summary_parts.append(f"{unlocked_count}/{len(milestones)} milestones unlocked.")

        return GoalsAnalyticsReport(
            total_goals_created=tot,
            active_goals_count=len(active),
            completed_goals_count=len(completed),
            paused_goals_count=len(paused),
            archived_goals_count=len(archived),
            overall_completion_rate=round(comp_rate, 2),
            achievements_unlocked_count=unlocked_count,
            total_achievements_count=len(milestones),
            active_goals=active,
            milestones=milestones,
            plan_recommendations=plan_recs,
            summary=" ".join(summary_parts),
        )
