"""Unit and integration tests for Milestone 6.3.20: Interview Performance Trends & Benchmark Analytics.

Validates:
- Multi-category score trend tracking (Overall, Correctness, Completion, Structure, Complexity, Time Management).
- Historical averages, latest, highest, lowest, and period deltas (improving/declining/stable).
- Rule-based performance pattern and recurring weakness detection.
- Track benchmarks (Beginner, Intermediate, Advanced, Mixed) with statistical reliability flags (N >= 3).
- Programming language benchmarks (Python, C, C++, Java) with neutral sample-size caveats.
- Problem and topic analytics mapped to algorithmic topics and integrated with DSA Roadmap and Spaced Revisions.
- Configurable interview practice goals with non-destructive storage in interview_analytics_goals and live progress.
- Multi-window date filtering (all_time, last_7_days, last_30_days, last_90_days, custom).
- 10 REST API endpoints in dashboard_server.py.
- Zero mock data in production; isolated SQLite fixtures only.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.interview_analytics import (
    GoalStatus,
    GoalType,
    InterviewAnalyticsGoal,
    InterviewAnalyticsManager,
    InterviewAnalyticsOverview,
    LanguageBenchmarkMetric,
    PerformanceInsight,
    ScoreCategoryTrend,
    TopicInterviewMetric,
    TrackBenchmarkMetric,
)
from intelligence.mock_interview import InterviewManager


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

    # Initialize InterviewManager to ensure mock_interviews schema is ready
    im = InterviewManager(tracking_db_path=track_db, progress_db_path=prog_db)

    # Initialize InterviewAnalyticsManager
    am = InterviewAnalyticsManager(tracking_db_path=track_db, progress_db_path=prog_db)

    return {
        "prog_db": prog_db,
        "track_db": track_db,
        "interview_mgr": im,
        "analytics_mgr": am,
        "tmp_path": tmp_path,
    }


def _insert_mock_interview(
    track_db: Path,
    interview_id: str,
    track: str = "intermediate",
    language: str = "python",
    status: str = "completed",
    total_score: float = 75.0,
    correctness_score: float = 30.0,
    completion_score: float = 16.0,
    structure_score: float = 12.0,
    complexity_score: float = 10.0,
    time_management_score: float = 7.0,
    created_at: str = "2026-11-20 10:00:00",
):
    """Helper to insert an evaluated mock interview record directly into the test database."""
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
                interview_id, f"Mock Interview {interview_id}", track, 45, language,
                2, 2, status, created_at,
                created_at, created_at, created_at, total_score, correctness_score,
                completion_score, structure_score, complexity_score, time_management_score,
                "Test feedback summary", "{}", "[]"
            ),
        )


def _insert_mock_problem(
    track_db: Path,
    interview_id: str,
    problem_id: str,
    status: str = "passed",
):
    """Helper to insert problem assignment for an interview."""
    with sqlite3.connect(track_db) as conn:
        conn.execute(
            """
            INSERT INTO mock_interview_problems (
                interview_id, problem_id, problem_order, difficulty, title,
                status, time_spent_seconds, best_passed_count, total_tests
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (interview_id, problem_id, 0, "easy", problem_id, status, 300, 2, 2),
        )


# =============================================================================
# 1. Empty Database Tests
# =============================================================================

def test_empty_database_analytics(test_env):
    """Verify overview handles zero interviews gracefully without division-by-zero."""
    am = test_env["analytics_mgr"]
    overview = am.get_analytics_overview()

    assert overview.total_completed_interviews == 0
    assert overview.average_score == 0.0
    assert overview.latest_score is None
    assert overview.highest_score is None
    assert overview.lowest_score is None
    assert overview.completion_rate_pct == 0.0

    # Check trends dictionary has all 6 categories with default zero values
    expected_categories = {"overall", "correctness", "completion", "structure", "complexity", "time_management"}
    assert set(overview.score_trends.keys()) == expected_categories
    for trend in overview.score_trends.values():
        assert trend.sample_count == 0
        assert trend.average_score == 0.0
        assert trend.trend_direction == "insufficient_data"

    # Track benchmarks exist for all 4 tracks with 0 count
    assert len(overview.track_benchmarks) == 4
    for tb in overview.track_benchmarks:
        assert tb.assessment_count == 0
        assert tb.is_statistically_reliable is False

    # Language benchmarks exist for all 4 languages with 0 count
    assert len(overview.language_benchmarks) == 4
    for lb in overview.language_benchmarks:
        assert lb.interview_count == 0

    assert overview.insights == []
    assert overview.topic_analytics == []
    assert overview.active_goals == []


# =============================================================================
# 2. Single Interview Analytics
# =============================================================================

def test_single_interview_analytics(test_env):
    """Verify calculations with exactly one completed assessment."""
    track_db = test_env["track_db"]
    _insert_mock_interview(
        track_db=track_db,
        interview_id="int_001",
        track="beginner",
        language="python",
        total_score=80.0,
        correctness_score=32.0,
        completion_score=16.0,
        structure_score=14.0,
        complexity_score=11.0,
        time_management_score=7.0,
    )

    am = test_env["analytics_mgr"]
    overview = am.get_analytics_overview()

    assert overview.total_completed_interviews == 1
    assert overview.average_score == 80.0
    assert overview.latest_score == 80.0
    assert overview.highest_score == 80.0
    assert overview.lowest_score == 80.0

    overall_trend = overview.score_trends["overall"]
    assert overall_trend.sample_count == 1
    assert overall_trend.average_score == 80.0
    assert overall_trend.delta_score is None  # Needs >= 2 for delta
    assert overall_trend.trend_direction == "insufficient_data"

    # Beginner track has 1 item, statistically unreliable (< 3)
    beg_track = next(t for t in overview.track_benchmarks if t.track == "beginner")
    assert beg_track.assessment_count == 1
    assert beg_track.average_score == 80.0
    assert beg_track.is_statistically_reliable is False


# =============================================================================
# 3. Score Trends and Deltas Across Multiple Interviews
# =============================================================================

def test_multi_interview_score_trends(test_env):
    """Verify trends, older-half vs newer-half deltas, and direction markers."""
    track_db = test_env["track_db"]

    # Insert 4 interviews with progressive scores
    # Older half: 60.0, 65.0 (avg = 62.5)
    # Newer half: 80.0, 90.0 (avg = 85.0) -> delta = +22.5 (improving)
    scores = [
        ("int_1", 60.0, 20.0, 10.0, 10.0, 8.0, 5.0, "2026-11-01 10:00:00"),
        ("int_2", 65.0, 25.0, 12.0, 11.0, 9.0, 6.0, "2026-11-05 10:00:00"),
        ("int_3", 80.0, 32.0, 16.0, 13.0, 11.0, 8.0, "2026-11-10 10:00:00"),
        ("int_4", 90.0, 38.0, 18.0, 14.0, 12.0, 8.0, "2026-11-15 10:00:00"),
    ]

    for i_id, tot, corr, comp, struct, cplx, tm, dt in scores:
        _insert_mock_interview(
            track_db=track_db,
            interview_id=i_id,
            track="intermediate",
            language="python",
            total_score=tot,
            correctness_score=corr,
            completion_score=comp,
            structure_score=struct,
            complexity_score=cplx,
            time_management_score=tm,
            created_at=dt,
        )

    am = test_env["analytics_mgr"]
    overview = am.get_analytics_overview()

    assert overview.total_completed_interviews == 4
    assert overview.average_score == 73.8
    assert overview.latest_score == 90.0
    assert overview.highest_score == 90.0
    assert overview.lowest_score == 60.0

    trend = overview.score_trends["overall"]
    assert trend.sample_count == 4
    assert trend.delta_score == 22.5
    assert trend.trend_direction == "improving"

    # Structure trend improved from older avg (10.5) to newer avg (13.5) delta = +3.0
    struct_trend = overview.score_trends["structure"]
    assert struct_trend.trend_direction == "improving"
    assert struct_trend.delta_score == 3.0


# =============================================================================
# 4. Weakness Pattern Detection
# =============================================================================

def test_weakness_pattern_detection(test_env):
    """Verify objective, rule-based weakness detection and consistency insights."""
    track_db = test_env["track_db"]

    # Low correctness (< 24.0), low completion (< 12.0), low complexity (< 9.0), and expired status
    _insert_mock_interview(
        track_db=track_db,
        interview_id="int_fail_1",
        status="expired",
        total_score=40.0,
        correctness_score=15.0,  # < 24.0
        completion_score=8.0,   # < 12.0
        structure_score=7.0,
        complexity_score=5.0,   # < 9.0
        time_management_score=5.0, # < 6.0
        created_at="2026-11-10 10:00:00",
    )
    _insert_mock_interview(
        track_db=track_db,
        interview_id="int_fail_2",
        status="expired",
        total_score=45.0,
        correctness_score=18.0,  # < 24.0
        completion_score=9.0,   # < 12.0
        structure_score=8.0,
        complexity_score=6.0,   # < 9.0
        time_management_score=4.0, # < 6.0
        created_at="2026-11-12 10:00:00",
    )

    am = test_env["analytics_mgr"]
    overview = am.get_analytics_overview()

    insight_ids = [i.insight_id for i in overview.insights]
    assert "weakness_correctness" in insight_ids
    assert "weakness_completion" in insight_ids
    assert "weakness_complexity" in insight_ids
    assert "weakness_time_management" in insight_ids

    # Check that rule applied and evidence are present
    corr_insight = next(i for i in overview.insights if i.insight_id == "weakness_correctness")
    assert corr_insight.pattern_type == "weakness"
    assert corr_insight.sample_count == 2
    assert "24.0" in corr_insight.rule_applied
    assert corr_insight.suggested_action != ""


def test_consistency_variance_pattern(test_env):
    """Verify high score variance detection across >= 3 sessions (spread >= 25.0)."""
    track_db = test_env["track_db"]

    _insert_mock_interview(track_db=track_db, interview_id="i1", total_score=95.0, created_at="2026-11-01 10:00:00")
    _insert_mock_interview(track_db=track_db, interview_id="i2", total_score=60.0, created_at="2026-11-02 10:00:00")
    _insert_mock_interview(track_db=track_db, interview_id="i3", total_score=80.0, created_at="2026-11-03 10:00:00")

    am = test_env["analytics_mgr"]
    overview = am.get_analytics_overview()

    insight_ids = [i.insight_id for i in overview.insights]
    assert "consistency_spread" in insight_ids
    spread_insight = next(i for i in overview.insights if i.insight_id == "consistency_spread")
    assert spread_insight.pattern_type == "consistency"
    assert "35.0" in spread_insight.evidence  # 95 - 60 = 35.0


# =============================================================================
# 5. Track and Language Benchmarks
# =============================================================================

def test_track_and_language_benchmarks(test_env):
    """Verify track sample reliability thresholds and language benchmarks."""
    track_db = test_env["track_db"]

    # 3 beginner assessments (statistically reliable)
    for idx in range(1, 4):
        _insert_mock_interview(
            track_db=track_db,
            interview_id=f"beg_{idx}",
            track="beginner",
            language="python",
            total_score=85.0,
            created_at=f"2026-11-0{idx} 10:00:00",
        )

    # 1 intermediate assessment (unreliable, count < 3)
    _insert_mock_interview(
        track_db=track_db,
        interview_id="inter_1",
        track="intermediate",
        language="cpp",
        total_score=70.0,
        created_at="2026-11-04 10:00:00",
    )

    am = test_env["analytics_mgr"]
    overview = am.get_analytics_overview()

    beg_metric = next(t for t in overview.track_benchmarks if t.track == "beginner")
    assert beg_metric.assessment_count == 3
    assert beg_metric.is_statistically_reliable is True
    assert "Statistically supported" in beg_metric.reliability_note

    inter_metric = next(t for t in overview.track_benchmarks if t.track == "intermediate")
    assert inter_metric.assessment_count == 1
    assert inter_metric.is_statistically_reliable is False
    assert "Insufficient sample size" in inter_metric.reliability_note

    # Languages: Python has 3, Cpp has 1, C has 0, Java has 0
    py_metric = next(l for l in overview.language_benchmarks if l.language == "python")
    assert py_metric.interview_count == 3
    assert py_metric.average_score == 85.0

    cpp_metric = next(l for l in overview.language_benchmarks if l.language == "cpp")
    assert cpp_metric.interview_count == 1
    assert cpp_metric.average_score == 70.0


# =============================================================================
# 6. Problem and Topic Analytics
# =============================================================================

def test_topic_analytics_and_mapping(test_env):
    """Verify mapping of interview problems to algorithmic topics with success rates."""
    track_db = test_env["track_db"]

    _insert_mock_interview(track_db=track_db, interview_id="int_top_1", created_at="2026-11-10 10:00:00")
    _insert_mock_problem(track_db=track_db, interview_id="int_top_1", problem_id="two-sum", status="passed")
    _insert_mock_problem(track_db=track_db, interview_id="int_top_1", problem_id="reverse-string", status="passed")

    _insert_mock_interview(track_db=track_db, interview_id="int_top_2", created_at="2026-11-11 10:00:00")
    _insert_mock_problem(track_db=track_db, interview_id="int_top_2", problem_id="two-sum", status="passed")
    _insert_mock_problem(track_db=track_db, interview_id="int_top_2", problem_id="valid-palindrome", status="failed")

    am = test_env["analytics_mgr"]
    overview = am.get_analytics_overview()

    assert len(overview.topic_analytics) > 0
    # Check that recommendations are generated without error
    assert isinstance(overview.recommended_roadmap_topics, list)
    assert isinstance(overview.recommended_revisions, list)


# =============================================================================
# 7. Interview Goals Management & Progress
# =============================================================================

def test_interview_goals_crud_and_live_progress(test_env):
    """Verify goal creation, validation, live progress calculation, auto-completion, and updates."""
    track_db = test_env["track_db"]
    am = test_env["analytics_mgr"]

    # 1. Validation: invalid type should raise ValueError
    with pytest.raises(ValueError, match="Invalid goal_type"):
        am.create_goal(goal_type="invalid_type", target_value=80.0)

    # 2. Validation: zero or negative target should raise ValueError
    with pytest.raises(ValueError, match="greater than zero"):
        am.create_goal(goal_type=GoalType.TARGET_AVERAGE_SCORE.value, target_value=0.0)

    # 3. Insert mock interviews with avg score = 70.0
    _insert_mock_interview(track_db=track_db, interview_id="g_int_1", total_score=70.0, created_at="2026-11-10 10:00:00")

    # 4. Create active goal: target 80.0
    goal = am.create_goal(goal_type=GoalType.TARGET_AVERAGE_SCORE.value, target_value=80.0)
    assert goal.goal_id.startswith("igoal_")
    assert goal.status == GoalStatus.ACTIVE.value
    assert goal.current_value == 70.0
    # 70.0 / 80.0 * 100 = 87.5%
    assert goal.progress_pct == 87.5
    assert goal.is_achieved is False

    # 5. Insert another high scoring interview to reach target >= 80.0
    _insert_mock_interview(track_db=track_db, interview_id="g_int_2", total_score=90.0, created_at="2026-11-12 10:00:00")
    # Now average is (70 + 90) / 2 = 80.0

    eval_goal = am.get_goal(goal.goal_id)
    assert eval_goal.current_value == 80.0
    assert eval_goal.progress_pct == 100.0
    assert eval_goal.is_achieved is True
    assert eval_goal.status == GoalStatus.COMPLETED.value

    # 6. Update goal parameters
    updated = am.update_goal(goal.goal_id, target_value=85.0, status=GoalStatus.ACTIVE.value)
    assert updated.target_value == 85.0
    assert updated.status == GoalStatus.ACTIVE.value
    # 80.0 / 85.0 * 100 = 94.1%
    assert updated.progress_pct == 94.1
    assert updated.is_achieved is False

    # 7. List goals
    active_goals = am.list_goals(status_filter="active")
    assert len(active_goals) == 1
    assert active_goals[0].goal_id == goal.goal_id


# =============================================================================
# 8. Multi-Window Date Filtering
# =============================================================================

def test_date_window_filtering(test_env):
    """Verify accurate filtering across all_time, last_7_days, last_30_days, last_90_days, custom."""
    track_db = test_env["track_db"]
    now = datetime.now(timezone.utc)

    # Record 1: 2 days ago
    d1 = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    _insert_mock_interview(track_db=track_db, interview_id="d_int_1", total_score=70.0, created_at=d1)

    # Record 2: 15 days ago
    d2 = (now - timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S")
    _insert_mock_interview(track_db=track_db, interview_id="d_int_2", total_score=75.0, created_at=d2)

    # Record 3: 60 days ago
    d3 = (now - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
    _insert_mock_interview(track_db=track_db, interview_id="d_int_3", total_score=80.0, created_at=d3)

    # Record 4: 120 days ago
    d4 = (now - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S")
    _insert_mock_interview(track_db=track_db, interview_id="d_int_4", total_score=85.0, created_at=d4)

    am = test_env["analytics_mgr"]

    # all_time -> 4
    assert len(am.get_completed_interviews(date_preset="all_time")) == 4

    # last_7_days -> 1 (d1)
    assert len(am.get_completed_interviews(date_preset="last_7_days")) == 1

    # last_30_days -> 2 (d1, d2)
    assert len(am.get_completed_interviews(date_preset="last_30_days")) == 2

    # last_90_days -> 3 (d1, d2, d3)
    assert len(am.get_completed_interviews(date_preset="last_90_days")) == 3

    # custom -> range covering d2 and d3
    custom_start = (now - timedelta(days=70)).strftime("%Y-%m-%d")
    custom_end = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    custom_items = am.get_completed_interviews(
        date_preset="custom",
        start_date=custom_start,
        end_date=custom_end,
    )
    assert len(custom_items) == 2


# =============================================================================
# 9. Dashboard REST API Endpoints
# =============================================================================

def test_flask_interview_analytics_endpoints(test_env):
    """Verify all 10 REST API endpoints in dashboard_server.py."""
    app = create_app(
        db_path=test_env["prog_db"],
        tracking_db_path=test_env["track_db"],
    )
    client = app.test_client()

    track_db = test_env["track_db"]
    _insert_mock_interview(track_db=track_db, interview_id="api_int_1", track="beginner", total_score=82.0)
    _insert_mock_interview(track_db=track_db, interview_id="api_int_2", track="intermediate", total_score=78.0)

    # 1. GET /api/interview-analytics
    res = client.get("/api/interview-analytics?timeframe=all_time")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_completed_interviews"] == 2
    assert "score_trends" in data
    assert "track_benchmarks" in data
    assert "language_benchmarks" in data

    # 2. GET /api/interview-analytics/trends
    res = client.get("/api/interview-analytics/trends")
    assert res.status_code == 200
    trends = res.get_json()
    assert "overall" in trends
    assert trends["overall"]["sample_count"] == 2

    # 3. GET /api/interview-analytics/tracks
    res = client.get("/api/interview-analytics/tracks")
    assert res.status_code == 200
    tracks = res.get_json()
    assert len(tracks) == 4

    # 4. GET /api/interview-analytics/languages
    res = client.get("/api/interview-analytics/languages")
    assert res.status_code == 200
    langs = res.get_json()
    assert len(langs) == 4

    # 5. GET /api/interview-analytics/insights
    res = client.get("/api/interview-analytics/insights")
    assert res.status_code == 200
    assert isinstance(res.get_json(), list)

    # 6. GET /api/interview-analytics/topics
    res = client.get("/api/interview-analytics/topics")
    assert res.status_code == 200
    topics_data = res.get_json()
    assert "topics" in topics_data
    assert "recommended_roadmap_topics" in topics_data
    assert "recommended_revisions" in topics_data

    # 7. POST /api/interview-analytics/goals (valid)
    post_res = client.post(
        "/api/interview-analytics/goals",
        json={"goal_type": "target_average_score", "target_value": 85.0},
    )
    assert post_res.status_code == 201
    goal_data = post_res.get_json()
    assert "goal_id" in goal_data
    goal_id = goal_data["goal_id"]

    # POST /api/interview-analytics/goals (invalid)
    bad_post = client.post(
        "/api/interview-analytics/goals",
        json={"goal_type": "invalid_goal_type", "target_value": 85.0},
    )
    assert bad_post.status_code == 400

    # 8. GET /api/interview-analytics/goals
    goals_res = client.get("/api/interview-analytics/goals")
    assert goals_res.status_code == 200
    goals_list = goals_res.get_json()
    assert len(goals_list) >= 1

    # 9. PUT /api/interview-analytics/goals/<goal_id>
    put_res = client.put(
        f"/api/interview-analytics/goals/{goal_id}",
        json={"target_value": 90.0, "status": "paused"},
    )
    assert put_res.status_code == 200
    updated_goal = put_res.get_json()
    assert updated_goal["target_value"] == 90.0
    assert updated_goal["status"] == "paused"

    # PUT 404 for unknown goal
    put_404 = client.put("/api/interview-analytics/goals/igoal_nonexistent", json={"target_value": 80.0})
    assert put_404.status_code == 404

    # 10. GET /api/interview-analytics/history
    hist_res = client.get("/api/interview-analytics/history?limit=10")
    assert hist_res.status_code == 200
    hist = hist_res.get_json()
    assert len(hist) == 2
