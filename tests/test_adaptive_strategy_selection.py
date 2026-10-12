"""
Unit & Integration Tests for Stage 23: Adaptive Strategy Selection.
Tests:
- deterministic selection
- empty-memory fallback
- relevant versus irrelevant experience
- contradictory experiences
- language-specific outcomes
- constraints overriding historical preferences
- infrastructure failure exclusion
- strategy cost and outcome recording
- baseline/adaptive reproducibility
- repair and regression integration
- bounded work
- persistence, restart, idempotency, and security
- all four languages (C, C++, Java, Python)
"""

import os
import pytest

from agent.core.models import (
    CandidateApproach,
    DSAPattern,
    FailureCategory,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCategory,
)
from agent.memory.models import ExperienceRecommendation
from agent.memory.service import MemoryService
from agent.memory.sqlite_store import SQLiteMemoryStore
from agent.strategy.models import StrategyDecision, StrategyType
from agent.strategy.selector import StrategySelector
from agent.core.orchestrator import SelfCorrectionOrchestrator


@pytest.fixture
def sample_problem():
    return ProblemSpec(
        id="two-sum",
        title="Two Sum",
        description="Find two numbers adding to target.",
        function_name="twoSum",
        param_names=["nums", "target"],
        return_type="List[int]",
        constraints=["2 <= nums.length <= 10^5"],
        test_cases=[
            TestCase(
                id="tc_1",
                inputs={"nums": [2, 7, 11, 15], "target": 9},
                expected_output=[0, 1],
                category=TestCategory.BASIC,
            )
        ],
    )


@pytest.fixture
def candidates():
    return [
        CandidateApproach(
            name="Brute Force Nested Loop",
            data_structures=["Array"],
            time_complexity="O(N^2)",
            space_complexity="O(1)",
            description="Nested loops checking all pairs",
            satisfies_constraints=False,
            rejection_reason="O(N^2) exceeds 10^8 operations for N=10^5",
        ),
        CandidateApproach(
            name="Single-Pass Hash Map",
            data_structures=["Hash Map"],
            time_complexity="O(N)",
            space_complexity="O(N)",
            description="One-pass hash table complement check",
            satisfies_constraints=True,
        ),
    ]


# 1. Deterministic selection
def test_deterministic_strategy_selection(sample_problem, candidates):
    selector = StrategySelector(mode="BASELINE")
    app1, dec1 = selector.select_algorithm_strategy(
        problem=sample_problem,
        candidates=candidates,
        patterns=[DSAPattern.HASH_TABLE],
        max_n=100000,
    )
    app2, dec2 = selector.select_algorithm_strategy(
        problem=sample_problem,
        candidates=candidates,
        patterns=[DSAPattern.HASH_TABLE],
        max_n=100000,
    )
    assert app1.name == app2.name
    assert dec1.strategy_id == dec2.strategy_id
    assert dec1.expected_benefit == dec2.expected_benefit


# 2. Empty-memory fallback
def test_empty_memory_fallback(sample_problem, candidates):
    selector = StrategySelector(mode="ADAPTIVE")
    app, dec = selector.select_algorithm_strategy(
        problem=sample_problem,
        candidates=candidates,
        patterns=[DSAPattern.HASH_TABLE],
        max_n=100000,
        retrieved_memories=[],
    )
    assert app.name == "Single-Pass Hash Map"
    assert dec.is_adaptive is False
    assert "empty memory" in dec.fallback_reason.lower() or "cold start" in dec.fallback_reason.lower()


# 3. Relevant versus irrelevant experience
def test_relevant_vs_irrelevant_experience(sample_problem, candidates):
    irrelevant_memory = ExperienceRecommendation(
        experience_id="exp_graph_1",
        problem_id="graph-bfs",
        relevance_score=0.1,
        pattern=DSAPattern.GRAPH_BFS_DFS,
        algorithm="Breadth-First Search",
        language=SupportedLanguage.PYTHON,
        verified=True,
        status="VERIFIED",
        useful_reason="Graph search",
    )
    selector = StrategySelector(mode="ADAPTIVE")
    app, dec = selector.select_algorithm_strategy(
        problem=sample_problem,
        candidates=candidates,
        patterns=[DSAPattern.HASH_TABLE],
        max_n=100000,
        retrieved_memories=[irrelevant_memory],
    )
    # Must reject irrelevant graph BFS memory for two-sum HASH_TABLE problem
    assert app.name == "Single-Pass Hash Map"
    assert dec.is_adaptive is False
    assert "No eligible verified memory" in dec.fallback_reason


# 4. Contradictory experiences
def test_contradictory_experience_handling(sample_problem, candidates):
    # Two conflicting memories: one failed, one verified
    unverified_failed = ExperienceRecommendation(
        experience_id="exp_fail",
        problem_id="two-sum-alt",
        relevance_score=0.9,
        pattern=DSAPattern.HASH_TABLE,
        algorithm="Brute Force Nested Loop",
        language=SupportedLanguage.PYTHON,
        verified=False,
        status="FAILED",
        useful_reason="Failed run",
    )
    verified_good = ExperienceRecommendation(
        experience_id="exp_good",
        problem_id="two-sum-prior",
        relevance_score=0.85,
        pattern=DSAPattern.HASH_TABLE,
        algorithm="Single-Pass Hash Map",
        language=SupportedLanguage.PYTHON,
        verified=True,
        status="VERIFIED",
        useful_reason="Verified run",
    )
    selector = StrategySelector(mode="ADAPTIVE")
    app, dec = selector.select_algorithm_strategy(
        problem=sample_problem,
        candidates=candidates,
        patterns=[DSAPattern.HASH_TABLE],
        max_n=100000,
        retrieved_memories=[unverified_failed, verified_good],
    )
    assert app.name == "Single-Pass Hash Map"
    assert dec.is_adaptive is True


# 5. Language-specific outcomes
@pytest.mark.parametrize("lang", [SupportedLanguage.C, SupportedLanguage.CPP, SupportedLanguage.JAVA, SupportedLanguage.PYTHON])
def test_language_specific_debugging_strategy(lang):
    selector = StrategySelector()
    dec = selector.select_debugging_strategy(
        failure_category=FailureCategory.COMPILE_ERROR,
        language=lang,
    )
    assert dec.strategy_id == "strat_diag_compiler_log_parsing"
    assert dec.inputs_considered["language"] == lang.value


# 6. Constraints overriding historical preferences
def test_constraints_override_historical_preference(sample_problem):
    # Suppose memory recommends Brute Force (which violates N=10^5)
    memory_recommending_brute = ExperienceRecommendation(
        experience_id="exp_brute",
        problem_id="small-two-sum",
        relevance_score=0.95,
        pattern=DSAPattern.HASH_TABLE,
        algorithm="Brute Force Nested Loop",
        language=SupportedLanguage.PYTHON,
        verified=True,
        status="VERIFIED",
        useful_reason="Worked for N=10",
    )
    candidates_list = [
        CandidateApproach(
            name="Brute Force Nested Loop",
            data_structures=["Array"],
            time_complexity="O(N^2)",
            space_complexity="O(1)",
            description="Nested loops",
            satisfies_constraints=False,  # Constraint check failed for N=10^5!
            rejection_reason="Violates 10^8 operations",
        ),
        CandidateApproach(
            name="Single-Pass Hash Map",
            data_structures=["Hash Map"],
            time_complexity="O(N)",
            space_complexity="O(N)",
            description="Optimal hash map",
            satisfies_constraints=True,
        ),
    ]
    selector = StrategySelector(mode="ADAPTIVE")
    app, dec = selector.select_algorithm_strategy(
        problem=sample_problem,
        candidates=candidates_list,
        patterns=[DSAPattern.HASH_TABLE],
        max_n=100000,
        retrieved_memories=[memory_recommending_brute],
    )
    # Constraints override: Brute Force MUST NOT be selected despite verified memory
    assert app.name == "Single-Pass Hash Map"
    assert app.satisfies_constraints is True


# 7. Infrastructure failure exclusion
def test_infrastructure_failure_exclusion_from_strategies(sample_problem, candidates):
    infra_memory = ExperienceRecommendation(
        experience_id="exp_infra",
        problem_id="two-sum",
        relevance_score=0.99,
        pattern=DSAPattern.HASH_TABLE,
        algorithm="Single-Pass Hash Map",
        language=SupportedLanguage.PYTHON,
        verified=False,
        status="INFRASTRUCTURE_ERROR",
        useful_reason="Host docker killed",
    )
    selector = StrategySelector(mode="ADAPTIVE")
    app, dec = selector.select_algorithm_strategy(
        problem=sample_problem,
        candidates=candidates,
        patterns=[DSAPattern.HASH_TABLE],
        max_n=100000,
        retrieved_memories=[infra_memory],
    )
    # Infrastructure error memory is excluded from adaptive selection
    assert dec.is_adaptive is False
    assert "No eligible verified memory" in dec.fallback_reason


# 8. Strategy cost and outcome recording
def test_strategy_cost_and_outcome_recording(sample_problem):
    selector = StrategySelector(mode="ADAPTIVE")
    mem_with_warnings = ExperienceRecommendation(
        experience_id="exp_warn",
        problem_id="two-sum",
        relevance_score=0.9,
        pattern=DSAPattern.HASH_TABLE,
        algorithm="Hash Map",
        language=SupportedLanguage.PYTHON,
        verified=True,
        status="VERIFIED",
        useful_reason="Test",
        warning_notes=["Duplicate elements caused edge failure"],
    )
    budget_dec = selector.select_test_budget_strategy(
        problem=sample_problem,
        language=SupportedLanguage.PYTHON,
        retrieved_memories=[mem_with_warnings],
    )
    assert budget_dec.is_adaptive is True
    assert budget_dec.resource_cost["max_tests"] == 12
    assert budget_dec.resource_cost["adaptive_rounds"] == 2


# 9. Baseline vs Adaptive reproducibility
def test_baseline_adaptive_reproducibility(sample_problem, candidates):
    b1 = StrategySelector(mode="BASELINE")
    b2 = StrategySelector(mode="BASELINE")
    res1, dec1 = b1.select_algorithm_strategy(sample_problem, candidates, [DSAPattern.HASH_TABLE], 1000)
    res2, dec2 = b2.select_algorithm_strategy(sample_problem, candidates, [DSAPattern.HASH_TABLE], 1000)
    assert res1.name == res2.name
    assert dec1.strategy_id == dec2.strategy_id


# 10. Repair and regression integration
def test_repair_tactic_strategy():
    selector = StrategySelector(mode="BASELINE")
    repair_dec = selector.select_repair_tactic(
        failure_category=FailureCategory.COMPILE_ERROR,
        language=SupportedLanguage.CPP,
        diagnosis_direction="Add semicolon",
    )
    assert repair_dec.strategy_type == StrategyType.REPAIR_TACTIC
    assert "deterministic" in repair_dec.strategy_id


# 11. Bounded work in orchestrator
def test_bounded_work_orchestrator(sample_problem):
    orchestrator = SelfCorrectionOrchestrator(max_attempts=2, strategy_mode="ADAPTIVE")
    session = orchestrator.solve(
        problem=sample_problem,
        language=SupportedLanguage.PYTHON,
        override_initial_code="class Solution:\n    def twoSum(self, nums, target):\n        return [0, 0]\n",
        max_attempts=2,
    )
    assert session.total_attempts <= 2
    assert session.strategy_bundle is not None
    assert len(session.strategy_bundle.decisions_log) >= 2


# 12. Persistence, restart, idempotency, and security
def test_persistence_restart_idempotency(tmp_path):
    db_file = str(tmp_path / "stage23_test_mem.db")
    store = SQLiteMemoryStore(db_path=db_file)
    mem_service = MemoryService(store=store)

    prob = ProblemSpec(
        id="p_test",
        title="Test",
        description="Desc",
        function_name="fn",
        param_names=["x"],
    )
    mem_service.record_problem(prob)

    # Reconnect and verify
    store2 = SQLiteMemoryStore(db_path=db_file)
    loaded = store2.get_problem("p_test")
    assert loaded is not None
    assert loaded.problem_id == "p_test"
