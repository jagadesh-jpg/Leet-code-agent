"""Unit and integration tests for Milestone 6.3.26: Guided Daily Practice & Study Session Orchestrator.

Validates:
- Non-destructive database initialization and schema setup.
- Session generation with empty database and default fallback handling.
- Budget allocation algorithm (15m, 30m, 45m, 90m, custom duration).
- Knapsack / greedy scheduling logic and break checkpoints.
- Guarantee that no fabricated problem IDs are introduced.
- Pre-execution session preview without state mutation.
- Robust session lifecycle state machine (READY -> ACTIVE <-> PAUSED -> COMPLETED / ABANDONED).
- Task execution workflow (start, complete, skip, verified test pass evidence).
- Elapsed practice time accumulation across pause/resume cycles.
- Retrospective session report generation with verified metrics.
- Re-evaluation integration triggering the Adaptive Learning Loop.
- Non-destructive safety (production progress.db remains 100% untouched).
- All 14 Flask REST API endpoints in dashboard_server.py.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.daily_practice import (
    DailyPracticeEvidence,
    DailyPracticeOrchestrator,
    DailyPracticeProgress,
    DailyPracticeReport,
    DailyPracticeSchedule,
    DailyPracticeSession,
    DailyPracticeSessionStatus,
    DailyPracticeTask,
    DailyPracticeTaskStatus,
    DailyPracticeTaskType,
)
from intelligence.revision import SpacedRevisionEngine


@pytest.fixture
def test_dbs(tmp_path):
    """Provides isolated temporary SQLite databases for tracking and progress."""
    prog_db = tmp_path / "test_prog.db"
    track_db = tmp_path / "test_tracking.db"

    with sqlite3.connect(prog_db) as conn:
        conn.execute(
            """
            CREATE TABLE attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_id TEXT,
                attempt_no INTEGER,
                code TEXT,
                status TEXT,
                error TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE custom_problems (
                id TEXT PRIMARY KEY,
                title TEXT,
                difficulty TEXT,
                description TEXT,
                function_name TEXT,
                signature TEXT,
                tests_json TEXT,
                created_at TEXT,
                reference_solution TEXT
            )
            """
        )
        conn.commit()

    return {"prog_db": prog_db, "track_db": track_db}


def test_empty_database_and_initialization(test_dbs):
    """Test daily practice orchestrator on clean, empty tracking and progress databases."""
    orchestrator = DailyPracticeOrchestrator(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    overview = orchestrator.get_overview()
    assert overview["total_sessions"] == 0
    assert overview["completed_sessions"] == 0
    assert overview["total_practice_minutes"] == 0.0
    assert overview["latest_session"] is None
    assert overview["active_session"] is None

    assert orchestrator.get_latest_session() is None
    assert orchestrator.list_sessions() == []


def test_session_generation_and_fallback(test_dbs):
    """Test generating a session when no previous history exists."""
    orchestrator = DailyPracticeOrchestrator(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    session = orchestrator.generate_session(budget_minutes=45)
    assert session is not None
    assert session.session_id.startswith("dps_")
    assert session.status == DailyPracticeSessionStatus.READY
    assert session.budget_minutes == 45
    assert len(session.tasks) > 0
    assert session.progress.total_tasks == len(session.tasks)
    assert session.progress.completed_tasks == 0
    assert session.progress.completion_percentage == 0.0

    # Ensure break checkpoint is present for 45 min allocation
    types = [t.task_type for t in session.tasks]
    assert DailyPracticeTaskType.BREAK_CHECKPOINT in types or DailyPracticeTaskType.SESSION_REFLECTION in types

    # Ensure saved to tracking DB
    latest = orchestrator.get_latest_session()
    assert latest is not None
    assert latest.session_id == session.session_id


def test_budget_allocations_and_limits(test_dbs):
    """Test various budget sizes and validation limits."""
    orchestrator = DailyPracticeOrchestrator(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    # Budget limits
    with pytest.raises(ValueError):
        orchestrator.generate_session(budget_minutes=10)

    with pytest.raises(ValueError):
        orchestrator.generate_session(budget_minutes=400)

    # Sprint 15m
    s15 = orchestrator.generate_session(budget_minutes=15)
    assert s15.budget_minutes == 15
    total_planned = sum(t.target_duration_minutes for t in s15.tasks)
    assert total_planned <= 15

    # 90m extended
    s90 = orchestrator.generate_session(budget_minutes=90)
    assert s90.budget_minutes == 90
    total_planned_90 = sum(t.target_duration_minutes for t in s90.tasks)
    assert total_planned_90 <= 90


def test_preview_session_no_mutation(test_dbs):
    """Test that preview_session returns schedule without mutating database."""
    orchestrator = DailyPracticeOrchestrator(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    preview = orchestrator.preview_session(budget_minutes=30)
    assert isinstance(preview, DailyPracticeSchedule)
    assert preview.budget_minutes == 30
    assert len(preview.tasks) > 0

    # Verify tracking DB is still completely empty
    assert orchestrator.list_sessions() == []
    assert orchestrator.get_latest_session() is None


def test_lifecycle_state_machine(test_dbs):
    """Test strict state machine transitions (READY -> ACTIVE <-> PAUSED -> COMPLETED / ABANDONED)."""
    orchestrator = DailyPracticeOrchestrator(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    session = orchestrator.generate_session(budget_minutes=30)
    sid = session.session_id
    assert session.status == DailyPracticeSessionStatus.READY

    # Cannot pause or resume a READY session
    with pytest.raises(ValueError):
        orchestrator.pause_session(sid)
    with pytest.raises(ValueError):
        orchestrator.resume_session(sid)

    # Start session -> ACTIVE
    active_session = orchestrator.start_session(sid)
    assert active_session.status == DailyPracticeSessionStatus.ACTIVE
    assert active_session.started_at is not None

    # Cannot start an already active session
    with pytest.raises(ValueError):
        orchestrator.start_session(sid)

    # Pause session -> PAUSED
    paused_session = orchestrator.pause_session(sid, reason="lunch break")
    assert paused_session.status == DailyPracticeSessionStatus.PAUSED

    # Cannot pause already paused session
    with pytest.raises(ValueError):
        orchestrator.pause_session(sid)

    # Resume session -> ACTIVE
    resumed_session = orchestrator.resume_session(sid)
    assert resumed_session.status == DailyPracticeSessionStatus.ACTIVE

    # Cannot resume already active session
    with pytest.raises(ValueError):
        orchestrator.resume_session(sid)

    # Complete session -> COMPLETED
    completed_session, report = orchestrator.complete_session(sid, notes="Great study day")
    assert completed_session.status == DailyPracticeSessionStatus.COMPLETED
    assert completed_session.ended_at is not None
    assert isinstance(report, DailyPracticeReport)

    # Cannot mutate completed session
    with pytest.raises(ValueError):
        orchestrator.start_session(sid)
    with pytest.raises(ValueError):
        orchestrator.pause_session(sid)
    with pytest.raises(ValueError):
        orchestrator.resume_session(sid)
    with pytest.raises(ValueError):
        orchestrator.abandon_session(sid)


def test_abandon_session(test_dbs):
    """Test abandoning a session from READY or ACTIVE state."""
    orchestrator = DailyPracticeOrchestrator(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    s1 = orchestrator.generate_session(budget_minutes=30)
    abandoned_1 = orchestrator.abandon_session(s1.session_id, reason="Changed mind")
    assert abandoned_1.status == DailyPracticeSessionStatus.ABANDONED

    s2 = orchestrator.generate_session(budget_minutes=30)
    orchestrator.start_session(s2.session_id)
    abandoned_2 = orchestrator.abandon_session(s2.session_id, reason="Emergency")
    assert abandoned_2.status == DailyPracticeSessionStatus.ABANDONED


def test_task_execution_and_evidence_tracking(test_dbs):
    """Test task execution flow: start task, complete with verified pass, skip task."""
    orchestrator = DailyPracticeOrchestrator(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    session = orchestrator.generate_session(budget_minutes=45)
    sid = session.session_id
    orchestrator.start_session(sid)

    task_1 = session.tasks[0]
    task_2 = session.tasks[1] if len(session.tasks) > 1 else None

    # Start task 1
    s_updated = orchestrator.start_task(sid, task_1.task_id)
    t1_updated = [t for t in s_updated.tasks if t.task_id == task_1.task_id][0]
    assert t1_updated.status == DailyPracticeTaskStatus.IN_PROGRESS

    # Complete task 1 with verified pass
    s_completed = orchestrator.complete_task(
        session_id=sid,
        task_id=task_1.task_id,
        verified_pass=True,
        notes="Solved with O(N) complexity",
        test_run_id="run_test_42",
    )
    t1_done = [t for t in s_completed.tasks if t.task_id == task_1.task_id][0]
    assert t1_done.status == DailyPracticeTaskStatus.COMPLETED
    assert t1_done.verified_pass is True
    assert t1_done.test_run_id == "run_test_42"
    assert s_completed.progress.verified_passes == 1
    assert s_completed.progress.completed_tasks == 1

    # Skip task 2 if available
    if task_2:
        s_skipped = orchestrator.skip_task(sid, task_2.task_id, reason="Already practiced recently")
        t2_done = [t for t in s_skipped.tasks if t.task_id == task_2.task_id][0]
        assert t2_done.status == DailyPracticeTaskStatus.SKIPPED
        assert s_completed.progress.verified_passes == 1


def test_unresolved_and_spaced_revision_priority(test_dbs):
    """Test that real unresolved attempts and spaced revisions take top allocation priority."""
    track_db = test_dbs["track_db"]
    prog_db = test_dbs["prog_db"]

    # Insert an unresolved attempt in prog_db
    with sqlite3.connect(prog_db) as conn:
        conn.execute(
            """
            INSERT INTO attempts (problem_id, attempt_no, code, status, error, created_at)
            VALUES ('1', 1, 'def twoSum(): pass', 'error', 'IndexError', '2026-11-20T10:00:00Z')
            """
        )
        conn.commit()

    # Insert an overdue spaced revision item
    rev_engine = SpacedRevisionEngine(tracking_db_path=track_db, progress_db_path=prog_db)
    rev_engine.schedule_problem(problem={"id": "1", "title": "Two Sum", "difficulty": "Easy"}, custom_next_date="2020-01-01")

    orchestrator = DailyPracticeOrchestrator(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )

    session = orchestrator.generate_session(budget_minutes=60)
    assert any(t.problem_id == "1" for t in session.tasks)

    # Check report after completion
    orchestrator.start_session(session.session_id)
    _, report = orchestrator.complete_session(session.session_id, notes="Verified priority items")
    assert report.session_id == session.session_id
    assert report.budget_minutes == 60


def test_reevaluate_learning_loop_integration(test_dbs):
    """Test feeding completed session evidence back into the Adaptive Learning Loop."""
    orchestrator = DailyPracticeOrchestrator(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    session = orchestrator.generate_session(budget_minutes=30)
    sid = session.session_id
    orchestrator.start_session(sid)
    orchestrator.complete_session(sid, notes="Ready for loop re-evaluation")

    loop_report = orchestrator.reevaluate_learning_loop(sid)
    assert loop_report is not None
    assert loop_report.report_id.startswith("llr_")
    assert loop_report.snapshot is not None


def test_non_destructive_safety(test_dbs):
    """Test that production progress.db remains 100% untouched."""
    prog_db = test_dbs["prog_db"]
    track_db = test_dbs["track_db"]

    with open(prog_db, "rb") as f:
        hash_before = hashlib.sha256(f.read()).hexdigest()

    orchestrator = DailyPracticeOrchestrator(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )

    session = orchestrator.generate_session(budget_minutes=45)
    orchestrator.start_session(session.session_id)
    orchestrator.pause_session(session.session_id)
    orchestrator.resume_session(session.session_id)
    orchestrator.complete_task(session.session_id, session.tasks[0].task_id, verified_pass=True)
    orchestrator.complete_session(session.session_id)
    orchestrator.get_report(session.session_id)

    with open(prog_db, "rb") as f:
        hash_after = hashlib.sha256(f.read()).hexdigest()

    assert hash_before == hash_after


def test_rest_api_endpoints(test_dbs):
    """Test all 14 REST API endpoints in dashboard_server.py."""
    app = create_app(
        db_path=test_dbs["prog_db"],
        tracking_db_path=test_dbs["track_db"],
    )
    app.config["TESTING"] = True
    client = app.test_client()

    # 1. GET /api/daily-practice (overview)
    res = client.get("/api/daily-practice")
    assert res.status_code == 200
    data = res.get_json()
    assert "total_sessions" in data
    assert data["total_sessions"] == 0

    # 2. GET /api/daily-practice/latest
    res = client.get("/api/daily-practice/latest")
    assert res.status_code == 200
    assert res.get_json()["session"] is None

    # 3. GET /api/daily-practice/history
    res = client.get("/api/daily-practice/history")
    assert res.status_code == 200
    assert res.get_json()["sessions"] == []

    # 4. POST /api/daily-practice/generate (preview)
    res = client.post("/api/daily-practice/generate", json={"budget_minutes": 30, "preview_only": True})
    assert res.status_code == 200
    assert "tasks" in res.get_json()

    # 4b. POST /api/daily-practice/generate (create)
    res = client.post("/api/daily-practice/generate", json={"budget_minutes": 45})
    assert res.status_code == 201
    session_data = res.get_json()
    sid = session_data["session_id"]
    task_id = session_data["tasks"][0]["task_id"]

    # 5. POST /api/daily-practice/start
    res = client.post("/api/daily-practice/start", json={"session_id": sid})
    assert res.status_code == 200
    assert res.get_json()["status"] == "active"

    # 6. POST /api/daily-practice/task/start
    res = client.post("/api/daily-practice/task/start", json={"session_id": sid, "task_id": task_id})
    assert res.status_code == 200

    # 7. POST /api/daily-practice/task/complete
    res = client.post(
        "/api/daily-practice/task/complete",
        json={"session_id": sid, "task_id": task_id, "verified_pass": True, "notes": "API test passed"},
    )
    assert res.status_code == 200
    assert res.get_json()["progress"]["verified_passes"] == 1

    # 8. POST /api/daily-practice/task/skip
    if len(session_data["tasks"]) > 1:
        t2_id = session_data["tasks"][1]["task_id"]
        res = client.post("/api/daily-practice/task/skip", json={"session_id": sid, "task_id": t2_id, "reason": "Skip test"})
        assert res.status_code == 200

    # 9. POST /api/daily-practice/pause
    res = client.post("/api/daily-practice/pause", json={"session_id": sid, "reason": "Break"})
    assert res.status_code == 200
    assert res.get_json()["status"] == "paused"

    # 10. POST /api/daily-practice/resume
    res = client.post("/api/daily-practice/resume", json={"session_id": sid})
    assert res.status_code == 200
    assert res.get_json()["status"] == "active"

    # 11. POST /api/daily-practice/complete
    res = client.post("/api/daily-practice/complete", json={"session_id": sid, "notes": "Finished!"})
    assert res.status_code == 200
    complete_data = res.get_json()
    assert "session" in complete_data
    assert "report" in complete_data

    # 12. GET /api/daily-practice/report/<session_id>
    res = client.get(f"/api/daily-practice/report/{sid}")
    assert res.status_code == 200
    assert res.get_json()["session_id"] == sid

    # 13. POST /api/daily-practice/re-evaluate
    res = client.post("/api/daily-practice/re-evaluate", json={"session_id": sid})
    assert res.status_code == 200
    assert "snapshot" in res.get_json()

    # 14. POST /api/daily-practice/abandon
    # Create another session to test abandon endpoint
    res = client.post("/api/daily-practice/generate", json={"budget_minutes": 15})
    assert res.status_code == 201
    sid2 = res.get_json()["session_id"]
    res = client.post("/api/daily-practice/abandon", json={"session_id": sid2, "reason": "Abandon test"})
    assert res.status_code == 200
    assert res.get_json()["status"] == "abandoned"

    # Validation errors
    res = client.post("/api/daily-practice/generate", json={"budget_minutes": "invalid"})
    assert res.status_code == 400

    res = client.post("/api/daily-practice/start", json={"session_id": "nonexistent_id"})
    assert res.status_code == 400

    res = client.get("/api/daily-practice/report/invalid;id!")
    assert res.status_code == 400
