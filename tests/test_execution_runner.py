"""
Tests for ExecutionRunner and Language Adapters.
Tests deterministic failure differentiation:
- compile/syntax error
- runtime exception
- timeout / TLE
- wrong answer / test failure
- successful execution
- infrastructure error
"""

import pytest
from agent.core.models import (
    ProblemSpec,
    TestCase,
    ExecutionStatus,
    FailureCategory,
    SupportedLanguage,
)
from agent.execution.runner import ExecutionRunner


@pytest.fixture
def two_sum_spec() -> ProblemSpec:
    return ProblemSpec(
        id="two-sum",
        title="Two Sum",
        description="Find indices of two numbers that add up to target.",
        constraints=["2 <= nums.length <= 10^4"],
        function_name="twoSum",
        param_names=["nums", "target"],
        return_type="List[int]",
        test_cases=[
            TestCase(
                id="tc1",
                inputs={"nums": [2, 7, 11, 15], "target": 9},
                expected_output=[0, 1],
                is_sample=True,
            ),
            TestCase(
                id="tc2",
                inputs={"nums": [3, 2, 4], "target": 6},
                expected_output=[1, 2],
                is_sample=True,
            ),
            TestCase(
                id="tc3",
                inputs={"nums": [3, 3], "target": 6},
                expected_output=[0, 1],
                is_sample=True,
            ),
        ],
    )


def test_successful_execution(two_sum_spec: ProblemSpec):
    """Verifies that an optimal, correct solution passes all tests with SUCCESS status."""
    runner = ExecutionRunner(timeout_seconds=3.0)
    solution = """
class Solution:
    def twoSum(self, nums, target):
        lookup = {}
        for i, num in enumerate(nums):
            diff = target - num
            if diff in lookup:
                return [lookup[diff], i]
            lookup[num] = i
        return []
"""
    result = runner.run(two_sum_spec, solution, language=SupportedLanguage.PYTHON)
    assert result.status == ExecutionStatus.SUCCESS
    assert result.exit_code == 0
    assert len(result.test_results) == 3
    assert all(tc.passed for tc in result.test_results)
    assert result.execution_time_ms > 0


def test_wrong_answer_detection(two_sum_spec: ProblemSpec):
    """Verifies that an incorrect return value is correctly flagged as WRONG_ANSWER."""
    runner = ExecutionRunner(timeout_seconds=3.0)
    solution = """
class Solution:
    def twoSum(self, nums, target):
        # Buggy implementation returning incorrect indices
        return [0, 0]
"""
    result = runner.run(two_sum_spec, solution, language=SupportedLanguage.PYTHON)
    assert result.status == ExecutionStatus.WRONG_ANSWER
    assert result.failure_category == FailureCategory.WRONG_ANSWER
    assert len(result.test_results) == 3
    # Check that at least one test case failed
    assert any(not tc.passed for tc in result.test_results)


def test_syntax_or_compile_error(two_sum_spec: ProblemSpec):
    """Verifies that malformed syntax triggers COMPILE_ERROR."""
    runner = ExecutionRunner(timeout_seconds=3.0)
    solution = """
class Solution:
    def twoSum(self, nums, target)
        # Missing colon
        return [0, 1]
"""
    result = runner.run(two_sum_spec, solution, language=SupportedLanguage.PYTHON)
    assert result.status == ExecutionStatus.COMPILE_ERROR
    assert result.failure_category == FailureCategory.COMPILE_ERROR
    assert "SyntaxError" in result.stderr or "SyntaxError" in result.error_detail


def test_runtime_error(two_sum_spec: ProblemSpec):
    """Verifies that unhandled runtime exceptions (IndexError, ZeroDivisionError) are caught."""
    runner = ExecutionRunner(timeout_seconds=3.0)
    solution = """
class Solution:
    def twoSum(self, nums, target):
        # Deliberate runtime error
        return nums[100]
"""
    result = runner.run(two_sum_spec, solution, language=SupportedLanguage.PYTHON)
    assert result.status == ExecutionStatus.WRONG_ANSWER or result.status == ExecutionStatus.RUNTIME_ERROR
    # If the harness caught it per-test-case:
    failed_cases = [tc for tc in result.test_results if not tc.passed]
    assert len(failed_cases) > 0
    assert "IndexError" in failed_cases[0].error_message


def test_timeout_enforcement(two_sum_spec: ProblemSpec):
    """Verifies that infinite loops are killed deterministically within the timeout limit."""
    runner = ExecutionRunner(timeout_seconds=1.0)
    solution = """
class Solution:
    def twoSum(self, nums, target):
        # Infinite loop
        while True:
            pass
        return []
"""
    result = runner.run(two_sum_spec, solution, language=SupportedLanguage.PYTHON, override_timeout_sec=1.0)
    assert result.status == ExecutionStatus.TIMEOUT
    assert result.failure_category == FailureCategory.TIME_LIMIT_EXCEEDED
    assert "timed out" in result.stderr.lower() or "limit" in result.error_detail.lower()


def test_infrastructure_error_for_missing_toolchain(two_sum_spec: ProblemSpec, monkeypatch):
    """
    Verifies that calling a language whose compiler is absent from PATH
    returns INFRASTRUCTURE_ERROR rather than a false logic failure.
    """
    monkeypatch.setenv("DISABLE_CPP_TOOLCHAIN", "1")
    runner = ExecutionRunner(timeout_seconds=3.0)
    cpp_solution = "class Solution {};"
    result = runner.run(two_sum_spec, cpp_solution, language=SupportedLanguage.CPP)
    assert result.status == ExecutionStatus.INFRASTRUCTURE_ERROR
    assert result.failure_category == FailureCategory.ENVIRONMENT_ERROR
    assert "not found" in result.error_detail.lower() or "toolchain" in result.error_detail.lower()
