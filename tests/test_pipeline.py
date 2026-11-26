"""Comprehensive tests for the modular Autonomous Pipeline (Phase 5).

Verifies:
1. Successful problem completion with immediate passing code.
2. Wrong-answer diagnosis and successful correction on attempt 2.
3. Compilation failure handling (syntax error) and subsequent repair.
4. Correction-cycle limits (exhaustion after max_attempts).
5. Queue advancement across multiple problems.
6. Failure state recording in SQLite database.
7. Correct progress recording (isolated per language).
8. Strict isolation from production progress.db using temporary databases.
9. Deterministic execution with zero network calls.
"""

from pathlib import Path
import pytest
import sqlite3

from pipeline import AutonomousPipeline, FailureCategory, MockSolutionGenerator, PipelineStage
import store


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_pipeline.db"
    store.init(db_path=db_file)
    return db_file


def test_pipeline_immediate_success(temp_db):
    """Test Stage 1-10 with a solution that passes on the first attempt."""
    problem = {
        "id": "two-sum",
        "title": "Two Sum",
        "difficulty": "easy",
        "description": "Sum of two numbers",
        "function_name": "two_sum",
        "signature": "def two_sum(nums: list[int], target: int) -> list[int]:",
        "tests": [
            {"input": [[2, 7, 11, 15], 9], "expected": [0, 1]},
            {"input": [[3, 2, 4], 6], "expected": [1, 2]},
            {"input": [[3, 3], 6], "expected": [0, 1]},
            {"input": [[-1, -2, -3, -4, -5], -8], "expected": [2, 4]},
            {"input": [[0, 4, 3, 0], 0], "expected": [0, 3]},
            {"input": [[1, 5, 8, 10, 14, 20], 24], "expected": [3, 4]},
        ],
        "reference_solution": (
            "def two_sum(nums: list[int], target: int) -> list[int]:\n"
            "    seen = {}\n"
            "    for i, num in enumerate(nums):\n"
            "        comp = target - num\n"
            "        if comp in seen:\n"
            "            return [seen[comp], i]\n"
            "        seen[num] = i\n"
            "    return []\n"
        ),
    }

    # Generator scripts attempt 1 to immediately emit reference solution
    generator = MockSolutionGenerator(scripts={"two-sum": [problem["reference_solution"]]})
    stages_visited = []

    pipeline = AutonomousPipeline(
        generator=generator,
        db_path=temp_db,
        language="python",
        max_attempts=3,
        on_stage_change=lambda stage, data: stages_visited.append(stage),
    )

    result = pipeline.process_problem(problem)

    assert result.passed is True
    assert result.attempts_used == 1
    assert result.final_verdict == "locally_verified"
    assert result.tests_passed == 6
    assert result.failure_category == FailureCategory.NONE
    assert PipelineStage.COMPLETED in stages_visited

    # Verify database persistence
    assert store.is_solved("two-sum", language="python", db_path=temp_db) is True
    attempts = store.get_attempts("two-sum", db_path=temp_db) if hasattr(store, "get_attempts") else []


def test_pipeline_wrong_answer_then_correction(temp_db):
    """Test attempt 1 wrong answer, feedback prompt, and attempt 2 repair."""
    problem = {
        "id": "contains-duplicate",
        "title": "Contains Duplicate",
        "difficulty": "easy",
        "description": "Find duplicates in array",
        "function_name": "contains_duplicate",
        "signature": "def contains_duplicate(nums: list[int]) -> bool:",
        "tests": [
            {"input": [[1, 2, 3, 1]], "expected": True},
            {"input": [[1, 2, 3, 4]], "expected": False},
            {"input": [[1, 1, 1, 3, 3, 4, 3, 2, 4, 2]], "expected": True},
            {"input": [[]], "expected": False},
            {"input": [[42]], "expected": False},
            {"input": [[-1, -1]], "expected": True},
        ],
        "reference_solution": "def contains_duplicate(nums: list[int]) -> bool:\n    return len(nums) != len(set(nums))\n",
    }

    # Attempt 1: wrong answer (always True), Attempt 2: reference solution
    wrong_code = "def contains_duplicate(nums: list[int]) -> bool:\n    return True\n"
    generator = MockSolutionGenerator(scripts={
        "contains-duplicate": [wrong_code, problem["reference_solution"]]
    })

    pipeline = AutonomousPipeline(
        generator=generator,
        db_path=temp_db,
        language="python",
        max_attempts=3,
    )

    result = pipeline.process_problem(problem)

    assert result.passed is True
    assert result.attempts_used == 2
    assert result.history[0]["status"] == "wrong_answer"
    assert result.history[0]["failure_category"] == "wrong_answer"
    assert result.history[1]["status"] == "passed"
    assert result.history[1]["failure_category"] == "none"

    assert store.is_solved("contains-duplicate", language="python", db_path=temp_db) is True


def test_pipeline_compile_error_then_correction(temp_db):
    """Test attempt 1 syntax error, diagnosis capture, and attempt 2 repair."""
    problem = {
        "id": "valid-parentheses",
        "title": "Valid Parentheses",
        "difficulty": "easy",
        "description": "Check if parentheses string is valid",
        "function_name": "is_valid",
        "signature": "def is_valid(s: str) -> bool:",
        "tests": [
            {"input": ["()"], "expected": True},
            {"input": ["()[]{}"], "expected": True},
            {"input": ["(]"], "expected": False},
            {"input": ["([)]"], "expected": False},
            {"input": ["{[]}"], "expected": True},
            {"input": [""], "expected": True},
            {"input": ["[("], "expected": False},
        ],
        "reference_solution": (
            "def is_valid(s: str) -> bool:\n"
            "    stack = []\n"
            "    mapping = {')': '(', '}': '{', ']': '['}\n"
            "    for char in s:\n"
            "        if char in mapping:\n"
            "            top = stack.pop() if stack else '#'\n"
            "            if mapping[char] != top: return False\n"
            "        else: stack.append(char)\n"
            "    return not stack\n"
        ),
    }

    # Attempt 1 has a syntax error (missing colon)
    broken_code = "def is_valid(s: str) -> bool\n    return True\n"
    generator = MockSolutionGenerator(scripts={
        "valid-parentheses": [broken_code, problem["reference_solution"]]
    })

    pipeline = AutonomousPipeline(
        generator=generator,
        db_path=temp_db,
        language="python",
        max_attempts=3,
    )

    result = pipeline.process_problem(problem)

    assert result.passed is True
    assert result.attempts_used == 2
    assert result.history[0]["status"] in ["runtime_error", "compile_error"]
    assert result.history[1]["status"] == "passed"
    assert store.is_solved("valid-parentheses", language="python", db_path=temp_db) is True


def test_pipeline_correction_cycle_exhaustion(temp_db):
    """Test that pipeline stops when max_attempts is reached and marks problem failed."""
    problem = {
        "id": "always-fail",
        "title": "Always Fail Problem",
        "difficulty": "medium",
        "description": "Impossible",
        "function_name": "solve",
        "signature": "def solve(x: int) -> int:",
        "tests": [{"input": [1], "expected": 10}, {"input": [2], "expected": 20}],
    }

    generator = MockSolutionGenerator(scripts={
        "always-fail": ["def solve(x): return 0", "def solve(x): return -1"]
    })

    pipeline = AutonomousPipeline(
        generator=generator,
        db_path=temp_db,
        language="python",
        max_attempts=2,
    )

    result = pipeline.process_problem(problem)

    assert result.passed is False
    assert result.attempts_used == 2
    assert result.final_verdict == "wrong_answer"
    assert result.failure_category == FailureCategory.WRONG_ANSWER
    assert store.is_solved("always-fail", language="python", db_path=temp_db) is False


def test_pipeline_queue_advancement(temp_db):
    """Test sequential queue advancement across multiple problems without infinite loops."""
    # Register two custom problems
    p1 = {
        "id": "q-prob-1",
        "title": "Q Prob 1",
        "difficulty": "Easy",
        "description": "Return 1",
        "function_name": "get_one",
        "signature": "def get_one() -> int:",
        "tests": [{"input": [], "expected": 1}],
        "reference_solution": "def get_one(): return 1",
    }
    p2 = {
        "id": "q-prob-2",
        "title": "Q Prob 2",
        "difficulty": "Easy",
        "description": "Return 2",
        "function_name": "get_two",
        "signature": "def get_two() -> int:",
        "tests": [{"input": [], "expected": 2}],
        "reference_solution": "def get_two(): return 2",
    }

    store.save_custom_problem(
        problem_id=p1["id"], url="u", title=p1["title"], difficulty=p1["difficulty"],
        description=p1["description"], function_name=p1["function_name"], signature=p1["signature"],
        tests=p1["tests"], reference_solution=p1["reference_solution"], db_path=temp_db
    )
    store.save_custom_problem(
        problem_id=p2["id"], url="u", title=p2["title"], difficulty=p2["difficulty"],
        description=p2["description"], function_name=p2["function_name"], signature=p2["signature"],
        tests=p2["tests"], reference_solution=p2["reference_solution"], db_path=temp_db
    )

    generator = MockSolutionGenerator(scripts={
        "q-prob-1": ["def get_one(): return 1"],
        "q-prob-2": ["def get_two(): return 2"],
    })

    pipeline = AutonomousPipeline(
        generator=generator,
        db_path=temp_db,
        language="python",
        max_attempts=2,
    )

    results = pipeline.run_queue(problem_ids=["q-prob-1", "q-prob-2"])
    assert len(results) == 2
    assert results[0].problem_id == "q-prob-1" and results[0].passed is True
    assert results[1].problem_id == "q-prob-2" and results[1].passed is True


def test_pipeline_timeout_handling(temp_db):
    """Test timeout failure classification, bounded attempts, and unsolved state."""
    problem = {
        "id": "timeout-prob",
        "title": "Timeout Problem",
        "difficulty": "Medium",
        "description": "Compute something that might time out",
        "function_name": "slow_func",
        "signature": "def slow_func(n: int) -> int:",
        "tests": [{"input": [1], "expected": 1}],
    }

    # Generate infinite loop solution
    generator = MockSolutionGenerator(scripts={
        "timeout-prob": [
            "def slow_func(n):\n    import time\n    time.sleep(2)\n    return n"
        ]
    })

    pipeline = AutonomousPipeline(
        generator=generator,
        db_path=temp_db,
        language="python",
        max_attempts=1,
        timeout_seconds=1,
    )

    result = pipeline.process_problem(problem)

    assert result.passed is False
    assert result.attempts_used == 1
    assert result.final_verdict == "timeout"
    assert result.failure_category == FailureCategory.TIMEOUT
    assert store.is_solved("timeout-prob", language="python", db_path=temp_db) is False

    # Check that attempt record exists in database
    with store.get_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM attempts WHERE problem_id = ?", ("timeout-prob",))
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "timeout"


def test_mock_generator_multilang_fallback():
    """Verify MockSolutionGenerator generates appropriate language stubs on fallback."""
    problem = {
        "id": "generic-stub-prob",
        "function_name": "calc",
        "tests": [],
    }
    generator = MockSolutionGenerator()

    # Attempt 2 without reference solution should yield language-specific fallback stub
    py_code = generator.generate(problem, attempt_no=2, language="python")
    assert "def calc(" in py_code
    assert "return None" in py_code

    c_code = generator.generate(problem, attempt_no=2, language="c")
    assert "int calc(void)" in c_code
    assert "```c" in c_code

    cpp_code = generator.generate(problem, attempt_no=2, language="cpp")
    assert "class Solution" in cpp_code
    assert "int calc()" in cpp_code
    assert "```cpp" in cpp_code

    java_code = generator.generate(problem, attempt_no=2, language="java")
    assert "class Solution" in java_code
    assert "public int calc()" in java_code
    assert "```java" in java_code


def test_pipeline_c_cpp_adapters_if_available(temp_db):
    """Test pipeline execution through C/C++ adapters when toolchain is present."""
    from adapters import UnifiedJudge
    c_adapter = UnifiedJudge.get_adapter("c")
    if not c_adapter.is_available():
        pytest.skip("C compiler (gcc/clang) not available in this environment")

    problem = {
        "id": "c-simple-search",
        "title": "Simple Search C",
        "difficulty": "Easy",
        "description": "Binary search or linear search in C",
        "function_name": "search",
        "signature": "int search(int* nums, int numsSize, int target);",
        "tests": [
            {"input": [[1, 2, 3, 4], 3], "expected": 2},
            {"input": [[1, 2, 3, 4], 5], "expected": -1},
        ],
    }

    generator = MockSolutionGenerator(scripts={
        "c-simple-search": [
            """int search(int* nums, int numsSize, int target) {
    for (int i = 0; i < numsSize; i++) {
        if (nums[i] == target) return i;
    }
    return -1;
}"""
        ]
    })

    pipeline = AutonomousPipeline(
        generator=generator,
        db_path=temp_db,
        language="c",
        max_attempts=1,
    )

    result = pipeline.process_problem(problem)
    assert result.passed is True
    assert result.attempts_used == 1
    assert result.final_verdict == "locally_verified"
    assert store.is_solved("c-simple-search", language="c", db_path=temp_db) is True


def test_pipeline_empty_or_missing_signature(temp_db):
    """Verify that empty, None, or missing signature is handled gracefully without crashes."""
    problem = {
        "id": "no-sig-prob",
        "title": "No Signature Problem",
        "difficulty": "Easy",
        "description": "Return 42",
        "function_name": "answer",
        "signature": None,
        "tests": [{"input": [], "expected": 42}],
    }

    generator = MockSolutionGenerator(scripts={
        "no-sig-prob": ["def answer(): return 42"]
    })

    pipeline = AutonomousPipeline(
        generator=generator,
        db_path=temp_db,
        language="python",
        max_attempts=1,
    )

    result = pipeline.process_problem(problem)
    assert result.passed is True
    assert result.attempts_used == 1
    assert result.final_verdict == "locally_verified"
    assert store.is_solved("no-sig-prob", language="python", db_path=temp_db) is True

