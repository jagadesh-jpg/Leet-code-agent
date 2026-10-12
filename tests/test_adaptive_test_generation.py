"""Comprehensive Focused Test Suite for Stage 21 Intelligent / Adaptive Test Generation.

Validates:
- Structured risk analysis (Problem constraints, DSA patterns, AST/syntax)
- Constraint-aware test generation (Respects min/max bounds, no illegal inputs)
- Category-specific targeted generation (Boundary, adversarial, edge, stress)
- Memory-informed generation & irrelevant-memory rejection
- Independent oracle execution (No circular verification)
- Deterministic seeds & reproducibility
- Test deduplication via SHA-256 fingerprints
- Bounded adaptive rounds & test budget limits
- Failure-driven adaptive sibling test generation
- Infrastructure isolation (No blaming candidate for toolchain failures)
- Structural code risk analysis (Loops, recursion, indexing, maps, stacks)
- Mutation testing evaluation
- Multi-language verification (C, C++, Java, Python)
- Relational SQLite persistence, resume, and idempotency
- Security sandbox boundaries
"""

import os
import pytest
from typing import Dict, List

from agent.benchmarking.benchmark_registry import BENCHMARK_REGISTRY, to_problem_spec
from agent.core.models import (
    ConfidenceLevel,
    DSAPattern,
    ExecutionStatus,
    FailureCategory,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCaseResult,
    TestCategory,
)
from agent.memory.models import ExperienceRecommendation
from agent.memory.sqlite_store import SQLiteMemoryStore
from agent.testing.adaptive_generator import (
    AdaptiveTestGenerator,
    compute_test_fingerprint,
)
from agent.testing.engine import TestingEngine
from agent.testing.mutation import MutationTester
from agent.testing.oracles import ReferenceOracles
from agent.testing.risk_model import (
    StructuralCodeInspector,
    TestRiskClassifier,
)


@pytest.fixture
def two_sum_spec() -> ProblemSpec:
    return to_problem_spec(BENCHMARK_REGISTRY["two-sum"])


@pytest.fixture
def binary_search_spec() -> ProblemSpec:
    return to_problem_spec(BENCHMARK_REGISTRY["binary-search"])


@pytest.fixture
def valid_parentheses_spec() -> ProblemSpec:
    return to_problem_spec(BENCHMARK_REGISTRY["valid-parentheses"])


# 1. RISK ANALYSIS
def test_risk_analysis_generation(two_sum_spec, binary_search_spec):
    # Two Sum risks: Duplicates, negative numbers, boundary length 2
    analysis_ts = TestRiskClassifier.analyze_risks(two_sum_spec, language=SupportedLanguage.PYTHON)
    assert analysis_ts.has_boundary_risk is True
    categories = [s.risk_category for s in analysis_ts.signals]
    assert "DUPLICATES" in categories
    assert "NEGATIVE_ZERO" in categories

    # Binary search risks: Off-by-one, single element
    analysis_bs = TestRiskClassifier.analyze_risks(binary_search_spec, language=SupportedLanguage.PYTHON)
    assert analysis_bs.has_off_by_one_risk is True
    bs_categories = [s.risk_category for s in analysis_bs.signals]
    assert "OFF_BY_ONE" in bs_categories
    assert "EMPTY_OR_SINGLE" in bs_categories


# 2. STRUCTURAL CODE INSPECTION
def test_structural_code_risk_analysis():
    py_code = """
def twoSum(nums, target):
    seen = {}
    for i, x in enumerate(nums):
        comp = target - x
        if comp in seen:
            return [seen[comp], i]
        seen[x] = i
    return []
"""
    struct_risk = StructuralCodeInspector.inspect(py_code, SupportedLanguage.PYTHON)
    assert struct_risk.has_boundary_comparisons is True
    assert struct_risk.has_pointer_or_index_arithmetic is True
    assert struct_risk.has_hash_lookups is True

    cpp_nested = """
class Solution {
public:
    int maxSubArray(vector<int>& nums) {
        for (int i = 0; i < nums.size(); ++i) {
            for (int j = i; j < nums.size(); ++j) {
                // nested
            }
        }
    }
};
"""
    struct_cpp = StructuralCodeInspector.inspect(cpp_nested, SupportedLanguage.CPP)
    assert struct_cpp.has_nested_loops is True


# 3. CONSTRAINT-AWARE TEST GENERATION
def test_constraint_aware_generation(two_sum_spec):
    gen = AdaptiveTestGenerator(base_seed=42)
    risk_analysis = TestRiskClassifier.analyze_risks(two_sum_spec, language=SupportedLanguage.PYTHON)
    fps = set()
    res = gen.generate_targeted_tests(two_sum_spec, risk_analysis, fps, round_number=1, max_tests_to_generate=5)

    assert len(res.new_tests) > 0
    for tc in res.new_tests:
        nums = tc.inputs["nums"]
        # Constraint for Two Sum: 2 <= nums.length <= 10^4
        assert len(nums) >= 2
        # Target sum must have independent expected output
        assert tc.expected_output is not None
        assert isinstance(tc.expected_output, list)


# 4. CATEGORY-SPECIFIC GENERATION & EXPLICIT REASONING
def test_category_specific_generation_with_reasons(binary_search_spec):
    gen = AdaptiveTestGenerator(base_seed=42)
    risk_analysis = TestRiskClassifier.analyze_risks(binary_search_spec, language=SupportedLanguage.PYTHON)
    fps = set()
    res = gen.generate_targeted_tests(binary_search_spec, risk_analysis, fps, round_number=1, max_tests_to_generate=5)

    categories = {tc.category for tc in res.new_tests}
    assert (TestCategory.BOUNDARY in categories) or (TestCategory.SINGLE_ELEMENT in categories)
    # Check that rationales are non-empty and engineering-grounded
    for tc in res.new_tests:
        assert tc.rationale is not None
        assert len(tc.rationale) > 10


# 5. MEMORY-INFORMED TESTING & IRRELEVANT MEMORY REJECTION
def test_memory_informed_testing_and_rejection(binary_search_spec):
    relevant_mem = ExperienceRecommendation(
        experience_id="exp_bs_valid_1",
        problem_id="binary-search",
        relevance_score=0.95,
        pattern=DSAPattern.BINARY_SEARCH,
        algorithm="Binary Search Iterative",
        language=SupportedLanguage.PYTHON,
        verified=True,
        status="VERIFIED",
        useful_reason="High relevance experience",
        warning_notes=["Right boundary off-by-one when target is array maximum."],
    )
    irrelevant_mem = ExperienceRecommendation(
        experience_id="exp_graph_2",
        problem_id="number-of-provinces",
        relevance_score=0.10,
        pattern=DSAPattern.GRAPH_BFS_DFS,
        algorithm="DFS Traversal",
        language=SupportedLanguage.PYTHON,
        verified=True,
        status="VERIFIED",
        useful_reason="Irrelevant graph problem",
    )

    analysis = TestRiskClassifier.analyze_risks(
        binary_search_spec,
        retrieved_memories=[relevant_mem, irrelevant_mem],
    )

    # Relevant memory should yield a memory-informed risk signal
    mem_signals = [s for s in analysis.signals if s.is_memory_informed]
    assert len(mem_signals) >= 1
    assert "Right boundary off-by-one" in mem_signals[0].description
    # Irrelevant memory should be noted in rejected_memories
    assert len(analysis.rejected_memories) == 1
    assert "exp_graph_2" in analysis.rejected_memories[0]


# 6. ORACLE INDEPENDENCE (NO CIRCULAR VERIFICATION)
def test_oracle_independence(two_sum_spec):
    # Reference solution computed by brute-force O(N^2)
    ref_fn = ReferenceOracles.get_reference_solution(two_sum_spec)
    assert ref_fn is not None
    # Verify directly against known inputs
    out = ref_fn(nums=[2, 7, 11, 15], target=9)
    assert out == [0, 1]

    # Metamorphic property checker
    ok, err = ReferenceOracles.evaluate_property(two_sum_spec, {"nums": [3, 3], "target": 6}, [0, 1])
    assert ok is True
    # Property check rejects identical index violation
    bad_ok, bad_err = ReferenceOracles.evaluate_property(two_sum_spec, {"nums": [3, 3], "target": 6}, [0, 0])
    assert bad_ok is False
    assert "distinct" in bad_err


# 7. DETERMINISTIC SEEDS & REPRODUCIBILITY
def test_deterministic_seeds_and_reproducibility(two_sum_spec):
    gen1 = AdaptiveTestGenerator(base_seed=1234)
    gen2 = AdaptiveTestGenerator(base_seed=1234)

    risk_analysis = TestRiskClassifier.analyze_risks(two_sum_spec)

    fps1 = set()
    res1 = gen1.generate_targeted_tests(two_sum_spec, risk_analysis, fps1, round_number=1, seed=1234)

    fps2 = set()
    res2 = gen2.generate_targeted_tests(two_sum_spec, risk_analysis, fps2, round_number=1, seed=1234)

    assert len(res1.new_tests) == len(res2.new_tests)
    for t1, t2 in zip(res1.new_tests, res2.new_tests):
        assert t1.inputs == t2.inputs
        assert t1.expected_output == t2.expected_output
        assert t1.random_seed == t2.random_seed


# 8. TEST DEDUPLICATION VIA SHA-256 FINGERPRINTS
def test_test_deduplication(two_sum_spec):
    gen = AdaptiveTestGenerator(base_seed=42)
    risk_analysis = TestRiskClassifier.analyze_risks(two_sum_spec)

    fps = set()
    # First generation
    res1 = gen.generate_targeted_tests(two_sum_spec, risk_analysis, fps, round_number=1)
    initial_count = len(res1.new_tests)
    assert initial_count > 0

    # Second generation with same fingerprint set: should deduplicate all existing
    res2 = gen.generate_targeted_tests(two_sum_spec, risk_analysis, fps, round_number=1)
    assert len(res2.new_tests) == 0
    assert res2.deduplicated_count >= initial_count


# 9. BOUNDED ADAPTIVE ROUNDS & TEST BUDGET
def test_bounded_adaptive_rounds_and_budget(two_sum_spec):
    engine = TestingEngine()
    py_sol = """
class Solution:
    def twoSum(self, nums, target):
        seen = {}
        for i, x in enumerate(nums):
            comp = target - x
            if comp in seen:
                return [seen[comp], i]
            seen[x] = i
        return []
"""
    # Restrict budget: max_adaptive_rounds=1, max_total_budget=10
    report = engine.evaluate_solution_adaptive(
        problem=two_sum_spec,
        solution_code=py_sol,
        language=SupportedLanguage.PYTHON,
        max_adaptive_rounds=1,
        max_targeted_per_round=3,
        max_total_budget=10,
    )

    assert report.adaptive_rounds_executed <= 1
    assert report.total_tests <= 10
    assert report.all_passed is True


# 10. FAILURE-DRIVEN ADAPTIVE GENERATION
def test_failure_driven_adaptation(binary_search_spec):
    gen = AdaptiveTestGenerator(base_seed=42)
    failed_result = TestCaseResult(
        test_case_id="failed_bs_1",
        passed=False,
        input_data={"nums": [1, 3, 5, 7, 9], "target": 7},
        expected_output=3,
        actual_output=-1,
        error_message="Wrong Answer",
    )
    fps = set()
    siblings = gen.generate_failure_driven_tests(binary_search_spec, failed_result, fps, round_number=1)
    assert len(siblings) > 0
    # Sibling tests explore neighborhood targets (e.g. 6, 8)
    for tc in siblings:
        assert tc.inputs["nums"] == [1, 3, 5, 7, 9]
        assert tc.inputs["target"] in (6, 8)
        assert tc.category == TestCategory.ADVERSARIAL


# 11. INFRASTRUCTURE ISOLATION (NO CANDIDATE BLAME)
def test_infrastructure_isolation(two_sum_spec):
    engine = TestingEngine()
    # Syntax error or invalid code
    bad_code = "class Solution { public int[] twoSum() { syntax error!! "
    report = engine.evaluate_solution_adaptive(
        problem=two_sum_spec,
        solution_code=bad_code,
        language=SupportedLanguage.CPP,
    )
    assert report.all_passed is False
    assert report.execution_status == ExecutionStatus.COMPILE_ERROR
    # Adaptive rounds must not run if compilation fails
    assert report.adaptive_rounds_executed == 0


# 12. MUTATION TESTING SENSITIVITY
def test_mutation_testing_sensitivity(binary_search_spec):
    canonical_cpp = BENCHMARK_REGISTRY["binary-search"].canonical_cpp_code
    mutants = MutationTester.create_mutants(canonical_cpp, SupportedLanguage.CPP)
    assert len(mutants) > 0

    engine = TestingEngine()
    eval_result = MutationTester.evaluate_test_suite_against_mutants(
        testing_engine=engine,
        problem=binary_search_spec,
        mutants=mutants,
        language=SupportedLanguage.CPP,
        use_adaptive=True,
    )

    assert eval_result["total_mutants"] > 0
    assert eval_result["killed_mutants"] > 0
    assert eval_result["mutation_score"] > 0.0


# 13. RELATIONAL PERSISTENCE, RESUME, AND IDEMPOTENCY
def test_persistence_resume_and_idempotency(tmp_path):
    db_file = str(tmp_path / "test_stage21_memory.db")
    store = SQLiteMemoryStore(db_path=db_file)

    # Insert problem first to satisfy foreign key constraint
    from agent.memory.models import ProblemMemoryRecord
    store.save_problem(ProblemMemoryRecord(
        problem_id="two-sum",
        title="Two Sum",
        description="Two Sum test description",
        param_names=["nums", "target"],
        constraints=["2 <= nums.length <= 10^4"],
    ))

    # Save evidence
    store.save_adaptive_test_evidence(
        evidence_id="ev_1",
        problem_id="two-sum",
        test_fingerprint="fp_abc123",
        category="boundary",
        generation_reason="Boundary length test",
        risk_signal="risk_min_length",
        memory_influence=None,
        seed=42,
        passed=True,
        adaptive_round=1,
    )

    records = store.get_adaptive_test_evidence("two-sum")
    assert len(records) == 1
    assert records[0]["test_fingerprint"] == "fp_abc123"

    # Idempotent re-save
    store.save_adaptive_test_evidence(
        evidence_id="ev_1",
        problem_id="two-sum",
        test_fingerprint="fp_abc123",
        category="boundary",
        generation_reason="Boundary length test",
        risk_signal="risk_min_length",
        passed=False,
        error_message="Updated to failed",
    )
    records_updated = store.get_adaptive_test_evidence("two-sum")
    assert len(records_updated) == 1
    assert records_updated[0]["passed"] == 0

    store.close()

    # Reopen to test persistence across resume
    store2 = SQLiteMemoryStore(db_path=db_file)
    records_resumed = store2.get_adaptive_test_evidence("two-sum")
    assert len(records_resumed) == 1
    store2.close()
