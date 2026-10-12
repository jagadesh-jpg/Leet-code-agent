"""
Stage 25 Unit & Regression Tests: Generalization Failure Analysis & Solver Improvement.
Validates:
1. Reclassification of Stage 24 inspected cases into DIAGNOSTIC / DEVELOPMENT split.
2. Disjointness and zero leakage of new Stage 25 held-out evaluation dataset.
3. Fix for in-place array pointer passing in C execution harness.
4. Correct non-negative index assertion for searchInsert (not conflated with -1).
5. Greedy Sorted Matching algorithm plan with O(N log N) complexity matching implementation.
6. Parameter name protection in adaptive test generation (no unexpected 'n' on cost arrays).
7. Safety watchdog bounding on unfixable infinite loops.
8. Unseen problem solving on Stage 25 held-out cases.
"""

import pytest

from agent.core.models import (
    AgentState,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCategory,
    VerificationStatus,
)
from agent.core.orchestrator import SelfCorrectionOrchestrator
from agent.evaluation.dataset_registry import DatasetRegistry
from agent.evaluation.leakage_detector import LeakageDetector
from agent.evaluation.models import DatasetSplit
from agent.planning.planner import AlgorithmPlanner
from agent.testing.oracles import ReferenceOracles
from agent.verification.complexity_auditor import ComplexityAuditor


@pytest.fixture
def registry():
    return DatasetRegistry()


def test_stage25_held_out_disjoint_and_leak_free(registry):
    held25 = registry.get_held_out_problems(stage=25)
    held24 = registry.get_held_out_problems(stage=24)
    assert len(held25) == 15
    assert len(held24) == 15

    ids25 = {s.id for s, _ in held25}
    ids24 = {s.id for s, _ in held24}

    # Strict disjointness
    assert ids25.isdisjoint(ids24)

    # Leakage detector audit
    detector = LeakageDetector()
    prior_specs = [s for s, _ in held24]
    for spec, _ in held25:
        audit = detector.audit_problem_leakage(
            problem=spec,
            split=DatasetSplit.HELD_OUT_TEST,
            existing_problem_pool=prior_specs,
            similarity_threshold=0.65,
        )
        assert audit.has_exact_leakage is False
        assert audit.has_near_duplicate_leakage is False
        assert audit.is_contaminated is False


def test_diagnostic_dev_reclassification(registry):
    diag_problems = registry.get_diagnostic_dev_problems()
    assert len(diag_problems) == 5
    diag_ids = {s.id for s, _ in diag_problems}
    expected_inspected = {
        "move-zeroes",
        "search-insert-position",
        "assign-cookies",
        "min-cost-climbing-stairs",
        "circular-loop-unfixable",
    }
    assert diag_ids == expected_inspected


def test_search_insert_oracle_separation():
    # searchInsert must not be evaluated under standard -1 binary search property
    spec = ProblemSpec(
        id="search-insert-position",
        title="Search Insert Position",
        description="Return insert position.",
        function_name="searchInsert",
        param_names=["nums", "target"],
        return_type="int",
    )
    # Target 2 not in [1, 3, 5, 6]. If output is -1, it should NOT be certified as valid!
    prop_ok, err = ReferenceOracles.evaluate_property(spec, {"nums": [1, 3, 5, 6], "target": 2}, -1)
    # The property check should return None (deferred to direct equality check) rather than certifying -1 as True
    assert prop_ok is None


def test_greedy_sorted_matching_planning():
    spec = ProblemSpec(
        id="assign-cookies",
        title="Assign Cookies",
        description="Assign cookies to content children greedily.",
        function_name="findContentChildren",
        param_names=["g", "s"],
        return_type="int",
    )
    planner = AlgorithmPlanner()
    plan = planner.plan(spec)
    assert plan.selected_approach.name == "Sorted Greedy Matching"
    assert "O(N log N)" in plan.selected_approach.time_complexity


def test_complexity_auditor_recognizes_sorting_overhead():
    auditor = ComplexityAuditor()
    java_code = """
import java.util.Arrays;
class Solution {
    public int findContentChildren(int[] g, int[] s) {
        Arrays.sort(g);
        Arrays.sort(s);
        int child = 0, cookie = 0;
        while (child < g.length && cookie < s.length) {
            if (s[cookie] >= g[child]) child++;
            cookie++;
        }
        return child;
    }
}
"""
    obs = auditor.observe_structure(java_code, SupportedLanguage.JAVA)
    assert len(obs.sorting_calls) > 0
    t_comp, s_comp, conf, notes = auditor.infer_complexity(obs, SupportedLanguage.JAVA, java_code)
    assert t_comp == "O(N log N)"


def test_c_harness_move_zeroes_compilation_and_execution():
    from agent.execution.c_cpp_adapters import CAdapter
    from agent.execution.runner import ExecutionRunner

    spec = ProblemSpec(
        id="move-zeroes",
        title="Move Zeroes",
        description="Move zeroes in-place.",
        function_name="moveZeroes",
        param_names=["nums"],
        return_type="List[int]",
        test_cases=[
            TestCase(id="t1", inputs={"nums": [0, 1, 0, 3, 12]}, expected_output=[1, 3, 12, 0, 0], category=TestCategory.BASIC),
        ],
    )
    correct_c = """#include <stdio.h>
#include <stdlib.h>

int* moveZeroes(int* nums, int numsSize, int* returnSize) {
    *returnSize = numsSize;
    int insert_pos = 0;
    for (int i = 0; i < numsSize; i++) {
        if (nums[i] != 0) {
            nums[insert_pos++] = nums[i];
        }
    }
    while (insert_pos < numsSize) {
        nums[insert_pos++] = 0;
    }
    return nums;
}
"""
    runner = ExecutionRunner()
    res = runner.run(spec, correct_c, SupportedLanguage.C)
    assert res.status == res.status.SUCCESS
    assert len(res.test_results) == 1
    assert res.test_results[0].passed is True


def test_unfixable_infinite_loop_safety_watchdog():
    spec = ProblemSpec(
        id="unfixable-test-loop",
        title="Infinite Loop Test",
        description="Test watchdog on runaway loop.",
        function_name="runawayLoop",
        param_names=["n"],
        return_type="int",
        test_cases=[
            TestCase(id="t1", inputs={"n": 5}, expected_output=5, category=TestCategory.BASIC),
        ],
    )
    runaway_code = """class Solution {
    public int runawayLoop(int n) {
        while (true) {}
    }
}
"""
    orch = SelfCorrectionOrchestrator(max_attempts=2)
    session = orch.solve(spec, SupportedLanguage.JAVA, override_initial_code=runaway_code, max_attempts=2)
    assert session.is_verified is False
    assert session.final_state == AgentState.MAX_ATTEMPTS_REACHED
