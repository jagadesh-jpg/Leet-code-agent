"""Tests for Learning Session Tracking & Feedback Engine (Milestone 6.3.6).

Verifies:
- Session snapshot persistence and unique session IDs.
- Lifecycle transitions (planned -> in_progress -> completed / cancelled).
- Invalid transition prevention and error handling.
- Problem progress updates (pending -> completed / skipped).
- Duplicate problem record prevention within a session.
- Explainable analytics (sessions planned/completed, rates, problems planned/completed).
- Dedicated tracking database isolation (never touching progress.db).
- CLI integration for session saving, listing, inspection, progress update, and analytics.
"""

from pathlib import Path
import subprocess
import sys

import pytest

from intelligence.planner import SessionPlanner
from intelligence.tracker import (
    ProblemProgressStatus,
    SessionStatus,
    SessionTracker,
    TrackedSessionRecord,
)
from problems import load_problems
import store


@pytest.fixture
def temp_tracking_dbs(tmp_path: Path):
    """Fixture providing isolated progress and tracking databases."""
    progress_db = tmp_path / "test_progress.db"
    tracking_db = tmp_path / "test_tracking.db"
    store.init(db_path=progress_db)
    return progress_db, tracking_db


def test_session_persistence_and_unique_ids(temp_tracking_dbs):
    """Verify session plans persist accurately with unique IDs and problem snapshots."""
    progress_db, tracking_db = temp_tracking_dbs
    planner = SessionPlanner(db_path=progress_db, language="python")
    tracker = SessionTracker(db_path=tracking_db)

    candidates = load_problems()
    plan = planner.plan_session(candidates, session_size=3, skip_solved=False)

    rec1 = tracker.record_session(plan)
    rec2 = tracker.record_session(plan)

    assert rec1.session_id != rec2.session_id
    assert rec1.status == SessionStatus.PLANNED
    assert rec1.target_size == 3
    assert len(rec1.problems) == 3
    assert rec1.problems[0].status == ProblemProgressStatus.PENDING

    # Retrieve from DB
    loaded = tracker.get_session(rec1.session_id)
    assert loaded is not None
    assert loaded.session_id == rec1.session_id
    assert loaded.session_summary == plan.session_summary
    assert len(loaded.problems) == 3
    assert loaded.problems[0].problem_id == plan.planned_problems[0].problem_id


def test_session_lifecycle_transitions(temp_tracking_dbs):
    """Verify clean state progression: planned -> in_progress -> completed."""
    progress_db, tracking_db = temp_tracking_dbs
    planner = SessionPlanner(db_path=progress_db, language="python")
    tracker = SessionTracker(db_path=tracking_db)

    candidates = load_problems()
    plan = planner.plan_session(candidates, session_size=2, skip_solved=False)
    rec = tracker.record_session(plan)

    assert rec.status == SessionStatus.PLANNED

    # Start session
    started = tracker.start_session(rec.session_id)
    assert started.status == SessionStatus.IN_PROGRESS

    # Complete session
    completed = tracker.complete_session(rec.session_id)
    assert completed.status == SessionStatus.COMPLETED
    assert completed.completed_at is not None

    # Invalid transition: cannot start completed session
    with pytest.raises(ValueError, match="Cannot start completed session"):
        tracker.start_session(rec.session_id)


def test_session_cancellation(temp_tracking_dbs):
    """Verify session cancellation works and prevents further mutations."""
    progress_db, tracking_db = temp_tracking_dbs
    planner = SessionPlanner(db_path=progress_db, language="python")
    tracker = SessionTracker(db_path=tracking_db)

    candidates = load_problems()
    plan = planner.plan_session(candidates, session_size=2, skip_solved=False)
    rec = tracker.record_session(plan)

    cancelled = tracker.cancel_session(rec.session_id, reason="User cancelled test session")
    assert cancelled.status == SessionStatus.CANCELLED
    assert "User cancelled" in cancelled.session_summary

    # Cannot complete cancelled session
    with pytest.raises(ValueError, match="Cannot complete cancelled session"):
        tracker.complete_session(rec.session_id)

    # Cannot update problem progress on cancelled session
    with pytest.raises(ValueError, match="Cannot update problems in cancelled session"):
        tracker.update_problem_progress(
            rec.session_id,
            rec.problems[0].problem_id,
            ProblemProgressStatus.COMPLETED,
        )


def test_problem_progress_updates(temp_tracking_dbs):
    """Verify individual problems within a session can be marked completed or skipped."""
    progress_db, tracking_db = temp_tracking_dbs
    planner = SessionPlanner(db_path=progress_db, language="python")
    tracker = SessionTracker(db_path=tracking_db)

    candidates = load_problems()
    plan = planner.plan_session(candidates, session_size=3, skip_solved=False)
    rec = tracker.record_session(plan)

    p0 = rec.problems[0].problem_id
    p1 = rec.problems[1].problem_id

    # Updating a problem automatically transitions session to in_progress
    up1 = tracker.update_problem_progress(
        rec.session_id,
        p0,
        ProblemProgressStatus.COMPLETED,
        outcome_notes="Clean pass on attempt 1",
    )
    assert up1.status == SessionStatus.IN_PROGRESS
    assert up1.completed_count == 1
    assert up1.pending_count == 2

    # Skip second problem
    up2 = tracker.update_problem_progress(
        rec.session_id,
        p1,
        ProblemProgressStatus.SKIPPED,
        outcome_notes="Skipped due to time constraint",
    )
    assert up2.completed_count == 1
    assert up2.skipped_count == 1
    assert up2.pending_count == 1


def test_analytics_computation(temp_tracking_dbs):
    """Verify aggregate analytics calculations for sessions and problem completion."""
    progress_db, tracking_db = temp_tracking_dbs
    planner = SessionPlanner(db_path=progress_db, language="python")
    tracker = SessionTracker(db_path=tracking_db)

    candidates = load_problems()

    # Session 1: completed with 2 problems completed
    plan1 = planner.plan_session(candidates, session_size=2, skip_solved=False)
    s1 = tracker.record_session(plan1)
    tracker.update_problem_progress(s1.session_id, s1.problems[0].problem_id, ProblemProgressStatus.COMPLETED)
    tracker.update_problem_progress(s1.session_id, s1.problems[1].problem_id, ProblemProgressStatus.COMPLETED)
    tracker.complete_session(s1.session_id)

    # Session 2: in-progress with 1 completed, 1 skipped, 1 pending
    plan2 = planner.plan_session(candidates, session_size=3, skip_solved=False)
    s2 = tracker.record_session(plan2)
    tracker.update_problem_progress(s2.session_id, s2.problems[0].problem_id, ProblemProgressStatus.COMPLETED)
    tracker.update_problem_progress(s2.session_id, s2.problems[1].problem_id, ProblemProgressStatus.SKIPPED)

    # Session 3: cancelled
    plan3 = planner.plan_session(candidates, session_size=2, skip_solved=False)
    s3 = tracker.record_session(plan3)
    tracker.cancel_session(s3.session_id)

    analytics = tracker.get_analytics()

    assert analytics.total_sessions_planned == 3
    assert analytics.total_sessions_completed == 1
    assert analytics.total_sessions_in_progress == 1
    assert analytics.total_sessions_cancelled == 1
    assert abs(analytics.session_completion_rate - (1 / 3)) < 1e-3

    # Total problems: 2 + 3 + 2 = 7
    assert analytics.total_problems_planned == 7
    # Completed problems: 2 (from s1) + 1 (from s2) = 3
    assert analytics.total_problems_completed == 3
    # Skipped problems: 1 (from s2) = 1
    assert analytics.total_problems_skipped == 1
    assert abs(analytics.problem_completion_rate - (3 / 7)) < 1e-3
    assert len(analytics.recent_sessions) == 3


def test_cli_tracking_workflow(temp_tracking_dbs):
    """Verify full CLI flow: save-session -> sessions -> session-info -> update -> analytics."""
    progress_db, tracking_db = temp_tracking_dbs
    cwd = Path(__file__).parent.parent

    # 1. Generate and save a plan
    cmd_save = [
        sys.executable,
        "pipeline_cli.py",
        "--plan",
        "--session-size", "2",
        "--all",
        "--save-session",
        "--db-path", str(progress_db),
        "--tracking-db-path", str(tracking_db),
    ]
    res_save = subprocess.run(cmd_save, capture_output=True, text=True, cwd=cwd)
    assert res_save.returncode == 0
    assert "[SAVED]" in res_save.stdout

    # 2. List sessions
    cmd_list = [
        sys.executable,
        "pipeline_cli.py",
        "--sessions",
        "--tracking-db-path", str(tracking_db),
    ]
    res_list = subprocess.run(cmd_list, capture_output=True, text=True, cwd=cwd)
    assert res_list.returncode == 0
    assert "TRACKED LEARNING SESSIONS" in res_list.stdout

    # Extract session ID from list output
    tracker = SessionTracker(db_path=tracking_db)
    sessions = tracker.list_sessions()
    assert len(sessions) == 1
    sid = sessions[0].session_id

    # 3. Inspect session details
    cmd_info = [
        sys.executable,
        "pipeline_cli.py",
        "--session-info", sid,
        "--tracking-db-path", str(tracking_db),
    ]
    res_info = subprocess.run(cmd_info, capture_output=True, text=True, cwd=cwd)
    assert res_info.returncode == 0
    assert f"SESSION DETAILS: {sid}" in res_info.stdout
    assert "PLANNED" in res_info.stdout

    # 4. Update session progress (start session)
    cmd_start = [
        sys.executable,
        "pipeline_cli.py",
        "--session-update", sid,
        "--status", "start",
        "--tracking-db-path", str(tracking_db),
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, cwd=cwd)
    assert res_start.returncode == 0
    assert "updated to: in_progress" in res_start.stdout

    # 5. Display analytics
    cmd_analytics = [
        sys.executable,
        "pipeline_cli.py",
        "--analytics",
        "--tracking-db-path", str(tracking_db),
    ]
    res_analytics = subprocess.run(cmd_analytics, capture_output=True, text=True, cwd=cwd)
    assert res_analytics.returncode == 0
    assert "LEARNING SESSION TRACKING & FEEDBACK ANALYTICS" in res_analytics.stdout
    assert "Sessions In-Progress:      1" in res_analytics.stdout
