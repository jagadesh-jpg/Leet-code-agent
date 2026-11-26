"""Unit and integration tests for Milestone 6.3.19: Offline Mock Interview & Assessment Mode.

Validates:
- Interview creation, track selection (beginner, intermediate, advanced, mixed), and duration bounds (30, 45, 60m).
- Lifecycle state transitions (created, in_progress, completed, expired, cancelled).
- Timestamp-based elapsed and remaining time calculations without real-time background timers.
- Problem selection from local inventory and workspace context extraction.
- Draft persistence and isolation.
- Submission execution using existing UnifiedJudge and SolutionReviewEngine.
- 5-category scoring rubric (Correctness, Completion, Structure, Complexity, Time Management).
- Deterministic feedback, DSA roadmap recommendations, and spaced repetition revisions.
- Terminal state protection (no overwriting, duplicate submissions, or restarts).
- Non-destructive persistence in session_tracking.db.
- Flask Dashboard REST API endpoints (/api/interview, /api/interview/start, /api/interview/<id>,
  /api/interview/<id>/problem, /api/interview/<id>/draft, /api/interview/<id>/submit,
  /api/interview/<id>/advance, /api/interview/<id>/finish, /api/interview/<id>/report,
  /api/interview/history, /api/interview/history/<id>).
- Database isolation (temporary SQLite databases only, zero modification to production progress.db).
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.mock_interview import (
    ASSESSMENT_DISCLAIMER,
    AssessmentReport,
    InterviewManager,
    InterviewProblemItem,
    InterviewStatus,
    InterviewSubmission,
    InterviewTrack,
    MockInterviewSession,
    RubricScoreBreakdown,
)


@pytest.fixture
def temp_environment(tmp_path):
    """Create isolated temporary progress.db and session_tracking.db for testing."""
    prog_db = tmp_path / "test_progress.db"
    track_db = tmp_path / "test_session_tracking.db"

    # Initialize minimal progress.db
    with sqlite3.connect(prog_db) as conn:
        conn.execute(
            """
            CREATE TABLE attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_id TEXT NOT NULL,
                language TEXT NOT NULL,
                passed INTEGER NOT NULL,
                total INTEGER NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.commit()

    return {
        "prog_db": prog_db,
        "track_db": track_db,
    }


def test_schema_initialization(temp_environment):
    """Verify mock interview tables are created non-destructively in session_tracking.db."""
    mgr = InterviewManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
    )
    with sqlite3.connect(temp_environment["track_db"]) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "mock_interviews" in tables
        assert "mock_interview_problems" in tables
        assert "mock_interview_submissions" in tables


def test_track_and_duration_validation(temp_environment):
    """Verify valid tracks and durations succeed while invalid values raise ValueError."""
    mgr = InterviewManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
    )

    # Valid track & duration
    session = mgr.create_interview(track="intermediate", duration_minutes=45, problem_count=2)
    assert session.track == "intermediate"
    assert session.duration_minutes == 45
    assert len(session.problems) == 2

    # Invalid track
    with pytest.raises(ValueError, match="Invalid track"):
        mgr.create_interview(track="expert", duration_minutes=45)

    # Invalid duration
    with pytest.raises(ValueError, match="Invalid duration"):
        mgr.create_interview(track="intermediate", duration_minutes=20)


def test_problem_selection_tracks(temp_environment):
    """Verify problems are selected according to the requested difficulty track."""
    mgr = InterviewManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
    )

    # Beginner track should select easy problems
    beg_session = mgr.create_interview(track="beginner", duration_minutes=30, problem_count=2)
    assert len(beg_session.problems) == 2
    assert all(p.difficulty in ("easy", "medium") for p in beg_session.problems)

    # Advanced track should prioritize hard problems
    adv_session = mgr.create_interview(track="advanced", duration_minutes=60, problem_count=2)
    assert len(adv_session.problems) == 2
    assert any(p.difficulty == "hard" for p in adv_session.problems)

    # Mixed track should have diverse difficulty
    mixed_session = mgr.create_interview(track="mixed", duration_minutes=45, problem_count=3)
    assert len(mixed_session.problems) == 3


def test_lifecycle_and_time_calculation(temp_environment):
    """Verify created -> in_progress -> completed lifecycle and timestamp-based timers."""
    mgr = InterviewManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
    )

    # Create without auto-start
    session = mgr.create_interview(track="intermediate", duration_minutes=45, auto_start=False)
    assert session.status == InterviewStatus.CREATED.value
    assert session.started_at is None
    assert session.remaining_seconds == 45 * 60

    # Start interview
    started = mgr.start_interview(session.interview_id)
    assert started.status == InterviewStatus.IN_PROGRESS.value
    assert started.started_at is not None
    assert started.expires_at is not None
    assert started.remaining_seconds <= 45 * 60
    assert not started.is_expired

    # Active interview getter
    active = mgr.get_active_interview()
    assert active is not None
    assert active.interview_id == session.interview_id

    # Advance problem
    advanced = mgr.advance_problem(session.interview_id)
    assert advanced.current_problem_index == 1

    # Cancel interview
    cancelled = mgr.cancel_interview(session.interview_id)
    assert cancelled.status == InterviewStatus.CANCELLED.value

    # Cannot restart cancelled interview
    with pytest.raises(ValueError, match="Cannot start interview in terminal state"):
        mgr.start_interview(session.interview_id)


def test_expired_interview_detection(temp_environment):
    """Verify expired interview state is dynamically calculated without backend workers."""
    mgr = InterviewManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
    )

    session = mgr.create_interview(track="beginner", duration_minutes=30, auto_start=True)

    # Simulate past timestamps
    past_start = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
    past_expire = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()

    with mgr.get_connection() as conn:
        conn.execute(
            "UPDATE mock_interviews SET started_at = ?, expires_at = ? WHERE interview_id = ?",
            (past_start, past_expire, session.interview_id),
        )
        conn.commit()

    reloaded = mgr.get_interview(session.interview_id)
    assert reloaded.is_expired is True
    assert reloaded.remaining_seconds == 0
    assert reloaded.elapsed_seconds >= 30 * 60


def test_draft_persistence_and_problem_context(temp_environment):
    """Verify draft code saving and sanitized problem context loading."""
    mgr = InterviewManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
    )

    session = mgr.create_interview(track="intermediate", duration_minutes=45, auto_start=True)
    target_prob = session.problems[0].problem_id

    # Load problem context
    ctx = mgr.get_current_problem(session.interview_id, problem_index=0)
    assert ctx.problem_id == target_prob
    assert ctx.title != ""
    assert ctx.description != ""
    # Reference solution must NOT be exposed
    assert not hasattr(ctx, "solution_code")

    # Save candidate draft
    draft_code = "def two_sum(nums, target):\n    return [0, 1]\n"
    draft = mgr.save_draft(session.interview_id, code=draft_code, problem_id=target_prob)
    assert draft["code"] == draft_code
    assert draft["problem_id"] == target_prob


def test_submission_and_judge_execution(temp_environment):
    """Verify submitting code runs local UnifiedJudge and updates problem metrics."""
    mgr = InterviewManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
    )

    session = mgr.create_interview(track="beginner", duration_minutes=30, problem_count=1, auto_start=True)
    prob_id = session.problems[0].problem_id

    # Valid solution for two-sum (or whichever beginner problem is first)
    if prob_id == "two-sum":
        sol_code = (
            "def two_sum(nums, target):\n"
            "    lookup = {}\n"
            "    for i, num in enumerate(nums):\n"
            "        diff = target - num\n"
            "        if diff in lookup:\n"
            "            return [lookup[diff], i]\n"
            "        lookup[num] = i\n"
            "    return []\n"
        )
    else:
        # Fallback dummy code
        sol_code = "def solve(*args):\n    return None\n"

    sub = mgr.submit_solution(session.interview_id, code=sol_code, problem_id=prob_id)

    assert isinstance(sub, InterviewSubmission)
    assert sub.interview_id == session.interview_id
    assert sub.problem_id == prob_id
    assert sub.status in ("passed", "wrong_answer", "compile_error", "runtime_error")
    assert sub.total_tests > 0
    assert sub.readability_score >= 0.0

    # Verify problem status updated in interview
    reloaded = mgr.get_interview(session.interview_id)
    assert len(reloaded.submissions) == 1
    assert reloaded.problems[0].status in ("passed", "failed")


def test_evaluation_and_scoring_rubric(temp_environment):
    """Verify the 5-category rubric scoring and deterministic assessment feedback."""
    mgr = InterviewManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
    )

    session = mgr.create_interview(track="beginner", duration_minutes=30, problem_count=1, auto_start=True)
    prob_id = session.problems[0].problem_id

    # Submit a working solution for two-sum
    sol_code = (
        "def two_sum(nums, target):\n"
        "    lookup = {}\n"
        "    for i, num in enumerate(nums):\n"
        "        diff = target - num\n"
        "        if diff in lookup:\n"
        "            return [lookup[diff], i]\n"
        "        lookup[num] = i\n"
        "    return []\n"
    )
    mgr.submit_solution(session.interview_id, code=sol_code, problem_id=prob_id)

    # Finish interview
    report = mgr.finish_interview(session.interview_id)

    assert isinstance(report, AssessmentReport)
    assert report.interview_id == session.interview_id
    assert report.status == InterviewStatus.COMPLETED.value
    assert report.rubric.total_score >= 0.0
    assert report.rubric.total_score <= 100.0

    # Rubric categories
    assert 0.0 <= report.rubric.correctness_score <= 40.0
    assert 0.0 <= report.rubric.completion_score <= 20.0
    assert 0.0 <= report.rubric.structure_score <= 15.0
    assert 0.0 <= report.rubric.complexity_score <= 15.0
    assert 0.0 <= report.rubric.time_management_score <= 10.0

    # Feedback observations
    assert len(report.correctness_observations) > 0
    assert len(report.time_management_observations) > 0
    assert len(report.code_quality_observations) > 0
    assert len(report.recommended_topics) > 0
    assert ASSESSMENT_DISCLAIMER in report.disclaimer

    # Idempotent finish check
    report2 = mgr.finish_interview(session.interview_id)
    assert report2.rubric.total_score == report.rubric.total_score

    # Cannot submit to completed interview
    with pytest.raises(ValueError, match="Cannot submit solution to interview in terminal status"):
        mgr.submit_solution(session.interview_id, code=sol_code)


def test_missing_evidence_scoring_honesty(temp_environment):
    """Verify that empty/abandoned interviews do not receive free perfect scores."""
    mgr = InterviewManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
    )

    session = mgr.create_interview(track="intermediate", duration_minutes=45, auto_start=True)

    # Finish immediately without any submissions
    report = mgr.finish_interview(session.interview_id)

    assert report.rubric.correctness_score == 0.0
    assert report.rubric.completion_score == 0.0
    assert report.rubric.structure_score == 0.0
    assert report.rubric.complexity_score == 0.0
    assert report.rubric.total_score <= 10.0  # Only time management points possible


def test_history_listing(temp_environment):
    """Verify historical interview sessions are logged and queryable."""
    mgr = InterviewManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
    )

    s1 = mgr.create_interview(track="beginner", duration_minutes=30)
    s2 = mgr.create_interview(track="advanced", duration_minutes=60)

    history = mgr.list_interview_history(limit=5)
    assert len(history) >= 2
    ids = [h["interview_id"] for h in history]
    assert s1.interview_id in ids
    assert s2.interview_id in ids


def test_dashboard_interview_endpoints(temp_environment):
    """Verify all Flask REST endpoints for mock interview management."""
    app = create_app(
        db_path=temp_environment["prog_db"],
        tracking_db_path=temp_environment["track_db"],
    )
    client = app.test_client()

    # 1. GET /api/interview (initial state)
    res_root = client.get("/api/interview")
    assert res_root.status_code == 200

    # 2. POST /api/interview/start
    res_start = client.post(
        "/api/interview/start",
        json={
            "track": "intermediate",
            "duration_minutes": 45,
            "problem_count": 2,
            "title": "Full-Stack Algorithm Screen",
        },
    )
    assert res_start.status_code == 201
    start_data = res_start.get_json()
    assert "interview_id" in start_data
    assert start_data["status"] == "in_progress"
    iid = start_data["interview_id"]

    # 3. GET /api/interview/<id>
    res_get = client.get(f"/api/interview/{iid}")
    assert res_get.status_code == 200
    assert res_get.get_json()["interview_id"] == iid

    # 4. GET /api/interview/<id>/problem
    res_prob = client.get(f"/api/interview/{iid}/problem?index=0")
    assert res_prob.status_code == 200
    prob_data = res_prob.get_json()
    assert "problem_id" in prob_data
    assert "description" in prob_data

    # 5. POST /api/interview/<id>/draft
    res_draft = client.post(
        f"/api/interview/{iid}/draft",
        json={"code": "# draft test\n"},
    )
    assert res_draft.status_code == 200
    assert res_draft.get_json()["code"] == "# draft test\n"

    # 6. POST /api/interview/<id>/submit
    res_sub = client.post(
        f"/api/interview/{iid}/submit",
        json={"code": "def solve(): pass\n"},
    )
    assert res_sub.status_code == 200
    sub_data = res_sub.get_json()
    assert "submission_id" in sub_data
    assert "status" in sub_data

    # 7. POST /api/interview/<id>/advance
    res_adv = client.post(f"/api/interview/{iid}/advance")
    assert res_adv.status_code == 200
    assert res_adv.get_json()["current_problem_index"] == 1

    # 8. POST /api/interview/<id>/finish
    res_fin = client.post(f"/api/interview/{iid}/finish")
    assert res_fin.status_code == 200
    fin_data = res_fin.get_json()
    assert "rubric" in fin_data
    assert "total_score" in fin_data["rubric"]

    # 9. GET /api/interview/<id>/report
    res_rep = client.get(f"/api/interview/{iid}/report")
    assert res_rep.status_code == 200
    assert res_rep.get_json()["interview_id"] == iid

    # 10. GET /api/interview/history
    res_hist = client.get("/api/interview/history")
    assert res_hist.status_code == 200
    assert len(res_hist.get_json()) >= 1

    # 11. GET /api/interview/history/<id>
    res_hdet = client.get(f"/api/interview/history/{iid}")
    assert res_hdet.status_code == 200
    assert res_hdet.get_json()["interview_id"] == iid

    # Error handling
    assert client.get("/api/interview/invalid!id").status_code == 400
    assert client.get("/api/interview/mock_0000000000").status_code == 404
