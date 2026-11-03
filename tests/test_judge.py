import pytest
from judge import run_solution, _normalize_nested
from problems import load_problems


def test_every_reference_solution_passes():
    problems = load_problems()
    for problem in problems:
        ref_code = problem["reference_solution"]
        res = run_solution(ref_code, problem, timeout=10)
        assert res["status"] == "passed", (
            f"Reference solution for '{problem['id']}' failed: "
            f"status={res['status']}, failure={res.get('failure')}, error={res.get('error')}"
        )
        assert res["passed_count"] == res["total"]


def test_correct_candidate_code_passes():
    problem = {
        "id": "dummy-sum",
        "title": "Dummy Sum",
        "difficulty": "easy",
        "description": "Add two numbers",
        "function_name": "add",
        "signature": "def add(a: int, b: int) -> int:",
        "compare": "exact",
        "tests": [
            {"input": [1, 2], "expected": 3},
            {"input": [0, 0], "expected": 0},
            {"input": [-1, 1], "expected": 0},
            {"input": [10, -5], "expected": 5},
            {"input": [100, 200], "expected": 300},
            {"input": [-5, -5], "expected": -10},
        ],
    }
    code = "def add(a, b):\n    return a + b\n"
    res = run_solution(code, problem)
    assert res["status"] == "passed"
    assert res["passed_count"] == 6
    assert res["total"] == 6


def test_incorrect_candidate_code_returns_wrong_answer():
    problem = {
        "id": "dummy-sum",
        "title": "Dummy Sum",
        "difficulty": "easy",
        "description": "Add two numbers",
        "function_name": "add",
        "signature": "def add(a: int, b: int) -> int:",
        "compare": "exact",
        "tests": [
            {"input": [1, 2], "expected": 3},
            {"input": [2, 2], "expected": 4},
            {"input": [3, 2], "expected": 5},
            {"input": [4, 2], "expected": 6},
            {"input": [5, 2], "expected": 7},
            {"input": [6, 2], "expected": 8},
        ],
    }
    code = "def add(a, b):\n    return 0\n"
    res = run_solution(code, problem)
    assert res["status"] == "wrong_answer"
    assert res["passed_count"] == 0
    assert res["failure"]["input"] == [1, 2]
    assert res["failure"]["expected"] == 3
    assert res["failure"]["actual"] == 0


def test_syntax_and_runtime_errors_handled():
    problem = {
        "id": "dummy-syntax",
        "title": "Dummy Syntax",
        "difficulty": "easy",
        "description": "Test",
        "function_name": "func",
        "signature": "def func():",
        "compare": "exact",
        "tests": [
            {"input": [], "expected": 1},
            {"input": [], "expected": 1},
            {"input": [], "expected": 1},
            {"input": [], "expected": 1},
            {"input": [], "expected": 1},
            {"input": [], "expected": 1},
        ],
    }
    # Syntax error
    code_syntax = "def func(:\n    return 1"
    res_syntax = run_solution(code_syntax, problem)
    assert res_syntax["status"] == "runtime_error"
    assert res_syntax["error"] is not None

    # ZeroDivision runtime error
    code_runtime = "def func():\n    return 1 / 0"
    res_runtime = run_solution(code_runtime, problem)
    assert res_runtime["status"] == "runtime_error"
    assert "ZeroDivisionError" in res_runtime["error"]


def test_timeout_handled():
    problem = {
        "id": "dummy-loop",
        "title": "Dummy Loop",
        "difficulty": "easy",
        "description": "Infinite loop",
        "function_name": "inf_loop",
        "signature": "def inf_loop():",
        "compare": "exact",
        "tests": [
            {"input": [], "expected": 0},
            {"input": [], "expected": 0},
            {"input": [], "expected": 0},
            {"input": [], "expected": 0},
            {"input": [], "expected": 0},
            {"input": [], "expected": 0},
        ],
    }
    code = "import time\ndef inf_loop():\n    while True:\n        time.sleep(0.1)\n"
    res = run_solution(code, problem, timeout=2)
    assert res["status"] == "timeout"
    assert "timed out" in res["error"]


def test_group_anagrams_nested_list_comparison():
    # Test _normalize_nested logic
    a = [["bat"], ["ate", "eat", "tea"], ["nat", "tan"]]
    b = [["eat", "tea", "ate"], ["tan", "nat"], ["bat"]]
    assert _normalize_nested(a) == _normalize_nested(b)

    # Test judge execution with compare == sorted_nested
    problem = {
        "id": "dummy-anagrams",
        "title": "Dummy Anagrams",
        "difficulty": "medium",
        "description": "Group anagrams",
        "function_name": "group_anagrams",
        "signature": "def group_anagrams(strs: list[str]) -> list[list[str]]:",
        "compare": "sorted_nested",
        "tests": [
            {
                "input": [["eat", "tea", "tan", "ate", "nat", "bat"]],
                "expected": [["bat"], ["nat", "tan"], ["ate", "eat", "tea"]],
            },
            {"input": [["a"]], "expected": [["a"]]},
            {"input": [[""]], "expected": [[""]]},
            {"input": [[]], "expected": []},
            {"input": [["ab", "ba"]], "expected": [["ab", "ba"]]},
            {"input": [["a", "b"]], "expected": [["a"], ["b"]]},
        ],
    }

    # Code returning groups in different order
    code = """
def group_anagrams(strs):
    from collections import defaultdict
    ans = defaultdict(list)
    for s in strs:
        ans[''.join(sorted(s))].append(s)
    # reverse order of groups to verify sorted_nested equality
    return list(ans.values())[::-1]
"""
    res = run_solution(code, problem)
    assert res["status"] == "passed"
    assert res["passed_count"] == 6
