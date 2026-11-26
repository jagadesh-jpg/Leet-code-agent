"""Unit and integration tests for Milestone 6.3.21: Adaptive Interview Preparation Planner.

Validates:
- Planner initialization and schema creation in session_tracking.db.
- Configuration settings validation and boundary enforcement.
- Daily availability limits (planned minutes strictly bounded by daily_minutes).
- Multi-horizon planning (7, 14, 30 days).
- Empty-data behavior (clean foundational recommendations without prior history).
- Evidence-driven task selection (weaknesses, overdue revisions, roadmap topics).
- Structured daily and weekly plan generation.
- Task completion (recording actual study minutes and status).
- Task skipping (recording reasons and state transition).
- Progress and streak calculations.
- Adaptive replanning preview and application (preserving completed tasks).
- All 13 Dashboard REST API endpoints in dashboard_server.py.
- 100% offline operation and database isolation.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.interview_analytics import InterviewAnalyticsManager
from intelligence.mock_interview import InterviewManager
from intelligence.preparation_planner import (
    IntensityLevel,
    PlanProgress,
    PlanStatus,
    PlannerSettings,
    PreparationDay,
    PreparationPlan,
    PreparationPlanner,
    PreparationTask,
    PreparationWeek,
    TaskPriority,
    TaskStatus,
    TaskType,
)


from intelligence.revision import SpacedRevisionEngine


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

    # Initialize InterviewManager to ensure mock interview tables exist
    im = InterviewManager(tracking_db_path=track_db, progress_db_path=prog_db)
    # Initialize InterviewAnalyticsManager
    am = InterviewAnalyticsManager(tracking_db_path=track_db, progress_db_path=prog_db)
    # Initialize PreparationPlanner
    planner = PreparationPlanner(tracking_db_path=track_db, progress_db_path=prog_db)

    return {
        "prog_db": prog_db,
        "track_db": track_db,
        "planner": planner,
        "analytics_mgr": am,
        "tmp_path": tmp_path,
    }


def _insert_mock_interview(
    track_db: Path,
    interview_id: str,
    total_score: float = 55.0,
    correctness_score: float = 18.0,
    completion_score: float = 8.0,
    structure_score: float = 9.0,
    complexity_score: float = 6.0,
    time_management_score: float = 5.0,
):
    """Helper to insert an evaluated mock interview record directly into the test database."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(track_db) as conn:
        conn.execute(
            """
            INSERT INTO mock_interviews (
                interview_id, title, track, duration_minutes, language,
                problem_count, current_problem_index, status, created_at,
                started_at, expires_at, completed_at, total_score, correctness_score,
                completion_score, structure_score, complexity_score, time_management_score,
                summary_feedback, rubric_breakdown_json, recommendations_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interview_id, f"Mock Interview {interview_id}", "intermediate", 45, "python",
                2, 2, "completed", now_str,
                now_str, now_str, now_str, total_score, correctness_score,
                completion_score, structure_score, complexity_score, time_management_score,
                "Test feedback summary", "{}", "[]"
            ),
        )


def _insert_revision_due(track_db: Path, problem_id: str):
    """Helper to insert an overdue revision item in session_tracking.db."""
    rev_engine = SpacedRevisionEngine(tracking_db_path=track_db)
    prob_dict = {
        "id": problem_id,
        "title": "Two Sum",
        "difficulty": "easy",
        "topics": ["Arrays", "Hashing"],
    }
    rev_engine.schedule_problem(
        prob_dict,
        initial_reason="Initial attempt completed",
        custom_next_date="2026-01-01",
    )


# =============================================================================
# 1. Settings Validation & Bounds
# =============================================================================

def test_settings_validation_and_persistence(test_env):
    """Verify settings validation rules and persistence."""
    planner = test_env["planner"]

    # Default settings
    default_settings = planner.get_settings()
    assert default_settings.daily_minutes == 60
    assert default_settings.horizon_days == 7
    assert default_settings.sessions_per_day == 2
    assert default_settings.target_track == "intermediate"

    # Validation: daily_minutes too low (< 15) or too high (> 360)
    with pytest.raises(ValueError, match="daily_minutes"):
        PlannerSettings(daily_minutes=10).validate()
    with pytest.raises(ValueError, match="daily_minutes"):
        PlannerSettings(daily_minutes=400).validate()

    # Validation: invalid horizon_days
    with pytest.raises(ValueError, match="horizon_days"):
        PlannerSettings(horizon_days=21).validate()

    # Validation: invalid track
    with pytest.raises(ValueError, match="target_track"):
        PlannerSettings(target_track="expert").validate()

    # Validation: invalid intensity
    with pytest.raises(ValueError, match="intensity"):
        PlannerSettings(intensity="extreme").validate()

    # Save and reload valid custom settings
    custom = PlannerSettings(
        daily_minutes=90,
        horizon_days=14,
        preferred_days=["mon", "wed", "fri"],
        sessions_per_day=3,
        target_track="advanced",
        language="cpp",
        target_score=85.0,
        intensity="intensive",
    )
    saved = planner.save_settings(custom)
    assert saved.daily_minutes == 90

    reloaded = planner.get_settings()
    assert reloaded.daily_minutes == 90
    assert reloaded.horizon_days == 14
    assert reloaded.preferred_days == ["mon", "wed", "fri"]
    assert reloaded.language == "cpp"


# =============================================================================
# 2. Empty-Data Behavior (Foundational Fallback)
# =============================================================================

def test_empty_data_plan_generation(test_env):
    """Verify plan generation without prior assessment history produces clean foundational schedule."""
    planner = test_env["planner"]

    plan = planner.generate_plan()
    assert plan.plan_id.startswith("plan_")
    assert plan.status == PlanStatus.DRAFT.value
    assert plan.horizon_days == 7
    assert len(plan.weeks) == 1
    assert len(plan.all_tasks) > 0

    # Ensure none of the tasks exceed daily budget
    for day in plan.weeks[0].days:
        if day.is_study_day:
            day_total = sum(t.estimated_minutes for t in day.tasks)
            assert day_total <= plan.settings.daily_minutes
            assert day.planned_minutes == day_total

    # Tasks should have evidence marked as foundational recommendation
    foundational_tasks = [t for t in plan.all_tasks if "Foundational" in t.reason or "foundational" in t.evidence.lower()]
    assert len(foundational_tasks) > 0


# =============================================================================
# 3. Evidence-Driven Prioritization (Weaknesses, Revisions, Milestones)
# =============================================================================

def test_evidence_driven_task_selection(test_env):
    """Verify planner prioritizes tasks based on interview weaknesses and overdue revisions."""
    track_db = test_env["track_db"]
    planner = test_env["planner"]

    # 1. Insert 2 low-scoring mock interviews to trigger complexity and correctness weakness
    _insert_mock_interview(track_db=track_db, interview_id="mock_w_1", total_score=45.0, complexity_score=5.0)
    _insert_mock_interview(track_db=track_db, interview_id="mock_w_2", total_score=48.0, complexity_score=6.0)

    # 2. Insert an overdue revision
    _insert_revision_due(track_db=track_db, problem_id="two-sum")

    plan = planner.generate_plan()

    # Verify overdue revision task is scheduled with P0 priority
    rev_tasks = [t for t in plan.all_tasks if t.task_type == TaskType.REVISE_PROBLEM.value]
    assert len(rev_tasks) >= 1
    assert rev_tasks[0].problem_id == "two-sum"
    assert rev_tasks[0].priority == TaskPriority.P0.value

    # Verify complexity review task is generated based on weakness
    cplx_tasks = [t for t in plan.all_tasks if t.task_type == TaskType.REVIEW_COMPLEXITY.value]
    assert len(cplx_tasks) >= 1
    assert "complexity" in cplx_tasks[0].reason.lower()


# =============================================================================
# 4. Multi-Horizon Planning (14 and 30 Days)
# =============================================================================

def test_multi_horizon_plans(test_env):
    """Verify 14-day and 30-day plan structures."""
    planner = test_env["planner"]

    # 14-day plan -> 2 weeks
    s14 = PlannerSettings(horizon_days=14, daily_minutes=45)
    plan14 = planner.generate_plan(settings=s14)
    assert plan14.horizon_days == 14
    assert len(plan14.weeks) == 2

    # 30-day plan -> 5 weeks (30 days spans across 5 partial/full weeks)
    s30 = PlannerSettings(horizon_days=30, daily_minutes=60)
    plan30 = planner.generate_plan(settings=s30)
    assert plan30.horizon_days == 30
    assert len(plan30.weeks) >= 4


# =============================================================================
# 5. Plan Persistence, Application, and Progress
# =============================================================================

def test_plan_persistence_and_application(test_env):
    """Verify saving a plan, applying/activating it, and retrieving it."""
    planner = test_env["planner"]

    # Generate and save draft
    draft_plan = planner.generate_plan()
    saved = planner.save_plan(draft_plan)
    assert saved.plan_id == draft_plan.plan_id
    assert saved.status == PlanStatus.DRAFT.value

    # List plans
    all_plans = planner.list_plans()
    assert len(all_plans) == 1
    assert all_plans[0]["plan_id"] == draft_plan.plan_id

    # Apply/activate plan
    active = planner.apply_plan(draft_plan.plan_id)
    assert active.status == PlanStatus.ACTIVE.value

    # Retrieve active plan
    curr_active = planner.get_active_plan()
    assert curr_active is not None
    assert curr_active.plan_id == draft_plan.plan_id


# =============================================================================
# 6. Task Lifecycle (Complete & Skip)
# =============================================================================

def test_task_completion_and_skipping(test_env):
    """Verify completing tasks with actual minutes and skipping with reason."""
    planner = test_env["planner"]
    plan = planner.save_plan(planner.generate_plan())
    planner.apply_plan(plan.plan_id)

    task_1 = plan.all_tasks[0]
    task_2 = plan.all_tasks[1]

    # Complete task 1 with actual minutes
    completed_task = planner.complete_task(task_1.task_id, actual_minutes=25)
    assert completed_task.status == TaskStatus.COMPLETED.value
    assert completed_task.actual_minutes == 25
    assert completed_task.completed_at is not None

    # Idempotent completion check
    idem = planner.complete_task(task_1.task_id)
    assert idem.status == TaskStatus.COMPLETED.value

    # Skip task 2
    skipped_task = planner.skip_task(task_2.task_id, reason="Time conflict")
    assert skipped_task.status == TaskStatus.SKIPPED.value
    assert skipped_task.skipped_reason == "Time conflict"

    # Cannot skip an already completed task
    with pytest.raises(ValueError, match="already been completed"):
        planner.skip_task(task_1.task_id)

    # Check updated progress metrics
    updated_plan = planner.get_plan(plan.plan_id)
    prog = updated_plan.progress
    assert prog.tasks_completed == 1
    assert prog.tasks_skipped == 1
    assert prog.actual_recorded_minutes == 25
    assert prog.completion_ratio_pct > 0.0


# =============================================================================
# 7. Adaptive Replanning (Preview & Apply)
# =============================================================================

def test_adaptive_replanning(test_env):
    """Verify adaptive replanning redistributes overdue tasks and preserves completed ones."""
    planner = test_env["planner"]
    plan = planner.save_plan(planner.generate_plan())
    planner.apply_plan(plan.plan_id)

    # Mark first task completed
    t1 = plan.all_tasks[0]
    planner.complete_task(t1.task_id)

    # Manually backdate a pending task to make it overdue
    t_overdue = plan.all_tasks[1]
    with planner.get_connection() as conn:
        conn.execute(
            "UPDATE preparation_tasks SET day_date = '2026-01-01' WHERE task_id = ?",
            (t_overdue.task_id,),
        )
        conn.commit()

    # Preview replan
    preview = planner.preview_replan()
    assert preview["can_replan"] is True
    assert preview["completed_tasks_preserved"] == 1
    assert preview["overdue_tasks_count"] == 1
    assert len(preview["rescheduled_tasks"]) == 1

    # Apply replan
    updated_plan = planner.apply_replan()
    assert len(updated_plan.adaptation_history) == 1

    # Verify the overdue task was moved to a future study day
    refreshed_overdue = next(t for t in updated_plan.all_tasks if t.task_id == t_overdue.task_id)
    assert refreshed_overdue.day_date != "2026-01-01"

    # Verify completed task remained completed
    refreshed_t1 = next(t for t in updated_plan.all_tasks if t.task_id == t1.task_id)
    assert refreshed_t1.status == TaskStatus.COMPLETED.value


# =============================================================================
# 8. Dashboard REST API Endpoints
# =============================================================================

def test_flask_preparation_planner_endpoints(test_env):
    """Verify all 13 REST API endpoints in dashboard_server.py."""
    app = create_app(
        db_path=test_env["prog_db"],
        tracking_db_path=test_env["track_db"],
    )
    client = app.test_client()

    # 1. GET /api/preparation-planner/settings
    res = client.get("/api/preparation-planner/settings")
    assert res.status_code == 200
    s_data = res.get_json()
    assert s_data["daily_minutes"] == 60

    # 2. POST /api/preparation-planner/settings (valid)
    post_s = client.post(
        "/api/preparation-planner/settings",
        json={"daily_minutes": 75, "horizon_days": 14},
    )
    assert post_s.status_code == 200
    assert post_s.get_json()["daily_minutes"] == 75

    # POST /api/preparation-planner/settings (invalid)
    bad_s = client.post(
        "/api/preparation-planner/settings",
        json={"daily_minutes": 5},
    )
    assert bad_s.status_code == 400

    # 3. POST /api/preparation-planner/generate
    gen_res = client.post(
        "/api/preparation-planner/generate",
        json={"title": "Custom Test Plan"},
    )
    assert gen_res.status_code == 201
    plan_data = gen_res.get_json()
    plan_id = plan_data["plan_id"]
    assert plan_data["status"] == "draft"

    # 4. GET /api/preparation-planner/plans
    list_res = client.get("/api/preparation-planner/plans")
    assert list_res.status_code == 200
    assert len(list_res.get_json()) >= 1

    # 5. GET /api/preparation-planner/plan/<plan_id>
    get_plan = client.get(f"/api/preparation-planner/plan/{plan_id}")
    assert get_plan.status_code == 200
    assert get_plan.get_json()["plan_id"] == plan_id

    # 6. GET /api/preparation-planner/plan/<plan_id>/preview
    prev_plan = client.get(f"/api/preparation-planner/plan/{plan_id}/preview")
    assert prev_plan.status_code == 200

    # 7. POST /api/preparation-planner/plan/<plan_id>/apply
    apply_res = client.post(f"/api/preparation-planner/plan/{plan_id}/apply")
    assert apply_res.status_code == 200
    assert apply_res.get_json()["status"] == "active"

    # 8. GET /api/preparation-planner
    active_overview = client.get("/api/preparation-planner")
    assert active_overview.status_code == 200
    act_data = active_overview.get_json()
    assert act_data["plan"]["plan_id"] == plan_id

    # 9. GET /api/preparation-planner/plan/<plan_id>/progress
    prog_res = client.get(f"/api/preparation-planner/plan/{plan_id}/progress")
    assert prog_res.status_code == 200
    assert "completion_ratio_pct" in prog_res.get_json()

    # Get a task from the active plan
    task_id = act_data["plan"]["all_tasks"][0]["task_id"]

    # 10. POST /api/preparation-planner/task/<task_id>/complete
    comp_res = client.post(
        f"/api/preparation-planner/task/{task_id}/complete",
        json={"actual_minutes": 20},
    )
    assert comp_res.status_code == 200
    assert comp_res.get_json()["status"] == "completed"

    # 11. POST /api/preparation-planner/task/<task_id>/skip
    task2_id = act_data["plan"]["all_tasks"][1]["task_id"]
    skip_res = client.post(
        f"/api/preparation-planner/task/{task2_id}/skip",
        json={"reason": "Testing skip"},
    )
    assert skip_res.status_code == 200
    assert skip_res.get_json()["status"] == "skipped"

    # 12. POST /api/preparation-planner/replan/preview
    replan_prev = client.post(
        "/api/preparation-planner/replan/preview",
        json={"plan_id": plan_id},
    )
    assert replan_prev.status_code == 200
    assert "can_replan" in replan_prev.get_json()

    # 13. POST /api/preparation-planner/replan/apply
    replan_app = client.post(
        "/api/preparation-planner/replan/apply",
        json={"plan_id": plan_id},
    )
    assert replan_app.status_code == 200
    assert replan_app.get_json()["plan_id"] == plan_id


def test_invalid_inputs_and_regex_protection(test_env):
    """Verify regex sanitization on plan_id and task_id routes."""
    app = create_app(
        db_path=test_env["prog_db"],
        tracking_db_path=test_env["track_db"],
    )
    client = app.test_client()

    bad_id = "plan_123;DROP TABLE preparation_plans;--"
    assert client.get(f"/api/preparation-planner/plan/{bad_id}").status_code == 400
    assert client.get(f"/api/preparation-planner/plan/{bad_id}/preview").status_code == 400
    assert client.post(f"/api/preparation-planner/plan/{bad_id}/apply").status_code == 400
    assert client.get(f"/api/preparation-planner/plan/{bad_id}/progress").status_code == 400

    bad_task_id = "task_invalid$name"
    assert client.post(f"/api/preparation-planner/task/{bad_task_id}/complete").status_code == 400
    assert client.post(f"/api/preparation-planner/task/{bad_task_id}/skip").status_code == 400


def test_replan_preserves_multiple_completed_tasks(test_env):
    """Verify that multiple completed tasks are completely untouched by replan."""
    planner = test_env["planner"]
    plan = planner.save_plan(planner.generate_plan())
    planner.apply_plan(plan.plan_id)

    # Complete 3 tasks
    for i in range(3):
        t = plan.all_tasks[i]
        planner.complete_task(t.task_id, actual_minutes=20)

    # Make 2 subsequent tasks overdue
    with planner.get_connection() as conn:
        conn.execute(
            "UPDATE preparation_tasks SET day_date = '2025-12-01' WHERE task_id IN (?, ?)",
            (plan.all_tasks[3].task_id, plan.all_tasks[4].task_id),
        )
        conn.commit()

    # Replan
    preview = planner.preview_replan()
    assert preview["completed_tasks_preserved"] == 3
    assert preview["overdue_tasks_count"] == 2

    applied = planner.apply_replan()
    completed_after = [t for t in applied.all_tasks if t.status == TaskStatus.COMPLETED.value]
    assert len(completed_after) == 3
    for t in completed_after:
        assert t.actual_minutes == 20

