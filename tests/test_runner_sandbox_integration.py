"""
Unit and regression tests for Task 4:
Integration of Docker sandbox into the real execution path in ExecutionRunner,
sandbox-unavailable fail-closed behavior, and status mapping.
"""

import pytest
from unittest.mock import MagicMock, patch

from agent.core.models import (
    Difficulty,
    ExecutionStatus,
    FailureCategory,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
)
from agent.execution.runner import ExecutionRunner
from agent.execution.sandbox.base import BaseSandbox
from agent.execution.sandbox.models import SandboxExecutionResult


@pytest.fixture
def sample_problem() -> ProblemSpec:
    return ProblemSpec(
        id="two-sum",
        title="Two Sum",
        description="Find two numbers that add up to target.",
        raw_statement="Find two numbers that add up to target.",
        difficulty=Difficulty.EASY,
        function_name="twoSum",
        param_names=["nums", "target"],
        return_type="List[int]",
        test_cases=[
            TestCase(id="tc_1", inputs={"nums": [2, 7, 11, 15], "target": 9}, expected_output=[0, 1])
        ],
    )


def test_runner_fails_closed_when_sandbox_unavailable(sample_problem: ProblemSpec):
    """When require_sandbox=True and sandbox is unavailable, ExecutionRunner returns INFRASTRUCTURE_ERROR and never executes on host."""
    mock_sandbox = MagicMock(spec=BaseSandbox)
    mock_sandbox.backend_name = "docker"
    mock_sandbox.is_available.return_value = False

    runner = ExecutionRunner(sandbox=mock_sandbox, require_sandbox=True)
    res = runner.run(sample_problem, "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 1]\n")

    assert res.status == ExecutionStatus.INFRASTRUCTURE_ERROR
    assert "unavailable on this host" in (res.error_detail or "")
    mock_sandbox.execute.assert_not_called()


def test_runner_delegates_to_sandbox_backend_when_available(sample_problem: ProblemSpec):
    """When sandbox is available, ExecutionRunner delegates execution to sandbox.execute and parses results."""
    mock_sandbox = MagicMock(spec=BaseSandbox)
    mock_sandbox.backend_name = "docker"
    mock_sandbox.is_available.return_value = True
    
    stdout_payload = """
<<<EXECUTION_RESULTS_START>>>
{
    "all_passed": true,
    "results": [
        {"test_case_id": "tc_1", "passed": true, "actual_output": [0, 1], "input_data": {"nums": [2, 7, 11, 15], "target": 9}, "expected_output": [0, 1], "error_message": null, "execution_time_ms": 1.2}
    ]
}
<<<EXECUTION_RESULTS_END>>>
"""
    mock_sandbox.execute.return_value = SandboxExecutionResult(
        status=ExecutionStatus.SUCCESS,
        exit_code=0,
        stdout=stdout_payload,
        stderr="",
        timed_out=False,
    )

    runner = ExecutionRunner(sandbox=mock_sandbox, require_sandbox=True)
    res = runner.run(sample_problem, "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 1]\n")

    assert mock_sandbox.execute.called
    assert res.status == ExecutionStatus.SUCCESS
    assert len(res.test_results) == 1
    assert res.test_results[0].passed is True


def test_runner_preserves_sandbox_timeout_status(sample_problem: ProblemSpec):
    """Sandbox timeout mapped to ExecutionStatus.TIMEOUT."""
    mock_sandbox = MagicMock(spec=BaseSandbox)
    mock_sandbox.backend_name = "docker"
    mock_sandbox.is_available.return_value = True
    mock_sandbox.execute.return_value = SandboxExecutionResult(
        status=ExecutionStatus.TIMEOUT,
        failure_category=FailureCategory.TIME_LIMIT_EXCEEDED,
        exit_code=124,
        stdout="",
        stderr="Process timed out",
        timed_out=True,
    )

    runner = ExecutionRunner(sandbox=mock_sandbox, require_sandbox=True)
    res = runner.run(sample_problem, "class Solution: def twoSum(self, nums, target): pass")

    assert res.status == ExecutionStatus.TIMEOUT
    assert res.failure_category == FailureCategory.TIME_LIMIT_EXCEEDED


def test_runner_preserves_compile_error_status(sample_problem: ProblemSpec):
    """C++ compilation failure inside sandbox correctly mapped to COMPILE_ERROR."""
    mock_sandbox = MagicMock(spec=BaseSandbox)
    mock_sandbox.backend_name = "docker"
    mock_sandbox.is_available.return_value = True
    mock_sandbox.execute.return_value = SandboxExecutionResult(
        status=ExecutionStatus.COMPILE_ERROR,
        failure_category=FailureCategory.COMPILE_ERROR,
        exit_code=1,
        stdout="",
        stderr="error: expected ';' before '}' token",
        timed_out=False,
    )

    runner = ExecutionRunner(sandbox=mock_sandbox, require_sandbox=True)
    res = runner.run(sample_problem, "class Solution {};", language=SupportedLanguage.CPP)

    assert res.status == ExecutionStatus.COMPILE_ERROR
    assert res.failure_category == FailureCategory.COMPILE_ERROR
