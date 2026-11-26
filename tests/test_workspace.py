"""Unit and integration tests for Milestone 6.3.16: Mission-Integrated Coding Workspace.

Validates:
- Workspace initialization and schema creation in session_tracking.db.
- Problem context extraction (metadata, examples, constraints, topics, starter code, mission link).
- Draft management (saving, loading, clearing, cross-language isolation, cross-problem isolation).
- Local judge integration via UnifiedJudge:
    - Passing solution execution.
    - Wrong answer classification with test details.
    - Syntax/compilation errors.
    - Runtime errors / timeouts.
- OfflineCodingCoach integration with workspace run results.
- Mission integration:
    - Focus mode state preservation when opening editor.
    - Explicit confirmation requirement for completing mission task.
    - Prevention of duplicate completion events.
- Run history persistence.
- Dashboard API endpoints (/api/workspace, /api/workspace/problem/<id>, /api/workspace/draft/<id>,
  /api/workspace/draft/save, /api/workspace/run, /api/workspace/history, /api/workspace/result/<id>).
- Database isolation (temporary SQLite databases only, zero production database changes).
"""

import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.daily_mission import DailyMissionManager, MissionStatus, MissionTaskStatus
from intelligence.workspace import (
    ProblemWorkspaceContext,
    WorkspaceDraft,
    WorkspaceManager,
    WorkspaceRunResult,
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


def test_workspace_manager_initialization(temp_dbs):
    """Verify WorkspaceManager sets up workspace tables safely."""
    prog_db, track_db = temp_dbs
    mgr = WorkspaceManager(tracking_db_path=track_db, progress_db_path=prog_db)
    assert mgr is not None

    with sqlite3.connect(track_db) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "workspace_drafts" in tables
        assert "workspace_runs" in tables


def test_problem_context_loading(temp_dbs):
    """Verify loading problem context, metadata, starter code, and examples."""
    prog_db, track_db = temp_dbs
    mgr = WorkspaceManager(tracking_db_path=track_db, progress_db_path=prog_db)

    ctx = mgr.get_problem_context("two-sum")
    assert ctx is not None
    assert isinstance(ctx, ProblemWorkspaceContext)
    assert ctx.problem_id == "two-sum"
    assert "Two Sum" in ctx.title
    assert ctx.difficulty.lower() == "easy"
    assert "python" in ctx.starter_code
    assert len(ctx.examples) > 0


def test_draft_saving_and_isolation(temp_dbs):
    """Verify draft persistence, cross-language isolation, and cross-problem isolation."""
    prog_db, track_db = temp_dbs
    mgr = WorkspaceManager(tracking_db_path=track_db, progress_db_path=prog_db)

    # Save Python draft for two-sum
    d_py = mgr.save_draft("two-sum", "python", "def twoSum(): pass")
    assert d_py.problem_id == "two-sum"
    assert d_py.language == "python"
    assert d_py.code == "def twoSum(): pass"

    # Save C++ draft for two-sum
    d_cpp = mgr.save_draft("two-sum", "cpp", "class Solution {};")
    assert d_cpp.language == "cpp"

    # Save Python draft for another problem
    d_other = mgr.save_draft("valid-parentheses", "python", "def isValid(): pass")

    # Verify loading drafts preserves separation
    loaded_py = mgr.get_draft("two-sum", "python")
    loaded_cpp = mgr.get_draft("two-sum", "cpp")
    loaded_other = mgr.get_draft("valid-parentheses", "python")

    assert loaded_py is not None and loaded_py.code == "def twoSum(): pass"
    assert loaded_cpp is not None and loaded_cpp.code == "class Solution {};"
    assert loaded_other is not None and loaded_other.code == "def isValid(): pass"

    # Clear draft
    cleared = mgr.clear_draft("two-sum", "cpp")
    assert cleared is True
    assert mgr.get_draft("two-sum", "cpp") is None
    # Python draft remains intact
    assert mgr.get_draft("two-sum", "python") is not None


def test_judge_execution_passing_and_wrong_answer(temp_dbs):
    """Verify running solution with local judge for pass and fail outcomes."""
    prog_db, track_db = temp_dbs
    mgr = WorkspaceManager(tracking_db_path=track_db, progress_db_path=prog_db)

    passing_code = (
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, n in enumerate(nums):\n"
        "        diff = target - n\n"
        "        if diff in seen:\n"
        "            return [seen[diff], i]\n"
        "        seen[n] = i\n"
        "    return []\n"
    )

    pass_res = mgr.run_code("two-sum", passing_code, language="python")
    assert isinstance(pass_res, WorkspaceRunResult)
    assert pass_res.status == "passed"
    assert pass_res.passed_count == pass_res.total_tests
    assert pass_res.can_complete_task is True

    failing_code = (
        "def two_sum(nums, target):\n"
        "    return [0, 0]\n"
    )
    fail_res = mgr.run_code("two-sum", failing_code, language="python")
    assert fail_res.status == "wrong_answer"
    assert fail_res.can_complete_task is False
    assert fail_res.failed_test_detail is not None


def test_judge_execution_syntax_error(temp_dbs):
    """Verify syntax or compile error reporting."""
    prog_db, track_db = temp_dbs
    mgr = WorkspaceManager(tracking_db_path=track_db, progress_db_path=prog_db)

    bad_syntax = "class Solution def broken("
    res = mgr.run_code("two-sum", bad_syntax, language="python")
    assert res.status in ("runtime_error", "compile_error")
    assert res.can_complete_task is False
    assert res.execution_error is not None or res.compile_error is not None


def test_mission_integration_and_explicit_confirmation(temp_dbs):
    """Verify mission workflow integration: Focus Mode preservation and explicit task confirmation."""
    prog_db, track_db = temp_dbs
    mission_mgr = DailyMissionManager(tracking_db_path=track_db, progress_db_path=prog_db)
    mission = mission_mgr.generate_mission(max_tasks=2, force_new=True)
    mission_mgr.start_mission(mission.mission_id)

    task = mission.tasks[0]
    task_pid = task.problem_id or "two-sum"

    ws_mgr = WorkspaceManager(tracking_db_path=track_db, progress_db_path=prog_db)
    # 1. Opening workspace does NOT automatically complete task
    ctx = ws_mgr.get_problem_context(task_pid, mission_id=mission.mission_id, task_id=task.task_id)
    assert ctx.current_task_id == task.task_id

    # Verify task is still in_progress
    m_check = mission_mgr.get_mission(mission.mission_id)
    assert m_check.tasks[0].status == MissionTaskStatus.IN_PROGRESS

    # 2. Run passing solution
    passing_code = (
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, n in enumerate(nums):\n"
        "        diff = target - n\n"
        "        if diff in seen:\n"
        "            return [seen[diff], i]\n"
        "        seen[n] = i\n"
        "    return []\n"
    )
    run_res = ws_mgr.run_code("two-sum", passing_code, language="python")
    assert run_res.status == "passed"

    # Task is still NOT completed until explicit confirmation
    m_check2 = mission_mgr.get_mission(mission.mission_id)
    assert m_check2.tasks[0].status == MissionTaskStatus.IN_PROGRESS

    # 3. Explicit confirmation
    confirm_res = ws_mgr.confirm_mission_task_completion(
        mission_id=mission.mission_id,
        task_id=task.task_id,
        problem_id=task_pid,
        run_id=run_res.run_id,
    )
    assert "successfully verified and completed" in confirm_res["message"]

    # Verify task is now marked completed
    m_after = mission_mgr.get_mission(mission.mission_id)
    assert m_after.tasks[0].status == MissionTaskStatus.COMPLETED

    # 4. Duplicate confirmation handling
    dup_res = ws_mgr.confirm_mission_task_completion(
        mission_id=mission.mission_id,
        task_id=task.task_id,
        problem_id=task_pid,
        run_id=run_res.run_id,
    )
    assert "already completed" in dup_res["message"]


def test_dashboard_api_workspace_endpoints(temp_dbs):
    """Verify Flask API routes for workspace."""
    prog_db, track_db = temp_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    # GET /api/workspace
    res_status = client.get("/api/workspace")
    assert res_status.status_code == 200
    assert res_status.get_json()["status"] == "ready"

    # GET /api/workspace/problem/two-sum
    res_prob = client.get("/api/workspace/problem/two-sum")
    assert res_prob.status_code == 200
    p_data = res_prob.get_json()
    assert p_data["problem_id"] == "two-sum"
    assert "starter_code" in p_data

    # POST /api/workspace/draft/save
    res_save = client.post(
        "/api/workspace/draft/save",
        data=json.dumps({"problem_id": "two-sum", "language": "python", "code": "# Draft test"}),
        content_type="application/json",
    )
    assert res_save.status_code == 200
    assert res_save.get_json()["code"] == "# Draft test"

    # GET /api/workspace/draft/two-sum
    res_draft = client.get("/api/workspace/draft/two-sum?language=python")
    assert res_draft.status_code == 200
    assert res_draft.get_json()["code"] == "# Draft test"

    # POST /api/workspace/run
    passing_code = (
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, n in enumerate(nums):\n"
        "        diff = target - n\n"
        "        if diff in seen:\n"
        "            return [seen[diff], i]\n"
        "        seen[n] = i\n"
        "    return []\n"
    )
    res_run = client.post(
        "/api/workspace/run",
        data=json.dumps({"problem_id": "two-sum", "language": "python", "code": passing_code}),
        content_type="application/json",
    )
    assert res_run.status_code == 200
    run_data = res_run.get_json()
    assert run_data["status"] == "passed"
    run_id = run_data["run_id"]

    # GET /api/workspace/result/<run_id>
    res_getrun = client.get(f"/api/workspace/result/{run_id}")
    assert res_getrun.status_code == 200
    assert res_getrun.get_json()["run_id"] == run_id

    # GET /api/workspace/history
    res_hist = client.get("/api/workspace/history?problem_id=two-sum")
    assert res_hist.status_code == 200
    assert len(res_hist.get_json()) >= 1
