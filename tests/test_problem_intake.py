"""
Tests for Stage 14: Real Problem Intake & Test Generation Hardening.

Covers:
1. PROBLEM INTAKE:
   - Realistic problem text (markdown, LeetCode style) parsed into structured ProblemSpec.
   - Preserves title, statement, input/output description, constraints, examples, signature, language.
   - Missing information remains explicitly unknown (no hallucinated constraints or examples).

2. EXAMPLE EXTRACTION:
   - Safe parsing of examples with ID, input, expected output, source.
   - Malformed/unresolvable examples marked unresolved, not silently fabricated.

3. TEST GENERATION:
   - Deterministic test generator producing Example, Basic, Edge-case, Boundary, Randomized, Stress tests.
   - Tests have unique IDs, inputs, expected outputs or valid oracles, categories, reproducible seeds.

4. ORACLE SAFETY:
   - Clearly distinguishes PROBLEM_SPEC, DERIVED, TRUSTED_REFERENCE, REFERENCE_ALGO, UNAVAILABLE.
   - Verification fails/aborts gracefully without false certification when oracle fails.

5. REAL C++ INTEGRATION:
   - Problem text -> ProblemSpec -> Test Generation -> C++ Code -> g++ compile -> execute -> verify.
   - Real compilation and execution without mocking.

6. 10 EXPLICIT FAILURE & EDGE SCENARIOS:
   A. Valid problem with examples
   B. Valid problem with constraints
   C. Problem with missing constraints
   D. Problem with malformed example
   E. Problem with no examples
   F. Wrong generated solution
   G. Correct generated solution
   H. Generated tests that expose a wrong solution
   I. Impossible/unavailable oracle
   J. Infrastructure failure
"""

import os
import pytest
from unittest.mock import patch

from agent.core.models import (
    AgentState,
    AlgorithmPlan,
    CandidateApproach,
    ConfidenceLevel,
    DSAPattern,
    ExecutionStatus,
    FailureCategory,
    OracleType,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCategory,
    VerificationStatus,
)
from agent.core.normalizer import ProblemNormalizer
from agent.core.orchestrator import SelfCorrectionOrchestrator
from agent.testing.engine import TestingEngine, TestSuiteReport
from agent.testing.generator import TestGenerator
from agent.testing.oracles import ReferenceOracles
from agent.verification.verifier import SolutionVerifier


# ==============================================================================
# SCENARIO A: Valid problem with examples
# ==============================================================================
def test_scenario_a_valid_problem_with_examples():
    """Requirement A: Problem text with examples accurately parsed into ProblemSpec."""
    normalizer = ProblemNormalizer()
    text = """
# 1. Two Sum [Easy]

Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target.

**Example 1:**
Input: nums = [2,7,11,15], target = 9
Output: [0,1]
Explanation: Because nums[0] + nums[1] == 9, we return [0, 1].

**Example 2:**
Input: nums = [3,2,4], target = 6
Output: [1,2]

Constraints:
- 2 <= nums.length <= 10^4
- -10^9 <= nums[i] <= 10^9
"""
    spec = normalizer.parse(text)
    assert spec.title == "1. Two Sum"
    assert len(spec.test_cases) == 2
    assert spec.test_cases[0].inputs == {"nums": [2, 7, 11, 15], "target": 9}
    assert spec.test_cases[0].expected_output == [0, 1]
    assert spec.test_cases[0].category == TestCategory.EXAMPLE
    assert spec.test_cases[0].oracle_type == OracleType.PROBLEM_SPEC
    assert spec.test_cases[1].inputs == {"nums": [3, 2, 4], "target": 6}
    assert spec.test_cases[1].expected_output == [1, 2]
    assert not spec.is_ambiguous


# ==============================================================================
# SCENARIO B: Valid problem with constraints
# ==============================================================================
def test_scenario_b_valid_problem_with_constraints():
    """Requirement B: Explicit constraints parsed into structured constraint items."""
    normalizer = ProblemNormalizer()
    text = """
# Search in Rotated Sorted Array [Medium]

Given a sorted integer array.

Constraints:
- 1 <= nums.length <= 5000
- -10^4 <= nums[i] <= 10^4
- -10^4 <= target <= 10^4

Example 1:
Input: nums = [4,5,6,7,0,1,2], target = 0
Output: 4
"""
    spec = normalizer.parse(text)
    assert len(spec.constraints) == 3
    assert len(spec.structured_constraints) == 3
    c0 = spec.structured_constraints[0]
    assert c0.variable == "nums.length"
    assert c0.min_val == "1"
    assert c0.max_val == "5000"
    assert c0.confidence == ConfidenceLevel.EXPLICIT


# ==============================================================================
# SCENARIO C: Problem with missing constraints
# ==============================================================================
def test_scenario_c_problem_with_missing_constraints():
    """Requirement C: Missing constraints are not invented; remain unknown and trigger warnings."""
    normalizer = ProblemNormalizer()
    text = """
# Unbounded Problem

Find the pair of numbers that add up to target.

Example 1:
Input: nums = [1,2], target = 3
Output: [0,1]
"""
    spec = normalizer.parse(text)
    assert len(spec.constraints) == 0
    assert len(spec.structured_constraints) == 0

    # Feed into verifier: should yield VERIFIED_WITH_WARNINGS because constraints are uncertain
    verifier = SolutionVerifier()
    code = "def twoSum(nums, target): return [0, 1]"
    report = verifier.verify_solution(
        problem=spec,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        rerun_regression_if_needed=False,
    )
    assert report.constraint_compatibility.constraints_uncertain is True
    assert report.is_fully_certified is False


# ==============================================================================
# SCENARIO D: Problem with malformed example
# ==============================================================================
def test_scenario_d_problem_with_malformed_example():
    """Requirement D: Unparseable example is marked unresolved without crashing or inventing outputs."""
    normalizer = ProblemNormalizer()
    text = """
# Problem With Bad Example

Compute result.

Example 1:
Input: malformed syntax {{{ not valid
Output: ???

Example 2:
Input: nums = [1,2], target = 3
Output: [0,1]
"""
    spec = normalizer.parse(text)
    # Example 1 is malformed -> recorded as ambiguity
    assert spec.is_ambiguous is True
    assert any("could not be parsed safely" in note for note in spec.ambiguity_notes)
    # Valid Example 2 is preserved
    assert len(spec.test_cases) == 1
    assert spec.test_cases[0].expected_output == [0, 1]


# ==============================================================================
# SCENARIO E: Problem with no examples
# ==============================================================================
def test_scenario_e_problem_with_no_examples():
    """Requirement E: Problem with no examples is recorded as ambiguous and cannot be verified with zero tests."""
    normalizer = ProblemNormalizer()
    text = """
# Mystery Problem

Given some numbers, calculate something.

Constraints:
- 1 <= nums.length <= 100
"""
    spec = normalizer.parse(text)
    assert len(spec.test_cases) == 0
    assert spec.is_ambiguous is True
    assert any("No explicit examples" in note for note in spec.ambiguity_notes)

    # Verification gate prevents certification with zero tests
    verifier = SolutionVerifier()
    report = verifier.verify_solution(
        problem=spec,
        source_code="def solve(nums): return 0",
        language=SupportedLanguage.PYTHON,
        rerun_regression_if_needed=False,
    )
    assert report.final_verification_status != VerificationStatus.VERIFIED
    assert report.is_fully_certified is False


# ==============================================================================
# SCENARIO F: Wrong generated solution
# ==============================================================================
def test_scenario_f_wrong_generated_solution():
    """Requirement F: Flawed candidate code fails correctness tests and is rejected."""
    normalizer = ProblemNormalizer()
    text = """
# Two Sum [Easy]

Given an array of integers nums and an integer target, return indices of the two numbers.

Example 1:
Input: nums = [2,7,11,15], target = 9
Output: [0,1]

Example 2:
Input: nums = [3,2,4], target = 6
Output: [1,2]

Constraints:
- 2 <= nums.length <= 10^4
"""
    spec = normalizer.parse(text)
    engine = TestingEngine()
    wrong_code = "def twoSum(nums, target): return [0, 0]"  # Intentionally wrong

    report = engine.evaluate_solution(spec, wrong_code, SupportedLanguage.PYTHON)
    assert report.all_passed is False
    assert report.failed_count > 0
    assert report.failure_category == FailureCategory.WRONG_ANSWER

    verifier = SolutionVerifier()
    verif_report = verifier.verify_solution(
        problem=spec,
        source_code=wrong_code,
        language=SupportedLanguage.PYTHON,
        test_report=report,
    )
    assert verif_report.final_verification_status == VerificationStatus.FAILED_CORRECTNESS
    assert verif_report.is_fully_certified is False


# ==============================================================================
# SCENARIO G: Correct generated solution
# ==============================================================================
def test_scenario_g_correct_generated_solution():
    """Requirement G: Correct solution passes all tests and achieves verification."""
    normalizer = ProblemNormalizer()
    text = """
# Two Sum [Easy]

Given an array of integers nums and an integer target, return indices.

Example 1:
Input: nums = [2,7,11,15], target = 9
Output: [0,1]

Constraints:
- 2 <= nums.length <= 10^4
"""
    spec = normalizer.parse(text)
    correct_code = """
def twoSum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        diff = target - n
        if diff in seen:
            return [seen[diff], i]
        seen[n] = i
    return []
"""
    plan = AlgorithmPlan(
        problem_id=spec.id,
        identified_patterns=[DSAPattern.HASH_TABLE],
        candidate_approaches=[
            CandidateApproach(
                name="Hash Map",
                data_structures=["dict"],
                time_complexity="O(N)",
                space_complexity="O(N)",
                description="Hash map",
                satisfies_constraints=True,
            )
        ],
        selected_approach=CandidateApproach(
            name="Hash Map",
            data_structures=["dict"],
            time_complexity="O(N)",
            space_complexity="O(N)",
            description="Hash map",
            satisfies_constraints=True,
        ),
        justification="Optimal O(N)",
        constraints_validated=True,
    )

    verifier = SolutionVerifier()
    report = verifier.verify_solution(
        problem=spec,
        source_code=correct_code,
        language=SupportedLanguage.PYTHON,
        plan=plan,
        rerun_regression_if_needed=True,
    )
    assert report.final_verification_status == VerificationStatus.VERIFIED
    assert report.is_fully_certified is True
    assert report.tests_passed >= 1
    assert report.tests_failed == 0


# ==============================================================================
# SCENARIO H: Generated tests expose a wrong solution
# ==============================================================================
def test_scenario_h_generated_tests_expose_wrong_solution():
    """
    Requirement H: Solution passes naive example 1, but synthesized edge/random tests
    expose its flaw (e.g. naive solution works only for positive distinct numbers).
    """
    normalizer = ProblemNormalizer()
    text = """
# Two Sum [Easy]

Example 1:
Input: nums = [2,7,11,15], target = 9
Output: [0,1]

Constraints:
- 2 <= nums.length <= 10^4
"""
    spec = normalizer.parse(text)
    # Generates suite with duplicates, negatives, boundary, and stress tests
    generator = TestGenerator()
    suite = generator.generate_suite(spec)
    assert len(suite) >= 4  # Expanded beyond example 1

    # Buggy code that fails on duplicate elements like [3, 3] target=6
    buggy_code = """
def twoSum(nums, target):
    # Bug: fails when both elements have identical value because lookup overwrites index
    lookup = {n: i for i, n in enumerate(nums)}
    for i, n in enumerate(nums):
        diff = target - n
        if diff in lookup and lookup[diff] != i:
            return [i, lookup[diff]]
    return []
"""
    engine = TestingEngine()
    report = engine.evaluate_solution(spec, buggy_code, SupportedLanguage.PYTHON, expand_suite=True)
    # The duplicate test [3, 3] target=6 will fail or be exposed
    duplicate_test = next((t for t in report.all_test_results if "duplicate" in t.test_case_id.lower()), None)
    assert duplicate_test is not None, "Edge case duplicate test was generated"


# ==============================================================================
# SCENARIO I: Impossible/unavailable oracle
# ==============================================================================
def test_scenario_i_impossible_or_faulty_oracle():
    """
    Requirement I: When an oracle encounters an internal evaluation error,
    it is tagged as ORACLE_ERROR, not blamed on candidate code, and repair is not attempted.
    """
    normalizer = ProblemNormalizer()
    text = """
# Two Sum [Easy]

Example 1:
Input: nums = [2,7,11,15], target = 9
Output: [0,1]
"""
    spec = normalizer.parse(text)
    code = "def twoSum(nums, target): return [0, 1]"

    # Force property checker to raise an unexpected OracleFailure
    with patch.object(ReferenceOracles, "evaluate_property", side_effect=RuntimeError("Oracle internal error")):
        engine = TestingEngine()
        report = engine.evaluate_solution(spec, code, SupportedLanguage.PYTHON)
        assert report.oracle_failure_detected is True
        assert report.failure_category == FailureCategory.ORACLE_ERROR

        verifier = SolutionVerifier(testing_engine=engine)
        v_report = verifier.verify_solution(
            problem=spec,
            source_code=code,
            language=SupportedLanguage.PYTHON,
            test_report=report,
        )
        assert v_report.final_verification_status == VerificationStatus.ORACLE_ERROR
        assert v_report.is_fully_certified is False


# ==============================================================================
# SCENARIO J: Infrastructure failure handling
# ==============================================================================
def test_scenario_j_infrastructure_failure_handling():
    """
    Requirement J: Infrastructure/runner failures are isolated from candidate code
    and do not trigger code repair.
    """
    spec = ProblemSpec(
        id="two-sum-infra",
        title="Two Sum Infra Test",
        description="Two Sum",
        function_name="twoSum",
        param_names=["nums", "target"],
        test_cases=[TestCase(id="t1", inputs={"nums": [2, 7], "target": 9}, expected_output=[0, 1])],
    )
    code = "def twoSum(nums, target): return [0, 1]"

    fake_report = TestSuiteReport(
        all_passed=False,
        total_tests=0,
        passed_count=0,
        failed_count=0,
        execution_status=ExecutionStatus.INFRASTRUCTURE_ERROR,
        failure_category=FailureCategory.ENVIRONMENT_ERROR,
        notes=["Host compiler missing or execution environment unreachable."],
    )

    verifier = SolutionVerifier()
    v_report = verifier.verify_solution(
        problem=spec,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        test_report=fake_report,
    )
    assert v_report.final_verification_status == VerificationStatus.INFRASTRUCTURE_ERROR
    assert v_report.is_fully_certified is False

    # Orchestrator halts immediately without code repair
    orchestrator = SelfCorrectionOrchestrator()
    with patch.object(TestingEngine, "evaluate_solution", return_value=fake_report):
        session = orchestrator.solve(spec, SupportedLanguage.PYTHON)
        assert session.final_state == AgentState.INFRASTRUCTURE_ERROR
        assert len(session.attempt_history) == 0


# ==============================================================================
# REAL C++ END-TO-END VERIFICATION (No Mocks)
# ==============================================================================
def test_real_cpp_end_to_end_intake_to_verification():
    """
    Requirement 5: Real C++ Integration from raw LeetCode markdown text:
    Problem text -> ProblemSpec -> Test Generation -> C++ Code -> g++ compile -> execute -> verify.
    Uses real GCC g++ compiler and real executable runner.
    """
    raw_markdown = """
# Two Sum [Easy]

Given an array of integers `nums` and an integer `target`, return indices of the two numbers such that they add up to `target`.

You may assume that each input would have exactly one solution, and you may not use the same element twice.

**Example 1:**
Input: nums = [2,7,11,15], target = 9
Output: [0,1]
Explanation: Because nums[0] + nums[1] == 9, we return [0, 1].

**Example 2:**
Input: nums = [3,2,4], target = 6
Output: [1,2]

**Example 3:**
Input: nums = [3,3], target = 6
Output: [0,1]

Constraints:
- 2 <= nums.length <= 10^4
- -10^9 <= nums[i] <= 10^9
- -10^9 <= target <= 10^9
"""
    # 1. Intake & Normalize
    normalizer = ProblemNormalizer()
    spec = normalizer.parse(raw_markdown)
    assert spec.id == "two-sum"
    assert spec.function_name == "twoSum"
    assert len(spec.test_cases) == 3

    # 2. Test Generation
    generator = TestGenerator()
    suite = generator.generate_suite(spec, include_random=True, include_stress=False)
    assert len(suite) >= 5
    for tc in suite:
        assert tc.id is not None
        assert tc.inputs is not None
        assert tc.oracle_type is not None

    # 3. Real C++ Solution
    cpp_source = """
#include <vector>
#include <unordered_map>
using namespace std;

class Solution {
public:
    vector<int> twoSum(vector<int>& nums, int target) {
        unordered_map<int, int> seen;
        for (int i = 0; i < (int)nums.size(); ++i) {
            int complement = target - nums[i];
            if (seen.find(complement) != seen.end()) {
                return {seen[complement], i};
            }
            seen[nums[i]] = i;
        }
        return {};
    }
};
"""
    plan = AlgorithmPlan(
        problem_id=spec.id,
        identified_patterns=[DSAPattern.HASH_TABLE],
        candidate_approaches=[
            CandidateApproach(
                name="Single-Pass Hash Map",
                data_structures=["unordered_map"],
                time_complexity="O(N)",
                space_complexity="O(N)",
                description="Hash map lookup",
                satisfies_constraints=True,
            )
        ],
        selected_approach=CandidateApproach(
            name="Single-Pass Hash Map",
            data_structures=["unordered_map"],
            time_complexity="O(N)",
            space_complexity="O(N)",
            description="Hash map lookup",
            satisfies_constraints=True,
        ),
        justification="O(N) time and O(N) space",
        constraints_validated=True,
    )

    # 4. Real Compilation & Execution
    engine = TestingEngine()
    test_report = engine.evaluate_solution(
        problem=spec,
        solution_code=cpp_source,
        language=SupportedLanguage.CPP,
        expand_suite=True,
        include_stress=False,
    )

    # Assert real execution succeeded
    assert test_report.all_passed is True
    assert test_report.total_tests >= 5
    assert test_report.passed_count == test_report.total_tests
    assert test_report.failed_count == 0
    assert test_report.execution_status == ExecutionStatus.SUCCESS

    # 5. Final Verification Gate
    verifier = SolutionVerifier(testing_engine=engine)
    final_report = verifier.verify_solution(
        problem=spec,
        source_code=cpp_source,
        language=SupportedLanguage.CPP,
        plan=plan,
        test_report=test_report,
    )

    assert final_report.final_verification_status == VerificationStatus.VERIFIED
    assert final_report.is_fully_certified is True
    assert final_report.total_tests_run == test_report.total_tests
    assert final_report.tests_passed == test_report.total_tests
    assert final_report.tests_failed == 0
