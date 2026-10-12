"""
Tests for Algorithm Planning & DSA Pattern Classification (Stage 4).
Verifies:
1. Brute force rejection: A problem with N <= 10^5 rejects O(N^2) and selects O(N).
2. Multiple valid candidates: Compares candidates and records rejection reasons.
3. Constraint elimination: A constraint (e.g. 10^5) clearly eliminates incompatible candidate.
4. Missing/ambiguous constraints: Planner marks constraints_uncertain=True without guessing.
5. Diverse DSA pattern classifications (Stack, Binary Search, Sliding Window, Trees, Graphs).
"""

from agent.core.models import (
    AlgorithmPlan,
    DSAPattern,
    ProblemSpec,
    TestCase,
)
from agent.planning.constraint_evaluator import ConstraintEvaluator
from agent.planning.pattern_classifier import PatternClassifier
from agent.planning.planner import AlgorithmPlanner


def test_1_brute_force_rejected_for_large_n():
    """
    Verifies that for N = 10^5 (Two Sum), O(N^2) brute force is rejected
    with an explicit reason, and O(N) Hash Map is selected.
    """
    problem = ProblemSpec(
        id="two-sum",
        title="Two Sum",
        description="Find two numbers in array that add up to target.",
        constraints=["2 <= nums.length <= 10^5", "-10^9 <= nums[i] <= 10^9"],
        function_name="twoSum",
        param_names=["nums", "target"],
        return_type="List[int]",
        test_cases=[
            TestCase(id="1", inputs={"nums": [2, 7, 11, 15], "target": 9}, expected_output=[0, 1]),
        ],
    )

    planner = AlgorithmPlanner()
    plan: AlgorithmPlan = planner.plan(problem)

    assert DSAPattern.HASH_TABLE in plan.identified_patterns
    assert len(plan.candidate_approaches) >= 2

    # Verify brute force candidate was rejected
    bf_cand = next(c for c in plan.candidate_approaches if c.time_complexity == "O(N^2)")
    assert bf_cand.satisfies_constraints is False
    assert "exceed" in bf_cand.rejection_reason.lower()

    # Verify O(N) candidate was selected
    assert plan.selected_approach.time_complexity == "O(N)"
    assert plan.selected_approach.satisfies_constraints is True
    assert plan.constraints_validated is True
    assert plan.constraints_uncertain is False


def test_2_multiple_valid_approaches_comparison():
    """
    Verifies that when multiple approaches are evaluated,
    both are recorded with time/space complexities and justification is provided.
    """
    problem = ProblemSpec(
        id="binary-search",
        title="Binary Search",
        description="Given a sorted array of integers nums and an integer target, search target in nums.",
        constraints=["1 <= nums.length <= 10^4"],
        function_name="search",
        param_names=["nums", "target"],
        return_type="int",
        test_cases=[
            TestCase(id="1", inputs={"nums": [-1, 0, 3, 5, 9, 12], "target": 9}, expected_output=4),
        ],
    )

    planner = AlgorithmPlanner()
    plan = planner.plan(problem)

    assert DSAPattern.BINARY_SEARCH in plan.identified_patterns
    assert len(plan.candidate_approaches) == 2

    # Linear scan and Binary search are both valid within 10^4, but O(log N) is optimal
    assert plan.selected_approach.time_complexity == "O(log N)"
    assert "selected" in plan.justification.lower()


def test_3_missing_or_ambiguous_constraints_not_fabricated():
    """
    Verifies that if constraints are missing or ambiguous,
    the planner sets constraints_uncertain=True and records explanatory notes.
    """
    problem = ProblemSpec(
        id="unknown-problem",
        title="Vague Problem",
        description="Compute answer without stated size constraints.",
        constraints=[],  # No bounds given
        function_name="solve",
        param_names=["data"],
        return_type="int",
        is_ambiguous=True,
        ambiguity_notes=["Size constraint not provided in problem statement."],
    )

    planner = AlgorithmPlanner()
    plan = planner.plan(problem)

    assert plan.constraints_uncertain is True
    assert plan.constraints_validated is False
    assert any("ambiguity" in note.lower() or "not explicitly" in note.lower() for note in plan.assumptions_and_notes)


def test_4_diverse_dsa_pattern_classification():
    """
    Verifies pattern classification across various DSA domains:
    Stack, Tree, Graph, Sliding Window, Intervals.
    """
    # 1. Stack / Valid Parentheses
    p_stack = ProblemSpec(
        id="valid-parentheses",
        title="Valid Parentheses",
        description="Determine if string of brackets '()' is valid using stack.",
        constraints=["1 <= s.length <= 10^4"],
        function_name="isValid",
        param_names=["s"],
        return_type="bool",
    )
    assert DSAPattern.STACK in PatternClassifier.classify(p_stack)

    # 2. Binary Tree
    p_tree = ProblemSpec(
        id="invert-tree",
        title="Invert Binary Tree",
        description="Given root of binary tree, invert the tree and return root.",
        constraints=["Number of nodes in tree is in range [0, 100]"],
        function_name="invertTree",
        param_names=["root"],
        return_type="TreeNode",
    )
    assert DSAPattern.BINARY_TREE in PatternClassifier.classify(p_tree)

    # 3. Shortest Path in Graph
    p_graph = ProblemSpec(
        id="network-delay-time",
        title="Network Delay Time",
        description="Find shortest path time for all nodes in weighted graph using dijkstra.",
        constraints=["1 <= k <= n <= 100"],
        function_name="networkDelayTime",
        param_names=["times", "n", "k"],
        return_type="int",
    )
    assert DSAPattern.SHORTEST_PATH in PatternClassifier.classify(p_graph)

    # 4. Intervals
    p_intervals = ProblemSpec(
        id="merge-intervals",
        title="Merge Intervals",
        description="Merge overlapping intervals in a collection.",
        constraints=["1 <= intervals.length <= 10^4"],
        function_name="merge",
        param_names=["intervals"],
        return_type="List[List[int]]",
    )
    assert DSAPattern.INTERVALS in PatternClassifier.classify(p_intervals)


def test_5_constraint_evaluator_operation_limits():
    """Verifies numeric operation count estimation and threshold enforcement."""
    # N = 10^5: O(N) is 10^5 (< 10^8) -> Pass
    sat_linear, _ = ConstraintEvaluator.evaluate_complexity("O(N)", 100000)
    assert sat_linear is True

    # N = 10^5: O(N^2) is 10^10 (> 10^8) -> Fail
    sat_quad, reason = ConstraintEvaluator.evaluate_complexity("O(N^2)", 100000)
    assert sat_quad is False
    assert "exceed" in reason.lower()

    # N = 20: O(2^N) is ~10^6 (< 10^8) -> Pass
    sat_exp_small, _ = ConstraintEvaluator.evaluate_complexity("O(2^N)", 20)
    assert sat_exp_small is True

    # N = 50: O(2^N) is ~10^15 (> 10^8) -> Fail
    sat_exp_large, _ = ConstraintEvaluator.evaluate_complexity("O(2^N)", 50)
    assert sat_exp_large is False
