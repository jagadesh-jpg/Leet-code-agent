import os
import pytest
from pathlib import Path

from mcp_server import list_problems, get_problem, submit_solution, get_progress
from problems import load_problems
import store


@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    """Ensure all MCP tests use an isolated SQLite database in tmp_path."""
    test_db = tmp_path / "test_progress.db"
    monkeypatch.setenv("LEETCODE_AGENT_DB_PATH", str(test_db))
    store.init(db_path=test_db)
    yield test_db


def test_list_problems_returns_all_nine():
    problems = list_problems()
    assert len(problems) == 9
    ids = [p["id"] for p in problems]
    assert "two-sum" in ids
    assert "trapping-rain-water" in ids
    for p in problems:
        assert "id" in p
        assert "title" in p
        assert "difficulty" in p
        assert "solved" in p
        # Ensure hidden test cases and reference solution are not leaked
        assert "reference_solution" not in p
        assert "tests" not in p


def test_list_problems_difficulty_filtering():
    easy_probs = list_problems(difficulty="easy")
    assert len(easy_probs) == 3
    assert all(p["difficulty"] == "easy" for p in easy_probs)

    med_probs = list_problems(difficulty="medium")
    assert len(med_probs) == 3
    assert all(p["difficulty"] == "medium" for p in med_probs)

    hard_probs = list_problems(difficulty="hard")
    assert len(hard_probs) == 3
    assert all(p["difficulty"] == "hard" for p in hard_probs)


def test_get_problem_returns_details_and_two_examples():
    prob = get_problem("two-sum")
    assert prob["id"] == "two-sum"
    assert prob["title"] == "Two Sum"
    assert prob["difficulty"] == "easy"
    assert "signature" in prob
    assert "description" in prob
    assert len(prob["examples"]) == 2
    # Ensure reference_solution is never exposed
    assert "reference_solution" not in prob
    assert "tests" not in prob


def test_get_problem_unknown_id():
    res = get_problem("non-existent-id")
    assert res == {"error": "unknown problem"}


def test_submit_solution_unknown_id():
    res = submit_solution("non-existent-id", "def foo(): pass")
    assert res == {"error": "unknown problem"}


def test_submit_solution_rejects_code_over_20k_chars():
    long_code = "a" * 20001
    res = submit_solution("two-sum", long_code)
    assert "error" in res
    assert "20,000 characters" in res["error"]


def test_submit_solution_correct_passes_and_marks_solved():
    all_probs = load_problems()
    two_sum_prob = next(p for p in all_probs if p["id"] == "two-sum")
    ref_code = two_sum_prob["reference_solution"]

    # Before submitting, problem should not be solved
    probs_before = list_problems()
    two_sum_meta = next(p for p in probs_before if p["id"] == "two-sum")
    assert two_sum_meta["solved"] is False

    # Submit reference solution
    res = submit_solution("two-sum", ref_code)
    assert res["status"] == "passed"
    assert res["passed_count"] == res["total"]
    assert res["total"] >= 6

    # Verify solved status in list_problems
    probs_after = list_problems()
    two_sum_meta_after = next(p for p in probs_after if p["id"] == "two-sum")
    assert two_sum_meta_after["solved"] is True


def test_submit_solution_wrong_answer():
    bad_code = "def two_sum(nums, target):\n    return [0, 0]\n"
    res = submit_solution("two-sum", bad_code)
    assert res["status"] == "wrong_answer"
    assert res["failure"] is not None


def test_submit_solution_live_regression():
    """Regression test replicating live MCP submit_solution call for Two Sum."""
    submitted_code = (
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, num in enumerate(nums):\n"
        "        complement = target - num\n"
        "        if complement in seen:\n"
        "            return [seen[complement], i]\n"
        "        seen[num] = i\n"
        "    return []\n"
    )
    res = submit_solution("two-sum", submitted_code)
    assert res["status"] == "passed"
    assert res["passed_count"] == res["total"]
    assert res["error"] is None


def test_get_progress_reflects_solved_problem():
    all_probs = load_problems()
    two_sum_prob = next(p for p in all_probs if p["id"] == "two-sum")

    progress_initial = get_progress()
    assert progress_initial["solved"] == 0

    submit_solution("two-sum", two_sum_prob["reference_solution"])

    progress_updated = get_progress()
    assert progress_updated["solved"] == 1
    assert progress_updated["by_difficulty"]["easy"]["solved"] == 1

