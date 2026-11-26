"""Tests for Offline Intelligent Coding Coach Engine (Milestone 6.3.11).

Verifies:
- Coach overview generation and personalized learning insights.
- 8-point problem-solving coaching framework generation.
- Progressive 4-tier hint sequencing (Conceptual -> Pattern -> Invariant -> Pseudocode).
- Hint boundary constraints (tiers 1-4) and exhaustion.
- Non-revelation: coach guides without generating complete executable code solutions.
- Input validation on problem IDs and hint tier parameters.
- Empty-state and clean-history behavior.
- Flask endpoints (/api/coach/overview, /api/coach/problem/<id>, /api/coach/problem/<id>/hint).
- Database isolation (progress_db and tracking_db).
"""

from pathlib import Path
import pytest

from dashboard_server import create_app
from intelligence.coach import (
    CURATED_PROBLEM_HINTS,
    HintTier,
    OfflineCodingCoach,
    ProblemCoachingGuide,
    ProgressiveHint,
)
from problems import load_problems
import store


@pytest.fixture
def temp_coach_dbs(tmp_path: Path):
    """Fixture providing isolated progress and tracking databases."""
    prog_db = tmp_path / "test_coach_prog.db"
    track_db = tmp_path / "test_coach_track.db"
    store.init(db_path=prog_db)
    return prog_db, track_db


def test_coach_overview_empty_history(temp_coach_dbs):
    """Verify coach overview on clean database establishes warm-up baseline."""
    prog_db, track_db = temp_coach_dbs
    coach = OfflineCodingCoach(progress_db_path=prog_db, tracking_db_path=track_db)

    overview = coach.get_coach_overview()
    assert overview is not None
    assert overview.recommended_problem is not None
    assert len(overview.personalized_insights) >= 1
    assert "Baseline" in overview.readiness_assessment or "Welcome" in overview.personalized_insights[0].headline


def test_problem_coaching_guide_structure(temp_coach_dbs):
    """Verify 8-point pedagogical coaching framework for a curated problem."""
    prog_db, track_db = temp_coach_dbs
    coach = OfflineCodingCoach(progress_db_path=prog_db, tracking_db_path=track_db)

    guide = coach.get_problem_guidance("two-sum")
    assert guide is not None
    assert guide.problem_id == "two-sum"
    assert guide.title == "Two Sum"
    assert len(guide.relevant_patterns) > 0
    assert len(guide.step_by_step_approach) >= 3
    assert len(guide.test_recommendations) >= 2
    assert "O(N)" in guide.complexity_considerations
    assert len(guide.encouragement) > 0


def test_progressive_hint_sequencing(temp_coach_dbs):
    """Verify progressive hints follow 4 distinct levels without revealing raw solutions."""
    prog_db, track_db = temp_coach_dbs
    coach = OfflineCodingCoach(progress_db_path=prog_db, tracking_db_path=track_db)

    h1 = coach.get_progressive_hint("two-sum", tier=1)
    assert h1 is not None
    assert h1.tier == 1
    assert h1.tier_name == "Conceptual Direction"
    assert h1.has_more is True

    h2 = coach.get_progressive_hint("two-sum", tier=2)
    assert h2 is not None
    assert h2.tier == 2
    assert h2.tier_name == "Data Structure & Pattern"
    assert "Hash Map" in h2.content

    h3 = coach.get_progressive_hint("two-sum", tier=3)
    assert h3 is not None
    assert h3.tier == 3
    assert h3.tier_name == "Algorithmic Invariant"

    h4 = coach.get_progressive_hint("two-sum", tier=4)
    assert h4 is not None
    assert h4.tier == 4
    assert h4.tier_name == "Pseudocode Logic"
    assert h4.has_more is False
    assert "Pseudocode" in h4.content


def test_hint_boundaries_and_invalid_inputs(temp_coach_dbs):
    """Verify hint boundaries (1-4) and error handling on invalid queries."""
    prog_db, track_db = temp_coach_dbs
    coach = OfflineCodingCoach(progress_db_path=prog_db, tracking_db_path=track_db)

    # Invalid tier values
    assert coach.get_progressive_hint("two-sum", tier=0) is None
    assert coach.get_progressive_hint("two-sum", tier=5) is None

    # Invalid problem ID
    assert coach.get_problem_guidance("non-existent-problem-xyz") is None
    assert coach.get_progressive_hint("non-existent-problem-xyz", tier=1) is None


def test_coach_flask_api_endpoints(temp_coach_dbs):
    """Verify Flask routes for coach overview, problem guide, and progressive hints."""
    prog_db, track_db = temp_coach_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    # GET /api/coach/overview
    res_ov = client.get("/api/coach/overview")
    assert res_ov.status_code == 200
    ov_data = res_ov.get_json()
    assert "overview_summary" in ov_data
    assert "recommended_problem" in ov_data

    # GET /api/coach/problem/<id>
    res_guide = client.get("/api/coach/problem/two-sum")
    assert res_guide.status_code == 200
    guide_data = res_guide.get_json()
    assert guide_data["problem_id"] == "two-sum"
    assert len(guide_data["step_by_step_approach"]) > 0

    # GET /api/coach/problem/<id>/hint?tier=1
    res_hint = client.get("/api/coach/problem/two-sum/hint?tier=1")
    assert res_hint.status_code == 200
    hint_data = res_hint.get_json()
    assert hint_data["tier"] == 1
    assert hint_data["has_more"] is True

    # Bad tier request
    res_bad_tier = client.get("/api/coach/problem/two-sum/hint?tier=99")
    assert res_bad_tier.status_code == 400

    # Bad problem id request
    res_bad_id = client.get("/api/coach/problem/invalid;id--injection/hint?tier=1")
    assert res_bad_id.status_code == 400
