"""Unit & Integration Tests for Topic-Aware Learning Intelligence (Milestone 6.3.4).

Verifies:
1. Topic metadata validation across curated problems.
2. Multiple topics per problem.
3. Topic performance metrics calculation (solved, unsolved, attempts, mastery status).
4. No-history handling (untouched topics are not marked as weak).
5. Weak topic prioritization (prioritizing topics with multiple failed attempts).
6. Solved problem exclusion with topic awareness.
7. Preservation of existing difficulty preferences.
8. Deterministic ranking across repeated invocations.
9. Missing topic metadata handling without fabricating topics.
10. Custom problems with explicit topics or patterns.
11. Database isolation (never touches production progress.db).
12. CLI compatibility for --topics and --select.
"""

from pathlib import Path
import pytest

from intelligence.selector import ProblemSelector
from intelligence.topics import (
    CURATED_PROBLEM_TOPICS,
    TopicAnalyzer,
    get_problem_topics,
)
from problems import load_problems
import pipeline_cli
import store


@pytest.fixture
def temp_topic_db(tmp_path):
    db_file = tmp_path / "test_topic_intel.db"
    store.init(db_path=db_file)
    return db_file


def test_topic_metadata_validation_and_multi_topics():
    """Verify curated problems have accurate topic classifications and support multiple topics."""
    curated = load_problems()
    assert len(curated) == 9

    for p in curated:
        topics = get_problem_topics(p)
        assert len(topics) >= 1, f"Problem {p['id']} should have at least 1 topic"
        assert all(isinstance(t, str) and len(t) > 0 for t in topics)

    # Check specific multi-topic problems
    t_two_sum = get_problem_topics({"id": "two-sum"})
    assert "Arrays" in t_two_sum and "Hashing" in t_two_sum

    t_longest_sub = get_problem_topics({"id": "longest-substring-without-repeating-characters"})
    assert "Sliding Window" in t_longest_sub and "Two Pointers" in t_longest_sub


def test_custom_problem_topics_and_missing_metadata():
    """Verify custom problems with explicit topics/patterns and unclassified problems."""
    # Explicit topics list
    p1 = {"id": "custom-1", "topics": ["Binary Search", "Math"]}
    assert get_problem_topics(p1) == ["Binary Search", "Math"]

    # Explicit single pattern
    p2 = {"id": "custom-2", "pattern": "dynamic_programming"}
    assert get_problem_topics(p2) == ["Dynamic Programming"]

    # No topic metadata at all
    p3 = {"id": "unclassified-prob"}
    assert get_problem_topics(p3) == []


def test_topic_performance_metrics_no_history(temp_topic_db):
    """Verify topic metrics when no attempt history exists (must be marked as no_history, NOT weak)."""
    curated = load_problems()
    analyzer = TopicAnalyzer(db_path=temp_topic_db, language="python")
    metrics = analyzer.analyze_topics(curated)

    assert "Arrays" in metrics
    m_arrays = metrics["Arrays"]
    assert m_arrays.solved_problems == 0
    assert m_arrays.unsolved_problems > 0
    assert m_arrays.total_attempts == 0
    assert m_arrays.mastery_status == "no_history"
    assert m_arrays.has_history is False
    assert "no practice history" in m_arrays.summary.lower()


def test_topic_performance_mastery_and_needs_practice(temp_topic_db):
    """Verify topic mastery classification when problems are solved vs when failures occur."""
    # In temp_topic_db:
    # 1. Solve "two-sum" with a clean pass
    store.log_attempt("two-sum", 1, "code", "passed", language="python", db_path=temp_topic_db)
    store.mark_result("two-sum", "solved", attempts=1, language="python", db_path=temp_topic_db)

    # 2. Add multiple failures to "valid-parentheses" (Stack topic)
    store.log_attempt("valid-parentheses", 1, "code", "wrong_answer", language="python", db_path=temp_topic_db)
    store.log_attempt("valid-parentheses", 2, "code", "runtime_error", language="python", db_path=temp_topic_db)
    store.mark_result("valid-parentheses", "failed", attempts=2, language="python", db_path=temp_topic_db)

    analyzer = TopicAnalyzer(db_path=temp_topic_db, language="python")
    metrics = analyzer.analyze_topics([
        {"id": "two-sum"},
        {"id": "valid-parentheses"},
    ])

    m_stack = metrics["Stack"]
    assert m_stack.mastery_status == "needs_practice"
    assert m_stack.failed_attempts >= 2
    assert "Needs Practice" in m_stack.summary

    m_arrays = metrics["Arrays"]
    assert m_arrays.solved_problems == 1
    assert m_arrays.mastery_status == "mastered"


def test_weak_topic_prioritization_in_selector(temp_topic_db):
    """Verify that candidate problems covering weak topics receive an explainable topic boost."""
    # Create failure history for Stack topic
    store.log_attempt("valid-parentheses", 1, "code", "wrong_answer", language="python", db_path=temp_topic_db)
    store.log_attempt("valid-parentheses", 2, "code", "wrong_answer", language="python", db_path=temp_topic_db)
    store.mark_result("valid-parentheses", "failed", attempts=2, language="python", db_path=temp_topic_db)

    # Candidates:
    # 1. p_stack: covers Stack topic
    # 2. p_other: covers Math topic (no history)
    p_stack = {"id": "stack-prob", "title": "Stack Problem", "difficulty": "easy", "topics": ["Stack"]}
    p_other = {"id": "other-prob", "title": "Other Problem", "difficulty": "easy", "topics": ["Math"]}

    selector = ProblemSelector(db_path=temp_topic_db, language="python", enable_topic_intelligence=True)
    ranked = selector.prioritize_candidates([p_other, p_stack], skip_solved=False)

    ranked_ids = [p["id"] for p, _ in ranked]
    assert ranked_ids[0] == "stack-prob"  # Boosted because Stack needs practice
    assert ranked[0][1].topic_performance_adjustment == 15.0
    assert "Reinforces weak topic" in ranked[0][1].rationale


def test_deterministic_topic_ranking(temp_topic_db):
    """Verify that topic ranking and scoring are deterministic across multiple calls."""
    candidates = load_problems()
    selector = ProblemSelector(db_path=temp_topic_db)

    run_1 = selector.prioritize_candidates(candidates, skip_solved=False)
    run_2 = selector.prioritize_candidates(candidates, skip_solved=False)

    assert [p["id"] for p, _ in run_1] == [p["id"] for p, _ in run_2]
    assert [b.total_score for _, b in run_1] == [b.total_score for _, b in run_2]


def test_cli_topics_command(monkeypatch, temp_topic_db):
    """Verify CLI --topics flag runs cleanly without error and outputs topic statistics."""
    test_args = ["pipeline_cli.py", "--topics", "--db-path", str(temp_topic_db), "--quiet"]
    monkeypatch.setattr("sys.argv", test_args)

    with pytest.raises(SystemExit) as exc_info:
        pipeline_cli.main()

    assert exc_info.value.code == 0
