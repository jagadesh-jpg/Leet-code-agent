"""Offline Mock Interview & Assessment Mode Engine.

Milestone 6.3.19: Offline Mock Interview & Assessment Mode.
Provides:
1. InterviewManager coordinating full interview sessions under time constraints (30, 45, 60 minutes).
2. Difficulty tracks: Beginner, Intermediate, Advanced, Mixed, selected from existing local problem inventory.
3. Strict lifecycle state management: created, in_progress, completed, expired, cancelled.
4. Timestamp-based time calculation (elapsed, remaining, expired) without background worker timers.
5. UnifiedJudge integration for live test case execution and submission persistence.
6. Transparent 5-category scoring rubric (Correctness 40%, Completion 20%, Structure & Readability 15%, Complexity Awareness 15%, Time Management 10%).
7. Evidence-based pedagogical assessment reports with actionable feedback, DSA roadmap guidance, and spaced repetition revisions.
8. Safe, non-destructive persistence in session_tracking.db.

100% offline, local-first, zero external API or LLM calls.
Never exposes reference solutions or hidden internal test paths.
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

from adapters import UnifiedJudge
from intelligence.roadmap import DsaRoadmapEngine
from intelligence.revision import SpacedRevisionEngine
from intelligence.solution_review import SolutionReviewEngine
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from intelligence.workspace import ProblemWorkspaceContext, WorkspaceManager
from languages import LanguageSupport
from problems import load_problems
import store

ASSESSMENT_DISCLAIMER = (
    "This assessment is calculated deterministically from local test runs and static code analysis. "
    "It does not measure real-world hiring probability or guarantee interview readiness."
)


class InterviewTrack(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    MIXED = "mixed"


class InterviewStatus(str, Enum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_utc_now_iso() -> str:
    return _get_utc_now().isoformat()


@dataclass
class InterviewProblemItem:
    """Individual problem assigned to a mock interview session."""
    problem_id: str
    problem_order: int
    difficulty: str
    title: str
    status: str = "unattempted"          # "unattempted", "attempted", "passed", "failed"
    time_spent_seconds: int = 0
    best_passed_count: int = 0
    total_tests: int = 0


@dataclass
class InterviewSubmission:
    """Recorded solution submission during a mock interview."""
    submission_id: str
    interview_id: str
    problem_id: str
    language: str
    code: str
    status: str                          # "passed", "wrong_answer", "runtime_error", "compile_error", "timeout"
    passed_count: int
    total_tests: int
    runtime_ms: Optional[float]
    submitted_at: str
    is_after_expiry: bool = False
    readability_score: float = 0.0
    structural_score: float = 0.0
    complexity_score: float = 0.0
    estimated_time_complexity: str = "Unknown"
    estimated_space_complexity: str = "Unknown"
    error_detail: Optional[str] = None


@dataclass
class RubricScoreBreakdown:
    """Transparent scoring rubric derived directly from measurable local evidence."""
    correctness_score: float             # 0 - 40.0 (Ratio of test cases passed)
    completion_score: float              # 0 - 20.0 (Ratio of problems completely solved)
    structure_score: float               # 0 - 15.0 (AST readability & clean structure)
    complexity_score: float              # 0 - 15.0 (Heuristic time-space complexity awareness)
    time_management_score: float         # 0 - 10.0 (Pacing and completion within time bounds)
    total_score: float                   # 0 - 100.0 (Sum of weighted categories)
    explanation: str = ""


@dataclass
class AssessmentReport:
    """Comprehensive evaluation and actionable feedback report for a completed mock interview."""
    interview_id: str
    title: str
    track: str
    language: str
    duration_minutes: int
    started_at: Optional[str]
    completed_at: Optional[str]
    time_taken_seconds: int
    is_expired: bool
    status: str
    rubric: RubricScoreBreakdown
    problems_summary: List[Dict[str, Any]]
    correctness_observations: List[str]
    time_management_observations: List[str]
    code_quality_observations: List[str]
    complexity_observations: List[str]
    recommended_topics: List[str]
    recommended_revisions: List[str]
    summary_feedback: str
    disclaimer: str = ASSESSMENT_DISCLAIMER


@dataclass
class MockInterviewSession:
    """Active or historical state of a mock interview."""
    interview_id: str
    title: str
    track: str
    duration_minutes: int
    language: str
    problem_count: int
    current_problem_index: int
    status: str
    created_at: str
    started_at: Optional[str]
    expires_at: Optional[str]
    completed_at: Optional[str]
    elapsed_seconds: int
    remaining_seconds: int
    is_expired: bool
    problems: List[InterviewProblemItem]
    submissions: List[InterviewSubmission] = field(default_factory=list)
    assessment: Optional[AssessmentReport] = None


class InterviewManager:
    """Manages interview lifecycle, problem selection, execution, scoring, and history."""

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
        """Create mock interview tables non-destructively in session_tracking.db."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_interviews (
                    interview_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    track TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    language TEXT NOT NULL,
                    problem_count INTEGER NOT NULL,
                    current_problem_index INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    expires_at TEXT,
                    completed_at TEXT,
                    total_score REAL,
                    correctness_score REAL,
                    completion_score REAL,
                    structure_score REAL,
                    complexity_score REAL,
                    time_management_score REAL,
                    summary_feedback TEXT,
                    rubric_breakdown_json TEXT,
                    recommendations_json TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_interview_problems (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    interview_id TEXT NOT NULL,
                    problem_id TEXT NOT NULL,
                    problem_order INTEGER NOT NULL,
                    difficulty TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'unattempted',
                    time_spent_seconds INTEGER NOT NULL DEFAULT 0,
                    best_passed_count INTEGER NOT NULL DEFAULT 0,
                    total_tests INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (interview_id) REFERENCES mock_interviews(interview_id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_interview_submissions (
                    submission_id TEXT PRIMARY KEY,
                    interview_id TEXT NOT NULL,
                    problem_id TEXT NOT NULL,
                    language TEXT NOT NULL,
                    code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    passed_count INTEGER NOT NULL,
                    total_tests INTEGER NOT NULL,
                    runtime_ms REAL,
                    submitted_at TEXT NOT NULL,
                    is_after_expiry INTEGER NOT NULL DEFAULT 0,
                    readability_score REAL,
                    structural_score REAL,
                    complexity_score REAL,
                    estimated_time_complexity TEXT,
                    estimated_space_complexity TEXT,
                    error_detail TEXT,
                    FOREIGN KEY (interview_id) REFERENCES mock_interviews(interview_id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()

    # -------------------------------------------------------------------------
    # Problem Selection & Track Filtering
    # -------------------------------------------------------------------------

    def select_problems_for_track(
        self,
        track: str = "intermediate",
        problem_count: int = 2,
    ) -> List[Dict[str, Any]]:
        """Select a deterministic sequence of problems from local inventory matching the track."""
        norm_track = track.strip().lower()
        if norm_track not in ("beginner", "intermediate", "advanced", "mixed"):
            raise ValueError(f"Invalid track '{track}'. Must be 'beginner', 'intermediate', 'advanced', or 'mixed'.")

        all_problems = load_problems()
        # Merge custom problems from progress_db if available
        if self.progress_db_path:
            try:
                custom_probs = store.list_custom_problems(db_path=self.progress_db_path)
                for cp in custom_probs:
                    if not any(p.get("id") == cp.get("id") for p in all_problems):
                        all_problems.append(cp)
            except Exception:
                pass

        easy_probs = [p for p in all_problems if p.get("difficulty", "").lower() == "easy"]
        med_probs = [p for p in all_problems if p.get("difficulty", "").lower() == "medium"]
        hard_probs = [p for p in all_problems if p.get("difficulty", "").lower() == "hard"]

        count = max(1, min(problem_count, 5))
        selected: List[Dict[str, Any]] = []

        if norm_track == "beginner":
            pool = easy_probs + med_probs
            selected = pool[:count]
        elif norm_track == "intermediate":
            pool = med_probs + easy_probs + hard_probs
            selected = pool[:count]
        elif norm_track == "advanced":
            pool = hard_probs + med_probs
            selected = pool[:count]
        elif norm_track == "mixed":
            # Balanced selection across difficulties
            slots = []
            if count == 1:
                slots = med_probs or easy_probs or hard_probs
            elif count == 2:
                slots = (easy_probs[:1] or med_probs[:1]) + (med_probs[:1] or hard_probs[:1])
            else:
                slots = (easy_probs[:1]) + (med_probs[:1]) + (hard_probs[:1])
                # Fill remaining if needed
                remaining_pool = [p for p in (easy_probs[1:] + med_probs[1:] + hard_probs[1:]) if p not in slots]
                slots.extend(remaining_pool[: count - len(slots)])
            selected = slots[:count]

        if not selected and all_problems:
            selected = all_problems[:count]

        if not selected:
            raise ValueError("No problems available in local inventory to create interview.")

        return selected

    # -------------------------------------------------------------------------
    # Interview Lifecycle Management
    # -------------------------------------------------------------------------

    def create_interview(
        self,
        track: str = "intermediate",
        duration_minutes: int = 45,
        language: str = "python",
        problem_count: int = 2,
        title: Optional[str] = None,
        auto_start: bool = True,
    ) -> MockInterviewSession:
        """Create and optionally start a new mock interview session."""
        norm_track = track.strip().lower()
        if norm_track not in ("beginner", "intermediate", "advanced", "mixed"):
            raise ValueError(f"Invalid track '{track}'. Must be 'beginner', 'intermediate', 'advanced', or 'mixed'.")

        valid_durations = (30, 45, 60)
        if duration_minutes not in valid_durations:
            raise ValueError(f"Invalid duration {duration_minutes}. Must be one of {valid_durations} minutes.")

        norm_lang = LanguageSupport.normalize_language(language)
        count = max(1, min(problem_count, 5))

        chosen_problems = self.select_problems_for_track(track=norm_track, problem_count=count)
        interview_id = f"mock_{uuid.uuid4().hex[:10]}"
        now = _get_utc_now()
        now_str = now.isoformat()

        session_title = title.strip() if title and title.strip() else f"{norm_track.title()} Coding Assessment ({duration_minutes}m)"

        started_at = None
        expires_at = None
        status = InterviewStatus.CREATED.value

        if auto_start:
            started_at = now_str
            expires_at = (now + timedelta(minutes=duration_minutes)).isoformat()
            status = InterviewStatus.IN_PROGRESS.value

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO mock_interviews (
                    interview_id, title, track, duration_minutes, language, problem_count,
                    current_problem_index, status, created_at, started_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    interview_id,
                    session_title,
                    norm_track,
                    duration_minutes,
                    norm_lang,
                    len(chosen_problems),
                    status,
                    now_str,
                    started_at,
                    expires_at,
                ),
            )

            for order, p in enumerate(chosen_problems):
                cursor.execute(
                    """
                    INSERT INTO mock_interview_problems (
                        interview_id, problem_id, problem_order, difficulty, title,
                        status, time_spent_seconds, best_passed_count, total_tests
                    ) VALUES (?, ?, ?, ?, ?, 'unattempted', 0, 0, ?)
                    """,
                    (
                        interview_id,
                        p.get("id"),
                        order,
                        p.get("difficulty", "medium").lower(),
                        p.get("title", p.get("id", "").replace("-", " ").title()),
                        len(p.get("test_cases", [])),
                    ),
                )
            conn.commit()

        return self.get_interview(interview_id)

    def start_interview(self, interview_id: str) -> MockInterviewSession:
        """Start a planned interview session. Sets started_at and expires_at."""
        interview = self.get_interview(interview_id)
        if not interview:
            raise ValueError(f"Interview '{interview_id}' not found.")

        if interview.status == InterviewStatus.IN_PROGRESS.value:
            return interview
        if interview.status in (InterviewStatus.COMPLETED.value, InterviewStatus.CANCELLED.value):
            raise ValueError(f"Cannot start interview in terminal state '{interview.status}'.")

        now = _get_utc_now()
        now_str = now.isoformat()
        expires_str = (now + timedelta(minutes=interview.duration_minutes)).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE mock_interviews
                SET status = ?, started_at = ?, expires_at = ?
                WHERE interview_id = ?
                """,
                (InterviewStatus.IN_PROGRESS.value, now_str, expires_str, interview_id),
            )
            conn.commit()

        return self.get_interview(interview_id)

    def get_interview(self, interview_id: str) -> Optional[MockInterviewSession]:
        """Fetch interview session with computed elapsed time, remaining time, and expiration."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mock_interviews WHERE interview_id = ?", (interview_id,))
            row = cursor.fetchone()
            if not row:
                return None

            cursor.execute(
                "SELECT * FROM mock_interview_problems WHERE interview_id = ? ORDER BY problem_order ASC",
                (interview_id,),
            )
            prob_rows = cursor.fetchall()

            cursor.execute(
                "SELECT * FROM mock_interview_submissions WHERE interview_id = ? ORDER BY submitted_at ASC",
                (interview_id,),
            )
            sub_rows = cursor.fetchall()

        problems = [
            InterviewProblemItem(
                problem_id=r["problem_id"],
                problem_order=r["problem_order"],
                difficulty=r["difficulty"],
                title=r["title"],
                status=r["status"],
                time_spent_seconds=r["time_spent_seconds"],
                best_passed_count=r["best_passed_count"],
                total_tests=r["total_tests"],
            )
            for r in prob_rows
        ]

        submissions = [
            InterviewSubmission(
                submission_id=s["submission_id"],
                interview_id=s["interview_id"],
                problem_id=s["problem_id"],
                language=s["language"],
                code=s["code"],
                status=s["status"],
                passed_count=s["passed_count"],
                total_tests=s["total_tests"],
                runtime_ms=s["runtime_ms"],
                submitted_at=s["submitted_at"],
                is_after_expiry=bool(s["is_after_expiry"]),
                readability_score=s["readability_score"] or 0.0,
                structural_score=s["structural_score"] or 0.0,
                complexity_score=s["complexity_score"] or 0.0,
                estimated_time_complexity=s["estimated_time_complexity"] or "Unknown",
                estimated_space_complexity=s["estimated_space_complexity"] or "Unknown",
                error_detail=s["error_detail"],
            )
            for s in sub_rows
        ]

        status = row["status"]
        started_at = row["started_at"]
        expires_at = row["expires_at"]
        completed_at = row["completed_at"]
        duration_mins = row["duration_minutes"]

        now = _get_utc_now()
        is_expired = False
        elapsed_seconds = 0
        remaining_seconds = duration_mins * 60

        if started_at:
            try:
                start_dt = datetime.fromisoformat(started_at)
                if expires_at:
                    expire_dt = datetime.fromisoformat(expires_at)
                else:
                    expire_dt = start_dt + timedelta(minutes=duration_mins)

                if status == InterviewStatus.IN_PROGRESS.value:
                    if now >= expire_dt:
                        is_expired = True
                        elapsed_seconds = int((expire_dt - start_dt).total_seconds())
                        remaining_seconds = 0
                    else:
                        elapsed_seconds = int((now - start_dt).total_seconds())
                        remaining_seconds = max(0, int((expire_dt - now).total_seconds()))
                else:
                    # Completed, cancelled, or expired
                    finish_dt = datetime.fromisoformat(completed_at) if completed_at else now
                    elapsed_seconds = max(0, int((finish_dt - start_dt).total_seconds()))
                    remaining_seconds = 0
                    if finish_dt > expire_dt:
                        is_expired = True
            except Exception:
                pass

        # Build assessment report if evaluated
        assessment = None
        if row["total_score"] is not None:
            rubric_json = json.loads(row["rubric_breakdown_json"] or "{}")
            recs_json = json.loads(row["recommendations_json"] or "{}")

            rubric = RubricScoreBreakdown(
                correctness_score=row["correctness_score"] or 0.0,
                completion_score=row["completion_score"] or 0.0,
                structure_score=row["structure_score"] or 0.0,
                complexity_score=row["complexity_score"] or 0.0,
                time_management_score=row["time_management_score"] or 0.0,
                total_score=row["total_score"] or 0.0,
                explanation=rubric_json.get("explanation", ""),
            )

            assessment = AssessmentReport(
                interview_id=row["interview_id"],
                title=row["title"],
                track=row["track"],
                language=row["language"],
                duration_minutes=duration_mins,
                started_at=started_at,
                completed_at=completed_at,
                time_taken_seconds=elapsed_seconds,
                is_expired=is_expired,
                status=status,
                rubric=rubric,
                problems_summary=[asdict(p) for p in problems],
                correctness_observations=recs_json.get("correctness", []),
                time_management_observations=recs_json.get("time_management", []),
                code_quality_observations=recs_json.get("code_quality", []),
                complexity_observations=recs_json.get("complexity", []),
                recommended_topics=recs_json.get("topics", []),
                recommended_revisions=recs_json.get("revisions", []),
                summary_feedback=row["summary_feedback"] or "",
            )

        return MockInterviewSession(
            interview_id=row["interview_id"],
            title=row["title"],
            track=row["track"],
            duration_minutes=duration_mins,
            language=row["language"],
            problem_count=row["problem_count"],
            current_problem_index=row["current_problem_index"],
            status=status,
            created_at=row["created_at"],
            started_at=started_at,
            expires_at=expires_at,
            completed_at=completed_at,
            elapsed_seconds=elapsed_seconds,
            remaining_seconds=remaining_seconds,
            is_expired=is_expired,
            problems=problems,
            submissions=submissions,
            assessment=assessment,
        )

    def get_active_interview(self) -> Optional[MockInterviewSession]:
        """Fetch currently active interview session if one exists."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT interview_id FROM mock_interviews WHERE status = ? ORDER BY created_at DESC LIMIT 1",
                (InterviewStatus.IN_PROGRESS.value,),
            )
            row = cursor.fetchone()
            if row:
                return self.get_interview(row["interview_id"])
        return None

    # -------------------------------------------------------------------------
    # Problem Context, Draft & Solution Submission
    # -------------------------------------------------------------------------

    def get_current_problem(
        self,
        interview_id: str,
        problem_index: Optional[int] = None,
    ) -> ProblemWorkspaceContext:
        """Fetch current problem context for active interview without exposing solutions."""
        interview = self.get_interview(interview_id)
        if not interview:
            raise ValueError(f"Interview '{interview_id}' not found.")

        idx = problem_index if problem_index is not None else interview.current_problem_index
        if idx < 0 or idx >= len(interview.problems):
            idx = 0

        target_prob = interview.problems[idx]
        ws_mgr = WorkspaceManager(
            tracking_db_path=self.tracking_db_path,
            progress_db_path=self.progress_db_path,
            language=interview.language,
        )
        ctx = ws_mgr.get_problem_context(
            problem_id=target_prob.problem_id,
            mission_id=interview_id,
            task_id=f"prob_{target_prob.problem_order}",
        )
        return ctx

    def save_draft(
        self,
        interview_id: str,
        code: str,
        problem_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save draft code for the current interview problem."""
        interview = self.get_interview(interview_id)
        if not interview:
            raise ValueError(f"Interview '{interview_id}' not found.")

        if interview.status != InterviewStatus.IN_PROGRESS.value:
            raise ValueError(f"Cannot save draft for interview in status '{interview.status}'.")

        target_pid = problem_id
        if not target_pid:
            idx = min(interview.current_problem_index, len(interview.problems) - 1)
            target_pid = interview.problems[idx].problem_id

        ws_mgr = WorkspaceManager(
            tracking_db_path=self.tracking_db_path,
            progress_db_path=self.progress_db_path,
            language=interview.language,
        )
        draft = ws_mgr.save_draft(
            problem_id=target_pid,
            language=interview.language,
            code=code,
        )
        return asdict(draft)

    def submit_solution(
        self,
        interview_id: str,
        code: Optional[str] = None,
        problem_id: Optional[str] = None,
        timeout: int = 10,
    ) -> InterviewSubmission:
        """Execute solution code using existing local judge and persist interview submission."""
        interview = self.get_interview(interview_id)
        if not interview:
            raise ValueError(f"Interview '{interview_id}' not found.")

        if interview.status in (InterviewStatus.COMPLETED.value, InterviewStatus.CANCELLED.value):
            raise ValueError(f"Cannot submit solution to interview in terminal status '{interview.status}'.")

        # Determine target problem
        target_pid = problem_id
        if not target_pid:
            idx = min(interview.current_problem_index, len(interview.problems) - 1)
            target_pid = interview.problems[idx].problem_id

        prob_item = next((p for p in interview.problems if p.problem_id == target_pid), None)
        if not prob_item:
            raise ValueError(f"Problem '{target_pid}' is not part of interview '{interview_id}'.")

        ws_mgr = WorkspaceManager(
            tracking_db_path=self.tracking_db_path,
            progress_db_path=self.progress_db_path,
            language=interview.language,
        )

        solution_code = code
        if solution_code is None:
            draft = ws_mgr.get_draft(problem_id=target_pid, language=interview.language)
            solution_code = draft.code if draft else ""

        # Execute using existing local judge via WorkspaceManager
        run_res = ws_mgr.run_code(
            problem_id=target_pid,
            code=solution_code,
            language=interview.language,
            timeout=timeout,
        )

        # Run static quality & complexity review via SolutionReviewEngine
        review_engine = SolutionReviewEngine(
            tracking_db_path=self.tracking_db_path,
            progress_db_path=self.progress_db_path,
        )
        rev_report = review_engine.review_solution(
            problem_id=target_pid,
            code=solution_code,
            language=interview.language,
        )

        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        now_str = _get_utc_now_iso()
        is_after_expiry = interview.is_expired

        submission = InterviewSubmission(
            submission_id=sub_id,
            interview_id=interview_id,
            problem_id=target_pid,
            language=interview.language,
            code=solution_code,
            status=run_res.status,
            passed_count=run_res.passed_count,
            total_tests=run_res.total_tests,
            runtime_ms=run_res.runtime_ms,
            submitted_at=now_str,
            is_after_expiry=is_after_expiry,
            readability_score=rev_report.quality_metrics.readability_score,
            structural_score=rev_report.quality_metrics.structural_score,
            complexity_score=rev_report.complexity_review.complexity_awareness_score,
            estimated_time_complexity=rev_report.complexity_review.estimated_time_complexity,
            estimated_space_complexity=rev_report.complexity_review.estimated_space_complexity,
            error_detail=run_res.compile_error or run_res.execution_error,
        )

        # Update problem status in database
        new_status = "passed" if run_res.status == "passed" else "failed"
        new_best = max(prob_item.best_passed_count, run_res.passed_count)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO mock_interview_submissions (
                    submission_id, interview_id, problem_id, language, code, status,
                    passed_count, total_tests, runtime_ms, submitted_at, is_after_expiry,
                    readability_score, structural_score, complexity_score,
                    estimated_time_complexity, estimated_space_complexity, error_detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission.submission_id,
                    submission.interview_id,
                    submission.problem_id,
                    submission.language,
                    submission.code,
                    submission.status,
                    submission.passed_count,
                    submission.total_tests,
                    submission.runtime_ms,
                    submission.submitted_at,
                    1 if submission.is_after_expiry else 0,
                    submission.readability_score,
                    submission.structural_score,
                    submission.complexity_score,
                    submission.estimated_time_complexity,
                    submission.estimated_space_complexity,
                    submission.error_detail,
                ),
            )
            cursor.execute(
                """
                UPDATE mock_interview_problems
                SET status = CASE WHEN status = 'passed' THEN 'passed' ELSE ? END,
                    best_passed_count = ?,
                    total_tests = ?
                WHERE interview_id = ? AND problem_id = ?
                """,
                (new_status, new_best, run_res.total_tests, interview_id, target_pid),
            )
            conn.commit()

        return submission

    def advance_problem(self, interview_id: str) -> MockInterviewSession:
        """Advance candidate to the next problem in the interview sequence."""
        interview = self.get_interview(interview_id)
        if not interview:
            raise ValueError(f"Interview '{interview_id}' not found.")

        if interview.status in (InterviewStatus.COMPLETED.value, InterviewStatus.CANCELLED.value):
            raise ValueError(f"Cannot advance problem in terminal interview status '{interview.status}'.")

        next_idx = min(interview.current_problem_index + 1, len(interview.problems) - 1)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE mock_interviews SET current_problem_index = ? WHERE interview_id = ?",
                (next_idx, interview_id),
            )
            conn.commit()

        return self.get_interview(interview_id)

    # -------------------------------------------------------------------------
    # Evaluation, Scoring Rubric & Assessment Synthesis
    # -------------------------------------------------------------------------

    def finish_interview(self, interview_id: str) -> AssessmentReport:
        """Finish interview session, evaluate performance using transparent rubric, and record report."""
        interview = self.get_interview(interview_id)
        if not interview:
            raise ValueError(f"Interview '{interview_id}' not found.")

        # Idempotent: return existing assessment if already evaluated
        if interview.assessment and interview.status in (InterviewStatus.COMPLETED.value, InterviewStatus.EXPIRED.value):
            return interview.assessment

        if interview.status == InterviewStatus.CANCELLED.value:
            raise ValueError("Cannot evaluate a cancelled interview.")

        now_str = _get_utc_now_iso()
        final_status = InterviewStatus.EXPIRED.value if interview.is_expired else InterviewStatus.COMPLETED.value

        # --- 1. Rubric Evaluation ---
        # A. Correctness (40%)
        total_tests_all = sum(p.total_tests for p in interview.problems)
        best_passed_all = sum(p.best_passed_count for p in interview.problems)
        correctness_ratio = (best_passed_all / max(1, total_tests_all)) if total_tests_all > 0 else 0.0
        correctness_score = round(40.0 * correctness_ratio, 1)

        # B. Problem Completion (20%)
        total_probs = len(interview.problems)
        solved_probs = sum(1 for p in interview.problems if p.status == "passed")
        completion_ratio = (solved_probs / max(1, total_probs)) if total_probs > 0 else 0.0
        completion_score = round(20.0 * completion_ratio, 1)

        # C. Code Structure & Readability (15%)
        # Based on average readability score from solution submissions
        subs = interview.submissions
        if subs:
            avg_readability = sum(s.readability_score for s in subs) / len(subs)
            structure_score = round(15.0 * (avg_readability / 100.0), 1)
        else:
            structure_score = 0.0

        # D. Complexity Awareness (15%)
        # Based on average complexity awareness score
        if subs:
            avg_complexity = sum(s.complexity_score for s in subs) / len(subs)
            complexity_score = round(15.0 * (avg_complexity / 100.0), 1)
        else:
            complexity_score = 0.0

        # E. Time Management (10%)
        # 10.0 if finished before time limit without expiring, penalized proportionally if overtime
        if not interview.is_expired and interview.elapsed_seconds <= (interview.duration_minutes * 60):
            time_management_score = 10.0
        else:
            overtime = max(0, interview.elapsed_seconds - (interview.duration_minutes * 60))
            time_management_score = max(0.0, round(10.0 - (overtime / 180.0) * 5.0, 1))

        total_score = round(
            correctness_score + completion_score + structure_score + complexity_score + time_management_score,
            1,
        )

        rubric = RubricScoreBreakdown(
            correctness_score=correctness_score,
            completion_score=completion_score,
            structure_score=structure_score,
            complexity_score=complexity_score,
            time_management_score=time_management_score,
            total_score=total_score,
            explanation=(
                f"Scored {total_score}/100 across Correctness ({correctness_score}/40), "
                f"Problem Completion ({completion_score}/20), Code Structure ({structure_score}/15), "
                f"Complexity Awareness ({complexity_score}/15), and Time Management ({time_management_score}/10)."
            ),
        )

        # --- 2. Feedback Synthesis ---
        correctness_obs: List[str] = []
        if solved_probs == total_probs and total_probs > 0:
            correctness_obs.append(f"Excellent accuracy: Passed all test cases across {solved_probs}/{total_probs} assigned problems.")
        elif solved_probs > 0:
            correctness_obs.append(f"Partially completed: Solved {solved_probs} out of {total_probs} problems with {best_passed_all}/{total_tests_all} tests passing.")
        else:
            correctness_obs.append(f"No problems passed all tests. Reviewed {len(subs)} code submissions.")

        time_obs: List[str] = []
        if not interview.is_expired:
            time_obs.append(f"Completed within the {interview.duration_minutes}-minute limit in {interview.elapsed_seconds // 60}m {interview.elapsed_seconds % 60}s.")
        else:
            time_obs.append(f"Time limit of {interview.duration_minutes} minutes was exceeded.")

        code_quality_obs: List[str] = []
        if subs:
            avg_read = sum(s.readability_score for s in subs) / len(subs)
            if avg_read >= 70.0:
                code_quality_obs.append(f"Clean solution structure with strong identifier clarity ({avg_read:.1f}/100 readability).")
            else:
                code_quality_obs.append(f"Consider refactoring for modularity and clearer variable names ({avg_read:.1f}/100 readability).")
        else:
            code_quality_obs.append("No code submissions were recorded for structural static analysis.")

        complexity_obs: List[str] = []
        if subs:
            complexities = [f"{s.problem_id}: {s.estimated_time_complexity}" for s in subs if s.estimated_time_complexity != "Unknown"]
            if complexities:
                complexity_obs.append("Estimated Time Complexities: " + ", ".join(complexities))
            else:
                complexity_obs.append("Analyzed code showed standard linear or constant execution characteristics.")
        else:
            complexity_obs.append("Missing code submissions to perform heuristic Big-O complexity evaluation.")

        # --- 3. Roadmap & Revision Recommendations ---
        rec_topics: List[str] = []
        try:
            rm_engine = DsaRoadmapEngine(
                progress_db_path=self.progress_db_path,
                tracking_db_path=self.tracking_db_path,
                language=interview.language,
            )
            recs = rm_engine.generate_recommendations(limit=3)
            rec_topics = [f"{r.topic_name} ({r.stage_name})" for r in recs]
        except Exception:
            rec_topics = ["Arrays & Hashing", "Two Pointers", "Binary Search"]

        rec_revisions: List[str] = []
        try:
            rev_engine = SpacedRevisionEngine(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            rev_queue = rev_engine.get_revision_queue()
            rec_revisions = [r.problem_id for r in rev_queue[:3]]
        except Exception:
            rec_revisions = []

        summary_text = (
            f"Assessment Score: {total_score}/100 ({final_status.title()}). "
            f"Solved {solved_probs}/{total_probs} problems in {interview.duration_minutes}m limit. "
            f"Correctness: {correctness_score}/40, Completion: {completion_score}/20, Structure: {structure_score}/15, "
            f"Complexity: {complexity_score}/15, Time Management: {time_management_score}/10."
        )

        # Update database with assessment evaluation
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE mock_interviews
                SET status = ?, completed_at = ?, total_score = ?,
                    correctness_score = ?, completion_score = ?, structure_score = ?,
                    complexity_score = ?, time_management_score = ?, summary_feedback = ?,
                    rubric_breakdown_json = ?, recommendations_json = ?
                WHERE interview_id = ?
                """,
                (
                    final_status,
                    now_str,
                    total_score,
                    correctness_score,
                    completion_score,
                    structure_score,
                    complexity_score,
                    time_management_score,
                    summary_text,
                    json.dumps(asdict(rubric)),
                    json.dumps({
                        "correctness": correctness_obs,
                        "time_management": time_obs,
                        "code_quality": code_quality_obs,
                        "complexity": complexity_obs,
                        "topics": rec_topics,
                        "revisions": rec_revisions,
                    }),
                    interview_id,
                ),
            )
            conn.commit()

        return AssessmentReport(
            interview_id=interview_id,
            title=interview.title,
            track=interview.track,
            language=interview.language,
            duration_minutes=interview.duration_minutes,
            started_at=interview.started_at,
            completed_at=now_str,
            time_taken_seconds=interview.elapsed_seconds,
            is_expired=interview.is_expired,
            status=final_status,
            rubric=rubric,
            problems_summary=[asdict(p) for p in interview.problems],
            correctness_observations=correctness_obs,
            time_management_observations=time_obs,
            code_quality_observations=code_quality_obs,
            complexity_observations=complexity_obs,
            recommended_topics=rec_topics,
            recommended_revisions=rec_revisions,
            summary_feedback=summary_text,
            disclaimer=ASSESSMENT_DISCLAIMER,
        )

    def cancel_interview(self, interview_id: str) -> MockInterviewSession:
        """Cancel an in-progress or created interview session."""
        interview = self.get_interview(interview_id)
        if not interview:
            raise ValueError(f"Interview '{interview_id}' not found.")

        if interview.status in (InterviewStatus.COMPLETED.value, InterviewStatus.EXPIRED.value):
            raise ValueError(f"Cannot cancel completed interview in terminal status '{interview.status}'.")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE mock_interviews SET status = ? WHERE interview_id = ?",
                (InterviewStatus.CANCELLED.value, interview_id),
            )
            conn.commit()

        return self.get_interview(interview_id)

    def list_interview_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List historical mock interviews ordered by creation timestamp."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT interview_id, title, track, duration_minutes, language, problem_count,
                       status, created_at, started_at, completed_at, total_score, summary_feedback
                FROM mock_interviews
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        return [dict(r) for r in rows]
