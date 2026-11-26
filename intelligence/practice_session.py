"""Plan-to-Practice Execution Bridge Engine.

Milestone 6.3.22: Plan-to-Practice Execution Bridge.
Provides:
1. Practice session lifecycle management:
   - States: pending, active, paused, completed, abandoned.
   - Prevention of duplicate concurrent active sessions.
   - High-fidelity elapsed time tracking across pause and resume transitions.
2. Planner Task Integration:
   - Links practice sessions to specific preparation tasks and plans.
   - Populates problem context and starter templates for coding tasks.
   - Supports non-coding tasks (complexity review, roadmap study, rubric reflection) with reflective notes.
3. Evidence Tracking:
   - Tracks local judge submissions, passed vs failed counts, and final outcome.
   - Enforces explicit task completion: a successful judge test run alone never silently marks a task complete.
   - Explicit confirmation invokes PreparationPlanner.complete_task() with verified actual elapsed minutes.
4. Comprehensive Session Notes:
   - Structured local capture of initial approach, mistakes, hints, final approach, Big-O complexities, and key learnings.
5. Audit History & Event Timeline:
   - Full event journaling for start, pause, resume, submission, notes_update, end, and task_confirm actions.

100% offline, local-first, zero external API or LLM calls.
Never fabricates judge submissions, test results, or study durations.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Tuple

from intelligence.preparation_planner import PreparationPlanner
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from languages import LanguageSupport
from problems import load_problems
import store


class PracticeSessionStatus(str, Enum):
    """Lifecycle states of a practice session."""
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_utc_now_iso() -> str:
    return _get_utc_now().isoformat()


@dataclass
class PracticeSessionNotes:
    """Learner's self-reported reflection and complexity notes."""
    initial_approach: str = ""
    mistakes_encountered: str = ""
    hints_used: str = ""
    final_approach: str = ""
    time_complexity: str = ""
    space_complexity: str = ""
    key_learning: str = ""
    follow_up_action: str = ""


@dataclass
class PracticeSessionEvent:
    """Immutable audit trail event for actions during a session."""
    event_id: str
    session_id: str
    event_type: str                   # "start", "pause", "resume", "submission", "notes_update", "end", "confirm_task"
    timestamp: str
    payload_json: str = "{}"


@dataclass
class SessionSummary:
    """Synthesized evidence-based summary of a finished or in-progress practice session."""
    session_id: str
    plan_id: Optional[str]
    task_id: Optional[str]
    task_title: Optional[str]
    task_type: Optional[str]
    problem_id: Optional[str]
    language: str
    status: str
    started_at: Optional[str]
    ended_at: Optional[str]
    total_elapsed_seconds: int
    total_elapsed_minutes: int
    submissions_count: int
    passed_submissions_count: int
    failed_submissions_count: int
    final_submission_passed: bool
    task_confirmed_completed: bool
    notes: PracticeSessionNotes
    events_count: int
    key_learnings_summary: str


@dataclass
class PracticeSession:
    """Active or historical practice session container."""
    session_id: str
    plan_id: Optional[str]
    task_id: Optional[str]
    task_title: Optional[str]
    task_type: Optional[str]
    problem_id: Optional[str]
    language: str
    status: str
    created_at: str
    started_at: Optional[str]
    paused_at: Optional[str]
    ended_at: Optional[str]
    elapsed_seconds: int
    submissions_count: int
    passed_submissions_count: int
    failed_submissions_count: int
    final_submission_passed: bool
    task_confirmed_completed: bool
    notes: PracticeSessionNotes = field(default_factory=PracticeSessionNotes)
    events: List[PracticeSessionEvent] = field(default_factory=list)


class PracticeSessionManager:
    """Coordinates practice session lifecycle, submission evidence tracking, and planner bridging."""

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
        """Create practice session tables non-destructively in session_tracking.db."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS practice_sessions (
                    session_id TEXT PRIMARY KEY,
                    plan_id TEXT,
                    task_id TEXT,
                    task_title TEXT,
                    task_type TEXT,
                    problem_id TEXT,
                    language TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    paused_at TEXT,
                    ended_at TEXT,
                    elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                    submissions_count INTEGER NOT NULL DEFAULT 0,
                    passed_submissions_count INTEGER NOT NULL DEFAULT 0,
                    failed_submissions_count INTEGER NOT NULL DEFAULT 0,
                    final_submission_passed INTEGER NOT NULL DEFAULT 0,
                    task_confirmed_completed INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS practice_session_notes (
                    session_id TEXT PRIMARY KEY,
                    initial_approach TEXT NOT NULL DEFAULT '',
                    mistakes_encountered TEXT NOT NULL DEFAULT '',
                    hints_used TEXT NOT NULL DEFAULT '',
                    final_approach TEXT NOT NULL DEFAULT '',
                    time_complexity TEXT NOT NULL DEFAULT '',
                    space_complexity TEXT NOT NULL DEFAULT '',
                    key_learning TEXT NOT NULL DEFAULT '',
                    follow_up_action TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES practice_sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS practice_session_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES practice_sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_ps_status ON practice_sessions(status)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_ps_task ON practice_sessions(task_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_pse_session ON practice_session_events(session_id, timestamp)"
            )
            conn.commit()

    # -------------------------------------------------------------------------
    # Active Session Inspection
    # -------------------------------------------------------------------------

    def get_active_session(self) -> Optional[PracticeSession]:
        """Fetch the current active or paused practice session if any."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT session_id FROM practice_sessions WHERE status IN (?, ?) ORDER BY created_at DESC LIMIT 1",
                (PracticeSessionStatus.ACTIVE.value, PracticeSessionStatus.PAUSED.value),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self.get_session(row["session_id"])

    def get_session(self, session_id: str) -> Optional[PracticeSession]:
        """Retrieve full practice session with current notes, events, and live elapsed seconds."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM practice_sessions WHERE session_id = ?", (session_id,))
            s_row = cursor.fetchone()
            if not s_row:
                return None

            cursor.execute("SELECT * FROM practice_session_notes WHERE session_id = ?", (session_id,))
            n_row = cursor.fetchone()

            cursor.execute("SELECT * FROM practice_session_events WHERE session_id = ? ORDER BY timestamp ASC", (session_id,))
            e_rows = cursor.fetchall()

        notes = PracticeSessionNotes()
        if n_row:
            notes = PracticeSessionNotes(
                initial_approach=n_row["initial_approach"] or "",
                mistakes_encountered=n_row["mistakes_encountered"] or "",
                hints_used=n_row["hints_used"] or "",
                final_approach=n_row["final_approach"] or "",
                time_complexity=n_row["time_complexity"] or "",
                space_complexity=n_row["space_complexity"] or "",
                key_learning=n_row["key_learning"] or "",
                follow_up_action=n_row["follow_up_action"] or "",
            )

        events = [
            PracticeSessionEvent(
                event_id=er["event_id"],
                session_id=er["session_id"],
                event_type=er["event_type"],
                timestamp=er["timestamp"],
                payload_json=er["payload_json"] or "{}",
            )
            for er in e_rows
        ]

        # Calculate live elapsed seconds if active
        elapsed = s_row["elapsed_seconds"]
        if s_row["status"] == PracticeSessionStatus.ACTIVE.value and s_row["started_at"]:
            try:
                start_dt = datetime.fromisoformat(s_row["started_at"]).replace(tzinfo=timezone.utc)
                live_delta = max(0, int((_get_utc_now() - start_dt).total_seconds()))
                elapsed += live_delta
            except Exception:
                pass

        return PracticeSession(
            session_id=s_row["session_id"],
            plan_id=s_row["plan_id"],
            task_id=s_row["task_id"],
            task_title=s_row["task_title"],
            task_type=s_row["task_type"],
            problem_id=s_row["problem_id"],
            language=s_row["language"],
            status=s_row["status"],
            created_at=s_row["created_at"],
            started_at=s_row["started_at"],
            paused_at=s_row["paused_at"],
            ended_at=s_row["ended_at"],
            elapsed_seconds=elapsed,
            submissions_count=s_row["submissions_count"],
            passed_submissions_count=s_row["passed_submissions_count"],
            failed_submissions_count=s_row["failed_submissions_count"],
            final_submission_passed=bool(s_row["final_submission_passed"]),
            task_confirmed_completed=bool(s_row["task_confirmed_completed"]),
            notes=notes,
            events=events,
        )

    # -------------------------------------------------------------------------
    # Session Lifecycle: Start, Pause, Resume, End
    # -------------------------------------------------------------------------

    def start_session(
        self,
        task_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        problem_id: Optional[str] = None,
        language: str = "python",
        force_switch: bool = False,
    ) -> PracticeSession:
        """Start a new practice session, either from a planner task or standalone."""
        # Check duplicate active session
        active = self.get_active_session()
        if active and not force_switch:
            raise ValueError(
                f"An active practice session ('{active.session_id}') is already in progress. "
                "Pause or end it before starting a new one."
            )

        norm_lang = LanguageSupport.normalize_language(language) if language else "python"
        now_str = _get_utc_now_iso()
        session_id = f"psess_{uuid.uuid4().hex[:10]}"

        final_plan_id = plan_id
        final_task_id = task_id
        task_title = None
        task_type = None
        final_problem_id = problem_id

        # If task_id provided, look up metadata from preparation_tasks
        if task_id:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM preparation_tasks WHERE task_id = ?", (task_id,))
                t_row = cursor.fetchone()
                if t_row:
                    final_plan_id = t_row["plan_id"]
                    task_title = t_row["title"]
                    task_type = t_row["task_type"]
                    if not final_problem_id and t_row["problem_id"]:
                        final_problem_id = t_row["problem_id"]

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO practice_sessions (
                    session_id, plan_id, task_id, task_title, task_type, problem_id,
                    language, status, created_at, started_at, paused_at, ended_at,
                    elapsed_seconds, submissions_count, passed_submissions_count,
                    failed_submissions_count, final_submission_passed, task_confirmed_completed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, 0, 0, 0, 0, 0)
                """,
                (
                    session_id,
                    final_plan_id,
                    final_task_id,
                    task_title,
                    task_type,
                    final_problem_id,
                    norm_lang,
                    PracticeSessionStatus.ACTIVE.value,
                    now_str,
                    now_str,
                ),
            )
            # Initialize empty notes record
            cursor.execute(
                """
                INSERT INTO practice_session_notes (
                    session_id, initial_approach, mistakes_encountered, hints_used,
                    final_approach, time_complexity, space_complexity, key_learning,
                    follow_up_action, updated_at
                ) VALUES (?, '', '', '', '', '', '', '', '', ?)
                """,
                (session_id, now_str),
            )
            conn.commit()

        self._record_event(session_id, "start", {
            "task_id": final_task_id,
            "problem_id": final_problem_id,
            "language": norm_lang,
        })

        session = self.get_session(session_id)
        assert session is not None
        return session

    def pause_session(self, session_id: str) -> PracticeSession:
        """Pause an active session and freeze elapsed time."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Practice session '{session_id}' not found.")

        if session.status == PracticeSessionStatus.PAUSED.value:
            raise ValueError(f"Session '{session_id}' is already paused.")

        if session.status in (PracticeSessionStatus.COMPLETED.value, PracticeSessionStatus.ABANDONED.value):
            raise ValueError(f"Cannot pause a session in terminal status '{session.status}'.")

        now_str = _get_utc_now_iso()
        # Compute elapsed delta
        delta_sec = 0
        if session.started_at:
            try:
                start_dt = datetime.fromisoformat(session.started_at).replace(tzinfo=timezone.utc)
                delta_sec = max(0, int((_get_utc_now() - start_dt).total_seconds()))
            except Exception:
                pass

        new_total_elapsed = session.elapsed_seconds + delta_sec

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE practice_sessions
                SET status = ?, elapsed_seconds = ?, paused_at = ?
                WHERE session_id = ?
                """,
                (PracticeSessionStatus.PAUSED.value, new_total_elapsed, now_str, session_id),
            )
            conn.commit()

        self._record_event(session_id, "pause", {"elapsed_seconds": new_total_elapsed})
        updated = self.get_session(session_id)
        assert updated is not None
        return updated

    def resume_session(self, session_id: str) -> PracticeSession:
        """Resume a paused practice session."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Practice session '{session_id}' not found.")

        if session.status == PracticeSessionStatus.ACTIVE.value:
            raise ValueError(f"Session '{session_id}' is already active.")

        if session.status in (PracticeSessionStatus.COMPLETED.value, PracticeSessionStatus.ABANDONED.value):
            raise ValueError(f"Cannot resume a session in terminal status '{session.status}'.")

        now_str = _get_utc_now_iso()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE practice_sessions
                SET status = ?, started_at = ?, paused_at = NULL
                WHERE session_id = ?
                """,
                (PracticeSessionStatus.ACTIVE.value, now_str, session_id),
            )
            conn.commit()

        self._record_event(session_id, "resume", {"resumed_at": now_str})
        updated = self.get_session(session_id)
        assert updated is not None
        return updated

    def end_session(
        self,
        session_id: str,
        status: str = PracticeSessionStatus.COMPLETED.value,
    ) -> PracticeSession:
        """End a session as either completed or abandoned."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Practice session '{session_id}' not found.")

        valid_terminal = [PracticeSessionStatus.COMPLETED.value, PracticeSessionStatus.ABANDONED.value]
        if status not in valid_terminal:
            raise ValueError(f"Invalid terminal status '{status}'. Must be one of {valid_terminal}.")

        if session.status in valid_terminal:
            raise ValueError(f"Session '{session_id}' is already {session.status}.")

        now_str = _get_utc_now_iso()
        total_elapsed = session.elapsed_seconds
        # If currently active, compute final delta
        if session.status == PracticeSessionStatus.ACTIVE.value and session.started_at:
            try:
                start_dt = datetime.fromisoformat(session.started_at).replace(tzinfo=timezone.utc)
                delta_sec = max(0, int((_get_utc_now() - start_dt).total_seconds()))
                total_elapsed += delta_sec
            except Exception:
                pass

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE practice_sessions
                SET status = ?, elapsed_seconds = ?, ended_at = ?
                WHERE session_id = ?
                """,
                (status, total_elapsed, now_str, session_id),
            )
            conn.commit()

        self._record_event(session_id, "end", {
            "status": status,
            "total_elapsed_seconds": total_elapsed,
        })

        updated = self.get_session(session_id)
        assert updated is not None
        return updated

    # -------------------------------------------------------------------------
    # Evidence & Submission Recording
    # -------------------------------------------------------------------------

    def record_submission(
        self,
        session_id: str,
        status: str,
        passed_count: int = 0,
        total_tests: int = 0,
        runtime_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> PracticeSession:
        """Record outcome of a code execution attempt within this session."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Practice session '{session_id}' not found.")

        if session.status in (PracticeSessionStatus.COMPLETED.value, PracticeSessionStatus.ABANDONED.value):
            raise ValueError(f"Cannot record submissions for a session in terminal status '{session.status}'.")

        is_passed = (status == "passed")
        passed_inc = 1 if is_passed else 0
        failed_inc = 0 if is_passed else 1

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE practice_sessions
                SET submissions_count = submissions_count + 1,
                    passed_submissions_count = passed_submissions_count + ?,
                    failed_submissions_count = failed_submissions_count + ?,
                    final_submission_passed = ?
                WHERE session_id = ?
                """,
                (passed_inc, failed_inc, 1 if is_passed else 0, session_id),
            )
            conn.commit()

        self._record_event(session_id, "submission", {
            "status": status,
            "passed_count": passed_count,
            "total_tests": total_tests,
            "runtime_ms": runtime_ms,
            "error": error,
        })

        updated = self.get_session(session_id)
        assert updated is not None
        return updated

    # -------------------------------------------------------------------------
    # Reflection & Notes Management
    # -------------------------------------------------------------------------

    def save_notes(
        self,
        session_id: str,
        notes: PracticeSessionNotes | Dict[str, Any],
    ) -> PracticeSessionNotes:
        """Save learner reflection notes for the session."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Practice session '{session_id}' not found.")

        if isinstance(notes, PracticeSessionNotes):
            n_dict = asdict(notes)
        else:
            n_dict = dict(notes)

        now_str = _get_utc_now_iso()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO practice_session_notes (
                    session_id, initial_approach, mistakes_encountered, hints_used,
                    final_approach, time_complexity, space_complexity, key_learning,
                    follow_up_action, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    initial_approach=excluded.initial_approach,
                    mistakes_encountered=excluded.mistakes_encountered,
                    hints_used=excluded.hints_used,
                    final_approach=excluded.final_approach,
                    time_complexity=excluded.time_complexity,
                    space_complexity=excluded.space_complexity,
                    key_learning=excluded.key_learning,
                    follow_up_action=excluded.follow_up_action,
                    updated_at=excluded.updated_at
                """,
                (
                    session_id,
                    n_dict.get("initial_approach", ""),
                    n_dict.get("mistakes_encountered", ""),
                    n_dict.get("hints_used", ""),
                    n_dict.get("final_approach", ""),
                    n_dict.get("time_complexity", ""),
                    n_dict.get("space_complexity", ""),
                    n_dict.get("key_learning", ""),
                    n_dict.get("follow_up_action", ""),
                    now_str,
                ),
            )
            conn.commit()

        self._record_event(session_id, "notes_update", {"updated_at": now_str})
        refreshed = self.get_session(session_id)
        assert refreshed is not None
        return refreshed.notes

    # -------------------------------------------------------------------------
    # Explicit Task Confirmation (Bridge to PreparationPlanner)
    # -------------------------------------------------------------------------

    def confirm_task_completion(
        self,
        session_id: str,
        notes: Optional[Dict[str, Any]] = None,
    ) -> PracticeSession:
        """Explicitly confirm completion of the associated planner task with real study evidence."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Practice session '{session_id}' not found.")

        if not session.task_id:
            raise ValueError(f"Cannot confirm task completion: session '{session_id}' is not linked to a planner task.")

        if notes:
            self.save_notes(session_id, notes)

        # Calculate actual minutes
        actual_min = max(1, (session.elapsed_seconds + 30) // 60)

        # Call PreparationPlanner to complete task non-destructively
        planner = PreparationPlanner(
            tracking_db_path=self.tracking_db_path,
            progress_db_path=self.progress_db_path,
        )
        planner.complete_task(session.task_id, actual_minutes=actual_min)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE practice_sessions
                SET task_confirmed_completed = 1
                WHERE session_id = ?
                """,
                (session_id,),
            )
            conn.commit()

        self._record_event(session_id, "confirm_task", {
            "task_id": session.task_id,
            "actual_minutes": actual_min,
        })

        # If session is still active or paused, end it as completed
        if session.status in (PracticeSessionStatus.ACTIVE.value, PracticeSessionStatus.PAUSED.value):
            self.end_session(session_id, status=PracticeSessionStatus.COMPLETED.value)

        updated = self.get_session(session_id)
        assert updated is not None
        return updated

    # -------------------------------------------------------------------------
    # Summaries & History
    # -------------------------------------------------------------------------

    def get_session_summary(self, session_id: str) -> SessionSummary:
        """Synthesize high-level structured evidence summary for a session."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Practice session '{session_id}' not found.")

        elapsed_min = max(0, (session.elapsed_seconds + 30) // 60)
        kl = session.notes.key_learning or "No explicit key learnings recorded."

        return SessionSummary(
            session_id=session.session_id,
            plan_id=session.plan_id,
            task_id=session.task_id,
            task_title=session.task_title,
            task_type=session.task_type,
            problem_id=session.problem_id,
            language=session.language,
            status=session.status,
            started_at=session.started_at,
            ended_at=session.ended_at,
            total_elapsed_seconds=session.elapsed_seconds,
            total_elapsed_minutes=elapsed_min,
            submissions_count=session.submissions_count,
            passed_submissions_count=session.passed_submissions_count,
            failed_submissions_count=session.failed_submissions_count,
            final_submission_passed=session.final_submission_passed,
            task_confirmed_completed=session.task_confirmed_completed,
            notes=session.notes,
            events_count=len(session.events),
            key_learnings_summary=kl,
        )

    def list_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List historical practice sessions."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT session_id, plan_id, task_id, task_title, task_type, problem_id,
                       language, status, created_at, started_at, ended_at, elapsed_seconds,
                       submissions_count, passed_submissions_count, failed_submissions_count,
                       final_submission_passed, task_confirmed_completed
                FROM practice_sessions
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Internal Event Logger
    # -------------------------------------------------------------------------

    def _record_event(self, session_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        """Internal append-only event logging."""
        event_id = f"pevt_{uuid.uuid4().hex[:10]}"
        now_str = _get_utc_now_iso()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO practice_session_events (
                    event_id, session_id, event_type, timestamp, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, session_id, event_type, now_str, json.dumps(payload)),
            )
            conn.commit()
