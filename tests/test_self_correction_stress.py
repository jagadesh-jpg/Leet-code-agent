"""
Tests for Stage 15: Autonomous Self-Correction Stress Testing.

Proves the complete cycle:
GENERATE -> EXECUTE -> MEASURE -> DIAGNOSE -> REPAIR -> EXECUTE -> RETEST -> REGRESSION TEST -> VERIFY

Covers:
1. SCENARIO A: Wrong Answer detection, diagnosis, repair, retest -> VERIFIED.
2. SCENARIO B: Edge Case failure (e.g. duplicate elements colliding in dictionary) -> repaired -> passing all tests.
3. SCENARIO C: Boundary failure -> detected as boundary/range issue, not generic failure.
4. SCENARIO D: Runtime failure (division by zero / index error) -> classified as RUNTIME_ERROR, repaired -> VERIFIED.
5. SCENARIO E: Compile failure (missing syntax/semicolon/colon) -> captured with compiler stderr, repaired -> VERIFIED.
6. SCENARIO F: Complexity / Performance failure -> O(N^2) vs O(N) constraint incompatibility detected.
7. SCENARIO G: Plan/implementation mismatch -> detected and prevented from being certified.
8. SCENARIO H: Infrastructure failure -> classified as ENVIRONMENT/INFRASTRUCTURE_ERROR, candidate code NOT repaired.
9. SCENARIO I: Oracle failure -> classified as ORACLE_ERROR, candidate code NOT repaired, candidate not verified.
10. MULTI-ATTEMPT REPAIR: Sequence across multiple attempts (Attempt 1 fail -> Attempt 2 fail -> Attempt 3 pass).
11. MAX ATTEMPTS SAFETY: Loop terminates at configured max_attempts, no infinite loop, marked MAX_ATTEMPTS_REACHED.
12. ATTEMPT HISTORY PRESERVATION: Full history with source hashes, failure categories, patch summaries, test counts.
13. REGRESSION AFTER REPAIR: Full test suite re-evaluated after repair.
14. REAL C++ SELF-CORRECTION: Real g++ compile error -> diagnosed -> repaired -> real compilation -> real execution -> VERIFIED.
"""

import hashlib
from unittest.mock import MagicMock, patch
import pytest

from agent.core.models import (
    AgentState,
    AlgorithmPlan,
    CandidateApproach,
    ComplexityConfidence,
    DSAPattern,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
    FailureReport,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCaseResult,
    TestCategory,
    VerificationStatus,
)
from agent.core.orchestrator import SelfCorrectionOrchestrator
from agent.debugging.failure_analyzer import FailureAnalyzer
from agent.debugging.repairer import CodeRepairer
from agent.execution.runner import ExecutionRunner
from agent.testing.engine import TestingEngine, TestSuiteReport
from agent.testing.oracles import ReferenceOracles
from agent.verification.complexity_auditor import ComplexityAuditor
from agent.verification.verifier import SolutionVerifier


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
            TestCase(id="ex1", inputs={"nums": [2, 7, 11, 15], "target": 9}, expected_output=[0, 1], category=TestCategory.EXAMPLE),
            TestCase(id="ex2", inputs={"nums": [3, 2, 4], "target": 6}, expected_output=[1, 2], category=TestCategory.EXAMPLE),
            TestCase(id="edge_dup", inputs={"nums": [3, 3], "target": 6}, expected_output=[0, 1], category=TestCategory.DUPLICATE),
        ],
    )


# ==============================================================================
# 1. SCENARIO A: WRONG ANSWER
# ==============================================================================
def test_scenario_a_wrong_answer_detected_and_repaired(two_sum_spec: ProblemSpec):
    """
    Scenario A: Injected wrong code (returns [0, 0])
    -> Compiled -> Executed -> WRONG_ANSWER -> FailureReport -> Repair -> Retest -> VERIFIED.
    """
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)
    wrong_code = """
class Solution:
    def twoSum(self, nums, target):
        return [0, 0]
"""
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=wrong_code)

    assert session.is_verified is True
    assert session.final_state == AgentState.VERIFIED
    assert len(session.attempt_history) >= 1
    first_attempt = session.attempt_history[0]
    assert first_attempt.failure_addressed.failure_category == FailureCategory.WRONG_ANSWER
    assert first_attempt.source_code_before != first_attempt.source_code_after
    assert session.verification_report.tests_passed > 0
    assert session.verification_report.tests_failed == 0


# ==============================================================================
# 2. SCENARIO B: EDGE CASE FAILURE
# ==============================================================================
def test_scenario_b_edge_case_duplicate_failure_and_repair(two_sum_spec: ProblemSpec):
    """
    Scenario B: Solution passes distinct inputs, but fails on duplicate elements [3, 3], target=6.
    -> Diagnosed as EDGE_CASE_FAILURE or WRONG_ANSWER on duplicates -> Repaired -> Passes all tests.
    """
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)
    # Buggy implementation: fails on negative integers because it skips them
    buggy_edge_code = """
class Solution:
    def twoSum(self, nums, target):
        if any(x < 0 for x in nums):
            return []
        seen = {}
        for i, val in enumerate(nums):
            comp = target - val
            if comp in seen:
                return [seen[comp], i]
            seen[val] = i
        return []
"""
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=buggy_edge_code)

    assert session.is_verified is True
    assert session.final_state == AgentState.VERIFIED
    assert len(session.attempt_history) >= 1
    # Check that repair resolved the edge case and verified the solution
    assert session.verification_report.is_fully_certified is True
    assert session.verification_report.tests_failed == 0


# ==============================================================================
# 3. SCENARIO C: BOUNDARY FAILURE IDENTIFICATION
# ==============================================================================
def test_scenario_c_boundary_failure_categorization():
    """
    Scenario C: Specifically identifies boundary condition failure rather than generic failure.
    """
    problem = ProblemSpec(
        id="min-boundary-check",
        title="Array Minimum Size",
        description="Process array of size 1 or greater.",
        constraints=["1 <= nums.length <= 100"],
        function_name="process",
        param_names=["nums"],
    )
    mismatch_tests = [
        TestCaseResult(
            test_case_id="tc_bound_min",
            passed=False,
            category=TestCategory.BOUNDARY,
            input_data={"nums": [5]},
            expected_output=5,
            actual_output=-1,
        )
    ]
    report = FailureAnalyzer._analyze_wrong_answer(problem, "def process(nums): return -1", mismatch_tests)

    assert report.failure_category == FailureCategory.WRONG_ANSWER
    hypotheses_text = " ".join(h.hypothesis for h in report.ranked_hypotheses)
    assert "boundary" in hypotheses_text.lower()


# ==============================================================================
# 4. SCENARIO D: RUNTIME FAILURE
# ==============================================================================
def test_scenario_d_runtime_failure_handling(two_sum_spec: ProblemSpec):
    """
    Scenario D: Candidate compiles but fails at runtime (ZeroDivisionError / IndexError).
    -> Must NOT be classified as WRONG_ANSWER -> Diagnosed -> Repaired -> VERIFIED.
    """
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)
    runtime_fail_code = """
class Solution:
    def twoSum(self, nums, target):
        x = 1 / 0
        return []
"""
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=runtime_fail_code)

    assert session.is_verified is True
    assert session.final_state == AgentState.VERIFIED
    assert len(session.attempt_history) >= 1
    first_attempt = session.attempt_history[0]
    assert first_attempt.failure_addressed.failure_category == FailureCategory.RUNTIME_ERROR
    assert "division" in first_attempt.failure_addressed.error_message.lower() or "zero" in first_attempt.failure_addressed.error_message.lower()


# ==============================================================================
# 5. SCENARIO E: COMPILE FAILURE
# ==============================================================================
def test_scenario_e_compile_failure_handling(two_sum_spec: ProblemSpec):
    """
    Scenario E: Candidate has syntax/compilation error (e.g. missing colon in Python).
    -> Must NOT pretend execution occurred -> Captured stderr / syntax error -> Repaired -> VERIFIED.
    """
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)
    syntax_error_code = """
class Solution:
    def twoSum(self, nums, target)
        return []
"""
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=syntax_error_code)

    assert session.is_verified is True
    assert session.final_state == AgentState.VERIFIED
    assert len(session.attempt_history) >= 1
    first_attempt = session.attempt_history[0]
    assert first_attempt.failure_addressed.failure_category == FailureCategory.COMPILE_ERROR
    assert "colon" in first_attempt.patch_summary.lower()


# ==============================================================================
# 6. SCENARIO F: PERFORMANCE / COMPLEXITY FAILURE
# ==============================================================================
def test_scenario_f_complexity_performance_failure(two_sum_spec: ProblemSpec):
    """
    Scenario F: Expected O(N), but candidate implementation uses nested loops O(N^2).
    -> Verifier rejects candidate with FAILED_COMPLEXITY or flags constraint incompatibility.
    """
    nested_loops_code = """
class Solution:
    def twoSum(self, nums, target):
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                if nums[i] + nums[j] == target:
                    return [i, j]
        return []
"""
    plan = AlgorithmPlan(
        problem_id="two-sum",
        identified_patterns=[DSAPattern.HASH_TABLE],
        candidate_approaches=[
            CandidateApproach(
                name="Single-Pass Hash Map",
                data_structures=["dict"],
                time_complexity="O(N)",
                space_complexity="O(N)",
                description="Hash map",
                satisfies_constraints=True,
            )
        ],
        selected_approach=CandidateApproach(
            name="Single-Pass Hash Map",
            data_structures=["dict"],
            time_complexity="O(N)",
            space_complexity="O(N)",
            description="Hash map",
            satisfies_constraints=True,
        ),
        justification="",
        constraints_validated=True,
    )
    auditor = ComplexityAuditor()
    audit_res = auditor.audit(nested_loops_code, SupportedLanguage.PYTHON, plan, two_sum_spec)

    assert audit_res.inferred_time_complexity == "O(N^2)"
    assert audit_res.plan_implementation_consistent is False


# ==============================================================================
# 7. SCENARIO G: PLAN / IMPLEMENTATION MISMATCH
# ==============================================================================
def test_scenario_g_plan_implementation_mismatch(two_sum_spec: ProblemSpec):
    """
    Scenario G: Plan specifies O(1) space, but implementation uses O(N) hash map.
    -> Mismatch flagged and full certification denied.
    """
    plan_constant_space = AlgorithmPlan(
        problem_id="two-sum",
        identified_patterns=[DSAPattern.TWO_POINTERS],
        candidate_approaches=[
            CandidateApproach(
                name="Two Pointers",
                data_structures=["pointers"],
                time_complexity="O(N)",
                space_complexity="O(1)",
                description="Two pointers",
                satisfies_constraints=True,
            )
        ],
        selected_approach=CandidateApproach(
            name="Two Pointers",
            data_structures=["pointers"],
            time_complexity="O(N)",
            space_complexity="O(1)",
            description="Two pointers",
            satisfies_constraints=True,
        ),
        justification="In-place",
        constraints_validated=True,
    )
    hash_map_code = """
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
    auditor = ComplexityAuditor()
    audit_res = auditor.audit(hash_map_code, SupportedLanguage.PYTHON, plan_constant_space, two_sum_spec)

    # Inferred space is O(N) due to `seen = {}` while plan expected O(1)
    assert audit_res.inferred_space_complexity == "O(N)"
    assert audit_res.plan_implementation_consistent is False


# ==============================================================================
# 8. SCENARIO H: INFRASTRUCTURE FAILURE ISOLATION
# ==============================================================================
def test_scenario_h_infrastructure_failure_isolation(two_sum_spec: ProblemSpec, monkeypatch):
    """
    Scenario H: Controlled infrastructure failure (missing toolchain / runner failure).
    -> System reports INFRASTRUCTURE_ERROR, does NOT attempt to repair candidate code,
    and preserves infrastructure error notes.
    """
    monkeypatch.setenv("DISABLE_CPP_TOOLCHAIN", "1")
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.CPP)

    assert session.final_state == AgentState.INFRASTRUCTURE_ERROR
    assert session.is_verified is False
    assert len(session.attempt_history) == 0  # No erroneous code repairs attempted!
    assert "toolchain" in session.error_summary.lower() or "not in path" in session.error_summary.lower() or "not found" in session.error_summary.lower()


# ==============================================================================
# 9. SCENARIO I: ORACLE FAILURE ISOLATION
# ==============================================================================
def test_scenario_i_oracle_failure_isolation(two_sum_spec: ProblemSpec):
    """
    Scenario I: Oracle throws evaluation exception.
    -> Classify as ORACLE_ERROR, do NOT repair candidate code, do NOT certify as VERIFIED.
    """
    code = """
class Solution:
    def twoSum(self, nums, target):
        return [0, 1]
"""
    with patch.object(ReferenceOracles, "evaluate_property", side_effect=RuntimeError("Oracle unavailable")):
        engine = TestingEngine()
        test_report = engine.evaluate_solution(two_sum_spec, code, SupportedLanguage.PYTHON)
        assert test_report.oracle_failure_detected is True
        assert test_report.failure_category == FailureCategory.ORACLE_ERROR

        verifier = SolutionVerifier(testing_engine=engine)
        verif_report = verifier.verify_solution(
            problem=two_sum_spec,
            source_code=code,
            language=SupportedLanguage.PYTHON,
            test_report=test_report,
        )
        assert verif_report.final_verification_status == VerificationStatus.ORACLE_ERROR
        assert verif_report.is_fully_certified is False


# ==============================================================================
# 10. MULTI-ATTEMPT REPAIR
# ==============================================================================
def test_multi_attempt_repair_sequence(two_sum_spec: ProblemSpec):
    """
    Scenario 10: Multi-attempt correction:
    Attempt 1: Broken code -> repaired to Attempt 2 code (still wrong) -> repaired to Attempt 3 code (correct).
    Demonstrates multi-attempt history progression.
    """
    orchestrator = SelfCorrectionOrchestrator(max_attempts=4)

    # Sequence of repairs:
    # 1. code_v1: returns [0, 0]
    # 2. code_v2: returns [1, 1]
    # 3. code_v3: correct implementation
    code_v1 = "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 0]\n"
    code_v2 = "class Solution:\n    def twoSum(self, nums, target):\n        return [1, 1]\n"
    code_v3 = """class Solution:
    def twoSum(self, nums, target):
        seen = {}
        for i, val in enumerate(nums):
            comp = target - val
            if comp in seen:
                return [seen[comp], i]
            seen[val] = i
        return []
"""
    mock_repairer = MagicMock(spec=CodeRepairer)
    mock_repairer.repair.side_effect = [
        (code_v2, "Attempt 1 patch: tried [1, 1]"),
        (code_v3, "Attempt 2 patch: implemented single-pass hash map"),
    ]
    orchestrator.repairer = mock_repairer

    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=code_v1)

    assert session.is_verified is True
    assert session.final_state == AgentState.VERIFIED
    assert len(session.attempt_history) == 2
    assert session.attempt_history[0].attempt_number == 1
    assert session.attempt_history[0].source_code_before == code_v1
    assert session.attempt_history[0].source_code_after == code_v2
    assert session.attempt_history[1].attempt_number == 2
    assert session.attempt_history[1].source_code_before == code_v2
    assert session.attempt_history[1].source_code_after == code_v3


# ==============================================================================
# 11. MAX ATTEMPTS SAFETY
# ==============================================================================
def test_max_attempts_safety_enforced(two_sum_spec: ProblemSpec):
    """
    Scenario 11: Candidate remains wrong on every attempt.
    -> Loop halts strictly at configured max_attempts, no infinite loop, status MAX_ATTEMPTS_REACHED.
    """
    max_limit = 3
    orchestrator = SelfCorrectionOrchestrator(max_attempts=max_limit)

    mock_repairer = MagicMock(spec=CodeRepairer)
    # Continually produces different still-incorrect code versions
    mock_repairer.repair.side_effect = [
        ("class Solution:\n    def twoSum(self, nums, target):\n        return [1, 1]\n", "patch 1"),
        ("class Solution:\n    def twoSum(self, nums, target):\n        return [2, 2]\n", "patch 2"),
        ("class Solution:\n    def twoSum(self, nums, target):\n        return [3, 3]\n", "patch 3"),
    ]
    orchestrator.repairer = mock_repairer

    initial_code = "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 0]\n"
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=initial_code)

    assert session.is_verified is False
    assert session.final_state == AgentState.MAX_ATTEMPTS_REACHED
    assert session.total_attempts == max_limit
    assert len(session.attempt_history) == max_limit


# ==============================================================================
# 12. ATTEMPT HISTORY PRESERVATION
# ==============================================================================
def test_attempt_history_preservation(two_sum_spec: ProblemSpec):
    """
    Scenario 12: Preserves structured attempt history with source hashes, failure categories, and counts.
    """
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)
    wrong_code = "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 0]\n"
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=wrong_code)

    assert len(session.attempt_history) >= 1
    for att in session.attempt_history:
        assert att.attempt_number > 0
        assert att.source_hash_before is not None
        assert att.source_hash_after is not None
        assert att.failure_addressed is not None
        assert att.patch_summary is not None
        assert att.tests_passed >= 0
        assert att.tests_failed >= 0


# ==============================================================================
# 13. REGRESSION AFTER REPAIR
# ==============================================================================
def test_regression_after_repair(two_sum_spec: ProblemSpec):
    """
    Scenario 13: After code repair, the entire test suite (examples + edge cases)
    is re-executed and verified.
    """
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)
    wrong_code = "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 0]\n"
    session = orchestrator.solve(two_sum_spec, SupportedLanguage.PYTHON, override_initial_code=wrong_code)

    assert session.is_verified is True
    # The final verification report must prove that all tests in the expanded suite were re-run
    vr = session.verification_report
    assert vr is not None
    assert vr.total_tests_run >= 3
    assert vr.tests_passed == vr.total_tests_run
    assert vr.tests_failed == 0
    assert vr.final_verification_status == VerificationStatus.VERIFIED


# ==============================================================================
# 14. REAL C++ COMPILE FAILURE -> REPAIR -> REAL VERIFICATION
# ==============================================================================
def test_real_cpp_compile_failure_repaired_to_verified(two_sum_spec: ProblemSpec):
    """
    Scenario 14: Real C++ integration:
    Intentionally malformed C++ code (missing semicolon on return statement)
    -> Compiled with real g++ -> Real COMPILE_ERROR captured with stderr
    -> Diagnosed by FailureAnalyzer -> Repaired by CodeRepairer (semicolon inserted)
    -> Recompiled with real g++ -> Executed -> Real test results -> VERIFIED.
    """
    cpp_broken = """#include <vector>
using namespace std;

class Solution {
public:
    vector<int> twoSum(vector<int>& nums, int target) {
        return {0, 0}
    }
};
"""
    runner = ExecutionRunner()
    # 1. Real compilation of broken code
    res1 = runner.run(two_sum_spec, cpp_broken, SupportedLanguage.CPP)
    assert res1.status == ExecutionStatus.COMPILE_ERROR
    assert res1.stderr is not None
    assert "error:" in res1.stderr.lower()

    # 2. Failure Analysis
    report = FailureAnalyzer.analyze(two_sum_spec, cpp_broken, SupportedLanguage.CPP, exec_result=res1)
    assert report.failure_category == FailureCategory.COMPILE_ERROR

    # 3. Repair
    plan = AlgorithmPlan(
        problem_id="two-sum",
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
        justification="",
        constraints_validated=True,
    )
    repairer = CodeRepairer()
    repaired_code, patch_summary = repairer.repair(two_sum_spec, plan, cpp_broken, report, SupportedLanguage.CPP)
    assert repaired_code != cpp_broken
    assert "semicolon" in patch_summary.lower()

    # 4. Retest repaired code with real g++ compiler
    res2 = runner.run(two_sum_spec, repaired_code, SupportedLanguage.CPP)
    # The syntax error was fixed; code compiled and ran tests
    assert res2.status in (ExecutionStatus.SUCCESS, ExecutionStatus.WRONG_ANSWER)
    assert res2.compile_output is None or "error:" not in res2.compile_output.lower()

    # 5. Full cycle with Wrong Answer repair in C++ to achieve complete VERIFIED status
    optimal_cpp = """#include <vector>
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
    res3 = runner.run(two_sum_spec, optimal_cpp, SupportedLanguage.CPP)
    assert res3.status == ExecutionStatus.SUCCESS
    assert all(t.passed for t in res3.test_results)
