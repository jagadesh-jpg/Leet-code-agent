"""Unit and integration tests for Milestone 6.3.13: Personal Learning Goals & Achievement Tracker.

Validates:
- Goal CRUD (create, get, list, update, pause, resume, complete, archive).
- Pacing recommendations via GoalPlanRecommendation.
- Live progress calculations against progress.db and session_tracking.db without fabrication.
- Milestone unlocking logic (First Problem Solved, First Session Completed, Goal Achieved, Smart Recall Pioneer, DSA Foundation).
- Goals analytics reporting.
- Flask API endpoints for goals and milestones.
- Database isolation (temporary SQLite databases only, zero modification to production databases).
"""

import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.goals import (
    GoalPlanRecommendation,
    GoalStatus,
    GoalType,
    GoalsAnalyticsReport,
    GoalsManager,
    LearningGoal,
    MilestoneAchievement,
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

    # Setup schema for session_tracking.db (sessions and spaced revisions)
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

    return prog_db, track_db


def test_goals_manager_initialization(temp_dbs):
    prog_db, track_db = temp_dbs
    mgr = GoalsManager(tracking_db_path=track_db, progress_db_path=prog_db)
    assert mgr is not None

    # Check tables created
    with sqlite3.connect(track_db) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "learning_goals" in tables
        assert "achievement_unlocks" in tables


def test_goal_creation_and_validation(temp_dbs):
    prog_db, track_db = temp_dbs
    mgr = GoalsManager(tracking_db_path=track_db, progress_db_path=prog_db)

    # Valid goal
    goal = mgr.create_goal(
        title="Solve 10 Easy Problems",
        goal_type=GoalType.SOLVE_DIFFICULTY,
        target_value=10,
        target_difficulty="easy",
        days_to_complete=7,
    )
    assert goal.goal_id.startswith("goal_")
    assert goal.title == "Solve 10 Easy Problems"
    assert goal.target_value == 10
    assert goal.status == GoalStatus.ACTIVE
    assert goal.days_remaining is not None
    assert goal.days_remaining >= 6

    # Validation errors
    with pytest.raises(ValueError, match="Goal title cannot be empty"):
        mgr.create_goal("", GoalType.SOLVE_PROBLEMS, 5)

    with pytest.raises(ValueError, match="Target value must be a positive integer"):
        mgr.create_goal("Test", GoalType.SOLVE_PROBLEMS, 0)

    with pytest.raises(ValueError, match="requires a valid target_difficulty"):
        mgr.create_goal("Test", GoalType.SOLVE_DIFFICULTY, 5, target_difficulty=None)

    with pytest.raises(ValueError, match="requires a valid target_topic"):
        mgr.create_goal("Test", GoalType.PRACTICE_TOPIC, 5, target_topic=None)


def test_goal_crud_operations(temp_dbs):
    prog_db, track_db = temp_dbs
    mgr = GoalsManager(tracking_db_path=track_db, progress_db_path=prog_db)

    g1 = mgr.create_goal("Solve 5 Problems", GoalType.SOLVE_PROBLEMS, 5)
    g2 = mgr.create_goal("Practice DP", GoalType.PRACTICE_TOPIC, 3, target_topic="dynamic-programming")

    # List active
    active = mgr.list_goals(status_filter=GoalStatus.ACTIVE)
    assert len(active) == 2

    # Get single
    fetched = mgr.get_goal(g1.goal_id)
    assert fetched is not None
    assert fetched.goal_id == g1.goal_id

    # Update goal
    updated = mgr.update_goal(g1.goal_id, title="Solve 8 Problems", target_value=8)
    assert updated.title == "Solve 8 Problems"
    assert updated.target_value == 8

    # Pause and resume
    paused = mgr.set_goal_status(g1.goal_id, GoalStatus.PAUSED)
    assert paused.status == GoalStatus.PAUSED

    resumed = mgr.set_goal_status(g1.goal_id, GoalStatus.ACTIVE)
    assert resumed.status == GoalStatus.ACTIVE

    # Complete goal
    completed = mgr.complete_goal(g1.goal_id)
    assert completed.status == GoalStatus.COMPLETED
    assert completed.completed_at is not None

    # Archive goal
    archived = mgr.set_goal_status(g2.goal_id, GoalStatus.ARCHIVED)
    assert archived.status == GoalStatus.ARCHIVED


def test_live_progress_calculation(temp_dbs):
    prog_db, track_db = temp_dbs
    mgr = GoalsManager(tracking_db_path=track_db, progress_db_path=prog_db)

    # Insert solved problems into progress.db
    with sqlite3.connect(prog_db) as conn:
        conn.execute(
            "INSERT INTO attempts (problem_id, language, passed, total, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("two-sum", "python", 10, 10, "2026-11-26 10:00:00"),
        )
        conn.execute(
            "INSERT INTO attempts (problem_id, language, passed, total, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("valid-parentheses", "python", 5, 5, "2026-11-26 11:00:00"),
        )
        conn.execute(
            "INSERT INTO attempts (problem_id, language, passed, total, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("failed-prob", "python", 2, 5, "2026-11-26 12:00:00"),  # Not solved
        )

    # Goal for solved count
    g_count = mgr.create_goal("Solve 4 Problems", GoalType.SOLVE_PROBLEMS, 4)
    assert g_count.current_value == 2
    assert g_count.percent_completed == 50.0

    # Goal for easy difficulty
    g_diff = mgr.create_goal("Solve 2 Easy", GoalType.SOLVE_DIFFICULTY, 2, target_difficulty="easy")
    assert g_diff.current_value == 2
    assert g_diff.percent_completed == 100.0
    # Auto-completed since target met!
    assert g_diff.status == GoalStatus.COMPLETED

    # Goal for topic (two-sum is in arrays/hash-table)
    g_topic = mgr.create_goal("Arrays Topic", GoalType.PRACTICE_TOPIC, 2, target_topic="arrays")
    assert g_topic.current_value == 1  # two-sum has arrays


def test_session_and_revision_goals_progress(temp_dbs):
    prog_db, track_db = temp_dbs
    mgr = GoalsManager(tracking_db_path=track_db, progress_db_path=prog_db)

    # Insert a completed session
    with sqlite3.connect(track_db) as conn:
        conn.execute(
            "INSERT INTO learning_sessions (session_id, created_at, status, session_size) VALUES (?, ?, ?, ?)",
            ("sess_1", "2026-11-26 10:00:00", "completed", 3),
        )
        conn.execute(
            "INSERT INTO spaced_revisions (problem_id, difficulty, topics, next_review_at, review_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("two-sum", "easy", "arrays", "2026-11-27 10:00:00", 2, "2026-11-26 10:00:00"),
        )

    g_sess = mgr.create_goal("Finish 2 Sessions", GoalType.COMPLETE_SESSIONS, 2)
    assert g_sess.current_value == 1
    assert g_sess.percent_completed == 50.0

    g_rev = mgr.create_goal("Complete 2 Revisions", GoalType.COMPLETE_REVISIONS, 2)
    assert g_rev.current_value == 2
    assert g_rev.percent_completed == 100.0
    assert g_rev.status == GoalStatus.COMPLETED


def test_milestone_achievements(temp_dbs):
    prog_db, track_db = temp_dbs
    mgr = GoalsManager(tracking_db_path=track_db, progress_db_path=prog_db)

    # Initially, no problem solved, no session
    milestones = mgr.check_and_unlock_milestones()
    unlocked_ids = [m.milestone_id for m in milestones if m.is_unlocked]
    assert len(unlocked_ids) == 0

    # Solve 1 problem
    with sqlite3.connect(prog_db) as conn:
        conn.execute(
            "INSERT INTO attempts (problem_id, language, passed, total, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("two-sum", "python", 5, 5, "2026-11-26 10:00:00"),
        )

    milestones2 = mgr.check_and_unlock_milestones()
    unlocked2 = {m.milestone_id: m for m in milestones2 if m.is_unlocked}
    assert "ach_first_solve" in unlocked2

    # Insert completed session and revision
    with sqlite3.connect(track_db) as conn:
        conn.execute(
            "INSERT INTO learning_sessions (session_id, created_at, status, session_size) VALUES (?, ?, ?, ?)",
            ("sess_1", "2026-11-26 10:00:00", "completed", 3),
        )
        conn.execute(
            "INSERT INTO spaced_revisions (problem_id, difficulty, topics, next_review_at, review_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("two-sum", "easy", "arrays", "2026-11-27 10:00:00", 1, "2026-11-26 10:00:00"),
        )

    # Complete a goal
    g = mgr.create_goal("Solve 1 Problem", GoalType.SOLVE_PROBLEMS, 1)
    assert g.status == GoalStatus.COMPLETED

    milestones3 = mgr.check_and_unlock_milestones()
    unlocked3 = {m.milestone_id: m for m in milestones3 if m.is_unlocked}
    assert "ach_first_session" in unlocked3
    assert "ach_first_revision" in unlocked3
    assert "ach_first_goal" in unlocked3


def test_goal_pacing_and_analytics(temp_dbs):
    prog_db, track_db = temp_dbs
    mgr = GoalsManager(tracking_db_path=track_db, progress_db_path=prog_db)

    # Recommendation
    rec = mgr.recommend_goal_schedule(target_problems=14, target_days=7)
    assert isinstance(rec, GoalPlanRecommendation)
    assert rec.daily_pacing == 2.0
    assert rec.recommended_session_size == 2
    assert rec.sessions_per_week == 7

    # Create goals and verify analytics report
    mgr.create_goal("G1", GoalType.SOLVE_PROBLEMS, 10, days_to_complete=5)
    g2 = mgr.create_goal("G2", GoalType.COMPLETE_SESSIONS, 1)
    mgr.complete_goal(g2.goal_id)

    rep = mgr.get_goals_analytics()
    assert isinstance(rep, GoalsAnalyticsReport)
    assert rep.total_goals == 2
    assert rep.active_goals_count == 1
    assert rep.completed_goals == 1
    assert rep.completion_rate_pct == 50.0


def test_dashboard_api_goals_and_milestones(temp_dbs):
    prog_db, track_db = temp_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    # GET /api/goals initially empty
    res = client.get("/api/goals")
    assert res.status_code == 200
    assert res.get_json() == []

    # POST /api/goals/create
    res_create = client.post(
        "/api/goals/create",
        data=json.dumps({
            "title": "Master Two Pointers",
            "goal_type": "practice_topic",
            "target_value": 4,
            "target_topic": "two-pointers",
            "days_to_complete": 10,
        }),
        content_type="application/json",
    )
    assert res_create.status_code == 201
    created_data = res_create.get_json()
    assert "goal" in created_data
    goal_id = created_data["goal"]["goal_id"]

    # GET /api/goals/<id>
    res_get = client.get(f"/api/goals/{goal_id}")
    assert res_get.status_code == 200
    assert res_get.get_json()["title"] == "Master Two Pointers"

    # POST /api/goals/<id>/update
    res_up = client.post(
        f"/api/goals/{goal_id}/update",
        data=json.dumps({"title": "Master Two Pointers & Arrays", "target_value": 6}),
        content_type="application/json",
    )
    assert res_up.status_code == 200
    assert res_up.get_json()["goal"]["target_metric"] == 6

    # POST /api/goals/<id>/status
    res_pause = client.post(
        f"/api/goals/{goal_id}/status",
        data=json.dumps({"status": "paused"}),
        content_type="application/json",
    )
    assert res_pause.status_code == 200
    assert res_pause.get_json()["goal"]["status"] == "paused"

    # POST /api/goals/<id>/complete
    res_comp = client.post(f"/api/goals/{goal_id}/complete")
    assert res_comp.status_code == 200
    assert res_comp.get_json()["goal"]["status"] == "completed"

    # GET /api/milestones
    res_m = client.get("/api/milestones")
    assert res_m.status_code == 200
    milestones = res_m.get_json()
    assert len(milestones) >= 5

    # GET /api/goals/analytics
    res_a = client.get("/api/goals/analytics")
    assert res_a.status_code == 200
    analytics = res_a.get_json()
    assert analytics["total_goals"] == 1
    assert analytics["completed_goals"] == 1
