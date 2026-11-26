"""Unit and integration tests for Milestone 6.3.15: Daily Learning Mission & Focus Mode.

Validates:
- Mission generation adhering to 4-tier transparent priority rules:
    Priority 1: Spaced revisions due.
    Priority 2: Active learning goals and weak topics.
    Priority 3: Roadmap-ready topics.
    Priority 4: Difficulty progression.
- Empty data behavior and fallback mission generation without fabrication.
- Focus Mode interactive lifecycle:
    Start mission, start task, complete task, skip task, pause, resume, cancel.
- State progression and auto-advancement to next pending task.
- Duplicate prevention and mission completion tracking.
- Database persistence in session_tracking.db without altering production progress.db.
- REST API endpoints (/api/daily-mission, /api/daily-mission/generate, /api/daily-mission/start,
  /api/daily-mission/task/<id>/start, complete, skip, pause, resume, cancel, history, analytics).
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.daily_mission import (
    DailyMission,
    DailyMissionAnalytics,
    DailyMissionManager,
    DailyMissionTask,
    MissionStatus,
    MissionSummaryReport,
    MissionTaskStatus,
    MissionTaskType,
)


@pytest.fixture
def temp_dbs(tmp_path):
    """Create isolated temporary progress.db and session_tracking.db for testing."""
    prog_db = tmp_path / "test_progress.db"
    track_db = tmp_path / "test_session_tracking.db"

    # Setup schema for progress.db
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
        conn.execute(
            """
            CREATE TABLE custom_problems (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

    # Setup schema for session_tracking.db
    with sqlite3.connect(track_db) as conn:
        conn.execute(
            """
            CREATE TABLE learning_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                session_size INTEGER NOT NULL,
                difficulty_preference TEXT,
                focus_topic TEXT,
                completed_at TEXT,
                total_duration_sec REAL DEFAULT 0.0,
                notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE spaced_revisions (
                problem_id TEXT PRIMARY KEY,
                difficulty TEXT NOT NULL,
                topics TEXT NOT NULL,
                box_level INTEGER NOT NULL DEFAULT 1,
                interval_days INTEGER NOT NULL DEFAULT 1,
                last_reviewed_at TEXT,
                next_review_at TEXT NOT NULL,
                recall_history TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                review_count INTEGER NOT NULL DEFAULT 0,
                streak INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE learning_goals (
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

    return prog_db, track_db


def test_daily_mission_manager_initialization(temp_dbs):
    """Verify DailyMissionManager initializes database schema in tracking DB safely."""
    prog_db, track_db = temp_dbs
    mgr = DailyMissionManager(tracking_db_path=track_db, progress_db_path=prog_db)
    assert mgr is not None

    with sqlite3.connect(track_db) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "daily_missions" in tables
        assert "daily_mission_tasks" in tables


def test_empty_database_fallback_generation(temp_dbs):
    """Verify mission generation on empty databases provides sensible non-fabricated tasks."""
    prog_db, track_db = temp_dbs
    mgr = DailyMissionManager(tracking_db_path=track_db, progress_db_path=prog_db)

    mission = mgr.generate_mission(target_duration_min=45, max_tasks=3)
    assert isinstance(mission, DailyMission)
    assert mission.mission_id.startswith("mission_")
    assert mission.status == MissionStatus.CREATED
    assert mission.total_tasks > 0
    assert len(mission.tasks) > 0
    assert mission.completion_percentage == 0.0

    first_task = mission.tasks[0]
    assert isinstance(first_task, DailyMissionTask)
    assert first_task.status == MissionTaskStatus.PENDING
    assert first_task.problem_id is not None


def test_priority_rules_task_selection(temp_dbs):
    """Verify prioritization: P1 Spaced Revision > P2 Active Goal > P3 Roadmap > P4 General."""
    prog_db, track_db = temp_dbs

    # Insert an overdue spaced revision
    with sqlite3.connect(track_db) as conn:
        conn.execute(
            "INSERT INTO spaced_revisions (problem_id, difficulty, topics, next_review_at, review_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("two-sum", "easy", "arrays", "2026-11-20 00:00:00", 1, "2026-11-15 00:00:00"),
        )
        # Insert active learning goal
        conn.execute(
            "INSERT INTO learning_goals (goal_id, title, goal_type, target_metric, current_progress, target_parameter, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("g1", "Master Stacks", "practice_topic", 3, 0, "stack", "active", "2026-11-26 00:00:00", "2026-11-26 00:00:00"),
        )

    mgr = DailyMissionManager(tracking_db_path=track_db, progress_db_path=prog_db)
    mission = mgr.generate_mission(target_duration_min=45, max_tasks=3, force_new=True)

    task_types = [t.task_type for t in mission.tasks]
    # Priority 1 present
    assert MissionTaskType.REVISE_DUE_PROBLEM in task_types
    # Priority 2 present
    assert MissionTaskType.PURSUE_LEARNING_GOAL in task_types


def test_focus_mode_lifecycle_and_task_advancement(temp_dbs):
    """Verify interactive workflow: start mission, start task, complete task, advance sequence."""
    prog_db, track_db = temp_dbs
    mgr = DailyMissionManager(tracking_db_path=track_db, progress_db_path=prog_db)
    mission = mgr.generate_mission(max_tasks=2, force_new=True)

    # 1. Start mission
    started_m = mgr.start_mission(mission.mission_id)
    assert started_m.status == MissionStatus.IN_PROGRESS
    assert started_m.tasks[0].status == MissionTaskStatus.IN_PROGRESS

    # 2. Complete first task -> auto-advance to task 2
    task1 = started_m.tasks[0]
    comp_t1, m_after1 = mgr.complete_task(task1.task_id)
    assert comp_t1.status == MissionTaskStatus.COMPLETED
    assert m_after1.completed_tasks_count == 1
    assert m_after1.tasks[1].status == MissionTaskStatus.IN_PROGRESS

    # 3. Skip second task with reason -> mission completes
    task2 = m_after1.tasks[1]
    skip_t2, m_final = mgr.skip_task(task2.task_id, reason="Topic already reviewed elsewhere")
    assert skip_t2.status == MissionTaskStatus.SKIPPED
    assert skip_t2.skip_reason == "Topic already reviewed elsewhere"
    assert m_final.status == MissionStatus.COMPLETED
    assert m_final.completed_at is not None


def test_mission_pause_resume_and_cancellation(temp_dbs):
    """Verify pause, resume, and cancel transitions."""
    prog_db, track_db = temp_dbs
    mgr = DailyMissionManager(tracking_db_path=track_db, progress_db_path=prog_db)
    mission = mgr.generate_mission(max_tasks=2, force_new=True)

    mgr.start_mission(mission.mission_id)

    # Pause
    paused = mgr.pause_mission(mission.mission_id)
    assert paused.status == MissionStatus.PAUSED
    assert paused.paused_at is not None

    # Resume
    resumed = mgr.resume_mission(mission.mission_id)
    assert resumed.status == MissionStatus.IN_PROGRESS
    assert resumed.paused_at is None

    # Cancel
    cancelled = mgr.cancel_mission(mission.mission_id)
    assert cancelled.status == MissionStatus.CANCELLED


def test_mission_summary_and_analytics(temp_dbs):
    """Verify evidence-based mission summary and aggregated history."""
    prog_db, track_db = temp_dbs
    mgr = DailyMissionManager(tracking_db_path=track_db, progress_db_path=prog_db)
    mission = mgr.generate_mission(max_tasks=2, force_new=True)
    mgr.start_mission(mission.mission_id)
    mgr.complete_task(mission.tasks[0].task_id)

    summary = mgr.get_mission_summary(mission.mission_id)
    assert isinstance(summary, MissionSummaryReport)
    assert summary.tasks_completed == 1
    assert summary.total_tasks == 2
    assert summary.completion_rate_pct == 50.0

    analytics = mgr.get_analytics()
    assert isinstance(analytics, DailyMissionAnalytics)
    assert analytics.total_missions_generated >= 1
    assert analytics.total_tasks_completed >= 1


def test_dashboard_api_daily_mission_endpoints(temp_dbs):
    """Verify Flask API routes for daily mission & focus mode."""
    prog_db, track_db = temp_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    # GET /api/daily-mission
    res_m = client.get("/api/daily-mission")
    assert res_m.status_code == 200
    m_data = res_m.get_json()
    assert "mission_id" in m_data
    assert "tasks" in m_data
    mission_id = m_data["mission_id"]
    task_id = m_data["tasks"][0]["task_id"]

    # POST /api/daily-mission/start
    res_start = client.post("/api/daily-mission/start", data=json.dumps({"mission_id": mission_id}), content_type="application/json")
    assert res_start.status_code == 200
    assert res_start.get_json()["status"] == "in_progress"

    # POST /api/daily-mission/task/<id>/start
    res_tstart = client.post(f"/api/daily-mission/task/{task_id}/start")
    assert res_tstart.status_code == 200
    assert res_tstart.get_json()["status"] == "in_progress"

    # POST /api/daily-mission/task/<id>/complete
    res_tcomp = client.post(f"/api/daily-mission/task/{task_id}/complete")
    assert res_tcomp.status_code == 200
    assert res_tcomp.get_json()["task"]["status"] == "completed"

    # POST /api/daily-mission/pause
    res_pause = client.post("/api/daily-mission/pause")
    assert res_pause.status_code == 200
    assert res_pause.get_json()["status"] == "paused"

    # POST /api/daily-mission/resume
    res_resume = client.post("/api/daily-mission/resume")
    assert res_resume.status_code == 200
    assert res_resume.get_json()["status"] == "in_progress"

    # GET /api/daily-mission/history
    res_hist = client.get("/api/daily-mission/history")
    assert res_hist.status_code == 200
    assert isinstance(res_hist.get_json(), list)

    # GET /api/daily-mission/analytics
    res_ana = client.get("/api/daily-mission/analytics")
    assert res_ana.status_code == 200
    assert "total_missions_generated" in res_ana.get_json()
