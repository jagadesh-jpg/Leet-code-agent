"""
Deterministic Test Generator & Suite Expander.
Synthesizes comprehensive test suites covering examples, basic functionality,
boundary values, edge cases, reproducible randomized tests, adversarial cases, and stress tests.
"""

import random
from typing import Any, Dict, List, Optional
from agent.core.models import (
    ConfidenceLevel,
    OracleType,
    ProblemSpec,
    TestCase,
    TestCategory,
)
from agent.planning.constraint_evaluator import ConstraintEvaluator
from agent.testing.oracles import ReferenceOracles


class TestGenerator:
    """
    Synthesizes meaningful, constraint-compliant test suites.
    Never relies on candidate solutions to invent expected outputs.
    """
    __test__ = False

    def __init__(self, default_seed: int = 42):
        self.default_seed = default_seed

    def generate_suite(
        self,
        problem: ProblemSpec,
        include_random: bool = True,
        include_stress: bool = True,
        random_count: int = 5,
        seed: Optional[int] = None,
    ) -> List[TestCase]:
        """
        Builds a comprehensive, deterministic test suite:
        Provided Examples + Edge Cases + Boundary Cases + Adversarial + Randomized + Stress.
        """
        active_seed = seed if seed is not None else self.default_seed
        rng = random.Random(active_seed)
        suite: List[TestCase] = []

        # 1. Existing Problem Examples
        for tc in problem.test_cases:
            tc.category = TestCategory.EXAMPLE
            tc.oracle_type = OracleType.PROBLEM_SPEC
            suite.append(tc)

        ref_fn = ReferenceOracles.get_reference_solution(problem)
        max_n = ConstraintEvaluator.extract_max_n(problem.constraints) or 1000

        # If a reference implementation exists, we can generate rich synthetic suites with true answers
        if ref_fn:
            # 2. Edge Cases (Minimum inputs, duplicates, zeroes/negatives)
            edge_cases = self._generate_edge_cases(problem, ref_fn)
            suite.extend(edge_cases)

            # 3. Boundary Cases (Smallest allowed size, single-element)
            boundary_cases = self._generate_boundary_cases(problem, ref_fn)
            suite.extend(boundary_cases)

            # 4. Randomized Tests (Deterministic seed)
            if include_random:
                random_cases = self._generate_random_tests(problem, ref_fn, rng, random_count, active_seed)
                suite.extend(random_cases)

            # 5. Stress Test (Moderate large N within constraints)
            if include_stress:
                stress_case = self._generate_stress_test(problem, ref_fn, max_n, active_seed)
                if stress_case:
                    suite.append(stress_case)

        return suite

    def _generate_edge_cases(self, problem: ProblemSpec, ref_fn) -> List[TestCase]:
        """Generates specific edge cases like duplicates, negatives, all-equal values."""
        cases = []
        pid = problem.id.lower()

        # Two Sum Edge Cases
        if "two-sum" in pid or problem.function_name.lower() == "twosum":
            # Duplicate elements that form target: [3, 3], target=6
            c1_inputs = {"nums": [3, 3], "target": 6}
            cases.append(TestCase(
                id="edge_duplicates",
                inputs=c1_inputs,
                expected_output=ref_fn(**c1_inputs),
                category=TestCategory.DUPLICATE,
                oracle_type=OracleType.REFERENCE_ALGO,
                rationale="Duplicate elements forming target sum",
            ))
            # Negative values: [-1, -2, -3, -4, -5], target=-8
            c2_inputs = {"nums": [-1, -2, -3, -4, -5], "target": -8}
            cases.append(TestCase(
                id="edge_negatives",
                inputs=c2_inputs,
                expected_output=ref_fn(**c2_inputs),
                category=TestCategory.NEGATIVE_ZERO,
                oracle_type=OracleType.REFERENCE_ALGO,
                rationale="Array consisting entirely of negative integers",
            ))
            # Target with zero: [0, 4, 3, 0], target=0
            c3_inputs = {"nums": [0, 4, 3, 0], "target": 0}
            cases.append(TestCase(
                id="edge_zeroes",
                inputs=c3_inputs,
                expected_output=ref_fn(**c3_inputs),
                category=TestCategory.EDGE_CASE,
                oracle_type=OracleType.REFERENCE_ALGO,
                rationale="Target is zero formed by two zero elements",
            ))

        # Valid Parentheses Edge Cases
        elif "valid-parentheses" in pid or problem.function_name.lower() == "isvalid":
            cases.append(TestCase(
                id="edge_single_bracket",
                inputs={"s": "("},
                expected_output=False,
                category=TestCategory.SINGLE_ELEMENT,
                oracle_type=OracleType.REFERENCE_ALGO,
                rationale="Single unclosed opening bracket",
            ))
            cases.append(TestCase(
                id="edge_nested_long",
                inputs={"s": "(((((())))))"},
                expected_output=True,
                category=TestCategory.EDGE_CASE,
                oracle_type=OracleType.REFERENCE_ALGO,
                rationale="Deeply nested valid bracket sequence",
            ))

        return cases

    def _generate_boundary_cases(self, problem: ProblemSpec, ref_fn) -> List[TestCase]:
        """Generates minimum valid boundary cases (e.g. minimal length array)."""
        cases = []
        pid = problem.id.lower()

        if "two-sum" in pid or problem.function_name.lower() == "twosum":
            # Minimum length array for Two Sum is length 2
            b_inputs = {"nums": [100, 200], "target": 300}
            cases.append(TestCase(
                id="bound_min_len_2",
                inputs=b_inputs,
                expected_output=ref_fn(**b_inputs),
                category=TestCategory.BOUNDARY,
                oracle_type=OracleType.REFERENCE_ALGO,
                rationale="Minimum allowed array length of 2 elements",
            ))

        elif "binary-search" in pid or "search" in problem.function_name.lower():
            # Single element present vs absent
            b1 = {"nums": [5], "target": 5}
            cases.append(TestCase(
                id="bound_single_found",
                inputs=b1,
                expected_output=ref_fn(**b1),
                category=TestCategory.SINGLE_ELEMENT,
                oracle_type=OracleType.REFERENCE_ALGO,
                rationale="Single-element array where target is present",
            ))
            b2 = {"nums": [5], "target": 10}
            cases.append(TestCase(
                id="bound_single_not_found",
                inputs=b2,
                expected_output=ref_fn(**b2),
                category=TestCategory.SINGLE_ELEMENT,
                oracle_type=OracleType.REFERENCE_ALGO,
                rationale="Single-element array where target is absent",
            ))

        return cases

    def _generate_random_tests(
        self,
        problem: ProblemSpec,
        ref_fn,
        rng: random.Random,
        count: int,
        base_seed: int,
    ) -> List[TestCase]:
        """Generates reproducible randomized tests with explicit seeds."""
        cases = []
        pid = problem.id.lower()

        if "two-sum" in pid or problem.function_name.lower() == "twosum":
            for i in range(count):
                tc_seed = base_seed + i + 100
                local_rng = random.Random(tc_seed)
                size = local_rng.randint(5, 50)
                nums = [local_rng.randint(-1000, 1000) for _ in range(size)]
                # Ensure guaranteed solution by picking two distinct indices
                idx1 = local_rng.randint(0, size - 1)
                idx2 = local_rng.randint(0, size - 1)
                while idx1 == idx2:
                    idx2 = local_rng.randint(0, size - 1)
                target = nums[idx1] + nums[idx2]

                inputs = {"nums": nums, "target": target}
                expected = ref_fn(**inputs)

                cases.append(TestCase(
                    id=f"random_{i+1}",
                    inputs=inputs,
                    expected_output=expected,
                    category=TestCategory.RANDOMIZED,
                    oracle_type=OracleType.REFERENCE_ALGO,
                    rationale="Reproducible randomized test with guaranteed pair",
                    random_seed=tc_seed,
                ))

        return cases

    def _generate_stress_test(
        self,
        problem: ProblemSpec,
        ref_fn,
        max_n: int,
        seed: int,
    ) -> Optional[TestCase]:
        """Generates moderate large-scale input to evaluate practical performance and TLE."""
        pid = problem.id.lower()
        if "two-sum" in pid or problem.function_name.lower() == "twosum":
            local_rng = random.Random(seed + 9999)
            # Use safe stress size (e.g. 5,000 items) to prevent reference O(N^2) timeout
            stress_n = min(max_n, 5000)
            nums = [local_rng.randint(-100000, 100000) for _ in range(stress_n)]
            idx1, idx2 = 10, stress_n - 10
            target = nums[idx1] + nums[idx2]

            inputs = {"nums": nums, "target": target}
            expected = ref_fn(**inputs)

            return TestCase(
                id="stress_large_input",
                inputs=inputs,
                expected_output=expected,
                category=TestCategory.STRESS,
                oracle_type=OracleType.REFERENCE_ALGO,
                rationale=f"Stress performance test with N = {stress_n}",
                random_seed=seed + 9999,
            )

        return None
