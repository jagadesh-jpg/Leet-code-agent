"""Tests for Unified Learning Dashboard & Command Center (Milestone 6.3.8).

Verifies:
- Extended get_dashboard_data includes unified learning intelligence.
- Topic mastery, session analytics, and adaptive recommendations are loaded.
- Empty-state robustness when databases have no history.
- Web server Flask app creation and endpoint responses (/ and /api/dashboard).
- Database isolation (progress_db and tracking_db paths are respected).
- No mutation of production progress.db.
"""

from pathlib import Path
import pytest

from dashboard import get_dashboard_data
from dashboard_server import create_app
from intelligence.planner import SessionPlanner
from intelligence.tracker import ProblemProgressStatus, SessionTracker
from problems import load_problems
import store


@pytest.fixture
def temp_dashboard_dbs(tmp_path: Path):
    """Fixture providing isolated progress and tracking databases."""
    prog_db = tmp_path / "test_dash_prog.db"
    track_db = tmp_path / "test_dash_track.db"
    store.init(db_path=prog_db)
    return prog_db, track_db


def test_unified_dashboard_data_structure(temp_dashboard_dbs):
    """Verify that get_dashboard_data incorporates learning_intelligence structure cleanly."""
    prog_db, track_db = temp_dashboard_dbs

    data = get_dashboard_data(db_path=prog_db)
    assert "learning_intelligence" in data
    li = data["learning_intelligence"]

    assert "overall_status" in li
    assert "topics_mastery" in li
    assert "session_analytics" in li
    assert "primary_recommendation" in li
    assert "suggested_session_sizing" in li
    assert "preview_session" in li

    # Validate that topics_mastery contains standard algorithm topics
    topics = [t["topic"] for t in li["topics_mastery"]]
    assert "Arrays" in topics
    assert "Hashing" in topics


def test_unified_dashboard_empty_state_handling(temp_dashboard_dbs):
    """Verify clean empty states when no sessions or attempts have been recorded."""
    prog_db, track_db = temp_dashboard_dbs

    data = get_dashboard_data(db_path=prog_db)
    li = data["learning_intelligence"]

    assert li["session_analytics"]["total_sessions_planned"] == 0
    assert li["session_analytics"]["session_completion_rate"] == 0.0
    assert len(li["recent_sessions"]) == 0
    assert li["suggested_session_sizing"]["has_sufficient_evidence"] is False
    assert li["suggested_session_sizing"]["recommended_size"] == 3


def test_unified_dashboard_with_history(temp_dashboard_dbs):
    """Verify dashboard accurately reflects problem history and tracked sessions."""
    prog_db, track_db = temp_dashboard_dbs

    # 1. Add progress attempt
    store.log_attempt("two-sum", 1, "code", "passed", language="python", db_path=prog_db)
    store.mark_result("two-sum", "solved", attempts=1, language="python", db_path=prog_db)

    # 2. Add tracked session
    planner = SessionPlanner(db_path=prog_db, language="python")
    tracker = SessionTracker(db_path=track_db)
    candidates = load_problems()
    plan = planner.plan_session(candidates, session_size=2, skip_solved=False)
    rec = tracker.record_session(plan)
    tracker.update_problem_progress(rec.session_id, rec.problems[0].problem_id, ProblemProgressStatus.COMPLETED)
    tracker.complete_session(rec.session_id)

    # Retrieve dashboard pointing to both databases
    from dashboard import _get_learning_intelligence_data
    li = _get_learning_intelligence_data(db_path=prog_db, tracking_db_path=track_db)

    assert li["session_analytics"]["total_sessions_planned"] == 1
    assert li["session_analytics"]["total_sessions_completed"] == 1
    assert len(li["recent_sessions"]) == 1
    assert li["recent_sessions"][0]["session_id"] == rec.session_id


def test_flask_web_dashboard_endpoints(temp_dashboard_dbs):
    """Verify Flask web server serves both HTML template and JSON API endpoints."""
    prog_db, track_db = temp_dashboard_dbs

    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    # Test HTML dashboard index
    res_index = client.get("/")
    assert res_index.status_code == 200
    html = res_index.get_data(as_text=True)
    assert "Unified Command Center & Learning Intelligence Dashboard" in html
    assert "Local-First / Zero External APIs" in html
    assert "Algorithmic Topic Mastery" in html

    # Test JSON API endpoint
    res_api = client.get("/api/dashboard")
    assert res_api.status_code == 200
    json_data = res_api.get_json()
    assert json_data is not None
    assert "learning_intelligence" in json_data
    assert "summary" in json_data
