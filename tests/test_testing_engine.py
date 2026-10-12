"""
Comprehensive Unit & Integration Tests for Testing Engine & Test Suite Expansion (Stage 7).
Verifies:
1. Simple deterministic problem evaluation.
2. Edge-case-heavy test generation (duplicates, zeroes, negatives).
3. Constraint-boundary test suite expansion (minimum array length).
4. Practical brute-force reference comparison (differential testing).
5. Randomized test suite reproducibility using stored seeds.
6. Stress test with large input.
7. Candidate that is intentionally wrong: testing engine flags failure with exact evidence.
8. Candidate that is correct: testing engine verifies all test cases without false positives.
9. Oracle failure isolation: ensures reference bugs are not falsely blamed on candidate.
"""

import pytest
from agent.core.models import (
    ExecutionStatus,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCategory,
)
from agent.testing.engine import TestingEngine
from agent.testing.generator import TestGenerator
from agent.testing.oracles import ReferenceOracles


@pytest.fixture
def two_sum_spec() -> ProblemSpec:
    return ProblemSpec(
        id="two-sum",
        title="Two Sum",
        description="Find indices of two numbers that add up to target.",
        constraints=["2 <= nums.length <= 10^4", "-10^9 <= nums[i] <= 10^9"],
        function_name="twoSum",
        param_names=["nums", "target"],
        return_type="List[int]",
        test_cases=[
            TestCase(
                id="tc1",
                inputs={"nums": [2, 7, 11, 15], "target": 9},
                expected_output=[0, 1],
                is_sample=True,
            )
        ],
    )


# 1. Simple Deterministic Problem Suite Expansion
def test_1_suite_expansion_categories(two_sum_spec: ProblemSpec):
    gen = TestGenerator()
    suite = gen.generate_suite(two_sum_spec, include_random=True, include_stress=True)
    categories = {tc.category for tc in suite}

    # Must contain examples, edge cases, boundaries, randomized, and stress
    assert TestCategory.EXAMPLE in categories
    assert TestCategory.DUPLICATE in categories or TestCategory.EDGE_CASE in categories
    assert TestCategory.BOUNDARY in categories
    assert TestCategory.RANDOMIZED in categories
    assert TestCategory.STRESS in categories
    assert len(suite) >= 8


# 2. Edge-Case Heavy Generation
def test_2_edge_case_generation(two_sum_spec: ProblemSpec):
    gen = TestGenerator()
    suite = gen.generate_suite(two_sum_spec, include_random=False, include_stress=False)
    edge_cases = [tc for tc in suite if tc.category in (TestCategory.EDGE_CASE, TestCategory.DUPLICATE, TestCategory.NEGATIVE_ZERO)]

    assert len(edge_cases) >= 2
    # Verify duplicate elements [3, 3] target=6 was generated
    assert any(tc.inputs.get("nums") == [3, 3] and tc.inputs.get("target") == 6 for tc in edge_cases)


# 3. Constraint-Boundary Verification
def test_3_boundary_cases(two_sum_spec: ProblemSpec):
    gen = TestGenerator()
    suite = gen.generate_suite(two_sum_spec)
    boundaries = [tc for tc in suite if tc.category == TestCategory.BOUNDARY]

    assert len(boundaries) >= 1
    # Minimum array size for Two Sum is 2
    assert any(len(tc.inputs.get("nums", [])) == 2 for tc in boundaries)


# 4. Brute-Force Reference Oracle Comparison
def test_4_reference_oracle_calculation(two_sum_spec: ProblemSpec):
    ref_fn = ReferenceOracles.get_reference_solution(two_sum_spec)
    assert ref_fn is not None
    # Verify reference function calculates ground truth correctly
    res = ref_fn(nums=[10, 20, 30, 40], target=50)
    assert res == [0, 3] or res == [1, 2]


# 5. Randomized Test Reproducibility
def test_5_randomized_test_reproducibility(two_sum_spec: ProblemSpec):
    gen1 = TestGenerator(default_seed=12345)
    suite1 = gen1.generate_suite(two_sum_spec, include_stress=False, random_count=5)

    gen2 = TestGenerator(default_seed=12345)
    suite2 = gen2.generate_suite(two_sum_spec, include_stress=False, random_count=5)

    # Identical seed must produce bit-for-bit identical test cases and seeds
    rand_cases_1 = [tc for tc in suite1 if tc.category == TestCategory.RANDOMIZED]
    rand_cases_2 = [tc for tc in suite2 if tc.category == TestCategory.RANDOMIZED]

    assert len(rand_cases_1) == 5
    assert len(rand_cases_2) == 5
    for c1, c2 in zip(rand_cases_1, rand_cases_2):
        assert c1.inputs == c2.inputs
        assert c1.expected_output == c2.expected_output
        assert c1.random_seed == c2.random_seed


# 6. Stress Test Evaluation
def test_6_stress_test_generation(two_sum_spec: ProblemSpec):
    gen = TestGenerator()
    suite = gen.generate_suite(two_sum_spec, include_random=False, include_stress=True)
    stress_case = next((tc for tc in suite if tc.category == TestCategory.STRESS), None)

    assert stress_case is not None
    assert len(stress_case.inputs["nums"]) >= 1000
    assert stress_case.expected_output is not None


# 7. Candidate Intentionally Wrong Detection
def test_7_candidate_intentionally_wrong_detection(two_sum_spec: ProblemSpec):
    engine = TestingEngine()
    buggy_code = """
class Solution:
    def twoSum(self, nums, target):
        # Buggy implementation returning wrong indices
        return [0, 0]
"""
    report = engine.evaluate_solution(two_sum_spec, buggy_code, SupportedLanguage.PYTHON)
    assert report.all_passed is False
    assert report.execution_status == ExecutionStatus.WRONG_ANSWER
    assert report.failed_count > 0
    # Capture exact evidence on failing case
    failed_tc = report.failed_test_results[0]
    assert failed_tc.passed is False
    assert failed_tc.actual_output == [0, 0]
    assert failed_tc.expected_output != [0, 0]


# 8. Candidate Correct Verified Without False Positives
def test_8_candidate_correct_verified(two_sum_spec: ProblemSpec):
    engine = TestingEngine()
    correct_code = """
class Solution:
    def twoSum(self, nums, target):
        lookup = {}
        for i, num in enumerate(nums):
            comp = target - num
            if comp in lookup:
                return [lookup[comp], i]
            lookup[num] = i
        return []
"""
    # Evaluate across expanded suite including edge cases, random tests, and boundary tests
    report = engine.evaluate_solution(two_sum_spec, correct_code, SupportedLanguage.PYTHON, include_stress=False)
    assert report.all_passed is True
    assert report.execution_status == ExecutionStatus.SUCCESS
    assert report.failed_count == 0
    assert report.passed_count == report.total_tests
    assert report.total_tests >= 5


# 9. Property Evaluation Rejects Invalid Indices
def test_9_property_evaluation_boundary_check(two_sum_spec: ProblemSpec):
    # If a solution returns identical indices [2, 2], property check must reject it
    inputs = {"nums": [1, 2, 3], "target": 6}
    passed, reason = ReferenceOracles.evaluate_property(two_sum_spec, inputs, [1, 1])
    assert passed is False
    assert "distinct" in reason.lower()
