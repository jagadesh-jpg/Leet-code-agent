"""Tests for Interactive Learning Command Center (Milestone 6.3.9).

Verifies:
- Safe localhost binding enforcement (127.0.0.1, rejecting 0.0.0.0).
- Dynamic session plan preview endpoint (/api/preview-plan).
- Saving preview plan as tracked session (/api/save-session).
- Listing tracked sessions (/api/sessions).
- Detailed session inspection (/api/session/<id>).
- Session lifecycle status updates (/api/session/<id>/status).
- Per-problem progress tracking: completed and skipped (/api/session/<id>/problem/<pid>).
- Input validation (invalid IDs, out-of-range sizes, invalid difficulties, invalid actions).
- Error handling on invalid state transitions.
- Database isolation (progress.db vs session_tracking.db).
"""

from pathlib import Path
import pytest

from dashboard_server import create_app, run_dashboard_server
from intelligence.tracker import ProblemProgressStatus, SessionStatus, SessionTracker
from problems import load_problems
import store


@pytest.fixture
def temp_interactive_dbs(tmp_path: Path):
    """Fixture providing isolated progress and tracking databases."""
    prog_db = tmp_path / "test_inter_prog.db"
    track_db = tmp_path / "test_inter_track.db"
    store.init(db_path=prog_db)
    return prog_db, track_db


def test_preview_plan_endpoint(temp_interactive_dbs):
    """Verify GET /api/preview-plan returns structured preview with specified constraints."""
    prog_db, track_db = temp_interactive_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    # Default preview
    res = client.get("/api/preview-plan?session_size=2&skip_solved=false")
    assert res.status_code == 200
    data = res.get_json()
    assert data["target_size"] == 2
    assert len(data["problems"]) == 2

    # Validation: invalid session_size
    res_bad = client.get("/api/preview-plan?session_size=99")
    assert res_bad.status_code == 400
    assert "session_size must be between 1 and 10" in res_bad.get_json()["error"]

    # Validation: invalid difficulty
    res_diff = client.get("/api/preview-plan?difficulty=impossible")
    assert res_diff.status_code == 400
    assert "Invalid difficulty" in res_diff.get_json()["error"]


def test_save_session_endpoint(temp_interactive_dbs):
    """Verify POST /api/save-session creates and persists a session into tracking database."""
    prog_db, track_db = temp_interactive_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    res = client.post(
        "/api/save-session",
        json={"session_size": 3, "difficulty": "easy", "skip_solved": False},
    )
    assert res.status_code == 201
    data = res.get_json()
    assert "session_id" in data
    assert data["status"] == "planned"
    assert data["total_problems"] == 3

    # Check persistence in tracking db
    tracker = SessionTracker(db_path=track_db)
    saved = tracker.get_session(data["session_id"])
    assert saved is not None
    assert saved.session_id == data["session_id"]


def test_list_and_inspect_sessions_endpoint(temp_interactive_dbs):
    """Verify GET /api/sessions and GET /api/session/<id> endpoints."""
    prog_db, track_db = temp_interactive_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    # Save session first
    res_save = client.post("/api/save-session", json={"session_size": 2, "skip_solved": False})
    sid = res_save.get_json()["session_id"]

    # List sessions
    res_list = client.get("/api/sessions")
    assert res_list.status_code == 200
    sessions = res_list.get_json()
    assert len(sessions) >= 1
    assert any(s["session_id"] == sid for s in sessions)

    # Inspect valid session
    res_inspect = client.get(f"/api/session/{sid}")
    assert res_inspect.status_code == 200
    detail = res_inspect.get_json()
    assert detail["session_id"] == sid
    assert len(detail["problems"]) == 2

    # Validation: non-existent session
    res_404 = client.get("/api/session/non_existent_123")
    assert res_404.status_code == 404

    # Validation: invalid ID characters
    res_bad_id = client.get("/api/session/invalid;drop--table")
    assert res_bad_id.status_code == 400


def test_session_lifecycle_status_endpoint(temp_interactive_dbs):
    """Verify POST /api/session/<id>/status for start, completed, cancel actions."""
    prog_db, track_db = temp_interactive_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    # Create session
    res_save = client.post("/api/save-session", json={"session_size": 2, "skip_solved": False})
    sid = res_save.get_json()["session_id"]

    # Start session
    res_start = client.post(f"/api/session/{sid}/status", json={"action": "start"})
    assert res_start.status_code == 200
    assert res_start.get_json()["status"] == "in_progress"

    # Complete session
    res_comp = client.post(f"/api/session/{sid}/status", json={"action": "completed"})
    assert res_comp.status_code == 200
    assert res_comp.get_json()["status"] == "completed"

    # Invalid transition: cannot start completed session
    res_invalid = client.post(f"/api/session/{sid}/status", json={"action": "start"})
    assert res_invalid.status_code == 400
    assert "Cannot start completed session" in res_invalid.get_json()["error"]

    # Invalid action
    res_bad_act = client.post(f"/api/session/{sid}/status", json={"action": "explode"})
    assert res_bad_act.status_code == 400


def test_problem_progress_update_endpoint(temp_interactive_dbs):
    """Verify POST /api/session/<id>/problem/<pid> marking problems completed or skipped."""
    prog_db, track_db = temp_interactive_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    # Create session
    res_save = client.post("/api/save-session", json={"session_size": 2, "skip_solved": False})
    sid = res_save.get_json()["session_id"]

    # Get problem IDs
    res_detail = client.get(f"/api/session/{sid}")
    p0 = res_detail.get_json()["problems"][0]["problem_id"]
    p1 = res_detail.get_json()["problems"][1]["problem_id"]

    # Mark first problem completed
    res_p0 = client.post(f"/api/session/{sid}/problem/{p0}", json={"status": "completed"})
    assert res_p0.status_code == 200
    data_p0 = res_p0.get_json()
    assert data_p0["completed_count"] == 1
    assert data_p0["session_status"] == "in_progress"

    # Mark second problem skipped (finishes all problems, auto-completing session)
    res_p1 = client.post(f"/api/session/{sid}/problem/{p1}", json={"status": "skipped"})
    assert res_p1.status_code == 200
    data_p1 = res_p1.get_json()
    assert data_p1["completed_count"] == 1
    assert data_p1["skipped_count"] == 1
    assert data_p1["pending_count"] == 0
    assert data_p1["session_status"] == "completed"


def test_localhost_binding_security(monkeypatch, temp_interactive_dbs):
    """Verify run_dashboard_server binds strictly to 127.0.0.1 and suppresses 0.0.0.0."""
    prog_db, track_db = temp_interactive_dbs
    captured_hosts = []

    def mock_run(self, host=None, port=None, debug=None):
        captured_hosts.append(host)

    monkeypatch.setattr("flask.Flask.run", mock_run)

    # When 0.0.0.0 is passed, it should automatically be converted to 127.0.0.1
    run_dashboard_server(host="0.0.0.0", port=5050, db_path=prog_db, tracking_db_path=track_db)
    assert captured_hosts[-1] == "127.0.0.1"

    # When default is used
    run_dashboard_server(host="127.0.0.1", port=5050, db_path=prog_db, tracking_db_path=track_db)
    assert captured_hosts[-1] == "127.0.0.1"
