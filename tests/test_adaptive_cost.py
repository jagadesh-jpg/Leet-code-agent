"""
Unit and regression tests for Task 5:
Adaptive testing cost optimization:
- Intermediate repair iterations evaluate only examples and accumulated failed regression cases
- Final verification evaluates full suite
- Failed regression cases are never omitted
"""

import pytest
from unittest.mock import MagicMock, call

from agent.core.models import (
    Difficulty,
    ExecutionStatus,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCaseResult,
    TestSuiteReport,
)
from agent.core.orchestrator import SelfCorrectionOrchestrator
from agent.debugging.repairer import CodeRepairer
from agent.testing.engine import TestingEngine


@pytest.fixture
def two_sum_spec() -> ProblemSpec:
    return ProblemSpec(
        id="two-sum",
        title="Two Sum",
        description="Find indices of two numbers that add up to target.",
        raw_statement="Find indices of two numbers that add up to target.",
        difficulty=Difficulty.EASY,
        function_name="twoSum",
        param_names=["nums", "target"],
        return_type="List[int]",
        test_cases=[
            TestCase(id="ex_1", inputs={"nums": [2, 7, 11, 15], "target": 9}, expected_output=[0, 1], is_sample=True),
            TestCase(id="ex_2", inputs={"nums": [3, 2, 4], "target": 6}, expected_output=[1, 2], is_sample=True),
        ],
    )


def test_intermediate_repair_tests_only_examples_and_failed_cases(two_sum_spec: ProblemSpec):
    """
    On attempt 1, full adaptive suite runs and fails on a specific edge case.
    On attempt 2, orchestrator retests candidate code against only examples + failed regression case,
    and only runs full adaptive verification when that targeted suite passes.
    """
    mock_engine = MagicMock(spec=TestingEngine)
    
    # 1. First run (attempt 1): evaluate_solution_adaptive fails with an edge case
    failed_tc = TestCaseResult(
        test_case_id="tc_edge_zero",
        passed=False,
        input_data={"nums": [0, 4, 3, 0], "target": 0},
        expected_output=[0, 3],
        error_message="Wrong Answer",
    )
    fail_report = TestSuiteReport(
        all_passed=False,
        total_tests=5,
        passed_count=4,
        failed_count=1,
        execution_status=ExecutionStatus.WRONG_ANSWER,
        failed_test_results=[failed_tc],
        all_test_results=[failed_tc],
    )
    
    # 2. Second run (attempt 2):
    # intermediate evaluate_solution passes on (examples + failed_tc)
    intermediate_pass_report = TestSuiteReport(
        all_passed=True,
        total_tests=3,
        passed_count=3,
        failed_count=0,
        execution_status=ExecutionStatus.SUCCESS,
    )
    # final adaptive run also passes
    full_adaptive_pass_report = TestSuiteReport(
        all_passed=True,
        total_tests=15,
        passed_count=15,
        failed_count=0,
        execution_status=ExecutionStatus.SUCCESS,
    )

    mock_engine.evaluate_solution_adaptive.side_effect = [fail_report, full_adaptive_pass_report]
    mock_engine.evaluate_solution.return_value = intermediate_pass_report

    mock_repairer = MagicMock(spec=CodeRepairer)
    mock_repairer.repair.return_value = ("class Solution:\n    def twoSum(self, nums, target):\n        return [0, 1]\n", "patch")

    orchestrator = SelfCorrectionOrchestrator(
        testing_engine=mock_engine,
        repairer=mock_repairer,
        max_attempts=2,
    )

    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code="class Solution: pass")

    # Verify intermediate call to evaluate_solution happened
    assert mock_engine.evaluate_solution.called
    intermediate_call_args = mock_engine.evaluate_solution.call_args[1]
    tested_spec = intermediate_call_args["problem"]
    tested_case_ids = [tc.id for tc in tested_spec.test_cases]
    
    # Must contain both original examples AND the regression case
    assert "ex_1" in tested_case_ids
    assert "ex_2" in tested_case_ids
    assert "tc_edge_zero" in tested_case_ids
    assert intermediate_call_args["expand_suite"] is False
    assert intermediate_call_args["include_stress"] is False

    # And full adaptive was run for final verification
    assert mock_engine.evaluate_solution_adaptive.call_count == 2
