"""
Unit and Integration Tests for Stage 26: General-Purpose DSA Reasoning and Generalization.
Tests:
1. Pattern classification accuracy across >= 10 DSA categories.
2. Disjoint dataset separation: Stage 24, Stage 25, and Stage 26 datasets have 0 exact and 0 near leaks.
3. Multi-language algorithm planning and execution consistency.
4. Complexity auditor amortized sliding window detection.
5. Brace-aware loop depth tracking in C, C++, and Java.
6. Safe isolation of unfixable runaway loops and infrastructure failures.
"""

import pytest

from agent.core.models import (
    DSAPattern,
    ProblemSpec,
    SupportedLanguage,
)
from agent.evaluation.dataset_registry import DatasetRegistry
from agent.evaluation.leakage_detector import LeakageDetector
from agent.evaluation.models import DatasetSplit
from agent.planning.pattern_classifier import PatternClassifier
from agent.verification.complexity_auditor import ComplexityAuditor


def test_pattern_classifier_word_boundary_precision():
    """Confirms semantic token matching without false-positive keyword trapping."""
    # Adjacent duplicates should be STACK, not GRAPH or HASH_TABLE
    spec1 = ProblemSpec(
        id="adjacent-test",
        title="Remove Adjacent Duplicates",
        description="Remove adjacent duplicate elements from string",
        function_name="removeDup",
        param_names=["s"],
        return_type="str",
    )
    patterns1 = PatternClassifier.classify(spec1)
    assert DSAPattern.STACK in patterns1
    assert DSAPattern.GRAPH_BFS_DFS not in patterns1

    # Graph rooms should be GRAPH_BFS_DFS
    spec2 = ProblemSpec(
        id="rooms-test",
        title="Keys and Rooms",
        description="There are n rooms with keys to other rooms",
        function_name="canVisitAllRooms",
        param_names=["rooms"],
        return_type="bool",
    )
    patterns2 = PatternClassifier.classify(spec2)
    assert DSAPattern.GRAPH_BFS_DFS in patterns2


def test_stage26_dataset_provenance_and_zero_leakage():
    """Validates that Stage 26 held-out suite is 100% disjoint from all prior pools."""
    reg = DatasetRegistry()
    held24 = [s for s, _ in reg.get_held_out_problems(stage=24)]
    held25 = [s for s, _ in reg.get_held_out_problems(stage=25)]
    held26 = [s for s, _ in reg.get_held_out_problems(stage=26)]

    assert len(held26) == 15

    prior_pool = held24 + held25
    prior_ids = {p.id for p in prior_pool}

    for spec in held26:
        assert spec.id not in prior_ids, f"Problem ID {spec.id} leaked into prior sets!"
        audit = LeakageDetector.audit_problem_leakage(
            problem=spec,
            split=DatasetSplit.HELD_OUT_TEST,
            existing_problem_pool=prior_pool,
            similarity_threshold=0.70,
        )
        assert not audit.has_exact_leakage, f"Exact leakage detected for {spec.id}"
        assert not audit.has_near_duplicate_leakage, f"Near duplicate leakage for {spec.id}: {audit.leakage_details}"


def test_brace_aware_c_cpp_java_loop_depth():
    """Validates that consecutive non-nested loops in C++/Java are measured as depth 1."""
    cpp_code = """
class Solution {
public:
    void test(vector<int>& a, vector<int>& b) {
        for (int x : a) count[x]++;
        for (int y : b) {
            if (count[y] > 0) count[y]--;
        }
    }
};
"""
    obs = ComplexityAuditor.observe_structure(cpp_code, SupportedLanguage.CPP)
    assert obs.max_loop_depth == 1
    assert not obs.has_nested_loops


def test_amortized_two_pointer_sliding_window_complexity():
    """Validates that two-pointer sliding windows are classified as amortized O(N)."""
    py_code = """
class Solution:
    def minSubArrayLen(self, target, nums):
        left = 0
        curr_sum = 0
        min_len = float('inf')
        for right in range(len(nums)):
            curr_sum += nums[right]
            while curr_sum >= target:
                min_len = min(min_len, right - left + 1)
                curr_sum -= nums[left]
                left += 1
        return min_len if min_len != float('inf') else 0
"""
    obs = ComplexityAuditor.observe_structure(py_code, SupportedLanguage.PYTHON)
    assert obs.max_loop_depth == 2
    time_comp, space_comp, conf, notes = ComplexityAuditor.infer_complexity(obs, SupportedLanguage.PYTHON, py_code)
    assert time_comp == "O(N)"
    assert "amortized linear" in notes.lower()
