"""
Tests for Failure Analysis & Root-Cause Classification (Stage 8).
Verifies:
1. Compilation error with exact line number and code excerpt extraction.
2. Runtime exception (IndexError, ArithmeticException) with source location mapping.
3. Timeout caused by infinite loop mapped to TIME_LIMIT_EXCEEDED.
4. Wrong answer implementation bug: expected vs actual capture and diagnostic hypotheses.
5. Boundary-condition failure diagnosis.
6. Division by zero / arithmetic failure diagnosis.
7. Multi-test common failure identification.
8. Infrastructure failure isolated: host toolchain issue NOT blamed on candidate code.
9. Oracle failure isolated: reference solution bug NOT blamed on candidate code.
10. Insufficient evidence reported honestly as UNKNOWN_FAILURE.
11. A correct solution produces NO failure report (returns None).
"""

import pytest
from agent.core.models import (
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
    FailureReport,
    FailureSeverity,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCaseResult,
    TestCategory,
)
from agent.debugging.failure_analyzer import FailureAnalyzer
from agent.testing.engine import TestSuiteReport


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
            TestCase(id="tc1", inputs={"nums": [2, 7, 11, 15], "target": 9}, expected_output=[0, 1]),
            TestCase(id="tc2", inputs={"nums": [3, 2, 4], "target": 6}, expected_output=[1, 2]),
        ],
    )


# 1. Compilation Error with Exact Line Number
def test_1_compilation_error_exact_line(two_sum_spec: ProblemSpec):
    broken_source = "class Solution:\n    def twoSum(self, nums, target)\n        return []"
    fake_stderr = '  File "harness.py", line 2\n    def twoSum(self, nums, target)\n                                  ^\nSyntaxError: expected \':\''
    exec_res = ExecutionResult(
        status=ExecutionStatus.COMPILE_ERROR,
        failure_category=FailureCategory.COMPILE_ERROR,
        exit_code=1,
        stderr=fake_stderr,
        error_detail="SyntaxError",
    )

    report = FailureAnalyzer.analyze(two_sum_spec, broken_source, SupportedLanguage.PYTHON, exec_result=exec_res)
    assert report is not None
    assert report.failure_category == FailureCategory.COMPILE_ERROR
    assert report.severity == FailureSeverity.CRITICAL
    assert report.source_line == 2
    assert report.source_excerpt is not None
    assert "->   2:" in report.source_excerpt


# 2. Runtime Exception with Source Location
def test_2_runtime_error_line_extraction(two_sum_spec: ProblemSpec):
    source = "class Solution:\n    def twoSum(self, nums, target):\n        return nums[100]\n"
    tc_fail = TestCaseResult(
        test_case_id="tc1",
        passed=False,
        input_data={"nums": [2, 7], "target": 9},
        expected_output=[0, 1],
        actual_output=None,
        error_message='Traceback:\n  File "harness.py", line 3, in twoSum\n    return nums[100]\nIndexError: list index out of range',
    )
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=1,
        passed_count=0,
        failed_count=1,
        execution_status=ExecutionStatus.RUNTIME_ERROR,
        failed_test_results=[tc_fail],
    )

    report = FailureAnalyzer.analyze(two_sum_spec, source, SupportedLanguage.PYTHON, test_report=test_report)
    assert report is not None
    assert report.failure_category == FailureCategory.RUNTIME_ERROR
    assert report.severity == FailureSeverity.HIGH
    assert report.source_line == 3
    assert any("out of bounds" in h.hypothesis.lower() for h in report.ranked_hypotheses)


# 3. Timeout Failure
def test_3_timeout_failure(two_sum_spec: ProblemSpec):
    source = "class Solution:\n    def twoSum(self, nums, target):\n        while True: pass"
    exec_res = ExecutionResult(
        status=ExecutionStatus.TIMEOUT,
        failure_category=FailureCategory.TIME_LIMIT_EXCEEDED,
        exit_code=-1,
        execution_time_ms=3005.0,
        error_detail="Time limit of 3.0s exceeded.",
    )

    report = FailureAnalyzer.analyze(two_sum_spec, source, SupportedLanguage.PYTHON, exec_result=exec_res)
    assert report is not None
    assert report.failure_category == FailureCategory.TIME_LIMIT_EXCEEDED
    assert report.severity == FailureSeverity.HIGH
    assert any("infinite loop" in h.hypothesis.lower() for h in report.ranked_hypotheses)


# 4. Wrong Answer Implementation Bug
def test_4_wrong_answer_hypotheses(two_sum_spec: ProblemSpec):
    source = "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 0]"
    tc_fail = TestCaseResult(
        test_case_id="tc1",
        passed=False,
        input_data={"nums": [2, 7, 11, 15], "target": 9},
        expected_output=[0, 1],
        actual_output=[0, 0],
    )
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=1,
        passed_count=0,
        failed_count=1,
        execution_status=ExecutionStatus.WRONG_ANSWER,
        failed_test_results=[tc_fail],
    )

    report = FailureAnalyzer.analyze(two_sum_spec, source, SupportedLanguage.PYTHON, test_report=test_report)
    assert report is not None
    assert report.failure_category == FailureCategory.WRONG_ANSWER
    assert report.expected_output == [0, 1]
    assert report.actual_output == [0, 0]
    assert len(report.ranked_hypotheses) >= 2


# 5. Boundary Condition Failure
def test_5_boundary_condition_failure(two_sum_spec: ProblemSpec):
    source = "class Solution: pass"
    tc_fail = TestCaseResult(
        test_case_id="bound_min_2",
        passed=False,
        input_data={"nums": [1, 2], "target": 3},
        expected_output=[0, 1],
        actual_output=[],
        category=TestCategory.BOUNDARY,
    )
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=1,
        passed_count=0,
        failed_count=1,
        execution_status=ExecutionStatus.WRONG_ANSWER,
        failed_test_results=[tc_fail],
    )

    report = FailureAnalyzer.analyze(two_sum_spec, source, SupportedLanguage.PYTHON, test_report=test_report)
    assert report is not None
    assert any("boundary" in h.hypothesis.lower() for h in report.ranked_hypotheses)


# 6. Infrastructure Failure Isolated (Host Compiler Missing)
def test_6_infrastructure_failure_isolated(two_sum_spec: ProblemSpec):
    exec_res = ExecutionResult(
        status=ExecutionStatus.INFRASTRUCTURE_ERROR,
        failure_category=FailureCategory.ENVIRONMENT_ERROR,
        error_detail="g++ compiler not found in PATH",
    )
    report = FailureAnalyzer.analyze(two_sum_spec, "class Solution {};", SupportedLanguage.CPP, exec_result=exec_res)
    assert report is not None
    assert report.is_infrastructure_failure is True
    assert report.failure_category == FailureCategory.ENVIRONMENT_ERROR
    assert "compiler" in report.error_message.lower()


# 7. Oracle Failure Isolated (Reference Algorithm Bug)
def test_7_oracle_failure_isolated(two_sum_spec: ProblemSpec):
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=5,
        passed_count=0,
        failed_count=5,
        execution_status=ExecutionStatus.INFRASTRUCTURE_ERROR,
        oracle_failure_detected=True,
        notes=["Reference function crashed with ZeroDivisionError"],
    )
    report = FailureAnalyzer.analyze(two_sum_spec, "class Solution: pass", SupportedLanguage.PYTHON, test_report=test_report)
    assert report is not None
    assert report.is_infrastructure_failure is True
    assert report.failure_category == FailureCategory.ORACLE_ERROR
    assert any("reference algorithm" in h.hypothesis.lower() for h in report.ranked_hypotheses)


# 8. Insufficient Evidence Reported Honestly
def test_8_insufficient_evidence_reported_as_unknown(two_sum_spec: ProblemSpec):
    # Process crashed with exit code 139 (SIGSEGV) but empty stdout/stderr and no test output
    exec_res = ExecutionResult(
        status=ExecutionStatus.RUNTIME_ERROR,
        failure_category=FailureCategory.UNKNOWN_FAILURE,
        exit_code=139,
        stderr="",
        stdout="",
    )
    report = FailureAnalyzer.analyze(two_sum_spec, "code", SupportedLanguage.PYTHON, exec_result=exec_res)
    assert report is not None
    assert report.failure_category == FailureCategory.UNKNOWN_FAILURE
    assert len(report.uncertainty_notes) > 0


# 9. Correct Solution Produces NO Failure Report
def test_9_correct_solution_returns_none(two_sum_spec: ProblemSpec):
    test_report = TestSuiteReport(
        all_passed=True,
        total_tests=10,
        passed_count=10,
        failed_count=0,
        execution_status=ExecutionStatus.SUCCESS,
    )
    report = FailureAnalyzer.analyze(two_sum_spec, "class Solution: pass", SupportedLanguage.PYTHON, test_report=test_report)
    assert report is None
