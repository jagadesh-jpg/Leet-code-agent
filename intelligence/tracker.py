"""Learning Session Tracking & Feedback Engine.

Milestone 6.3.6: Learning Session Tracking & Feedback Engine.
Provides offline persistence, lifecycle tracking, progress monitoring, and analytics
for structured learning sessions without modifying production progress.db.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from intelligence.planner import LearningSessionPlan, PlannedProblem, SessionProblemRole

# Dedicated default local tracking database (separate from progress.db)
DEFAULT_TRACKING_DB_PATH = Path(__file__).resolve().parent.parent / "session_tracking.db"


class SessionStatus(str, Enum):
    """Lifecycle states of a learning session."""
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProblemProgressStatus(str, Enum):
    """Progress status of a planned problem within a session."""
    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"


@dataclass
class TrackedProblemItem:
    """Snapshot of a planned problem stored within a tracked session."""
    session_id: str
    problem_id: str
    rank: int
    role: str
    difficulty: str
    topics: List[str]
    priority_score: float
    reason: str
    status: ProblemProgressStatus = ProblemProgressStatus.PENDING
    completed_at: Optional[str] = None
    outcome_notes: Optional[str] = None


@dataclass
class TrackedSessionRecord:
    """Full database record of a learning session."""
    session_id: str
    target_language: str
    target_size: int
    status: SessionStatus
    created_at: str
    updated_at: str
    completed_at: Optional[str]
    session_summary: str
    weak_topics: List[str]
    covered_topics: List[str]
    problems: List[TrackedProblemItem] = field(default_factory=list)

    @property
    def total_problems(self) -> int:
        return len(self.problems)

    @property
    def completed_count(self) -> int:
        return sum(1 for p in self.problems if p.status == ProblemProgressStatus.COMPLETED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for p in self.problems if p.status == ProblemProgressStatus.SKIPPED)

    @property
    def pending_count(self) -> int:
        return sum(1 for p in self.problems if p.status == ProblemProgressStatus.PENDING)


@dataclass
class TrackingAnalytics:
    """Explainable offline analytics computed across historical sessions."""
    total_sessions_planned: int
    total_sessions_completed: int
    total_sessions_in_progress: int
    total_sessions_cancelled: int
    session_completion_rate: float
    total_problems_planned: int
    total_problems_completed: int
    total_problems_skipped: int
    problem_completion_rate: float
    recent_sessions: List[Dict[str, Any]] = field(default_factory=list)


def _get_utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionTracker:
    """Local, offline session tracking and feedback engine."""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_TRACKING_DB_PATH
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initialize the local schema in the dedicated tracking database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_sessions (
                    session_id TEXT PRIMARY KEY,
                    target_language TEXT NOT NULL,
                    target_size INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    session_summary TEXT NOT NULL,
                    weak_topics_json TEXT NOT NULL,
                    covered_topics_json TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS session_problem_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    problem_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    topics_json TEXT NOT NULL,
                    priority_score REAL NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    completed_at TEXT,
                    outcome_notes TEXT,
                    FOREIGN KEY (session_id) REFERENCES learning_sessions(session_id) ON DELETE CASCADE,
                    UNIQUE(session_id, problem_id)
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_session_problems ON session_problem_items(session_id)"
            )
            conn.commit()

    def record_session(
        self,
        plan: LearningSessionPlan,
        session_id: Optional[str] = None,
    ) -> TrackedSessionRecord:
        """Record a newly generated learning session plan snapshot."""
        if not session_id:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"

        now_str = _get_utc_now_iso()
        status = SessionStatus.PLANNED

        weak_json = json.dumps(plan.weak_topics)
        covered_json = json.dumps(plan.covered_topics)

        problem_items: List[TrackedProblemItem] = []
        for p in plan.planned_problems:
            topics_json = json.dumps(p.topics)
            item = TrackedProblemItem(
                session_id=session_id,
                problem_id=p.problem_id,
                rank=p.rank,
                role=p.role.value if isinstance(p.role, SessionProblemRole) else str(p.role),
                difficulty=p.difficulty,
                topics=p.topics,
                priority_score=p.priority_score,
                reason=p.reason,
                status=ProblemProgressStatus.PENDING,
            )
            problem_items.append(item)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO learning_sessions (
                    session_id, target_language, target_size, status,
                    created_at, updated_at, completed_at,
                    session_summary, weak_topics_json, covered_topics_json
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    session_id,
                    plan.target_language,
                    plan.target_size,
                    status.value,
                    now_str,
                    now_str,
                    plan.session_summary,
                    weak_json,
                    covered_json,
                ),
            )

            for item in problem_items:
                cursor.execute(
                    """
                    INSERT INTO session_problem_items (
                        session_id, problem_id, rank, role, difficulty,
                        topics_json, priority_score, reason, status, completed_at, outcome_notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        item.session_id,
                        item.problem_id,
                        item.rank,
                        item.role,
                        item.difficulty,
                        json.dumps(item.topics),
                        item.priority_score,
                        item.reason,
                        item.status.value,
                    ),
                )
            conn.commit()

        return TrackedSessionRecord(
            session_id=session_id,
            target_language=plan.target_language,
            target_size=plan.target_size,
            status=status,
            created_at=now_str,
            updated_at=now_str,
            completed_at=None,
            session_summary=plan.session_summary,
            weak_topics=list(plan.weak_topics),
            covered_topics=list(plan.covered_topics),
            problems=problem_items,
        )

    def get_session(self, session_id: str) -> Optional[TrackedSessionRecord]:
        """Retrieve full details of a session by session ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM learning_sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            cursor.execute(
                "SELECT * FROM session_problem_items WHERE session_id = ? ORDER BY rank ASC",
                (session_id,),
            )
            p_rows = cursor.fetchall()
            problems: List[TrackedProblemItem] = []
            for p in p_rows:
                problems.append(
                    TrackedProblemItem(
                        session_id=p["session_id"],
                        problem_id=p["problem_id"],
                        rank=p["rank"],
                        role=p["role"],
                        difficulty=p["difficulty"],
                        topics=json.loads(p["topics_json"]),
                        priority_score=float(p["priority_score"]),
                        reason=p["reason"],
                        status=ProblemProgressStatus(p["status"]),
                        completed_at=p["completed_at"],
                        outcome_notes=p["outcome_notes"],
                    )
                )

            return TrackedSessionRecord(
                session_id=row["session_id"],
                target_language=row["target_language"],
                target_size=row["target_size"],
                status=SessionStatus(row["status"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                completed_at=row["completed_at"],
                session_summary=row["session_summary"],
                weak_topics=json.loads(row["weak_topics_json"]),
                covered_topics=json.loads(row["covered_topics_json"]),
                problems=problems,
            )

    def list_sessions(self, limit: int = 50) -> List[TrackedSessionRecord]:
        """List past learning sessions ordered by creation date descending."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT session_id FROM learning_sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()

        result: List[TrackedSessionRecord] = []
        for r in rows:
            sess = self.get_session(r["session_id"])
            if sess:
                result.append(sess)
        return result

    def start_session(self, session_id: str) -> TrackedSessionRecord:
        """Transition session status from planned to in_progress."""
        sess = self.get_session(session_id)
        if not sess:
            raise ValueError(f"Session '{session_id}' not found.")
        if sess.status == SessionStatus.COMPLETED:
            raise ValueError(f"Cannot start completed session '{session_id}'.")
        if sess.status == SessionStatus.CANCELLED:
            raise ValueError(f"Cannot start cancelled session '{session_id}'.")

        now_str = _get_utc_now_iso()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE learning_sessions SET status = ?, updated_at = ? WHERE session_id = ?",
                (SessionStatus.IN_PROGRESS.value, now_str, session_id),
            )
            conn.commit()

        sess.status = SessionStatus.IN_PROGRESS
        sess.updated_at = now_str
        return sess

    def update_problem_progress(
        self,
        session_id: str,
        problem_id: str,
        status: ProblemProgressStatus,
        outcome_notes: Optional[str] = None,
    ) -> TrackedSessionRecord:
        """Mark a specific planned problem as completed or skipped."""
        sess = self.get_session(session_id)
        if not sess:
            raise ValueError(f"Session '{session_id}' not found.")
        if sess.status == SessionStatus.CANCELLED:
            raise ValueError(f"Cannot update problems in cancelled session '{session_id}'.")

        # Find target problem
        target_item = next((p for p in sess.problems if p.problem_id == problem_id), None)
        if not target_item:
            raise ValueError(f"Problem '{problem_id}' is not part of session '{session_id}'.")

        now_str = _get_utc_now_iso()
        completed_at = now_str if status == ProblemProgressStatus.COMPLETED else None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE session_problem_items
                SET status = ?, completed_at = ?, outcome_notes = ?
                WHERE session_id = ? AND problem_id = ?
                """,
                (status.value, completed_at, outcome_notes, session_id, problem_id),
            )
            # Automatically advance session to in_progress if currently planned
            new_session_status = sess.status
            if sess.status == SessionStatus.PLANNED:
                new_session_status = SessionStatus.IN_PROGRESS

            cursor.execute(
                "UPDATE learning_sessions SET status = ?, updated_at = ? WHERE session_id = ?",
                (new_session_status.value, now_str, session_id),
            )
            conn.commit()

        updated_sess = self.get_session(session_id)
        assert updated_sess is not None
        return updated_sess

    def complete_session(self, session_id: str) -> TrackedSessionRecord:
        """Finalize and complete a learning session."""
        sess = self.get_session(session_id)
        if not sess:
            raise ValueError(f"Session '{session_id}' not found.")
        if sess.status == SessionStatus.CANCELLED:
            raise ValueError(f"Cannot complete cancelled session '{session_id}'.")
        if sess.status == SessionStatus.COMPLETED:
            return sess

        now_str = _get_utc_now_iso()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE learning_sessions
                SET status = ?, updated_at = ?, completed_at = ?
                WHERE session_id = ?
                """,
                (SessionStatus.COMPLETED.value, now_str, now_str, session_id),
            )
            conn.commit()

        sess.status = SessionStatus.COMPLETED
        sess.updated_at = now_str
        sess.completed_at = now_str
        return sess

    def cancel_session(self, session_id: str, reason: Optional[str] = None) -> TrackedSessionRecord:
        """Cancel a planned or in-progress session."""
        sess = self.get_session(session_id)
        if not sess:
            raise ValueError(f"Session '{session_id}' not found.")
        if sess.status == SessionStatus.COMPLETED:
            raise ValueError(f"Cannot cancel completed session '{session_id}'.")

        now_str = _get_utc_now_iso()
        summary = sess.session_summary
        if reason:
            summary = f"{summary} [Cancelled: {reason}]"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE learning_sessions
                SET status = ?, updated_at = ?, session_summary = ?
                WHERE session_id = ?
                """,
                (SessionStatus.CANCELLED.value, now_str, summary, session_id),
            )
            conn.commit()

        sess.status = SessionStatus.CANCELLED
        sess.updated_at = now_str
        sess.session_summary = summary
        return sess

    def get_analytics(self) -> TrackingAnalytics:
        """Compute aggregate offline session tracking analytics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM learning_sessions")
            s_rows = cursor.fetchall()

            cursor.execute("SELECT status FROM session_problem_items")
            p_rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT session_id, target_language, status, created_at, session_summary
                FROM learning_sessions
                ORDER BY created_at DESC
                LIMIT 5
                """
            )
            recent_rows = cursor.fetchall()

        total_sessions = len(s_rows)
        completed_sessions = sum(1 for r in s_rows if r["status"] == SessionStatus.COMPLETED.value)
        in_progress_sessions = sum(1 for r in s_rows if r["status"] == SessionStatus.IN_PROGRESS.value)
        cancelled_sessions = sum(1 for r in s_rows if r["status"] == SessionStatus.CANCELLED.value)

        session_completion_rate = (
            completed_sessions / total_sessions if total_sessions > 0 else 0.0
        )

        total_problems = len(p_rows)
        completed_problems = sum(1 for r in p_rows if r["status"] == ProblemProgressStatus.COMPLETED.value)
        skipped_problems = sum(1 for r in p_rows if r["status"] == ProblemProgressStatus.SKIPPED.value)

        problem_completion_rate = (
            completed_problems / total_problems if total_problems > 0 else 0.0
        )

        recent_sessions = [
            {
                "session_id": r["session_id"],
                "target_language": r["target_language"],
                "status": r["status"],
                "created_at": r["created_at"],
                "summary": r["session_summary"],
            }
            for r in recent_rows
        ]

        return TrackingAnalytics(
            total_sessions_planned=total_sessions,
            total_sessions_completed=completed_sessions,
            total_sessions_in_progress=in_progress_sessions,
            total_sessions_cancelled=cancelled_sessions,
            session_completion_rate=session_completion_rate,
            total_problems_planned=total_problems,
            total_problems_completed=completed_problems,
            total_problems_skipped=skipped_problems,
            problem_completion_rate=problem_completion_rate,
            recent_sessions=recent_sessions,
        )
