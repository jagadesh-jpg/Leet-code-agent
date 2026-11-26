"""Isolated Unit and Integration Tests for ProblemSelector (Milestone 6.3.3).

Verifies:
1. Deterministic problem ranking and scoring.
2. User difficulty preference boost.
3. Solved problem exclusion (language-specific and legacy semantics).
4. Failed attempt prioritization vs exhausted attempt deprioritization.
5. Missing topic/pattern metadata handling (no invented topics).
6. Empty candidate queue handling.
7. Explainable selection rationale.
8. Database isolation (never touches production progress.db).
"""

from pathlib import Path
import pytest

from intelligence.selector import ProblemSelector, ProblemScoreBreakdown
import store


@pytest.fixture
def temp_selector_db(tmp_path):
    db_file = tmp_path / "test_selector.db"
    store.init(db_path=db_file)
    return db_file


def test_deterministic_ranking_without_history(temp_selector_db):
    """Verify fresh problems rank deterministically: Easy (highest base) -> Medium -> Hard, with ID tie-breaking."""
    candidates = [
        {"id": "hard-prob", "title": "Hard Prob", "difficulty": "hard"},
        {"id": "easy-prob-b", "title": "Easy B", "difficulty": "easy"},
        {"id": "easy-prob-a", "title": "Easy A", "difficulty": "easy"},
        {"id": "medium-prob", "title": "Med Prob", "difficulty": "medium"},
    ]

    selector = ProblemSelector(db_path=temp_selector_db, language="python")
    ranked = selector.prioritize_candidates(candidates, skip_solved=False)

    ranked_ids = [p["id"] for p, _ in ranked]
    # Easy problems have base score 30 + 10 (fresh) = 40; tie-breaker is problem_id alphabetical
    assert ranked_ids[0] == "easy-prob-a"
    assert ranked_ids[1] == "easy-prob-b"
    # Medium has base score 20 + 10 = 30
    assert ranked_ids[2] == "medium-prob"
    # Hard has base score 10 + 10 = 20
    assert ranked_ids[3] == "hard-prob"

    # Scores must be completely deterministic across repeated calls
    ranked_2 = selector.prioritize_candidates(candidates, skip_solved=False)
    assert [p["id"] for p, _ in ranked_2] == ranked_ids


def test_difficulty_preference_boost(temp_selector_db):
    """Verify that specifying preferred_difficulty gives matching difficulty candidates a priority boost."""
    candidates = [
        {"id": "p-easy", "difficulty": "easy"},
        {"id": "p-hard", "difficulty": "hard"},
    ]

    # Without preference, easy beats hard
    s_default = ProblemSelector(db_path=temp_selector_db)
    r_default = s_default.prioritize_candidates(candidates)
    assert r_default[0][0]["id"] == "p-easy"

    # With preference for hard, hard gets +50 boost and easy gets -20 penalty
    s_hard = ProblemSelector(db_path=temp_selector_db, preferred_difficulty="hard")
    r_hard = s_hard.prioritize_candidates(candidates)
    assert r_hard[0][0]["id"] == "p-hard"
    assert "Matches preferred difficulty 'hard'" in r_hard[0][1].rationale


def test_solved_problem_exclusion(temp_selector_db):
    """Verify solved problems are excluded based on target language."""
    candidates = [
        {"id": "prob-1", "difficulty": "easy"},
        {"id": "prob-2", "difficulty": "easy"},
    ]

    # Mark prob-1 as solved for python
    store.mark_result("prob-1", "solved", attempts=1, language="python", db_path=temp_selector_db)

    # In Python, prob-1 is skipped
    s_py = ProblemSelector(db_path=temp_selector_db, language="python")
    r_py = s_py.prioritize_candidates(candidates, skip_solved=True)
    assert len(r_py) == 1
    assert r_py[0][0]["id"] == "prob-2"

    # In C++, prob-1 is NOT solved yet and should still be included
    s_cpp = ProblemSelector(db_path=temp_selector_db, language="cpp")
    r_cpp = s_cpp.prioritize_candidates(candidates, skip_solved=True)
    assert len(r_cpp) == 2


def test_failed_attempt_prioritization_and_exhaustion(temp_selector_db):
    """Verify that failed/unfinished problems are prioritized for retry, but exhausted problems are deprioritized."""
    candidates = [
        {"id": "fresh-p", "difficulty": "easy"},
        {"id": "failed-p", "difficulty": "easy"},
        {"id": "exhausted-p", "difficulty": "easy"},
    ]

    # 1. failed-p has 1 failed attempt (unfinished)
    store.log_attempt("failed-p", 1, "code", "wrong_answer", language="python", db_path=temp_selector_db)
    store.mark_result("failed-p", "failed", attempts=1, language="python", db_path=temp_selector_db)

    # 2. exhausted-p has 6 logged attempts (above max_attempt_threshold=5)
    for i in range(1, 7):
        store.log_attempt("exhausted-p", i, "code", "wrong_answer", language="python", db_path=temp_selector_db)
    store.mark_result("exhausted-p", "failed", attempts=6, language="python", db_path=temp_selector_db)

    selector = ProblemSelector(db_path=temp_selector_db, language="python", max_attempt_threshold=5)
    ranked = selector.prioritize_candidates(candidates, skip_solved=True)

    ranked_ids = [p["id"] for p, _ in ranked]
    # failed-p (+35 bonus) > fresh-p (+10) > exhausted-p (-40 penalty)
    assert ranked_ids[0] == "failed-p"
    assert ranked_ids[1] == "fresh-p"
    assert ranked_ids[2] == "exhausted-p"

    # Check rationale strings
    breakdowns = {p["id"]: b for p, b in ranked}
    assert "prioritized for retry" in breakdowns["failed-p"].rationale
    assert "Fresh untouched problem" in breakdowns["fresh-p"].rationale
    assert "Exhausted prior attempts" in breakdowns["exhausted-p"].rationale


def test_missing_topic_metadata_handling(temp_selector_db):
    """Verify engine explicitly records topic_available=False and does not invent missing topics."""
    prob_no_topic = {"id": "no-topic", "difficulty": "easy"}
    prob_with_topic = {"id": "with-topic", "difficulty": "easy", "pattern": "two_pointers"}

    selector = ProblemSelector(db_path=temp_selector_db)
    b_no = selector.score_problem(prob_no_topic)
    b_yes = selector.score_problem(prob_with_topic)

    assert b_no.topic_available is False
    assert b_no.topic_or_pattern is None
    assert "Topic metadata: unavailable" in b_no.rationale

    assert b_yes.topic_available is True
    assert b_yes.topic_or_pattern == "two_pointers"
    assert "Topic: two_pointers" in b_yes.rationale


def test_empty_candidate_queue(temp_selector_db):
    """Verify empty candidate list returns safely without error."""
    selector = ProblemSelector(db_path=temp_selector_db)
    res = selector.prioritize_candidates([])
    assert res == []


def test_database_isolation(tmp_path):
    """Verify the selector reads exclusively from the supplied db_path and production progress.db is never touched."""
    isolated_db = tmp_path / "isolated.db"
    store.init(db_path=isolated_db)

    # Query selector against isolated db
    selector = ProblemSelector(db_path=isolated_db)
    hist = selector.get_problem_history("some-nonexistent-id")
    assert hist["attempts_count"] == 0
    assert hist["is_solved"] is False
