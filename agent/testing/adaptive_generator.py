"""Intelligent, Constraint-Aware, Deduplicated Adaptive Test Generator for Stage 21.

Synthesizes targeted test cases driven by:
- Problem specifications & strict constraints
- TestRiskAnalysis & structural code signals
- Retrieved Stage 20 experience warnings
- Real observed test failures from execution rounds
- Independent reference oracles (no circular self-verification)

Enforces:
- Deterministic seeds for full reproducibility
- SHA-256 test input deduplication
- Strict constraint adherence
- Explicit structured engineering reasons (no ungrounded hallucinations)
"""

import hashlib
import json
import random
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from agent.core.models import (
    ConfidenceLevel,
    FailureCategory,
    OracleType,
    ProblemSpec,
    TestCase,
    TestCaseResult,
    TestCategory,
)
from agent.testing.oracles import ReferenceOracles
from agent.testing.risk_model import TestRiskAnalysis, TestRiskSignal


def compute_test_fingerprint(inputs: Dict[str, Any]) -> str:
    """Computes deterministic SHA-256 fingerprint for test input deduplication."""
    serialized = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


class AdaptiveGenerationResult(BaseModel):
    """Result of an adaptive test generation round."""
    round_number: int
    new_tests: List[TestCase] = Field(default_factory=list)
    deduplicated_count: int = 0
    signals_addressed: List[str] = Field(default_factory=list)
    generation_reasons: List[str] = Field(default_factory=list)
    budget_exhausted: bool = False


class AdaptiveTestGenerator:
    """
    Synthesizes targeted tests adaptively based on risk signals and failure evidence.
    Guarantees independent oracle execution and deterministic reproducibility.
    """

    def __init__(self, base_seed: int = 42):
        self.base_seed = base_seed

    def generate_targeted_tests(
        self,
        problem: ProblemSpec,
        risk_analysis: TestRiskAnalysis,
        existing_test_fingerprints: Set[str],
        round_number: int = 1,
        max_tests_to_generate: int = 5,
        seed: Optional[int] = None,
    ) -> AdaptiveGenerationResult:
        """
        Generates targeted tests driven by risk signals (boundaries, duplicates, extremes).
        """
        active_seed = (seed if seed is not None else self.base_seed) + (round_number * 1000)
        rng = random.Random(active_seed)
        ref_fn = ReferenceOracles.get_reference_solution(problem)

        new_tests: List[TestCase] = []
        addressed: List[str] = []
        reasons: List[str] = []
        dedup_count = 0

        pid = problem.id.lower()
        fn = problem.function_name.lower()

        # Helper to safely evaluate and add test case
        def try_add(tc_id: str, inputs: Dict[str, Any], cat: TestCategory, rationale: str, sig_id: str):
            nonlocal dedup_count
            if len(new_tests) >= max_tests_to_generate:
                return
            fp = compute_test_fingerprint(inputs)
            if fp in existing_test_fingerprints:
                dedup_count += 1
                return

            if ref_fn is None:
                # Oracle unavailable: mark explicitly as UNAVAILABLE or skip
                return

            try:
                expected = ref_fn(**inputs)
            except Exception:
                return

            existing_test_fingerprints.add(fp)
            new_tests.append(TestCase(
                id=tc_id,
                inputs=inputs,
                expected_output=expected,
                category=cat,
                oracle_type=OracleType.TRUSTED_REFERENCE,
                rationale=rationale,
                random_seed=active_seed,
            ))
            addressed.append(sig_id)
            reasons.append(rationale)

        # 1. Target signals
        for sig in risk_analysis.signals:
            if len(new_tests) >= max_tests_to_generate:
                break

            # TWO SUM
            if "two-sum" in pid or fn == "twosum":
                if sig.risk_category == "DUPLICATES":
                    try_add(
                        f"adapt_r{round_number}_dup_pair",
                        {"nums": [10, 20, 10, 40], "target": 20},
                        TestCategory.DUPLICATE,
                        "Targeted duplicate element validation: pair of identical numbers forming target sum",
                        sig.signal_id,
                    )
                elif sig.risk_category == "NEGATIVE_ZERO":
                    try_add(
                        f"adapt_r{round_number}_neg_zero",
                        {"nums": [-50, 0, 50, -10], "target": 0},
                        TestCategory.NEGATIVE_ZERO,
                        "Targeted zero/negative validation: positive and negative opposites summing to 0",
                        sig.signal_id,
                    )
                elif sig.risk_category == "BOUNDARY":
                    try_add(
                        f"adapt_r{round_number}_min_boundary",
                        {"nums": [1000000, -1000000], "target": 0},
                        TestCategory.BOUNDARY,
                        "Targeted boundary length 2 with extreme integer magnitude values",
                        sig.signal_id,
                    )

            # BINARY SEARCH
            elif "binary-search" in pid or "search" in fn:
                if sig.risk_category == "OFF_BY_ONE":
                    # First element, last element, midpoint boundary
                    try_add(
                        f"adapt_r{round_number}_bs_first",
                        {"nums": [2, 4, 6, 8, 10, 12, 14], "target": 2},
                        TestCategory.BOUNDARY,
                        "Targeted boundary check: target located at array index 0",
                        sig.signal_id,
                    )
                    try_add(
                        f"adapt_r{round_number}_bs_last",
                        {"nums": [2, 4, 6, 8, 10, 12, 14], "target": 14},
                        TestCategory.BOUNDARY,
                        "Targeted boundary check: target located at array index N-1",
                        sig.signal_id,
                    )
                elif sig.risk_category == "EMPTY_OR_SINGLE":
                    try_add(
                        f"adapt_r{round_number}_bs_single_absent",
                        {"nums": [42], "target": 99},
                        TestCategory.SINGLE_ELEMENT,
                        "Targeted boundary check: single element array where target is absent",
                        sig.signal_id,
                    )
                elif sig.risk_category == "BOUNDARY":
                    try_add(
                        f"adapt_r{round_number}_bs_outside_range",
                        {"nums": [10, 20, 30, 40], "target": 5},
                        TestCategory.ADVERSARIAL,
                        "Targeted boundary check: target smaller than smallest array element",
                        sig.signal_id,
                    )

            # VALID PARENTHESES
            elif "valid-parentheses" in pid or fn == "isvalid":
                if sig.risk_category == "EMPTY_OR_SINGLE":
                    try_add(
                        f"adapt_r{round_number}_stack_single_close",
                        {"s": "]"},
                        TestCategory.SINGLE_ELEMENT,
                        "Targeted single closing bracket causing immediate stack underflow",
                        sig.signal_id,
                    )
                    try_add(
                        f"adapt_r{round_number}_stack_unclosed_pair",
                        {"s": "(()"},
                        TestCategory.BOUNDARY,
                        "Targeted bracket sequence with leftover unclosed opening bracket",
                        sig.signal_id,
                    )
                elif sig.risk_category == "STRESS":
                    try_add(
                        f"adapt_r{round_number}_stack_deep_mixed",
                        {"s": "{[()()]}" * 5},
                        TestCategory.STRESS,
                        "Targeted alternating composite nested bracket sequence",
                        sig.signal_id,
                    )

            # MAXIMUM SUBARRAY
            elif "max-subarray" in pid or fn == "maxsubarray":
                try_add(
                    f"adapt_r{round_number}_all_negative",
                    {"nums": [-10, -5, -20, -1, -8]},
                    TestCategory.NEGATIVE_ZERO,
                    "Targeted all-negative array where maximum subarray is the least negative single element",
                    sig.signal_id,
                )
                try_add(
                    f"adapt_r{round_number}_single_neg",
                    {"nums": [-99]},
                    TestCategory.SINGLE_ELEMENT,
                    "Targeted boundary single negative element",
                    sig.signal_id,
                )

            # VALID ANAGRAM
            elif "valid-anagram" in pid or fn == "isanagram":
                try_add(
                    f"adapt_r{round_number}_diff_len",
                    {"s": "abc", "t": "ab"},
                    TestCategory.BOUNDARY,
                    "Targeted length mismatch boundary for anagram validation",
                    sig.signal_id,
                )
                try_add(
                    f"adapt_r{round_number}_same_char_diff_count",
                    {"s": "aab", "t": "abb"},
                    TestCategory.ADVERSARIAL,
                    "Targeted frequency mismatch with identical unique character set",
                    sig.signal_id,
                )

            # VALID PALINDROME
            elif "valid-palindrome" in pid or fn == "ispalindrome":
                try_add(
                    f"adapt_r{round_number}_punct_only",
                    {"s": ".,;!?"},
                    TestCategory.BOUNDARY,
                    "Targeted empty-after-stripping punctuation palindrome boundary",
                    sig.signal_id,
                )
                try_add(
                    f"adapt_r{round_number}_single_char",
                    {"s": "z"},
                    TestCategory.SINGLE_ELEMENT,
                    "Targeted single character alphanumeric palindrome boundary",
                    sig.signal_id,
                )

            # LONGEST SUBSTRING WITHOUT REPEATING CHARACTERS
            elif "longest-substring" in pid or fn == "lengthoflongestsubstring":
                try_add(
                    f"adapt_r{round_number}_all_same",
                    {"s": "bbbbbbb"},
                    TestCategory.ADVERSARIAL,
                    "Targeted all identical characters sliding window boundary (length 1)",
                    sig.signal_id,
                )
                try_add(
                    f"adapt_r{round_number}_all_unique",
                    {"s": "abcdefg"},
                    TestCategory.BOUNDARY,
                    "Targeted all unique characters sliding window boundary (length N)",
                    sig.signal_id,
                )

            # REVERSE LINKED LIST
            elif "reverse-linked-list" in pid or fn == "reverselist":
                try_add(
                    f"adapt_r{round_number}_rev_empty",
                    {"head": []},
                    TestCategory.BOUNDARY,
                    "Targeted empty list boundary for reverse list",
                    sig.signal_id,
                )
                try_add(
                    f"adapt_r{round_number}_rev_single",
                    {"head": [100]},
                    TestCategory.SINGLE_ELEMENT,
                    "Targeted single node boundary for reverse list",
                    sig.signal_id,
                )

            # MAXIMUM DEPTH OF BINARY TREE
            elif "maximum-depth" in pid or fn == "maxdepth":
                try_add(
                    f"adapt_r{round_number}_tree_empty",
                    {"nodes": []},
                    TestCategory.BOUNDARY,
                    "Targeted empty tree boundary with 0 depth",
                    sig.signal_id,
                )
                try_add(
                    f"adapt_r{round_number}_tree_single",
                    {"nodes": [1]},
                    TestCategory.SINGLE_ELEMENT,
                    "Targeted single root node with depth 1",
                    sig.signal_id,
                )

            # NUMBER OF ISLANDS
            elif "number-of-islands" in pid or fn == "numislands":
                try_add(
                    f"adapt_r{round_number}_all_water",
                    {"grid": [[0, 0], [0, 0]]},
                    TestCategory.BOUNDARY,
                    "Targeted all-water grid boundary (0 islands)",
                    sig.signal_id,
                )
                try_add(
                    f"adapt_r{round_number}_single_land",
                    {"grid": [[1]]},
                    TestCategory.SINGLE_ELEMENT,
                    "Targeted minimal 1x1 land grid boundary",
                    sig.signal_id,
                )

            # KTH LARGEST ELEMENT
            elif "kth-largest" in pid or fn == "findkthlargest":
                try_add(
                    f"adapt_r{round_number}_k_1",
                    {"nums": [5, 2, 8, 1, 9], "k": 1},
                    TestCategory.BOUNDARY,
                    "Targeted boundary k=1 (maximum element in array)",
                    sig.signal_id,
                )
                try_add(
                    f"adapt_r{round_number}_k_n",
                    {"nums": [5, 2, 8, 1, 9], "k": 5},
                    TestCategory.BOUNDARY,
                    "Targeted boundary k=N (minimum element in array)",
                    sig.signal_id,
                )

            # SUBSETS
            elif "subsets" in pid or fn == "subsets":
                try_add(
                    f"adapt_r{round_number}_subsets_single",
                    {"nums": [7]},
                    TestCategory.SINGLE_ELEMENT,
                    "Targeted minimal single element power set boundary",
                    sig.signal_id,
                )

            # NUMBER OF PROVINCES
            elif "number-of-provinces" in pid or fn == "findcirclenum":
                try_add(
                    f"adapt_r{round_number}_all_disconnected",
                    {"isConnected": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
                    TestCategory.ADVERSARIAL,
                    "Targeted completely disconnected graph boundary (identity matrix, N provinces)",
                    sig.signal_id,
                )

            # CLIMBING STAIRS
            elif ("climbing-stairs" in pid or fn == "climbstairs") and "n" in problem.param_names:
                try_add(
                    f"adapt_r{round_number}_climb_1",
                    {"n": 1},
                    TestCategory.BOUNDARY,
                    "Targeted minimum step base case n=1",
                    sig.signal_id,
                )
                try_add(
                    f"adapt_r{round_number}_climb_2",
                    {"n": 2},
                    TestCategory.BOUNDARY,
                    "Targeted base case n=2",
                    sig.signal_id,
                )

            # BEST TIME TO BUY AND SELL STOCK
            elif "best-time-to-buy-and-sell-stock" in pid or fn == "maxprofit":
                try_add(
                    f"adapt_r{round_number}_strictly_decreasing",
                    {"prices": [10, 8, 6, 4, 2, 1]},
                    TestCategory.ADVERSARIAL,
                    "Targeted strictly decreasing prices where 0 profit is attainable",
                    sig.signal_id,
                )
                try_add(
                    f"adapt_r{round_number}_stock_single",
                    {"prices": [5]},
                    TestCategory.SINGLE_ELEMENT,
                    "Targeted single day trading boundary (profit 0)",
                    sig.signal_id,
                )

        return AdaptiveGenerationResult(
            round_number=round_number,
            new_tests=new_tests,
            deduplicated_count=dedup_count,
            signals_addressed=addressed,
            generation_reasons=reasons,
            budget_exhausted=len(new_tests) >= max_tests_to_generate,
        )

    def generate_failure_driven_tests(
        self,
        problem: ProblemSpec,
        failed_result: TestCaseResult,
        existing_test_fingerprints: Set[str],
        round_number: int = 1,
        max_tests: int = 3,
        seed: Optional[int] = None,
    ) -> List[TestCase]:
        """
        Generates focused sibling/neighborhood tests when a candidate fails a test case.
        """
        active_seed = (seed if seed is not None else self.base_seed) + 5555
        rng = random.Random(active_seed)
        ref_fn = ReferenceOracles.get_reference_solution(problem)
        if ref_fn is None:
            return []

        sibling_tests: List[TestCase] = []
        inp = failed_result.input_data or {}
        pid = problem.id.lower()

        # Binary Search off-by-one neighborhood
        if "binary-search" in pid or "search" in problem.function_name.lower():
            nums = inp.get("nums", [])
            target = inp.get("target")
            if isinstance(nums, list) and len(nums) > 1 and isinstance(target, int):
                # Try target + 1, target - 1, and adjacent indices
                candidates = [target - 1, target + 1]
                for idx, cand in enumerate(candidates):
                    if len(sibling_tests) >= max_tests:
                        break
                    cand_inp = {"nums": list(nums), "target": cand}
                    fp = compute_test_fingerprint(cand_inp)
                    if fp not in existing_test_fingerprints:
                        existing_test_fingerprints.add(fp)
                        sibling_tests.append(TestCase(
                            id=f"failure_driven_bs_{round_number}_{idx+1}",
                            inputs=cand_inp,
                            expected_output=ref_fn(**cand_inp),
                            category=TestCategory.ADVERSARIAL,
                            oracle_type=OracleType.TRUSTED_REFERENCE,
                            rationale=f"Failure-driven boundary neighborhood test around failing target={target}",
                            random_seed=active_seed,
                        ))

        # Array Max Subarray / Two Sum neighborhood
        elif "max-subarray" in pid or "maxsubarray" in problem.function_name.lower():
            nums = inp.get("nums", [])
            if isinstance(nums, list) and nums:
                # Invert or append zero
                alt_inp = {"nums": [-abs(x) for x in nums]}
                fp = compute_test_fingerprint(alt_inp)
                if fp not in existing_test_fingerprints:
                    existing_test_fingerprints.add(fp)
                    sibling_tests.append(TestCase(
                        id=f"failure_driven_ms_{round_number}_neg",
                        inputs=alt_inp,
                        expected_output=ref_fn(**alt_inp),
                        category=TestCategory.ADVERSARIAL,
                        oracle_type=OracleType.TRUSTED_REFERENCE,
                        rationale="Failure-driven negative variation targeting sub-optimal sign handling",
                        random_seed=active_seed,
                    ))

        return sibling_tests
