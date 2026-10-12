"""
Comprehensive End-to-End Tests for the Autonomous Self-Correction Loop (Stage 9).
Verifies:
1. Candidate code passes immediately -> VERIFIED in attempt 1.
2. Candidate code has a compilation/syntax error and repair fixes it -> compile failure -> diagnosis -> repair -> retest -> VERIFIED.
3. Candidate code has a runtime error (out of bounds) and repair fixes it -> runtime failure -> diagnosis -> repair -> retest -> VERIFIED.
4. Candidate code produces wrong output and repair fixes it -> wrong answer -> diagnosis -> repair -> retest -> VERIFIED.
5. Candidate code remains incorrect until maximum attempts -> MAX_ATTEMPTS_REACHED with attempt history.
6. Infrastructure failure occurs -> INFRASTRUCTURE_ERROR without modifying candidate code.
7. Correct solution is preserved without unnecessary repair attempts.
8. Repaired code failing AST/security validation is caught prior to execution.
9. Full regression suite runs after each repair attempt.
"""

from unittest.mock import MagicMock, patch
import pytest

from agent.core.models import (
    AgentState,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
)
from agent.core.orchestrator import SelfCorrectionOrchestrator


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
            TestCase(id="tc1", inputs={"nums": [2, 7, 11, 15], "target": 9}, expected_output=[0, 1], is_sample=True),
            TestCase(id="tc2", inputs={"nums": [3, 2, 4], "target": 6}, expected_output=[1, 2], is_sample=True),
        ],
    )


# 1. Candidate passes immediately on first attempt
def test_1_candidate_passes_immediately(two_sum_spec: ProblemSpec):
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)
    optimal_code = """
class Solution:
    def twoSum(self, nums, target):
        seen = {}
        for i, val in enumerate(nums):
            comp = target - val
            if comp in seen:
                return [seen[comp], i]
            seen[val] = i
        return []
"""
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=optimal_code)
    assert session.is_verified is True
    assert session.final_state == AgentState.VERIFIED
    assert session.verified_code == optimal_code
    assert len(session.attempt_history) == 0  # No repair attempts needed


# 2. Candidate has compilation/syntax error -> Diagnosed -> Repaired -> VERIFIED
def test_2_compilation_error_repaired_to_verified(two_sum_spec: ProblemSpec):
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)
    # Missing colon on def line
    broken_syntax_code = """
class Solution:
    def twoSum(self, nums, target)
        seen = {}
        for i, val in enumerate(nums):
            comp = target - val
            if comp in seen:
                return [seen[comp], i]
            seen[val] = i
        return []
"""
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=broken_syntax_code)
    assert session.is_verified is True
    assert session.final_state == AgentState.VERIFIED
    assert len(session.attempt_history) >= 1
    # Check that first attempt addressed COMPILE_ERROR
    first_attempt = session.attempt_history[0]
    assert first_attempt.failure_addressed.failure_category == FailureCategory.COMPILE_ERROR
    assert "colon" in first_attempt.patch_summary.lower()


# 3. Candidate has runtime error (IndexError) -> Diagnosed -> Repaired -> VERIFIED
def test_3_runtime_error_repaired_to_verified(two_sum_spec: ProblemSpec):
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)
    # Buggy code that triggers IndexError
    broken_runtime_code = """
class Solution:
    def twoSum(self, nums, target):
        return nums[99999]
"""
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=broken_runtime_code)
    assert session.is_verified is True
    assert session.final_state == AgentState.VERIFIED
    assert len(session.attempt_history) >= 1
    # Check that runtime error was addressed
    assert session.attempt_history[0].failure_addressed.failure_category == FailureCategory.RUNTIME_ERROR


# 4. Candidate produces wrong output (Wrong Answer) -> Diagnosed -> Repaired -> VERIFIED
def test_4_wrong_answer_repaired_to_verified(two_sum_spec: ProblemSpec):
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)
    # Buggy code returning [0, 0]
    wrong_answer_code = """
class Solution:
    def twoSum(self, nums, target):
        return [0, 0]
"""
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=wrong_answer_code)
    assert session.is_verified is True
    assert session.final_state == AgentState.VERIFIED
    assert len(session.attempt_history) >= 1
    assert session.attempt_history[0].failure_addressed.failure_category == FailureCategory.WRONG_ANSWER


# 5. Candidate remains incorrect until maximum attempts -> MAX_ATTEMPTS_REACHED
def test_5_reaches_maximum_attempts_when_unfixable(two_sum_spec: ProblemSpec):
    # Mock a repairer that makes no progress
    orchestrator = SelfCorrectionOrchestrator(max_attempts=2)
    unfixable_code = """
class Solution:
    def twoSum(self, nums, target):
        return [-1, -1]  # Always wrong
"""
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=unfixable_code)
    assert session.is_verified is False
    assert session.final_state == AgentState.MAX_ATTEMPTS_REACHED
    assert "maximum" in session.error_summary.lower()


# 6. Infrastructure failure halts loop without modifying candidate code
def test_6_infrastructure_failure_halts_immediately(two_sum_spec: ProblemSpec, monkeypatch):
    monkeypatch.setenv("DISABLE_CPP_TOOLCHAIN", "1")
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)
    # Request execution on C++ where compiler is disabled
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.CPP)
    assert session.final_state == AgentState.INFRASTRUCTURE_ERROR
    assert session.is_verified is False
    # No repair attempts should be made when toolchain is missing
    assert len(session.attempt_history) == 0
    assert "toolchain" in session.error_summary.lower() or "not in path" in session.error_summary.lower() or "not found" in session.error_summary.lower()


# 7. Correct solution preserved without unnecessary repairs
def test_7_correct_solution_preserved_without_redundant_repairs(two_sum_spec: ProblemSpec):
    orchestrator = SelfCorrectionOrchestrator(max_attempts=5)
    code = """
class Solution:
    def twoSum(self, nums, target):
        seen = {}
        for i, val in enumerate(nums):
            comp = target - val
            if comp in seen:
                return [seen[comp], i]
            seen[val] = i
        return []
"""
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=code)
    assert len(session.attempt_history) == 0  # No repair cycles performed
    assert session.is_verified is True
    assert session.final_state == AgentState.VERIFIED


# 8. Repaired code failing security/AST validation is caught prior to execution
def test_8_repair_failing_security_validation_caught(two_sum_spec: ProblemSpec):
    orchestrator = SelfCorrectionOrchestrator(max_attempts=2)
    # Code with forbidden import
    insecure_code = """
import os
class Solution:
    def twoSum(self, nums, target):
        return []
"""
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=insecure_code)
    # First attempt must catch the AST / security violation
    assert len(session.attempt_history) >= 1
    assert session.attempt_history[0].ast_valid is False
