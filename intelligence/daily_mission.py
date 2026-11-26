"""Daily Learning Mission & Focus Mode Engine.

Milestone 6.3.15: Daily Learning Mission & Focus Mode.
Provides:
1. Deterministic generation of a personalized daily mission synthesizing:
   - Priority 1: Overdue spaced revisions.
   - Priority 2: Weak topics & active learning goals.
   - Priority 3: Roadmap-ready topics.
   - Priority 4: Difficulty progression & coach feedback.
2. Mission task sequencing with clear task state machine (pending, in_progress, completed, skipped).
3. Focus Mode interactive workflow (start mission, start task, complete task, skip task, pause, resume, cancel).
4. Mission persistence & completion intelligence stored safely in session_tracking.db without touching progress.db.
5. Complete analytics and evidence-based summaries.

100% offline, deterministic, zero external API calls, read-only on progress.db.
Never fabricates metrics, streaks, or completion history.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from intelligence.goals import GoalStatus, GoalType, GoalsManager
from intelligence.revision import SpacedRevisionEngine
from intelligence.roadmap import DsaRoadmapEngine, TopicMasteryStatus
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from problems import load_problems
import store


class MissionStatus(str, Enum):
    """Lifecycle states of a daily learning mission."""
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MissionTaskType(str, Enum):
    """Categorized daily mission task types."""
    REVISE_DUE_PROBLEM = "revise_due_problem"
    PRACTICE_WEAK_TOPIC = "practice_weak_topic"
    PURSUE_LEARNING_GOAL = "pursue_learning_goal"
    START_ROADMAP_TOPIC = "start_roadmap_topic"
    PROGRESS_DIFFICULTY = "progress_difficulty"
    REVIEW_COACH_GUIDANCE = "review_coach_guidance"


class MissionTaskStatus(str, Enum):
    """Progress status of an individual task inside a mission."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


@dataclass
class DailyMissionTask:
    """Actionable task unit within a daily mission."""
    task_id: str
    mission_id: str
    task_type: MissionTaskType
    sequence_order: int
    title: str
    description: str
    problem_id: Optional[str]
    topic: Optional[str]
    difficulty: Optional[str]
    estimated_duration_min: int
    selection_reason: str
    status: MissionTaskStatus = MissionTaskStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    skip_reason: Optional[str] = None


@dataclass
class DailyMission:
    """A personalized daily coding practice mission."""
    mission_id: str
    mission_date: str                   # YYYY-MM-DD
    title: str
    summary: str
    estimated_duration_min: int
    total_tasks: int
    completed_tasks_count: int
    status: MissionStatus
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    paused_at: Optional[str] = None
    reasoning: str = ""
    tasks: List[DailyMissionTask] = field(default_factory=list)

    @property
    def completion_percentage(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return round((self.completed_tasks_count / self.total_tasks) * 100.0, 1)

    @property
    def current_task(self) -> Optional[DailyMissionTask]:
        # Return currently in_progress task, or next pending task
        for t in self.tasks:
            if t.status == MissionTaskStatus.IN_PROGRESS:
                return t
        for t in self.tasks:
            if t.status == MissionTaskStatus.PENDING:
                return t
        return None


@dataclass
class MissionSummaryReport:
    """Evidence-based completion summary of a daily learning mission."""
    mission_id: str
    mission_title: str
    mission_date: str
    status: MissionStatus
    total_tasks: int
    tasks_completed: int
    tasks_skipped: int
    problems_solved: List[str]
    topics_practiced: List[str]
    revisions_completed: int
    goals_progressed: List[str]
    completion_rate_pct: float
    total_duration_min: int
    suggested_next_mission: str
    summary: str


@dataclass
class DailyMissionAnalytics:
    """Aggregated historical mission statistics."""
    total_missions_generated: int
    completed_missions_count: int
    in_progress_missions_count: int
    cancelled_missions_count: int
    overall_completion_rate: float
    total_tasks_completed: int
    total_tasks_skipped: int
    current_streak_days: int
    recent_missions: List[DailyMission] = field(default_factory=list)


def _get_utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_today_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class DailyMissionManager:
    """Manages creation, execution workflow, and persistence of daily learning missions."""

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
        """Create daily mission tables safely in session_tracking.db."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_missions (
                    mission_id TEXT PRIMARY KEY,
                    mission_date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    estimated_duration_min INTEGER NOT NULL,
                    total_tasks INTEGER NOT NULL,
                    completed_tasks_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    paused_at TEXT,
                    reasoning TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_mission_tasks (
                    task_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    sequence_order INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    problem_id TEXT,
                    topic TEXT,
                    difficulty TEXT,
                    estimated_duration_min INTEGER NOT NULL,
                    selection_reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    skip_reason TEXT,
                    FOREIGN KEY (mission_id) REFERENCES daily_missions(mission_id)
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mission_date ON daily_missions(mission_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mission_status ON daily_missions(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_mission ON daily_mission_tasks(mission_id)")
            conn.commit()

    def _get_solved_problem_ids(self) -> Set[str]:
        """Fetch distinct solved problem IDs from progress.db."""
        solved: Set[str] = set()
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

    def generate_mission(
        self,
        target_duration_min: int = 45,
        max_tasks: int = 3,
        force_new: bool = False,
    ) -> DailyMission:
        """Generate a personalized daily mission adhering to transparent priority rules."""
        today = _get_today_date_str()

        # If an active or today's mission already exists and not force_new, return it
        if not force_new:
            existing = self.get_today_mission()
            if existing and existing.status in (MissionStatus.CREATED, MissionStatus.IN_PROGRESS, MissionStatus.PAUSED):
                return existing

        all_problems = load_problems()
        solved_ids = self._get_solved_problem_ids()
        prob_map = {p["id"]: p for p in all_problems if p.get("id")}

        # Engines for context
        rev_engine = SpacedRevisionEngine(
            tracking_db_path=self.tracking_db_path,
            progress_db_path=self.progress_db_path,
        )
        goals_mgr = GoalsManager(
            tracking_db_path=self.tracking_db_path,
            progress_db_path=self.progress_db_path,
            language=self.language,
        )
        roadmap_engine = DsaRoadmapEngine(
            progress_db_path=self.progress_db_path,
            tracking_db_path=self.tracking_db_path,
            language=self.language,
        )

        candidate_tasks: List[DailyMissionTask] = []
        mission_id = f"mission_{uuid.uuid4().hex[:10]}"
        now_str = _get_utc_now_iso()

        # ---------------------------------------------------------------------
        # Priority 1: Overdue or Due Spaced Revisions
        # ---------------------------------------------------------------------
        try:
            now_iso = _get_utc_now_iso()
            # Check tracking DB directly for both revision_items and spaced_revisions tables
            with self.get_connection() as conn:
                cur = conn.cursor()
                tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if "revision_items" in tables:
                    cur.execute(
                        "SELECT problem_id, difficulty, topics_json, next_review_at FROM revision_items WHERE status = 'active' AND next_review_at <= ?",
                        (now_iso,),
                    )
                    for r in cur.fetchall():
                        pid = r["problem_id"]
                        p_meta = prob_map.get(pid)
                        diff = p_meta.get("difficulty", r["difficulty"]) if p_meta else r["difficulty"]
                        try:
                            topics_list = json.loads(r["topics_json"])
                        except Exception:
                            topics_list = ["Core DSA"]
                        topic = topics_list[0] if topics_list else "Core DSA"
                        candidate_tasks.append(
                            DailyMissionTask(
                                task_id=f"task_{uuid.uuid4().hex[:8]}",
                                mission_id=mission_id,
                                task_type=MissionTaskType.REVISE_DUE_PROBLEM,
                                sequence_order=len(candidate_tasks) + 1,
                                title=f"Spaced Revision: {pid}",
                                description=f"Review and re-solve problem '{pid}' to reinforce algorithmic recall.",
                                problem_id=pid,
                                topic=topic,
                                difficulty=diff,
                                estimated_duration_min=15,
                                selection_reason="Problem is due for spaced repetition review.",
                            )
                        )
                if "spaced_revisions" in tables:
                    cur.execute(
                        "SELECT problem_id, difficulty, topics, next_review_at FROM spaced_revisions WHERE status = 'active' AND next_review_at <= ?",
                        (now_iso,),
                    )
                    for r in cur.fetchall():
                        pid = r["problem_id"]
                        if not any(t.problem_id == pid for t in candidate_tasks):
                            p_meta = prob_map.get(pid)
                            diff = p_meta.get("difficulty", r["difficulty"]) if p_meta else r["difficulty"]
                            topic = (p_meta.get("topics") or [r["topics"]])[0] if p_meta else r["topics"]
                            candidate_tasks.append(
                                DailyMissionTask(
                                    task_id=f"task_{uuid.uuid4().hex[:8]}",
                                    mission_id=mission_id,
                                    task_type=MissionTaskType.REVISE_DUE_PROBLEM,
                                    sequence_order=len(candidate_tasks) + 1,
                                    title=f"Spaced Revision: {pid}",
                                    description=f"Review and re-solve problem '{pid}' to reinforce algorithmic recall.",
                                    problem_id=pid,
                                    topic=topic,
                                    difficulty=diff,
                                    estimated_duration_min=15,
                                    selection_reason="Problem is due for spaced repetition review.",
                                )
                            )
        except Exception:
            pass

        # ---------------------------------------------------------------------
        # Priority 2: Active Goals & Weak Topics
        # ---------------------------------------------------------------------
        try:
            active_goals = goals_mgr.list_goals(status_filter=GoalStatus.ACTIVE)
            for g in active_goals:
                if len(candidate_tasks) >= max_tasks:
                    break
                target_p = g.target_parameter
                cand_prob = None
                if target_p:
                    for p in all_problems:
                        if p["id"] not in solved_ids:
                            # match topic or diff
                            p_diff = str(p.get("difficulty", "")).lower()
                            p_topics = [t.lower() for t in (p.get("topics") or [])]
                            if target_p.lower() == p_diff or target_p.lower() in p_topics or target_p.lower() in str(p.get("pattern", "")).lower():
                                cand_prob = p
                                break
                if not cand_prob:
                    cand_prob = next((p for p in all_problems if p["id"] not in solved_ids), None)

                if cand_prob:
                    candidate_tasks.append(
                        DailyMissionTask(
                            task_id=f"task_{uuid.uuid4().hex[:8]}",
                            mission_id=mission_id,
                            task_type=MissionTaskType.PURSUE_LEARNING_GOAL,
                            sequence_order=len(candidate_tasks) + 1,
                            title=f"Goal Pursuit: {cand_prob['id']}",
                            description=f"Solve problem '{cand_prob['id']}' to advance active goal '{g.title}'.",
                            problem_id=cand_prob["id"],
                            topic=(cand_prob.get("topics") or [target_p or "General"])[0],
                            difficulty=cand_prob.get("difficulty", "medium"),
                            estimated_duration_min=20,
                            selection_reason=f"Advances goal '{g.title}' ({g.percent_completed}% completed).",
                        )
                    )
        except Exception:
            pass

        # ---------------------------------------------------------------------
        # Priority 3: Roadmap-Ready Topics
        # ---------------------------------------------------------------------
        if len(candidate_tasks) < max_tasks:
            try:
                roadmap_overview = roadmap_engine.get_roadmap_overview()
                ready_topics = roadmap_overview.ready_to_learn_topics
                if ready_topics:
                    for t_name in ready_topics[:2]:
                        if len(candidate_tasks) >= max_tasks:
                            break
                        # Find an unsolved problem in this topic
                        node = next((n for n in roadmap_engine.nodes if n.display_name.lower() == t_name.lower()), None)
                        if node:
                            for p in all_problems:
                                if p["id"] not in solved_ids and roadmap_engine._match_problem_to_node(p, node):
                                    candidate_tasks.append(
                                        DailyMissionTask(
                                            task_id=f"task_{uuid.uuid4().hex[:8]}",
                                            mission_id=mission_id,
                                            task_type=MissionTaskType.START_ROADMAP_TOPIC,
                                            sequence_order=len(candidate_tasks) + 1,
                                            title=f"Roadmap Skill: {p['id']}",
                                            description=f"Begin topic '{node.display_name}' by solving introductory problem '{p['id']}'.",
                                            problem_id=p["id"],
                                            topic=node.display_name,
                                            difficulty=p.get("difficulty", "easy"),
                                            estimated_duration_min=15,
                                            selection_reason=f"Topic '{node.display_name}' has all prerequisites met and is ready on your DSA roadmap.",
                                        )
                                    )
                                    break
            except Exception:
                pass

        # ---------------------------------------------------------------------
        # Priority 4: Difficulty Progression or Fallback Inventory Problem
        # ---------------------------------------------------------------------
        if len(candidate_tasks) < max_tasks:
            for p in all_problems:
                if len(candidate_tasks) >= max_tasks:
                    break
                if p["id"] not in solved_ids and not any(t.problem_id == p["id"] for t in candidate_tasks):
                    diff = p.get("difficulty", "easy")
                    candidate_tasks.append(
                        DailyMissionTask(
                            task_id=f"task_{uuid.uuid4().hex[:8]}",
                            mission_id=mission_id,
                            task_type=MissionTaskType.PROGRESS_DIFFICULTY,
                            sequence_order=len(candidate_tasks) + 1,
                            title=f"Practice Problem: {p['id']}",
                            description=f"Solve {diff.title()} problem '{p['id']}' to broaden pattern familiarity.",
                            problem_id=p["id"],
                            topic=(p.get("topics") or ["General"])[0],
                            difficulty=diff,
                            estimated_duration_min=15 if diff.lower() == "easy" else 25,
                            selection_reason="Selected from local inventory to maintain consistent daily practice cadence.",
                        )
                    )

        # Fallback if inventory is exhausted or already solved
        if not candidate_tasks:
            fallback_prob = all_problems[0] if all_problems else {"id": "two-sum", "difficulty": "easy"}
            candidate_tasks.append(
                DailyMissionTask(
                    task_id=f"task_{uuid.uuid4().hex[:8]}",
                    mission_id=mission_id,
                    task_type=MissionTaskType.REVIEW_COACH_GUIDANCE,
                    sequence_order=1,
                    title=f"Review & Practice: {fallback_prob['id']}",
                    description=f"Practice foundational problem '{fallback_prob['id']}'.",
                    problem_id=fallback_prob["id"],
                    topic="Foundations",
                    difficulty=fallback_prob.get("difficulty", "easy"),
                    estimated_duration_min=15,
                    selection_reason="Foundational daily practice.",
                )
            )

        # Truncate to max_tasks and re-index sequence_order
        candidate_tasks = candidate_tasks[:max_tasks]
        for idx, t in enumerate(candidate_tasks):
            t.sequence_order = idx + 1

        total_est_min = sum(t.estimated_duration_min for t in candidate_tasks)
        primary_topic = candidate_tasks[0].topic or "Core DSA"
        title = f"Daily Mission: Focus on {primary_topic}"
        summary = f"Complete {len(candidate_tasks)} structured tasks (~{total_est_min} mins) targeting revisions, goals, and roadmap advancement."
        reasoning = "Synthesized from your active learning goals, spaced revision queue, and DSA roadmap readiness."

        mission = DailyMission(
            mission_id=mission_id,
            mission_date=today,
            title=title,
            summary=summary,
            estimated_duration_min=total_est_min,
            total_tasks=len(candidate_tasks),
            completed_tasks_count=0,
            status=MissionStatus.CREATED,
            created_at=now_str,
            reasoning=reasoning,
            tasks=candidate_tasks,
        )

        # Persist to database
        self._save_mission(mission)
        return mission

    def _save_mission(self, mission: DailyMission) -> None:
        """Persist or update mission and tasks in session_tracking.db."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO daily_missions (
                    mission_id, mission_date, title, summary, estimated_duration_min,
                    total_tasks, completed_tasks_count, status, created_at, started_at,
                    completed_at, paused_at, reasoning
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mission.mission_id,
                    mission.mission_date,
                    mission.title,
                    mission.summary,
                    mission.estimated_duration_min,
                    mission.total_tasks,
                    mission.completed_tasks_count,
                    mission.status.value,
                    mission.created_at,
                    mission.started_at,
                    mission.completed_at,
                    mission.paused_at,
                    mission.reasoning,
                ),
            )
            for t in mission.tasks:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO daily_mission_tasks (
                        task_id, mission_id, task_type, sequence_order, title, description,
                        problem_id, topic, difficulty, estimated_duration_min, selection_reason,
                        status, started_at, completed_at, skip_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        t.task_id,
                        t.mission_id,
                        t.task_type.value,
                        t.sequence_order,
                        t.title,
                        t.description,
                        t.problem_id,
                        t.topic,
                        t.difficulty,
                        t.estimated_duration_min,
                        t.selection_reason,
                        t.status.value,
                        t.started_at,
                        t.completed_at,
                        t.skip_reason,
                    ),
                )
            conn.commit()

    def get_mission(self, mission_id: str) -> Optional[DailyMission]:
        """Fetch mission with all ordered tasks by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM daily_missions WHERE mission_id = ?", (mission_id,))
            row = cursor.fetchone()
            if not row:
                return None
            cursor.execute(
                "SELECT * FROM daily_mission_tasks WHERE mission_id = ? ORDER BY sequence_order ASC",
                (mission_id,),
            )
            t_rows = cursor.fetchall()

        tasks = [
            DailyMissionTask(
                task_id=tr["task_id"],
                mission_id=tr["mission_id"],
                task_type=MissionTaskType(tr["task_type"]),
                sequence_order=tr["sequence_order"],
                title=tr["title"],
                description=tr["description"],
                problem_id=tr["problem_id"],
                topic=tr["topic"],
                difficulty=tr["difficulty"],
                estimated_duration_min=tr["estimated_duration_min"],
                selection_reason=tr["selection_reason"],
                status=MissionTaskStatus(tr["status"]),
                started_at=tr["started_at"],
                completed_at=tr["completed_at"],
                skip_reason=tr["skip_reason"],
            )
            for tr in t_rows
        ]

        return DailyMission(
            mission_id=row["mission_id"],
            mission_date=row["mission_date"],
            title=row["title"],
            summary=row["summary"],
            estimated_duration_min=row["estimated_duration_min"],
            total_tasks=row["total_tasks"],
            completed_tasks_count=row["completed_tasks_count"],
            status=MissionStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            paused_at=row["paused_at"],
            reasoning=row["reasoning"] or "",
            tasks=tasks,
        )

    def get_today_mission(self) -> Optional[DailyMission]:
        """Fetch the most recent mission for today."""
        today = _get_today_date_str()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT mission_id FROM daily_missions WHERE mission_date = ? ORDER BY created_at DESC LIMIT 1",
                (today,),
            )
            row = cursor.fetchone()
            if row:
                return self.get_mission(row["mission_id"])

            # Fallback: check any in-progress or paused mission
            cursor.execute(
                "SELECT mission_id FROM daily_missions WHERE status IN ('in_progress', 'paused') ORDER BY created_at DESC LIMIT 1"
            )
            row2 = cursor.fetchone()
            if row2:
                return self.get_mission(row2["mission_id"])
        return None

    # -------------------------------------------------------------------------
    # Focus Mode Lifecycle Actions
    # -------------------------------------------------------------------------

    def start_mission(self, mission_id: Optional[str] = None) -> DailyMission:
        """Start the daily mission and its first task."""
        mission = self.get_mission(mission_id) if mission_id else self.get_today_mission()
        if not mission:
            mission = self.generate_mission()

        if mission.status == MissionStatus.COMPLETED:
            raise ValueError(f"Mission '{mission.mission_id}' is already completed.")

        now_str = _get_utc_now_iso()
        mission.status = MissionStatus.IN_PROGRESS
        if not mission.started_at:
            mission.started_at = now_str
        mission.paused_at = None

        # Start first pending task if none is in progress
        first_pending = next((t for t in mission.tasks if t.status == MissionTaskStatus.PENDING), None)
        if first_pending and not any(t.status == MissionTaskStatus.IN_PROGRESS for t in mission.tasks):
            first_pending.status = MissionTaskStatus.IN_PROGRESS
            first_pending.started_at = now_str

        self._save_mission(mission)
        return mission

    def start_task(self, task_id: str) -> DailyMissionTask:
        """Explicitly begin working on a specific task."""
        mission, task = self._find_task_and_mission(task_id)
        if task.status in (MissionTaskStatus.COMPLETED, MissionTaskStatus.SKIPPED):
            raise ValueError(f"Task '{task_id}' is already {task.status.value}.")

        now_str = _get_utc_now_iso()
        # Mark other in-progress tasks as pending
        for t in mission.tasks:
            if t.task_id != task_id and t.status == MissionTaskStatus.IN_PROGRESS:
                t.status = MissionTaskStatus.PENDING

        task.status = MissionTaskStatus.IN_PROGRESS
        task.started_at = now_str

        if mission.status != MissionStatus.IN_PROGRESS:
            mission.status = MissionStatus.IN_PROGRESS
            if not mission.started_at:
                mission.started_at = now_str

        self._save_mission(mission)
        return task

    def complete_task(self, task_id: str) -> Tuple[DailyMissionTask, DailyMission]:
        """Mark a task complete and advance the mission."""
        mission, task = self._find_task_and_mission(task_id)
        if task.status == MissionTaskStatus.COMPLETED:
            return task, mission

        now_str = _get_utc_now_iso()
        task.status = MissionTaskStatus.COMPLETED
        task.completed_at = now_str

        mission.completed_tasks_count = sum(1 for t in mission.tasks if t.status == MissionTaskStatus.COMPLETED)

        # Check if all tasks are completed or skipped
        all_done = all(t.status in (MissionTaskStatus.COMPLETED, MissionTaskStatus.SKIPPED) for t in mission.tasks)
        if all_done:
            mission.status = MissionStatus.COMPLETED
            mission.completed_at = now_str
        else:
            # Advance to next pending task
            next_pending = next((t for t in mission.tasks if t.status == MissionTaskStatus.PENDING), None)
            if next_pending:
                next_pending.status = MissionTaskStatus.IN_PROGRESS
                next_pending.started_at = now_str

        self._save_mission(mission)
        return task, mission

    def skip_task(self, task_id: str, reason: str = "Skipped by user") -> Tuple[DailyMissionTask, DailyMission]:
        """Skip a task with a recorded reason and advance mission."""
        mission, task = self._find_task_and_mission(task_id)
        if task.status in (MissionTaskStatus.COMPLETED, MissionTaskStatus.SKIPPED):
            return task, mission

        now_str = _get_utc_now_iso()
        task.status = MissionTaskStatus.SKIPPED
        task.completed_at = now_str
        task.skip_reason = reason.strip() or "Skipped by user"

        all_done = all(t.status in (MissionTaskStatus.COMPLETED, MissionTaskStatus.SKIPPED) for t in mission.tasks)
        if all_done:
            mission.status = MissionStatus.COMPLETED
            mission.completed_at = now_str
        else:
            next_pending = next((t for t in mission.tasks if t.status == MissionTaskStatus.PENDING), None)
            if next_pending:
                next_pending.status = MissionTaskStatus.IN_PROGRESS
                next_pending.started_at = now_str

        self._save_mission(mission)
        return task, mission

    def pause_mission(self, mission_id: Optional[str] = None) -> DailyMission:
        """Pause mission and freeze active task."""
        mission = self.get_mission(mission_id) if mission_id else self.get_today_mission()
        if not mission:
            raise ValueError("No active mission found to pause.")

        if mission.status == MissionStatus.COMPLETED:
            raise ValueError("Cannot pause a completed mission.")

        mission.status = MissionStatus.PAUSED
        mission.paused_at = _get_utc_now_iso()
        self._save_mission(mission)
        return mission

    def resume_mission(self, mission_id: Optional[str] = None) -> DailyMission:
        """Resume a paused mission."""
        mission = self.get_mission(mission_id) if mission_id else self.get_today_mission()
        if not mission:
            raise ValueError("No mission found to resume.")

        mission.status = MissionStatus.IN_PROGRESS
        mission.paused_at = None

        # Ensure active task exists
        if not any(t.status == MissionTaskStatus.IN_PROGRESS for t in mission.tasks):
            pending = next((t for t in mission.tasks if t.status == MissionTaskStatus.PENDING), None)
            if pending:
                pending.status = MissionTaskStatus.IN_PROGRESS
                pending.started_at = _get_utc_now_iso()

        self._save_mission(mission)
        return mission

    def cancel_mission(self, mission_id: Optional[str] = None) -> DailyMission:
        """Cancel an in-progress or paused mission."""
        mission = self.get_mission(mission_id) if mission_id else self.get_today_mission()
        if not mission:
            raise ValueError("No active mission found to cancel.")

        mission.status = MissionStatus.CANCELLED
        mission.completed_at = _get_utc_now_iso()
        self._save_mission(mission)
        return mission

    def _find_task_and_mission(self, task_id: str) -> Tuple[DailyMission, DailyMissionTask]:
        """Locate task and its parent mission, raising error if not found."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT mission_id FROM daily_mission_tasks WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Task '{task_id}' not found.")
            mission_id = row["mission_id"]

        mission = self.get_mission(mission_id)
        if not mission:
            raise ValueError(f"Mission '{mission_id}' not found.")
        task = next((t for t in mission.tasks if t.task_id == task_id), None)
        if not task:
            raise ValueError(f"Task '{task_id}' not found in mission.")
        return mission, task

    # -------------------------------------------------------------------------
    # Mission Intelligence & Summary
    # -------------------------------------------------------------------------

    def get_mission_summary(self, mission_id: str) -> MissionSummaryReport:
        """Generate an evidence-based summary of completed/active mission."""
        mission = self.get_mission(mission_id)
        if not mission:
            raise ValueError(f"Mission '{mission_id}' not found.")

        completed_tasks = [t for t in mission.tasks if t.status == MissionTaskStatus.COMPLETED]
        skipped_tasks = [t for t in mission.tasks if t.status == MissionTaskStatus.SKIPPED]

        problems_solved = [t.problem_id for t in completed_tasks if t.problem_id]
        topics_practiced = list({t.topic for t in completed_tasks if t.topic})
        revisions_completed = sum(1 for t in completed_tasks if t.task_type == MissionTaskType.REVISE_DUE_PROBLEM)
        goals_progressed = [t.title for t in completed_tasks if t.task_type == MissionTaskType.PURSUE_LEARNING_GOAL]

        # Calculate duration
        total_duration = 0
        if mission.started_at and mission.completed_at:
            try:
                t1 = datetime.fromisoformat(mission.started_at)
                t2 = datetime.fromisoformat(mission.completed_at)
                total_duration = max(1, int((t2 - t1).total_seconds() / 60))
            except Exception:
                total_duration = mission.estimated_duration_min
        else:
            total_duration = sum(t.estimated_duration_min for t in completed_tasks)

        # Suggested next mission
        if mission.status == MissionStatus.COMPLETED:
            suggested = "Ready for tomorrow's mission! Review your DSA roadmap or log another session."
        else:
            rem = len(mission.tasks) - len(completed_tasks) - len(skipped_tasks)
            suggested = f"Continue today's mission: {rem} task(s) remaining."

        summary_text = (
            f"Mission '{mission.title}': {len(completed_tasks)}/{mission.total_tasks} tasks completed "
            f"({mission.completion_percentage}%). Practiced: {', '.join(topics_practiced) if topics_practiced else 'None'}."
        )

        return MissionSummaryReport(
            mission_id=mission.mission_id,
            mission_title=mission.title,
            mission_date=mission.mission_date,
            status=mission.status,
            total_tasks=mission.total_tasks,
            tasks_completed=len(completed_tasks),
            tasks_skipped=len(skipped_tasks),
            problems_solved=problems_solved,
            topics_practiced=topics_practiced,
            revisions_completed=revisions_completed,
            goals_progressed=goals_progressed,
            completion_rate_pct=mission.completion_percentage,
            total_duration_min=total_duration,
            suggested_next_mission=suggested,
            summary=summary_text,
        )

    def get_analytics(self) -> DailyMissionAnalytics:
        """Calculate aggregated mission analytics across history."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM daily_missions ORDER BY created_at DESC")
            m_rows = cursor.fetchall()
            cursor.execute("SELECT status, COUNT(*) as cnt FROM daily_mission_tasks GROUP BY status")
            task_counts = {r["status"]: r["cnt"] for r in cursor.fetchall()}

        total_missions = len(m_rows)
        completed_m = sum(1 for r in m_rows if r["status"] == MissionStatus.COMPLETED.value)
        in_prog_m = sum(1 for r in m_rows if r["status"] in (MissionStatus.IN_PROGRESS.value, MissionStatus.PAUSED.value))
        cancelled_m = sum(1 for r in m_rows if r["status"] == MissionStatus.CANCELLED.value)

        rate = round((completed_m / total_missions) * 100.0, 1) if total_missions > 0 else 0.0

        # Load recent missions (up to 5)
        recent: List[DailyMission] = []
        for r in m_rows[:5]:
            m = self.get_mission(r["mission_id"])
            if m:
                recent.append(m)

        # Streak calculation (consecutive dates with completed missions)
        streak = 0
        completed_dates = {r["mission_date"] for r in m_rows if r["status"] == MissionStatus.COMPLETED.value}
        curr = datetime.now(timezone.utc).date()
        while curr.strftime("%Y-%m-%d") in completed_dates:
            streak += 1
            curr = curr - datetime.timedelta(days=1)

        return DailyMissionAnalytics(
            total_missions_generated=total_missions,
            completed_missions_count=completed_m,
            in_progress_missions_count=in_prog_m,
            cancelled_missions_count=cancelled_m,
            overall_completion_rate=rate,
            total_tasks_completed=task_counts.get(MissionTaskStatus.COMPLETED.value, 0),
            total_tasks_skipped=task_counts.get(MissionTaskStatus.SKIPPED.value, 0),
            current_streak_days=streak,
            recent_missions=recent,
        )

    def list_mission_history(self, limit: int = 10) -> List[DailyMission]:
        """Fetch historical missions ordered by creation date."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT mission_id FROM daily_missions ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()

        result = []
        for r in rows:
            m = self.get_mission(r["mission_id"])
            if m:
                result.append(m)
        return result
