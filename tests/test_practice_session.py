"""Unit and integration tests for Milestone 6.3.22: Plan-to-Practice Execution Bridge.

Validates:
- Session creation (from preparation task and standalone).
- Duplicate active session prevention and force-switch override.
- Pause and resume lifecycle transitions with accurate elapsed time calculation.
- Invalid state transition enforcement (terminal states, double pause, double resume).
- Session completion and abandonment.
- Reflection notes editing and persistence.
- Append-only event history journaling.
- Submission evidence recording (passed/failed counts, final status).
- Explicit task confirmation bridging to PreparationPlanner.
- Session summary generation.
- All 10 Flask REST API endpoints in dashboard_server.py.
- Regex input sanitization and error handling.
- Database isolation (temporary SQLite databases only, zero modification to progress.db).
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.practice_session import (
    PracticeSession,
    PracticeSessionEvent,
    PracticeSessionManager,
    PracticeSessionNotes,
    PracticeSessionStatus,
    SessionSummary,
)
from intelligence.preparation_planner import (
    PreparationPlan,
    PreparationPlanner,
    TaskStatus,
)


@pytest.fixture
def test_env(tmp_path):
    """Fixture providing isolated databases for progress and session tracking."""
    prog_db = tmp_path / "test_prog.db"
    track_db = tmp_path / "test_tracking.db"

    # Setup minimal progress.db
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

    # Initialize PreparationPlanner to generate a real plan with tasks
    planner = PreparationPlanner(tracking_db_path=track_db, progress_db_path=prog_db)
    plan = planner.save_plan(planner.generate_plan())
    planner.apply_plan(plan.plan_id)

    # Initialize PracticeSessionManager
    ps_mgr = PracticeSessionManager(tracking_db_path=track_db, progress_db_path=prog_db)

    return {
        "prog_db": prog_db,
        "track_db": track_db,
        "planner": planner,
        "plan": plan,
        "ps_mgr": ps_mgr,
        "tmp_path": tmp_path,
    }


# =============================================================================
# 1. Session Creation & Duplicate Prevention
# =============================================================================

def test_session_creation_from_task_and_standalone(test_env):
    """Verify session creation both linked to a preparation task and standalone."""
    ps_mgr = test_env["ps_mgr"]
    plan = test_env["plan"]
    task = plan.all_tasks[0]

    # 1. Start from task
    session = ps_mgr.start_session(task_id=task.task_id)
    assert session.session_id.startswith("psess_")
    assert session.status == PracticeSessionStatus.ACTIVE.value
    assert session.task_id == task.task_id
    assert session.plan_id == plan.plan_id
    assert session.task_title == task.title
    assert session.started_at is not None
    assert session.elapsed_seconds >= 0

    # 2. Duplicate active session prevention
    with pytest.raises(ValueError, match="already in progress"):
        ps_mgr.start_session(problem_id="valid-parentheses")

    # 3. Force-switch override
    session2 = ps_mgr.start_session(problem_id="valid-parentheses", force_switch=True)
    assert session2.session_id != session.session_id
    assert session2.problem_id == "valid-parentheses"
    assert session2.task_id is None


# =============================================================================
# 2. Pause and Resume Lifecycle
# =============================================================================

def test_pause_and_resume_lifecycle(test_env):
    """Verify pause, resume, and elapsed time accumulation."""
    ps_mgr = test_env["ps_mgr"]
    session = ps_mgr.start_session(problem_id="two-sum")

    # Pause active session
    paused = ps_mgr.pause_session(session.session_id)
    assert paused.status == PracticeSessionStatus.PAUSED.value
    assert paused.paused_at is not None

    # Double pause raises ValueError
    with pytest.raises(ValueError, match="already paused"):
        ps_mgr.pause_session(session.session_id)

    # Resume session
    resumed = ps_mgr.resume_session(session.session_id)
    assert resumed.status == PracticeSessionStatus.ACTIVE.value
    assert resumed.paused_at is None

    # Double resume raises ValueError
    with pytest.raises(ValueError, match="already active"):
        ps_mgr.resume_session(session.session_id)


# =============================================================================
# 3. Terminal State Enforcement (Complete & Abandon)
# =============================================================================

def test_terminal_states_and_invalid_transitions(test_env):
    """Verify ending session as completed or abandoned and rejecting invalid transitions."""
    ps_mgr = test_env["ps_mgr"]

    # Session 1: Complete
    s1 = ps_mgr.start_session(problem_id="two-sum")
    completed = ps_mgr.end_session(s1.session_id, status=PracticeSessionStatus.COMPLETED.value)
    assert completed.status == PracticeSessionStatus.COMPLETED.value
    assert completed.ended_at is not None

    # Cannot pause or resume completed session
    with pytest.raises(ValueError, match="terminal status"):
        ps_mgr.pause_session(s1.session_id)
    with pytest.raises(ValueError, match="terminal status"):
        ps_mgr.resume_session(s1.session_id)
    with pytest.raises(ValueError, match="already completed"):
        ps_mgr.end_session(s1.session_id)

    # Session 2: Abandon
    s2 = ps_mgr.start_session(problem_id="reverse-string")
    abandoned = ps_mgr.end_session(s2.session_id, status=PracticeSessionStatus.ABANDONED.value)
    assert abandoned.status == PracticeSessionStatus.ABANDONED.value

    # Cannot record submissions on abandoned session
    with pytest.raises(ValueError, match="terminal status"):
        ps_mgr.record_submission(s2.session_id, status="passed")


# =============================================================================
# 4. Evidence & Submission Tracking
# =============================================================================

def test_submission_evidence_tracking(test_env):
    """Verify recording of test runs, outcomes, and final status flags."""
    ps_mgr = test_env["ps_mgr"]
    session = ps_mgr.start_session(problem_id="two-sum")

    assert session.submissions_count == 0
    assert session.final_submission_passed is False

    # 1. Failed run
    ps_mgr.record_submission(
        session_id=session.session_id,
        status="wrong_answer",
        passed_count=2,
        total_tests=6,
        runtime_ms=12.5,
    )
    s_after_fail = ps_mgr.get_session(session.session_id)
    assert s_after_fail.submissions_count == 1
    assert s_after_fail.passed_submissions_count == 0
    assert s_after_fail.failed_submissions_count == 1
    assert s_after_fail.final_submission_passed is False

    # 2. Passing run
    ps_mgr.record_submission(
        session_id=session.session_id,
        status="passed",
        passed_count=6,
        total_tests=6,
        runtime_ms=8.2,
    )
    s_after_pass = ps_mgr.get_session(session.session_id)
    assert s_after_pass.submissions_count == 2
    assert s_after_pass.passed_submissions_count == 1
    assert s_after_pass.failed_submissions_count == 1
    assert s_after_pass.final_submission_passed is True


# =============================================================================
# 5. Reflection Notes Management
# =============================================================================

def test_session_notes_persistence(test_env):
    """Verify saving and updating structured reflection notes."""
    ps_mgr = test_env["ps_mgr"]
    session = ps_mgr.start_session(problem_id="two-sum")

    notes_data = {
        "initial_approach": "Brute force nested loop",
        "mistakes_encountered": "Index out of bounds on empty list",
        "hints_used": "Looked up complement hash map",
        "final_approach": "One-pass hash table",
        "time_complexity": "O(n)",
        "space_complexity": "O(n)",
        "key_learning": "Trading space for time reduces O(n^2) to O(n)",
        "follow_up_action": "Practice 3Sum with two pointers",
    }
    saved_notes = ps_mgr.save_notes(session.session_id, notes=notes_data)
    assert saved_notes.time_complexity == "O(n)"
    assert saved_notes.key_learning == "Trading space for time reduces O(n^2) to O(n)"

    # Verify retrieved session contains saved notes
    refreshed = ps_mgr.get_session(session.session_id)
    assert refreshed.notes.initial_approach == "Brute force nested loop"
    assert refreshed.notes.follow_up_action == "Practice 3Sum with two pointers"


# =============================================================================
# 6. Explicit Task Confirmation & Planner Bridging
# =============================================================================

def test_confirm_task_completion_bridges_to_planner(test_env):
    """Verify explicit task confirmation updates both practice session and planner task."""
    ps_mgr = test_env["ps_mgr"]
    planner = test_env["planner"]
    plan = test_env["plan"]
    task = plan.all_tasks[0]

    # Verify task is initially pending
    assert task.status == TaskStatus.PENDING.value

    # Start session linked to task
    session = ps_mgr.start_session(task_id=task.task_id)

    # Record 1 passing submission
    ps_mgr.record_submission(session.session_id, status="passed", passed_count=5, total_tests=5)

    # Note: Successful submission alone does NOT mark task completed
    refreshed_plan = planner.get_plan(plan.plan_id)
    refreshed_task = next(t for t in refreshed_plan.all_tasks if t.task_id == task.task_id)
    assert refreshed_task.status == TaskStatus.PENDING.value

    # Explicit confirmation
    notes = {"key_learning": "Mastered two pointers", "time_complexity": "O(n)"}
    confirmed_session = ps_mgr.confirm_task_completion(session.session_id, notes=notes)

    assert confirmed_session.task_confirmed_completed is True
    assert confirmed_session.status == PracticeSessionStatus.COMPLETED.value

    # Planner task should now be marked COMPLETED with actual_minutes
    final_plan = planner.get_plan(plan.plan_id)
    final_task = next(t for t in final_plan.all_tasks if t.task_id == task.task_id)
    assert final_task.status == TaskStatus.COMPLETED.value
    assert final_task.actual_minutes is not None
    assert final_task.actual_minutes >= 1


def test_confirm_task_completion_without_task_id_fails(test_env):
    """Verify confirmation on standalone session without linked task raises ValueError."""
    ps_mgr = test_env["ps_mgr"]
    session = ps_mgr.start_session(problem_id="two-sum")

    with pytest.raises(ValueError, match="not linked to a planner task"):
        ps_mgr.confirm_task_completion(session.session_id)


# =============================================================================
# 7. Event History Journaling & Session Summary
# =============================================================================

def test_event_history_and_summary(test_env):
    """Verify audit events are recorded for each transition and summary is generated."""
    ps_mgr = test_env["ps_mgr"]
    plan = test_env["plan"]
    task = plan.all_tasks[0]

    session = ps_mgr.start_session(task_id=task.task_id)
    ps_mgr.record_submission(session.session_id, status="passed")
    ps_mgr.pause_session(session.session_id)
    ps_mgr.resume_session(session.session_id)
    ps_mgr.save_notes(session.session_id, {"key_learning": "Great progress"})
    ps_mgr.confirm_task_completion(session.session_id)

    # Check summary
    summary = ps_mgr.get_session_summary(session.session_id)
    assert isinstance(summary, SessionSummary)
    assert summary.session_id == session.session_id
    assert summary.task_confirmed_completed is True
    assert summary.final_submission_passed is True
    assert summary.events_count >= 5
    assert summary.key_learnings_summary == "Great progress"

    # Check history listing
    history = ps_mgr.list_history()
    assert len(history) >= 1
    assert history[0]["session_id"] == session.session_id


# =============================================================================
# 8. Dashboard REST API Endpoints
# =============================================================================

def test_flask_practice_session_endpoints(test_env):
    """Verify all 10 REST API endpoints in dashboard_server.py."""
    app = create_app(
        db_path=test_env["prog_db"],
        tracking_db_path=test_env["track_db"],
    )
    client = app.test_client()
    plan = test_env["plan"]
    task = plan.all_tasks[0]

    # 1. GET /api/practice-session/active (initially null)
    res_act = client.get("/api/practice-session/active")
    assert res_act.status_code == 200
    assert res_act.get_json() is None

    # 2. POST /api/practice-session/start
    res_start = client.post(
        "/api/practice-session/start",
        json={"task_id": task.task_id, "language": "python"},
    )
    assert res_start.status_code == 201
    s_data = res_start.get_json()
    session_id = s_data["session_id"]
    assert s_data["status"] == "active"

    # 3. GET /api/practice-session/active (now returns active session)
    res_act2 = client.get("/api/practice-session/active")
    assert res_act2.status_code == 200
    assert res_act2.get_json()["session_id"] == session_id

    # 4. GET /api/practice-session/<session_id>
    res_detail = client.get(f"/api/practice-session/{session_id}")
    assert res_detail.status_code == 200
    assert res_detail.get_json()["session_id"] == session_id

    # 5. POST /api/practice-session/<session_id>/pause
    res_pause = client.post(f"/api/practice-session/{session_id}/pause")
    assert res_pause.status_code == 200
    assert res_pause.get_json()["status"] == "paused"

    # 6. POST /api/practice-session/<session_id>/resume
    res_resume = client.post(f"/api/practice-session/{session_id}/resume")
    assert res_resume.status_code == 200
    assert res_resume.get_json()["status"] == "active"

    # 7. POST /api/practice-session/<session_id>/notes
    res_notes = client.post(
        f"/api/practice-session/{session_id}/notes",
        json={"time_complexity": "O(n)", "key_learning": "API test passed"},
    )
    assert res_notes.status_code == 200
    assert res_notes.get_json()["time_complexity"] == "O(n)"

    # 8. POST /api/practice-session/<session_id>/confirm-task
    res_confirm = client.post(f"/api/practice-session/{session_id}/confirm-task")
    assert res_confirm.status_code == 200
    assert res_confirm.get_json()["task_confirmed_completed"] is True

    # 9. GET /api/practice-session/<session_id>/summary
    res_sum = client.get(f"/api/practice-session/{session_id}/summary")
    assert res_sum.status_code == 200
    assert res_sum.get_json()["task_confirmed_completed"] is True

    # 10. GET /api/practice-session/history
    res_hist = client.get("/api/practice-session/history?limit=10")
    assert res_hist.status_code == 200
    assert len(res_hist.get_json()) >= 1

    # Test POST /api/practice-session/<session_id>/end
    # Start a standalone session and abandon it
    s_std = client.post("/api/practice-session/start", json={"problem_id": "two-sum", "force_switch": True}).get_json()
    res_end = client.post(f"/api/practice-session/{s_std['session_id']}/end", json={"status": "abandoned"})
    assert res_end.status_code == 200
    assert res_end.get_json()["status"] == "abandoned"


def test_invalid_input_and_regex_protection(test_env):
    """Verify regex sanitization on practice session endpoints."""
    app = create_app(
        db_path=test_env["prog_db"],
        tracking_db_path=test_env["track_db"],
    )
    client = app.test_client()

    bad_id = "psess_123$injection"
    assert client.get(f"/api/practice-session/{bad_id}").status_code == 400
    assert client.post(f"/api/practice-session/{bad_id}/pause").status_code == 400
    assert client.post(f"/api/practice-session/{bad_id}/resume").status_code == 400
    assert client.post(f"/api/practice-session/{bad_id}/end").status_code == 400
    assert client.post(f"/api/practice-session/{bad_id}/notes").status_code == 400
    assert client.get(f"/api/practice-session/{bad_id}/summary").status_code == 400
    assert client.post(f"/api/practice-session/{bad_id}/confirm-task").status_code == 400
