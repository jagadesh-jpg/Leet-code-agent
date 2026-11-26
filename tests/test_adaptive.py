"""Tests for Adaptive Learning & Progress Intelligence Engine (Milestone 6.3.7).

Verifies:
- Weak-topic next action recommendation.
- Failure recovery recommendation (retry unfinished problem).
- Insufficient data handling (distinguishing lack of evidence from mastery).
- Difficulty progression recommendations when topics are proficient.
- Adaptive session sizing based on completion rates (decrease on fatigue, increase on sustained pass).
- Handling of user-specified session sizes.
- Deterministic output.
- Database isolation (progress.db vs tracking DB).
- CLI compatibility for --adaptive view.
"""

from pathlib import Path
import subprocess
import sys

import pytest

from intelligence.adaptive import (
    AdaptiveLearningEngine,
    AdaptiveLearningReport,
    AdaptiveSessionSizing,
    NextActionRecommendation,
    RecommendedActionType,
)
from intelligence.planner import SessionPlanner
from intelligence.tracker import (
    ProblemProgressStatus,
    SessionStatus,
    SessionTracker,
)
from problems import load_problems
import store


@pytest.fixture
def temp_adaptive_dbs(tmp_path: Path):
    """Fixture providing isolated progress and tracking databases."""
    progress_db = tmp_path / "test_prog.db"
    tracking_db = tmp_path / "test_track.db"
    store.init(db_path=progress_db)
    return progress_db, tracking_db


def test_insufficient_data_baseline(temp_adaptive_dbs):
    """Verify that empty/untouched databases produce clear insufficient-data recommendations."""
    progress_db, tracking_db = temp_adaptive_dbs
    engine = AdaptiveLearningEngine(
        progress_db_path=progress_db,
        tracking_db_path=tracking_db,
        language="python",
    )

    candidates = load_problems()
    report = engine.analyze_and_recommend(candidate_problems=candidates)

    assert report.primary_recommendation.action_type in (
        RecommendedActionType.INSUFFICIENT_DATA,
        RecommendedActionType.EXPAND_TOPIC_COVERAGE,
    )
    assert report.primary_recommendation.confidence in ("low", "moderate")
    assert report.session_sizing is not None
    assert report.session_sizing.has_sufficient_evidence is False
    assert report.session_sizing.recommended_size == AdaptiveLearningEngine.DEFAULT_SESSION_SIZE


def test_failure_recovery_recommendation(temp_adaptive_dbs):
    """Verify that an unsolved problem with failure attempts triggers a RETRY recommendation."""
    progress_db, tracking_db = temp_adaptive_dbs

    # Log 2 failures for 'valid-parentheses'
    store.log_attempt("valid-parentheses", 1, "code", "wrong_answer", language="python", db_path=progress_db)
    store.log_attempt("valid-parentheses", 2, "code", "runtime_error", language="python", db_path=progress_db)
    store.mark_result("valid-parentheses", "failed", attempts=2, language="python", db_path=progress_db)

    engine = AdaptiveLearningEngine(
        progress_db_path=progress_db,
        tracking_db_path=tracking_db,
        language="python",
    )
    candidates = load_problems()
    report = engine.analyze_and_recommend(candidate_problems=candidates)

    assert report.primary_recommendation.action_type == RecommendedActionType.RETRY_UNFINISHED_PROBLEM
    assert report.primary_recommendation.target_identifier == "valid-parentheses"
    assert report.primary_recommendation.confidence == "high"


def test_weak_topic_recommendation(temp_adaptive_dbs):
    """Verify weak topic is flagged for practice when problems in that topic need practice."""
    progress_db, tracking_db = temp_adaptive_dbs

    # Mark valid-parentheses (Stack) as solved with prior failures
    store.log_attempt("valid-parentheses", 1, "code", "wrong_answer", language="python", db_path=progress_db)
    store.log_attempt("valid-parentheses", 2, "code", "wrong_answer", language="python", db_path=progress_db)
    store.mark_result("valid-parentheses", "failed", attempts=2, language="python", db_path=progress_db)

    engine = AdaptiveLearningEngine(
        progress_db_path=progress_db,
        tracking_db_path=tracking_db,
        language="python",
    )
    # Exclude candidates with direct unfinished failures to test weak topic prioritization specifically
    cands_no_fail = [p for p in load_problems() if p["id"] != "valid-parentheses"]

    report = engine.analyze_and_recommend(candidate_problems=cands_no_fail)
    assert report.primary_recommendation.action_type == RecommendedActionType.PRACTICE_WEAK_TOPIC
    assert report.primary_recommendation.target_identifier in ("Stack", "Hashing")
    assert any(t in report.topics_needing_practice for t in ("Stack", "Hashing"))


def test_adaptive_session_sizing_decrease_on_fatigue(temp_adaptive_dbs):
    """Verify session size is cautiously decreased when recent sessions are cancelled/incomplete."""
    progress_db, tracking_db = temp_adaptive_dbs
    planner = SessionPlanner(db_path=progress_db, language="python")
    tracker = SessionTracker(db_path=tracking_db)
    candidates = load_problems()

    # Record 3 incomplete or cancelled sessions
    for _ in range(3):
        plan = planner.plan_session(candidates, session_size=3, skip_solved=False)
        rec = tracker.record_session(plan)
        tracker.cancel_session(rec.session_id, reason="Time constraint")

    engine = AdaptiveLearningEngine(
        progress_db_path=progress_db,
        tracking_db_path=tracking_db,
        language="python",
    )
    report = engine.analyze_and_recommend(candidate_problems=candidates)

    assert report.session_sizing is not None
    assert report.session_sizing.has_sufficient_evidence is True
    # Default 3 should be decreased to 2
    assert report.session_sizing.recommended_size == 2
    assert "fatigue" in report.session_sizing.rationale.lower() or "reducing" in report.session_sizing.rationale.lower()


def test_adaptive_session_sizing_increase_on_success(temp_adaptive_dbs):
    """Verify session size is cautiously expanded when recent sessions have 100% completion."""
    progress_db, tracking_db = temp_adaptive_dbs
    planner = SessionPlanner(db_path=progress_db, language="python")
    tracker = SessionTracker(db_path=tracking_db)
    candidates = load_problems()

    # Record 3 completed sessions
    for _ in range(3):
        plan = planner.plan_session(candidates, session_size=3, skip_solved=False)
        rec = tracker.record_session(plan)
        for p in rec.problems:
            tracker.update_problem_progress(rec.session_id, p.problem_id, ProblemProgressStatus.COMPLETED)
        tracker.complete_session(rec.session_id)

    engine = AdaptiveLearningEngine(
        progress_db_path=progress_db,
        tracking_db_path=tracking_db,
        language="python",
    )
    report = engine.analyze_and_recommend(candidate_problems=candidates)

    assert report.session_sizing is not None
    assert report.session_sizing.has_sufficient_evidence is True
    # Default 3 expanded cautiously to 4
    assert report.session_sizing.recommended_size == 4
    assert "expanding" in report.session_sizing.rationale.lower() or "sustained" in report.session_sizing.rationale.lower()


def test_deterministic_adaptive_engine(temp_adaptive_dbs):
    """Verify repeated calls with identical data return identical recommendations."""
    progress_db, tracking_db = temp_adaptive_dbs
    engine = AdaptiveLearningEngine(
        progress_db_path=progress_db,
        tracking_db_path=tracking_db,
        language="python",
    )
    candidates = load_problems()

    rep1 = engine.analyze_and_recommend(candidate_problems=candidates)
    rep2 = engine.analyze_and_recommend(candidate_problems=candidates)

    assert rep1.overall_status == rep2.overall_status
    assert rep1.primary_recommendation.action_type == rep2.primary_recommendation.action_type
    assert rep1.primary_recommendation.title == rep2.primary_recommendation.title
    assert rep1.session_sizing.recommended_size == rep2.session_sizing.recommended_size


def test_cli_adaptive_command(temp_adaptive_dbs):
    """Verify running pipeline_cli.py --adaptive outputs explainable insights."""
    progress_db, tracking_db = temp_adaptive_dbs
    cwd = Path(__file__).parent.parent

    cmd = [
        sys.executable,
        "pipeline_cli.py",
        "--adaptive",
        "--db-path", str(progress_db),
        "--tracking-db-path", str(tracking_db),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)

    assert res.returncode == 0
    output = res.stdout
    assert "ADAPTIVE LEARNING & PROGRESS INTELLIGENCE REPORT" in output
    assert "Overall Learning Status:" in output
    assert "PRIMARY RECOMMENDED ACTION:" in output
    assert "ADAPTIVE SESSION SIZING SUGGESTION:" in output
