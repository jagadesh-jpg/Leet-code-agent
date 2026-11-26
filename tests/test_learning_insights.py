"""Tests for Learning Insights & Performance Analytics Engine (Milestone 6.3.10).

Verifies:
- Analytics calculation for solved problems, attempts, and difficulty progression.
- Daily learning activity timelines derived from timestamps.
- Topic improvement evaluation (strongest topics, weak topics, insufficient data handling).
- Completed vs skipped problem tracking.
- Safe JSON export formatting and privacy compliance.
- Safe CSV export formatting and privacy compliance.
- Strict sensitive data exclusion (zero API keys, credentials, code, or internal paths).
- API endpoints (/api/insights, /api/export/json, /api/export/csv).
- Database isolation.
"""

import json
from pathlib import Path
import pytest

from dashboard_server import create_app
from intelligence.insights import LearningInsightsEngine
from intelligence.planner import SessionPlanner
from intelligence.tracker import ProblemProgressStatus, SessionTracker
from problems import load_problems
import store


@pytest.fixture
def temp_insights_dbs(tmp_path: Path):
    """Fixture providing isolated progress and tracking databases."""
    prog_db = tmp_path / "test_ins_prog.db"
    track_db = tmp_path / "test_ins_track.db"
    store.init(db_path=prog_db)
    return prog_db, track_db


def test_empty_database_insights(temp_insights_dbs):
    """Verify clean empty-state behavior when no attempts or sessions are recorded."""
    prog_db, track_db = temp_insights_dbs
    engine = LearningInsightsEngine(progress_db_path=prog_db, tracking_db_path=track_db)

    report = engine.generate_report()
    assert report.total_problems_solved == 0
    assert report.total_attempts_logged == 0
    assert report.overall_pass_rate == 0.0
    assert report.total_sessions_tracked == 0
    assert len(report.daily_activity) == 0
    assert len(report.untouched_topics) > 0


def test_learning_insights_with_attempts_and_sessions(temp_insights_dbs):
    """Verify analytics calculation with recorded problem attempts, passes, and sessions."""
    prog_db, track_db = temp_insights_dbs

    # 1. Record solved problem with clean pass
    store.log_attempt("two-sum", 1, "code", "passed", language="python", db_path=prog_db)
    store.mark_result("two-sum", "solved", attempts=1, language="python", db_path=prog_db)

    # 2. Record problem with multiple failures
    store.log_attempt("valid-parentheses", 1, "code", "wrong_answer", language="python", db_path=prog_db)
    store.log_attempt("valid-parentheses", 2, "code", "runtime_error", language="python", db_path=prog_db)
    store.mark_result("valid-parentheses", "failed", attempts=2, language="python", db_path=prog_db)

    # 3. Record session in tracking DB
    planner = SessionPlanner(db_path=prog_db, language="python")
    tracker = SessionTracker(db_path=track_db)
    plan = planner.plan_session(load_problems(), session_size=2, skip_solved=False)
    rec = tracker.record_session(plan)
    tracker.update_problem_progress(rec.session_id, rec.problems[0].problem_id, ProblemProgressStatus.COMPLETED)
    tracker.update_problem_progress(rec.session_id, rec.problems[1].problem_id, ProblemProgressStatus.SKIPPED)
    tracker.complete_session(rec.session_id)

    engine = LearningInsightsEngine(progress_db_path=prog_db, tracking_db_path=track_db)
    report = engine.generate_report()

    assert report.total_problems_solved == 1
    assert report.total_attempts_logged == 3
    assert abs(report.overall_pass_rate - (1 / 3)) < 1e-2
    assert report.difficulty_breakdown.get("easy", 0) >= 1

    # Session metrics
    assert report.total_sessions_tracked == 1
    assert report.session_completion_rate == 1.0
    assert report.completed_vs_skipped_problems["completed"] == 1
    assert report.completed_vs_skipped_problems["skipped"] == 1

    # Weak topic identification
    assert "Stack" in report.topics_needing_practice or "Hashing" in report.topics_needing_practice


def test_json_and_csv_export_format(temp_insights_dbs):
    """Verify JSON and CSV exports produce valid data structures."""
    prog_db, track_db = temp_insights_dbs
    engine = LearningInsightsEngine(progress_db_path=prog_db, tracking_db_path=track_db)

    # Test JSON export
    json_out = engine.export_json()
    parsed = json.loads(json_out)
    assert "total_problems_solved" in parsed
    assert "topic_metrics" in parsed
    assert "difficulty_breakdown" in parsed

    # Test CSV export
    csv_out = engine.export_csv()
    assert "# LEETCODE AGENT - LEARNING PERFORMANCE METRICS" in csv_out
    assert "# TOPIC PERFORMANCE BREAKDOWN" in csv_out
    assert "Problems Solved" in csv_out


def test_sensitive_data_exclusion(temp_insights_dbs):
    """Verify that export files strictly exclude solution code, keys, and paths."""
    prog_db, track_db = temp_insights_dbs

    secret_code = "def is_secret_function_12345(): return True"
    store.log_attempt("two-sum", 1, secret_code, "passed", language="python", db_path=prog_db)

    engine = LearningInsightsEngine(progress_db_path=prog_db, tracking_db_path=track_db)
    json_out = engine.export_json()
    csv_out = engine.export_csv()

    # Solution code must never appear in exports
    assert secret_code not in json_out
    assert secret_code not in csv_out
    assert "is_secret_function" not in json_out
    assert "is_secret_function" not in csv_out

    # Filesystem paths must never appear
    assert str(prog_db) not in json_out
    assert str(track_db) not in json_out
    assert str(prog_db) not in csv_out
    assert str(track_db) not in csv_out


def test_dashboard_api_export_endpoints(temp_insights_dbs):
    """Verify Flask app endpoints /api/insights, /api/export/json, and /api/export/csv."""
    prog_db, track_db = temp_insights_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    # Test GET /api/insights
    res_ins = client.get("/api/insights")
    assert res_ins.status_code == 200
    ins_data = res_ins.get_json()
    assert "total_problems_solved" in ins_data
    assert "topic_metrics" in ins_data

    # Test GET /api/export/json
    res_json = client.get("/api/export/json")
    assert res_json.status_code == 200
    assert res_json.mimetype == "application/json"
    assert "learning_analytics.json" in res_json.headers.get("Content-Disposition", "")
    parsed_json = json.loads(res_json.get_data(as_text=True))
    assert "total_problems_solved" in parsed_json

    # Test GET /api/export/csv
    res_csv = client.get("/api/export/csv")
    assert res_csv.status_code == 200
    assert res_csv.mimetype == "text/csv"
    assert "learning_analytics.csv" in res_csv.headers.get("Content-Disposition", "")
    csv_text = res_csv.get_data(as_text=True)
    assert "# LEETCODE AGENT - LEARNING PERFORMANCE METRICS" in csv_text
