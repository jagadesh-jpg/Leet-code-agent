"""
Tests for Stage 13: Verification Gate Hardening.
Deterministically validates:
A. Zero tests -> NOT strong VERIFIED (VERIFICATION_INCOMPLETE).
B. One passing executable test -> correctness evidence exists.
C. Passing tests + complexity mismatch -> strong VERIFIED blocked (FAILED_COMPLEXITY).
D. Passing tests + correct complexity -> can proceed toward VERIFIED.
E. Infrastructure failure -> INFRASTRUCTURE_ERROR.
F. Runtime failure -> runtime failure / FAILED_CORRECTNESS, not VERIFIED.
G. Wrong answer -> FAILED_CORRECTNESS.
H. Unknown constraints -> VERIFIED_WITH_WARNINGS or equivalent, not full certification.
I. Real C++ execution -> Solution compiled by g++ and executed, real test counts reach verifier.
"""

import pytest

from agent.core.models import (
    AlgorithmPlan,
    CandidateApproach,
    ComplexityConfidence,
    DSAPattern,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCaseResult,
    VerificationStatus,
)
from agent.execution.runner import ExecutionRunner
from agent.testing.engine import TestingEngine, TestSuiteReport
from agent.verification.complexity_auditor import ComplexityAuditor
from agent.verification.verifier import SolutionVerifier


@pytest.fixture
def two_sum_spec() -> ProblemSpec:
    return ProblemSpec(
        id="two-sum",
        title="Two Sum",
        description="Given an array of integers nums and an integer target, return indices of the two numbers.",
        function_name="twoSum",
        param_names=["nums", "target"],
        constraints=["2 <= nums.length <= 10^5", "-10^9 <= nums[i] <= 10^9"],
        test_cases=[
            TestCase(id="t1", inputs={"nums": [2, 7, 11, 15], "target": 9}, expected_output=[0, 1]),
            TestCase(id="t2", inputs={"nums": [3, 2, 4], "target": 6}, expected_output=[1, 2]),
        ],
    )


@pytest.fixture
def efficient_plan() -> AlgorithmPlan:
    approach = CandidateApproach(
        name="Hash Map",
        data_structures=["Hash Map"],
        time_complexity="O(N)",
        space_complexity="O(N)",
        description="One-pass hash map to find complement in O(1) time.",
        satisfies_constraints=True,
    )
    return AlgorithmPlan(
        problem_id="two-sum",
        identified_patterns=[DSAPattern.HASH_TABLE],
        candidate_approaches=[approach],
        selected_approach=approach,
        justification="O(N) time and O(N) space handles N=10^5.",
        constraints_validated=True,
    )


def test_gate_a_zero_tests_cannot_be_verified(two_sum_spec, efficient_plan):
    """Requirement A: Zero tests -> NOT strong VERIFIED; must report VERIFICATION_INCOMPLETE."""
    code = """def twoSum(nums, target):
    return [0, 1]
"""
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=0,
        passed_count=0,
        failed_count=0,
        execution_status=ExecutionStatus.WRONG_ANSWER,
        all_test_results=[],
    )

    verifier = SolutionVerifier()
    report = verifier.verify_solution(
        problem=two_sum_spec,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        plan=efficient_plan,
        test_report=test_report,
    )

    assert report.final_verification_status == VerificationStatus.VERIFICATION_INCOMPLETE
    assert report.is_fully_certified is False
    assert report.total_tests_run == 0
    assert "Zero executable test cases were executed" in report.warnings[0]


def test_gate_b_one_passing_executable_test(two_sum_spec, efficient_plan):
    """Requirement B: One passing executable test -> correctness evidence exists."""
    code = """def twoSum(nums, target):
    return [0, 1]
"""
    test_report = TestSuiteReport(
        all_passed=True,
        total_tests=1,
        passed_count=1,
        failed_count=0,
        execution_status=ExecutionStatus.SUCCESS,
        all_test_results=[
            TestCaseResult(test_case_id="t1", passed=True, input_data={"nums": [2, 7], "target": 9}, expected_output=[0, 1]),
        ],
    )

    verifier = SolutionVerifier()
    report = verifier.verify_solution(
        problem=two_sum_spec,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        plan=efficient_plan,
        test_report=test_report,
    )

    assert report.total_tests_run == 1
    assert report.tests_passed == 1
    assert report.tests_failed == 0
    assert report.final_verification_status in (VerificationStatus.VERIFIED, VerificationStatus.VERIFIED_WITH_WARNINGS)


def test_gate_c_passing_tests_plus_complexity_mismatch(two_sum_spec):
    """
    Requirement C: Passing tests + complexity mismatch.
    Plan expects O(1) space, but implementation uses unordered_map / dict (O(N) space).
    Expected: strong VERIFIED blocked -> FAILED_COMPLEXITY.
    """
    plan_with_o1_space = AlgorithmPlan(
        problem_id="two-sum",
        identified_patterns=[DSAPattern.HASH_TABLE],
        candidate_approaches=[
            CandidateApproach(
                name="Flawed Space Plan",
                data_structures=["Hash Map"],
                time_complexity="O(N)",
                space_complexity="O(1)",  # Incorrect claim!
                description="Claims O(1) space despite using hash table.",
                satisfies_constraints=True,
            )
        ],
        selected_approach=CandidateApproach(
            name="Flawed Space Plan",
            data_structures=["Hash Map"],
            time_complexity="O(N)",
            space_complexity="O(1)",
            description="Claims O(1) space despite using hash table.",
            satisfies_constraints=True,
        ),
        justification="Flawed",
        constraints_validated=True,
    )

    code = """def twoSum(nums, target):
    seen = dict()
    for i, num in enumerate(nums):
        diff = target - num
        if diff in seen:
            return [seen[diff], i]
        seen[num] = i
    return []
"""
    test_report = TestSuiteReport(
        all_passed=True,
        total_tests=2,
        passed_count=2,
        failed_count=0,
        execution_status=ExecutionStatus.SUCCESS,
        all_test_results=[
            TestCaseResult(test_case_id="t1", passed=True, input_data={}, expected_output=[0, 1]),
            TestCaseResult(test_case_id="t2", passed=True, input_data={}, expected_output=[1, 2]),
        ],
    )

    verifier = SolutionVerifier()
    report = verifier.verify_solution(
        problem=two_sum_spec,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        plan=plan_with_o1_space,
        test_report=test_report,
    )

    assert report.final_verification_status == VerificationStatus.FAILED_COMPLEXITY
    assert report.is_fully_certified is False
    assert report.complexity_audit.plan_implementation_consistent is False
    assert report.complexity_audit.expected_space_complexity == "O(1)"
    assert report.complexity_audit.inferred_space_complexity == "O(N)"
    assert any("Space complexity inconsistency" in a for a in report.warnings)


def test_gate_d_passing_tests_plus_correct_complexity(two_sum_spec, efficient_plan):
    """Requirement D: Passing tests + correct complexity -> proceeds toward VERIFIED."""
    code = """def twoSum(nums, target):
    seen = {}
    for i, num in enumerate(nums):
        diff = target - num
        if diff in seen:
            return [seen[diff], i]
        seen[num] = i
    return []
"""
    test_report = TestSuiteReport(
        all_passed=True,
        total_tests=2,
        passed_count=2,
        failed_count=0,
        execution_status=ExecutionStatus.SUCCESS,
        all_test_results=[
            TestCaseResult(test_case_id="t1", passed=True, input_data={}, expected_output=[0, 1]),
            TestCaseResult(test_case_id="t2", passed=True, input_data={}, expected_output=[1, 2]),
        ],
    )

    verifier = SolutionVerifier()
    report = verifier.verify_solution(
        problem=two_sum_spec,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        plan=efficient_plan,
        test_report=test_report,
    )

    assert report.final_verification_status == VerificationStatus.VERIFIED
    assert report.is_fully_certified is True
    assert report.complexity_audit.plan_implementation_consistent is True


def test_gate_e_infrastructure_failure(two_sum_spec, efficient_plan):
    """Requirement E: Infrastructure failure -> INFRASTRUCTURE_ERROR."""
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=0,
        passed_count=0,
        failed_count=0,
        execution_status=ExecutionStatus.INFRASTRUCTURE_ERROR,
        notes=["Compiler toolchain missing."],
    )

    verifier = SolutionVerifier()
    report = verifier.verify_solution(
        problem=two_sum_spec,
        source_code="def twoSum(): pass",
        language=SupportedLanguage.PYTHON,
        plan=efficient_plan,
        test_report=test_report,
    )

    assert report.final_verification_status == VerificationStatus.INFRASTRUCTURE_ERROR
    assert report.is_fully_certified is False


def test_gate_f_runtime_failure(two_sum_spec, efficient_plan):
    """Requirement F: Runtime failure -> not VERIFIED."""
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=2,
        passed_count=0,
        failed_count=2,
        execution_status=ExecutionStatus.RUNTIME_ERROR,
        failure_category=FailureCategory.RUNTIME_ERROR,
        failed_test_results=[
            TestCaseResult(test_case_id="t1", passed=False, input_data={}, expected_output=[0, 1], error_message="ZeroDivisionError"),
        ],
        all_test_results=[
            TestCaseResult(test_case_id="t1", passed=False, input_data={}, expected_output=[0, 1], error_message="ZeroDivisionError"),
        ],
    )

    verifier = SolutionVerifier()
    report = verifier.verify_solution(
        problem=two_sum_spec,
        source_code="def twoSum(): 1/0",
        language=SupportedLanguage.PYTHON,
        plan=efficient_plan,
        test_report=test_report,
    )

    assert report.final_verification_status != VerificationStatus.VERIFIED
    assert report.is_fully_certified is False


def test_gate_g_wrong_answer(two_sum_spec, efficient_plan):
    """Requirement G: Wrong answer -> FAILED_CORRECTNESS."""
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=2,
        passed_count=1,
        failed_count=1,
        execution_status=ExecutionStatus.WRONG_ANSWER,
        all_test_results=[
            TestCaseResult(test_case_id="t1", passed=True, input_data={}, expected_output=[0, 1]),
            TestCaseResult(test_case_id="t2", passed=False, input_data={}, expected_output=[1, 2], actual_output=[0, 0]),
        ],
    )

    verifier = SolutionVerifier()
    report = verifier.verify_solution(
        problem=two_sum_spec,
        source_code="def twoSum(): return [0, 0]",
        language=SupportedLanguage.PYTHON,
        plan=efficient_plan,
        test_report=test_report,
    )

    assert report.final_verification_status == VerificationStatus.FAILED_CORRECTNESS
    assert report.is_fully_certified is False


def test_gate_h_unknown_constraints(efficient_plan):
    """Requirement H: Unknown constraints -> VERIFIED_WITH_WARNINGS, not full certification."""
    spec_unconstrained = ProblemSpec(
        id="two-sum-no-limits",
        title="Two Sum Without Limits",
        description="Find two numbers.",
        function_name="twoSum",
        param_names=["nums", "target"],
        constraints=[],
    )

    code = """def twoSum(nums, target):
    seen = {}
    for i, num in enumerate(nums):
        diff = target - num
        if diff in seen:
            return [seen[diff], i]
        seen[num] = i
    return []
"""
    test_report = TestSuiteReport(
        all_passed=True,
        total_tests=1,
        passed_count=1,
        failed_count=0,
        execution_status=ExecutionStatus.SUCCESS,
        all_test_results=[
            TestCaseResult(test_case_id="t1", passed=True, input_data={}, expected_output=[0, 1]),
        ],
    )

    verifier = SolutionVerifier()
    report = verifier.verify_solution(
        problem=spec_unconstrained,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        plan=efficient_plan,
        test_report=test_report,
    )

    assert report.final_verification_status == VerificationStatus.VERIFIED_WITH_WARNINGS
    assert report.is_fully_certified is False
    assert report.constraint_compatibility.constraints_uncertain is True


def test_gate_i_real_cpp_compilation_and_execution():
    """
    Requirement I / Real Execution:
    Compiles real C++ Two Sum code with g++, runs executable tests,
    and proves real executable test evidence reaches the verifier.
    """
    cpp_problem = ProblemSpec(
        id="two-sum-cpp",
        title="Two Sum C++",
        description="Two Sum problem in C++",
        function_name="twoSum",
        param_names=["nums", "target"],
        constraints=["2 <= nums.length <= 10^4"],
        test_cases=[
            TestCase(id="t1", inputs={"nums": [2, 7, 11, 15], "target": 9}, expected_output=[0, 1]),
            TestCase(id="t2", inputs={"nums": [3, 2, 4], "target": 6}, expected_output=[1, 2]),
        ],
    )

    cpp_code = """#include <vector>
#include <unordered_map>
using namespace std;

class Solution {
public:
    vector<int> twoSum(vector<int>& nums, int target) {
        unordered_map<int, int> seen;
        for (int i = 0; i < (int)nums.size(); ++i) {
            int comp = target - nums[i];
            if (seen.find(comp) != seen.end()) {
                return {seen[comp], i};
            }
            seen[nums[i]] = i;
        }
        return {};
    }
};
"""

    plan = AlgorithmPlan(
        problem_id="two-sum-cpp",
        identified_patterns=[DSAPattern.HASH_TABLE],
        candidate_approaches=[
            CandidateApproach(
                name="Single-Pass Hash Map",
                data_structures=["unordered_map"],
                time_complexity="O(N)",
                space_complexity="O(N)",
                description="Hash map lookup.",
                satisfies_constraints=True,
            )
        ],
        selected_approach=CandidateApproach(
            name="Single-Pass Hash Map",
            data_structures=["unordered_map"],
            time_complexity="O(N)",
            space_complexity="O(N)",
            description="Hash map lookup.",
            satisfies_constraints=True,
        ),
        justification="O(N) time and O(N) space.",
        constraints_validated=True,
    )

    verifier = SolutionVerifier()
    report = verifier.verify_solution(
        problem=cpp_problem,
        source_code=cpp_code,
        language=SupportedLanguage.CPP,
        plan=plan,
        rerun_regression_if_needed=True,
    )

    assert report.total_tests_run >= 2
    assert report.tests_passed == report.total_tests_run
    assert report.tests_failed == 0
    assert report.final_verification_status == VerificationStatus.VERIFIED
    assert report.is_fully_certified is True
    assert report.complexity_audit.inferred_time_complexity == "O(N)"
    assert report.complexity_audit.inferred_space_complexity == "O(N)"
    assert report.complexity_audit.plan_implementation_consistent is True
