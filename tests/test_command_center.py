"""Unit and integration tests for Milestone 6.3.27: Unified Learning Command Center.

Validates:
- Non-destructive database operations (production progress.db remains unmutated).
- CommandCenterOverview aggregation across all 6 core sections:
  1. Overall Activity (overview_stats & coding_performance)
  2. Today's Learning
  3. My Skill Focus
  4. Adaptive Learning Loop
  5. Interview & Preparation
  6. Recent Activity Stream
- Unified Action Flow priority ranking:
  P0: Active/Paused practice session
  P1: Ready practice session
  P1: Pending plan proposals
  P1: Overdue spaced revisions
  P2: Unresolved failing attempts
  P2: Top algorithmic skill gap
  P3: Default baseline practice session
- Graceful empty database handling and zero-division resilience.
- Flask REST API endpoints:
  GET /api/command-center
  GET /api/command-center/action
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.command_center import (
    CommandCenterManager,
    CommandCenterOverview,
    PrimaryAction,
    PrimaryActionType,
)
from intelligence.daily_practice import (
    DailyPracticeOrchestrator,
    DailyPracticeSession,
    DailyPracticeSessionStatus,
    DailyPracticeTask,
    DailyPracticeTaskStatus,
    DailyPracticeTaskType,
)
from intelligence.learning_loop import (
    AdaptiveLearningLoop,
    LearningLoopPhase,
    LearningLoopChangeProposal,
    ProposalActionType,
    ProposalStatus,
)
from intelligence.preparation_planner import (
    PreparationPlan,
    PreparationPlanner,
    PreparationTask,
    TaskStatus,
    TaskType,
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


def test_empty_database_and_defaults(test_dbs):
    """Test Command Center overview and action derivation on empty databases."""
    manager = CommandCenterManager(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    overview = manager.get_overview()
    assert isinstance(overview, CommandCenterOverview)
    assert overview.today_learning["status"] == "none"
    assert overview.today_learning["completion_pct"] == 0.0
    assert overview.overview_stats["total_attempts"] == 0
    assert overview.overview_stats["total_solved"] == 0
    assert overview.skill_focus["has_data"] is False
    assert overview.adaptive_learning["pending_proposals_count"] == 0

    # Default action must be P3 baseline practice
    action = manager.derive_primary_action()
    assert isinstance(action, PrimaryAction)
    assert action.priority == "P3"
    assert action.action_type == PrimaryActionType.GENERATE_DAILY_PRACTICE.value
    assert "Generate Today's Practice Session" in action.title


def test_action_flow_p0_active_session(test_dbs):
    """Test priority P0: Active daily practice session takes top priority."""
    orchestrator = DailyPracticeOrchestrator(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )
    session = orchestrator.generate_session(budget_minutes=30, title="Active Test Session")
    orchestrator.start_session(session.session_id)

    manager = CommandCenterManager(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    action = manager.derive_primary_action()
    assert action.priority == "P0"
    assert action.action_type == PrimaryActionType.CONTINUE_DAILY_PRACTICE.value
    assert "Continue Active Practice" in action.title
    assert action.target_id == session.session_id


def test_action_flow_p1_ready_session(test_dbs):
    """Test priority P1: Generated READY session awaiting user start."""
    orchestrator = DailyPracticeOrchestrator(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )
    session = orchestrator.generate_session(budget_minutes=45, title="Ready Test Session")

    manager = CommandCenterManager(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    action = manager.derive_primary_action()
    assert action.priority == "P1"
    assert action.action_type == PrimaryActionType.START_DAILY_PRACTICE.value
    assert "Start Scheduled Session" in action.title
    assert action.target_id == session.session_id


def test_action_flow_p1_pending_proposals(test_dbs):
    """Test priority P1: Pending adaptive plan proposals take priority when no session is active/ready."""
    loop = AdaptiveLearningLoop(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )
    loop.init_schema()
    with sqlite3.connect(test_dbs["track_db"]) as conn:
        conn.execute(
            """
            INSERT INTO learning_loop_snapshots
            (snapshot_id, created_at, phase, confidence, snapshot_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("snap_1", "2026-11-20T10:00:00", "re_evaluation", "high", "{}"),
        )
        conn.execute(
            """
            INSERT INTO learning_loop_proposals
            (proposal_id, snapshot_id, action_type, status, plan_id, task_id, topic, problem_id, target_difficulty, title, description, rationale, supporting_evidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "prop_test_1",
                "snap_1",
                "add_task",
                "pending",
                "plan_1",
                None,
                "recursion",
                "subsets",
                "Medium",
                "Inject Priority Review",
                "Practice recursion to address verified weakness",
                "Detected difficulty in recursion",
                "Multiple recursion errors",
                "2026-11-20T10:00:00",
            ),
        )
        conn.commit()

    manager = CommandCenterManager(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    action = manager.derive_primary_action()
    assert action.priority == "P1"
    assert action.action_type == PrimaryActionType.REVIEW_PROPOSALS.value
    assert "Review 1 Pending Plan Change Proposal" in action.title
    assert action.target_id == "prop_test_1"


def test_action_flow_p1_overdue_revisions(test_dbs):
    """Test priority P1: Overdue spaced revisions take priority when no proposals exist."""
    rev_engine = SpacedRevisionEngine(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )
    rev_engine.schedule_problem(
        problem={"id": "two-sum", "title": "Two Sum", "difficulty": "easy"},
        custom_next_date="2020-01-01",
    )

    manager = CommandCenterManager(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    action = manager.derive_primary_action()
    assert action.priority == "P1"
    assert action.action_type == PrimaryActionType.REVIEW_REVISIONS.value
    assert "Review 1 Overdue Spaced Repetition Problem" in action.title
    assert action.target_id == "two-sum"


def test_action_flow_p2_unresolved_failing_attempt(test_dbs):
    """Test priority P2: Failing attempt without resolution triggers targeted fix."""
    with sqlite3.connect(test_dbs["prog_db"]) as conn:
        conn.execute(
            """
            INSERT INTO attempts (problem_id, attempt_no, code, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("valid-parentheses", 1, "def isValid(): pass", "failed", "SyntaxError", "2026-11-20T10:00:00"),
        )
        conn.commit()

    manager = CommandCenterManager(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    action = manager.derive_primary_action()
    assert action.priority == "P2"
    assert action.action_type == PrimaryActionType.SOLVE_UNRESOLVED.value
    assert "Resolve Test Failures on Problem 'valid-parentheses'" in action.title
    assert action.target_id == "valid-parentheses"


def test_multi_subsystem_aggregation(test_dbs):
    """Test full multi-subsystem aggregation inside CommandCenterOverview."""
    # 1. Add some solved problems
    with sqlite3.connect(test_dbs["prog_db"]) as conn:
        conn.execute(
            """
            INSERT INTO attempts (problem_id, attempt_no, code, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("two-sum", 1, "def twoSum(): return [0, 1]", "passed", None, "2026-11-20T10:00:00"),
        )
        conn.commit()

    # 2. Add a preparation plan
    planner = PreparationPlanner(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )
    plan = planner.generate_plan(title="Interview Sprint")
    planner.save_plan(plan)
    planner.apply_plan(plan.plan_id)

    manager = CommandCenterManager(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    overview = manager.get_overview()
    assert overview.overview_stats["total_solved"] == 1
    assert overview.overview_stats["total_attempts"] == 1
    assert overview.overview_stats["passed_attempts"] == 1
    assert overview.overview_stats["first_attempt_pass_rate_pct"] == 100.0

    assert overview.interview_prep["active_plan"]["title"] == "Interview Sprint"
    assert overview.interview_prep["active_plan"]["total_tasks"] > 0

    assert isinstance(overview.recent_activity, list)


def test_non_destructive_safety(test_dbs):
    """Ensure that progress.db hash is 100% unchanged after invoking CommandCenterManager."""
    with open(test_dbs["prog_db"], "rb") as f:
        hash_before = hashlib.sha256(f.read()).hexdigest()

    manager = CommandCenterManager(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    # Perform multiple analytical operations
    _ = manager.get_overview()
    _ = manager.derive_primary_action()

    with open(test_dbs["prog_db"], "rb") as f:
        hash_after = hashlib.sha256(f.read()).hexdigest()

    assert hash_before == hash_after, "Command Center mutated progress.db!"


def test_flask_rest_api_endpoints(test_dbs):
    """Test Flask REST API endpoints /api/command-center and /api/command-center/action."""
    app = create_app(
        db_path=str(test_dbs["prog_db"]),
        tracking_db_path=str(test_dbs["track_db"]),
    )
    client = app.test_client()

    # 1. GET /api/command-center
    res = client.get("/api/command-center")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert "timestamp" in data
    assert "primary_action" in data
    assert "today_learning" in data
    assert "skill_focus" in data
    assert "adaptive_learning" in data
    assert "interview_prep" in data
    assert "overview_stats" in data
    assert "recent_activity" in data

    # 2. GET /api/command-center/action
    res_action = client.get("/api/command-center/action")
    assert res_action.status_code == 200
    action_data = json.loads(res_action.data)
    assert "action_type" in action_data
    assert "priority" in action_data
    assert "title" in action_data
    assert "cta_label" in action_data
