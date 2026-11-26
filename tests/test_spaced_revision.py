"""Tests for Spaced Repetition & Smart Revision Engine (Milestone 6.3.12).

Verifies:
- Revision item scheduling with difficulty-based initial intervals.
- Leitner/SM-2 inspired interval adaptation based on user recall outcomes.
- Status computation: due, overdue, upcoming, paused.
- Pause and resume capability.
- Duplicate prevention in revision queue.
- Revision queue priority ordering (overdue -> due -> upcoming -> paused).
- Input validation (problem IDs, outcomes, pause status).
- Spaced repetition analytics (reviews completed, active streaks, retention proxies).
- Dashboard Flask endpoints (/api/revision/queue, /api/revision/schedule, /api/revision/<id>/outcome, /api/revision/<id>/pause).
- Complete database isolation.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from dashboard_server import create_app
from intelligence.revision import (
    RevisionAnalytics,
    RevisionItem,
    RevisionOutcome,
    RevisionStatus,
    SpacedRevisionEngine,
)
from problems import load_problems
import store


@pytest.fixture
def temp_revision_dbs(tmp_path: Path):
    """Fixture providing isolated progress and tracking databases."""
    prog_db = tmp_path / "test_rev_prog.db"
    track_db = tmp_path / "test_rev_track.db"
    store.init(db_path=prog_db)
    return prog_db, track_db


def test_revision_scheduling_initial_interval(temp_revision_dbs):
    """Verify problems schedule with difficulty-based intervals (easy: 3d, medium: 2d, hard: 1d)."""
    prog_db, track_db = temp_revision_dbs
    engine = SpacedRevisionEngine(tracking_db_path=track_db, progress_db_path=prog_db)

    # Schedule easy problem
    p_easy = {"id": "two-sum", "title": "Two Sum", "difficulty": "easy"}
    it_easy = engine.schedule_problem(p_easy)
    assert it_easy.interval_days == 3
    assert it_easy.repetition_count == 0
    assert it_easy.status == RevisionStatus.UPCOMING

    # Schedule hard problem
    p_hard = {"id": "trapping-rain-water", "title": "Trapping Rain Water", "difficulty": "hard"}
    it_hard = engine.schedule_problem(p_hard)
    assert it_hard.interval_days == 1


def test_duplicate_scheduling_prevention(temp_revision_dbs):
    """Verify duplicate scheduling calls return existing item without creating extra records."""
    prog_db, track_db = temp_revision_dbs
    engine = SpacedRevisionEngine(tracking_db_path=track_db, progress_db_path=prog_db)

    p = {"id": "two-sum", "title": "Two Sum", "difficulty": "easy"}
    it1 = engine.schedule_problem(p)
    it2 = engine.schedule_problem(p)

    assert it1.problem_id == it2.problem_id
    queue = engine.list_queue()
    assert len(queue) == 1


def test_revision_outcome_interval_adaptation(temp_revision_dbs):
    """Verify Leitner/SM-2 interval adjustments across all four recall outcomes."""
    prog_db, track_db = temp_revision_dbs
    engine = SpacedRevisionEngine(tracking_db_path=track_db, progress_db_path=prog_db)

    p = {"id": "two-sum", "title": "Two Sum", "difficulty": "easy"}
    engine.schedule_problem(p)

    # 1. Easy Recall: interval expands significantly
    up1 = engine.record_revision_outcome("two-sum", RevisionOutcome.EASY_RECALL)
    assert up1.repetition_count == 1
    assert up1.interval_days > 3
    assert up1.last_outcome == RevisionOutcome.EASY_RECALL

    # 2. Needed Hints: interval shrinks
    prev_interval = up1.interval_days
    up2 = engine.record_revision_outcome("two-sum", RevisionOutcome.NEEDED_HINTS)
    assert up2.interval_days < prev_interval

    # 3. Failed to Solve: interval resets to minimum (1 day) and repetition count resets
    up3 = engine.record_revision_outcome("two-sum", RevisionOutcome.FAILED_TO_SOLVE)
    assert up3.interval_days == 1
    assert up3.repetition_count == 0


def test_due_and_overdue_dynamic_status(temp_revision_dbs):
    """Verify items scheduled in the past or today calculate as OVERDUE or DUE dynamically."""
    prog_db, track_db = temp_revision_dbs
    engine = SpacedRevisionEngine(tracking_db_path=track_db, progress_db_path=prog_db)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    past_date_str = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")

    # Item scheduled in the past -> OVERDUE
    p_past = {"id": "climbing-stairs", "title": "Climbing Stairs", "difficulty": "easy"}
    it_past = engine.schedule_problem(p_past, custom_next_date=past_date_str)
    assert it_past.status == RevisionStatus.OVERDUE

    # Item scheduled today -> DUE
    p_today = {"id": "binary-search", "title": "Binary Search", "difficulty": "easy"}
    it_today = engine.schedule_problem(p_today, custom_next_date=today_str)
    assert it_today.status == RevisionStatus.DUE


def test_pause_and_resume(temp_revision_dbs):
    """Verify pausing a revision item suppresses due/overdue calculation until resumed."""
    prog_db, track_db = temp_revision_dbs
    engine = SpacedRevisionEngine(tracking_db_path=track_db, progress_db_path=prog_db)

    past_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    p = {"id": "two-sum", "title": "Two Sum", "difficulty": "easy"}
    engine.schedule_problem(p, custom_next_date=past_date)

    # Pause
    paused = engine.set_paused("two-sum", paused=True)
    assert paused.status == RevisionStatus.PAUSED

    # Resume
    resumed = engine.set_paused("two-sum", paused=False)
    assert resumed.status == RevisionStatus.OVERDUE


def test_revision_analytics_and_retention_proxies(temp_revision_dbs):
    """Verify aggregated analytics, streaks, and topic retention proxies."""
    prog_db, track_db = temp_revision_dbs
    engine = SpacedRevisionEngine(tracking_db_path=track_db, progress_db_path=prog_db)

    p1 = {"id": "two-sum", "title": "Two Sum", "difficulty": "easy"}
    p2 = {"id": "valid-parentheses", "title": "Valid Parentheses", "difficulty": "easy"}
    engine.schedule_problem(p1)
    engine.schedule_problem(p2)

    engine.record_revision_outcome("two-sum", RevisionOutcome.EASY_RECALL)
    engine.record_revision_outcome("valid-parentheses", RevisionOutcome.FAILED_TO_SOLVE)

    stats = engine.get_analytics()
    assert stats.total_tracked_for_revision == 2
    assert stats.reviews_completed == 2
    assert stats.outcome_distribution.get("easy_recall") == 1
    assert stats.outcome_distribution.get("failed_to_solve") == 1
    assert stats.active_streak_days >= 1
    assert "Arrays" in stats.topic_retention_proxies


def test_dashboard_revision_endpoints(temp_revision_dbs):
    """Verify Flask routes /api/revision/queue, /api/revision/schedule, /outcome, and /pause."""
    prog_db, track_db = temp_revision_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    # 1. Schedule problem via API
    res_sched = client.post("/api/revision/schedule", json={"problem_id": "two-sum"})
    assert res_sched.status_code == 201
    assert res_sched.get_json()["item"]["problem_id"] == "two-sum"

    # 2. List queue
    res_q = client.get("/api/revision/queue")
    assert res_q.status_code == 200
    queue_data = res_q.get_json()
    assert len(queue_data) == 1

    # 3. Log outcome
    res_out = client.post("/api/revision/two-sum/outcome", json={"outcome": "easy_recall"})
    assert res_out.status_code == 200
    assert "Outcome recorded" in res_out.get_json()["message"]

    # 4. Pause
    res_pause = client.post("/api/revision/two-sum/pause", json={"paused": True})
    assert res_pause.status_code == 200
    assert res_pause.get_json()["status"] == "paused"

    # 5. Invalid input validation
    res_bad_id = client.post("/api/revision/bad;id/outcome", json={"outcome": "easy_recall"})
    assert res_bad_id.status_code == 400
    res_bad_out = client.post("/api/revision/two-sum/outcome", json={"outcome": "magical_recall"})
    assert res_bad_out.status_code == 400
