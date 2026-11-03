import pytest
from pathlib import Path

from assistant import validate_problem_url, solve_problem_flow
from judge import run_solution
from mcp_server import import_problem, solve_problem, record_verdict, get_progress
from prompts import format_copy_ready_solution
import store


class FakeAssistantLLM:
    """Mock LLM for testing solve_problem_flow without external API calls."""

    def __init__(self, solutions_by_id=None):
        self.solutions_by_id = solutions_by_id or {}
        self.call_count = 0

    def ask(self, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        # If prompt is complexity request
        if "time and space complexity" in user_prompt:
            return '{"time_complexity": "O(n)", "space_complexity": "O(1)", "explanation": "Single pass"}'

        # Find matching solution
        for pid, sol in self.solutions_by_id.items():
            if pid in user_prompt:
                # If first call, simulate wrong answer then correct
                if self.call_count == 1:
                    return f"```python\ndef {sol['fn']}(*args): return -999\n```"
                return f"```python\n{sol['code']}\n```"

        return "```python\ndef solve(*args): return None\n```"


@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_assistant.db"
    monkeypatch.setenv("LEETCODE_AGENT_DB_PATH", str(test_db))
    store.init(db_path=test_db)
    yield test_db


def test_validate_problem_url():
    assert validate_problem_url("https://leetcode.com/problems/3sum/") is True
    assert validate_problem_url("https://leetcode.cn/problems/two-sum/") is True
    assert validate_problem_url("https://google.com/search") is False
    assert validate_problem_url("") is False
    assert validate_problem_url(None) is False


def test_class_solution_judge_support():
    problem = {
        "id": "dummy-class-test",
        "title": "Class Test",
        "difficulty": "easy",
        "function_name": "add",
        "compare": "exact",
        "tests": [
            {"input": [2, 3], "expected": 5},
            {"input": [10, -5], "expected": 5},
        ],
    }
    class_code = """
class Solution:
    def add(self, a: int, b: int) -> int:
        return a + b
"""
    res = run_solution(class_code, problem)
    assert res["status"] == "passed"
    assert res["passed_count"] == 2


def test_format_copy_ready_solution():
    standalone = "def add(a, b):\n    return a + b"
    wrapped = format_copy_ready_solution(standalone, "add")
    assert "class Solution:" in wrapped
    assert "def add(self, a, b):" in wrapped

    already_wrapped = "class Solution:\n    def add(self, a, b):\n        return a + b"
    assert format_copy_ready_solution(already_wrapped, "add") == already_wrapped


def test_import_custom_problem_and_verdict(isolate_db):
    res = import_problem(
        url="https://leetcode.com/problems/3sum/",
        title="3Sum",
        difficulty="medium",
        description="Find all unique triplets in the array which gives the sum of zero.",
        function_name="threeSum",
        signature="def threeSum(nums: list[int]) -> list[list[int]]:",
        example_tests=[
            {"input": [[-1, 0, 1, 2, -1, -4]], "expected": [[-1, -1, 2], [-1, 0, 1]]}
        ],
    )
    assert res["status"] == "imported"
    assert res["problem_id"] == "3sum"

    # Verify retrieval
    stored = store.get_custom_problem("3sum", db_path=isolate_db)
    assert stored is not None
    assert stored["title"] == "3Sum"
    assert len(stored["tests"]) == 1

    # Record official verdict
    v_res = record_verdict(
        problem_id="3sum",
        verdict="Accepted",
        runtime_ms=45.2,
        memory_mb=18.5,
        notes="First attempt passed",
    )
    assert v_res["status"] == "recorded"
    assert v_res["record"]["verdict"] == "Accepted"

    # Check progress summary
    prog = get_progress()
    assert prog["custom_problems"]["total_imported"] == 1
    assert prog["official_verdicts"]["total_recorded"] == 1
    assert prog["official_verdicts"]["breakdown"]["Accepted"] == 1


def test_solve_problem_flow_with_fake_llm(isolate_db):
    problem = {
        "id": "custom-reverse",
        "title": "Reverse String",
        "difficulty": "easy",
        "description": "Reverse a list of characters.",
        "function_name": "reverse_string",
        "signature": "def reverse_string(s: list[str]) -> list[str]:",
        "compare": "exact",
        "tests": [
            {"input": [["h", "e", "l", "l", "o"]], "expected": ["o", "l", "l", "e", "h"]},
            {"input": [["H", "a", "n", "n", "a", "h"]], "expected": ["h", "a", "n", "n", "a", "H"]},
        ],
    }

    correct_code = "def reverse_string(s: list[str]) -> list[str]:\n    return s[::-1]"
    fake_llm = FakeAssistantLLM(
        solutions_by_id={"custom-reverse": {"fn": "reverse_string", "code": correct_code}}
    )

    result = solve_problem_flow(problem, fake_llm, max_attempts=3, db_path=isolate_db)

    assert result["passed"] is True
    assert result["local_status"] == "locally_verified"
    assert result["attempts"] == 2
    assert "class Solution:" in result["copy_ready_code"]
    assert "LOCALLY VERIFIED" in result["disclaimer"]
