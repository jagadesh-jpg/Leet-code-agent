"""
Stage 20 Experience-Based Learning & Intelligent Memory Test Suite.
Validates:
1. empty-memory cold start
2. successful experience storage
3. failed experience storage
4. repair experience storage
5. MAX_ATTEMPTS experience storage
6. infrastructure failure separation
7. problem fingerprinting
8. relevant experience retrieval
9. irrelevant experience rejection
10. deterministic ranking
11. top-K limit
12. pattern-based retrieval
13. constraint-aware retrieval
14. language-aware retrieval
15. algorithm experience vs language bug separation
16. memory-aware planning
17. memory does not override current constraints
18. memory cannot directly certify a solution
19. memory retrieval failure fallback
20. duplicate experience handling
21. persistence across restart
22. verified evidence requirement
23. bad memory isolation
24. current solution independently verified
25. learning after successful repair
26. retrieval of previous failure pattern
27. no chain-of-thought persistence
28. end-to-end memory-assisted solving
"""

import os
import pytest
from typing import List

from agent.benchmarking.benchmark_registry import BENCHMARK_REGISTRY, to_problem_spec
from agent.core.models import (
    AgentState,
    AlgorithmPlan,
    CandidateApproach,
    ComplexityAuditResult,
    ConstraintCompatibilityResult,
    DSAPattern,
    FailureCategory,
    FailureReport,
    FailureSeverity,
    FinalVerificationReport,
    ProblemSpec,
    RepairAttempt,
    RootCauseHypothesis,
    SelfCorrectionSession,
    SupportedLanguage,
    VerificationStatus,
)
from agent.core.orchestrator import SelfCorrectionOrchestrator
from agent.memory.models import (
    ExperienceRecord,
    ExperienceRecommendation,
    MemoryRetrievalReport,
)
from agent.memory.service import MemoryService
from agent.memory.sqlite_store import SQLiteMemoryStore
from agent.planning.planner import AlgorithmPlanner
from agent.testing.engine import TestingEngine


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_stage20_memory.db"
    store = SQLiteMemoryStore(db_path=str(db_file))
    service = MemoryService(store=store)
    yield service
    service.close()


def make_dummy_verification_report(problem_id: str, is_verified: bool = True) -> FinalVerificationReport:
    return FinalVerificationReport(
        problem_id=problem_id,
        source_version_hash="dummy_hash_1234",
        language=SupportedLanguage.PYTHON,
        test_suite_status="ALL_PASSED" if is_verified else "FAILED",
        total_tests_run=5,
        tests_passed=5 if is_verified else 3,
        tests_failed=0 if is_verified else 2,
        has_edge_case_evidence=True,
        has_boundary_evidence=True,
        complexity_audit=ComplexityAuditResult(
            expected_time_complexity="O(N)",
            expected_space_complexity="O(N)",
            inferred_time_complexity="O(N)",
            inferred_space_complexity="O(N)",
            plan_implementation_consistent=True,
        ),
        constraint_compatibility=ConstraintCompatibilityResult(
            compatible=True,
            max_input_bound=10000,
            estimated_operations=10000.0,
        ),
        final_verification_status=VerificationStatus.VERIFIED if is_verified else VerificationStatus.FAILED_CORRECTNESS,
        is_fully_certified=is_verified,
    )


# 1. Cold-start behavior: Empty memory returns valid report without error
def test_1_empty_memory_cold_start(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    report = temp_db.retrieve_relevant_experiences(problem=spec, dsa_pattern=DSAPattern.HASH_TABLE)
    assert report.retrieval_status == "NO_RELEVANT_EXPERIENCE"
    assert len(report.recommendations) == 0
    assert "cold start" in report.notes[0]


# 2. Successful experience storage
def test_2_successful_experience_storage(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    vr = make_dummy_verification_report(spec.id, is_verified=True)
    plan = AlgorithmPlanner().plan(spec)
    session = SelfCorrectionSession(
        session_id="run_test_2",
        problem_id=spec.id,
        language=SupportedLanguage.PYTHON,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="def twoSum(nums, target): return []",
        plan=plan,
        verification_report=vr,
    )
    rec = temp_db.learn_from_session(spec, session)
    assert rec is not None
    assert rec.is_verified is True
    assert rec.status == "VERIFIED"
    assert rec.dsa_pattern == DSAPattern.HASH_TABLE
    assert rec.tests_passed == 5


# 3. Failed experience storage
def test_3_failed_experience_storage(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    vr = make_dummy_verification_report(spec.id, is_verified=False)
    session = SelfCorrectionSession(
        session_id="run_test_3",
        problem_id=spec.id,
        language=SupportedLanguage.PYTHON,
        final_state=AgentState.FAILED,
        is_verified=False,
        verification_report=vr,
    )
    rec = temp_db.learn_from_session(spec, session)
    assert rec is not None
    assert rec.is_verified is False
    assert rec.status == "FAILED"


# 4. Repair experience storage
def test_4_repair_experience_storage(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["binary-search"])
    plan = AlgorithmPlanner().plan(spec)
    attempt = RepairAttempt(
        attempt_number=1,
        state_at_start=AgentState.EXECUTING_TESTS,
        source_hash_before="before123",
        source_code_before="code_before",
        source_hash_after="after123",
        source_code_after="code_after",
        failure_addressed=FailureReport(
            failure_id="fail_1",
            failure_category=FailureCategory.WRONG_ANSWER,
            ranked_hypotheses=[
                RootCauseHypothesis(
                    hypothesis="Off-by-one boundary on mid calculation",
                    confidence="inferred",
                )
            ],
        ),
        patch_summary="Updated right = mid - 1 to preserve loop invariant",
        tests_passed=5,
        tests_failed=0,
        resulting_state=AgentState.VERIFIED,
    )
    vr = make_dummy_verification_report(spec.id, is_verified=True)
    session = SelfCorrectionSession(
        session_id="run_test_4",
        problem_id=spec.id,
        language=SupportedLanguage.PYTHON,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="code_after",
        plan=plan,
        attempt_history=[attempt],
        verification_report=vr,
    )
    rec = temp_db.learn_from_session(spec, session)
    assert "WRONG_ANSWER" in rec.failure_categories
    assert "Updated right = mid - 1 to preserve loop invariant" in rec.repair_actions
    assert "Off-by-one boundary on mid calculation" in rec.failure_hypotheses


# 5. MAX_ATTEMPTS_REACHED experience storage
def test_5_max_attempts_experience_storage(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["reverse-linked-list"])
    session = SelfCorrectionSession(
        session_id="run_test_5",
        problem_id=spec.id,
        language=SupportedLanguage.PYTHON,
        final_state=AgentState.MAX_ATTEMPTS_REACHED,
        is_verified=False,
        total_attempts=5,
    )
    rec = temp_db.learn_from_session(spec, session)
    assert rec.status == "MAX_ATTEMPTS_REACHED"
    assert rec.is_verified is False
    assert rec.attempt_count == 5


# 6. Infrastructure failure separation
def test_6_infrastructure_failure_separation(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["valid-parentheses"])
    session = SelfCorrectionSession(
        session_id="run_test_6",
        problem_id=spec.id,
        language=SupportedLanguage.JAVA,
        final_state=AgentState.INFRASTRUCTURE_ERROR,
        is_verified=False,
    )
    rec = temp_db.learn_from_session(spec, session)
    assert rec.status == "INFRASTRUCTURE_ERROR"

    # Ensure retrieval rejects infrastructure failure
    retrieval = temp_db.retrieve_relevant_experiences(spec, dsa_pattern=DSAPattern.STACK)
    assert retrieval.retrieval_status == "NO_RELEVANT_EXPERIENCE"
    assert retrieval.rejected_count >= 1
    assert any("infrastructure" in r.lower() for r in retrieval.rejection_reasons)


# 7. Problem fingerprinting determinism and robustness
def test_7_problem_fingerprinting(temp_db):
    spec1 = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    fp1 = temp_db.compute_problem_fingerprint(spec1)
    fp2 = temp_db.compute_problem_fingerprint(spec1)
    assert fp1 == fp2  # Deterministic

    # Create variant with different wording
    spec_variant = spec1.model_copy(update={"title": "Find Two Numbers Whose Sum Equals Target"})
    fp_variant = temp_db.compute_problem_fingerprint(spec_variant)
    assert len(fp_variant) == 16


# 8. Relevant experience retrieval
def test_8_relevant_experience_retrieval(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    plan = AlgorithmPlanner().plan(spec)
    vr = make_dummy_verification_report(spec.id, is_verified=True)
    session = SelfCorrectionSession(
        session_id="run_test_8",
        problem_id=spec.id,
        language=SupportedLanguage.CPP,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="class Solution { ... }",
        plan=plan,
        verification_report=vr,
    )
    temp_db.learn_from_session(spec, session)

    report = temp_db.retrieve_relevant_experiences(spec, dsa_pattern=DSAPattern.HASH_TABLE)
    assert report.retrieval_status == "SUCCESS"
    assert len(report.recommendations) == 1
    rec = report.recommendations[0]
    assert rec.pattern == DSAPattern.HASH_TABLE
    assert rec.verified is True
    assert rec.relevance_score > 0.5


# 9. Irrelevant experience rejection
def test_9_irrelevant_experience_rejection(temp_db):
    # Store Two Sum (HASH_TABLE)
    spec_ts = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    plan = AlgorithmPlanner().plan(spec_ts)
    vr = make_dummy_verification_report(spec_ts.id, is_verified=True)
    session = SelfCorrectionSession(
        session_id="run_test_9",
        problem_id=spec_ts.id,
        language=SupportedLanguage.CPP,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="code",
        plan=plan,
        verification_report=vr,
    )
    temp_db.learn_from_session(spec_ts, session)

    # Query with completely unrelated problem: Binary Tree
    spec_tree = to_problem_spec(BENCHMARK_REGISTRY["maximum-depth-of-binary-tree"])
    report = temp_db.retrieve_relevant_experiences(spec_tree, dsa_pattern=DSAPattern.BINARY_TREE)
    assert report.retrieval_status == "NO_RELEVANT_EXPERIENCE"
    assert len(report.recommendations) == 0



# 10. Deterministic ranking
def test_10_deterministic_ranking(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    plan = AlgorithmPlanner().plan(spec)
    vr = make_dummy_verification_report(spec.id, is_verified=True)

    # Experience 1: Verified Two Sum in C++
    s1 = SelfCorrectionSession(
        session_id="s1",
        problem_id=spec.id,
        language=SupportedLanguage.CPP,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="code1",
        plan=plan,
        verification_report=vr,
    )
    temp_db.learn_from_session(spec, s1)

    # Experience 2: General Hashing problem
    spec_other = to_problem_spec(BENCHMARK_REGISTRY["valid-anagram"])
    plan_other = AlgorithmPlanner().plan(spec_other)
    s2 = SelfCorrectionSession(
        session_id="s2",
        problem_id=spec_other.id,
        language=SupportedLanguage.PYTHON,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="code2",
        plan=plan_other,
        verification_report=vr,
    )
    temp_db.learn_from_session(spec_other, s2)

    rep1 = temp_db.retrieve_relevant_experiences(spec, dsa_pattern=DSAPattern.HASH_TABLE)
    rep2 = temp_db.retrieve_relevant_experiences(spec, dsa_pattern=DSAPattern.HASH_TABLE)

    assert [r.experience_id for r in rep1.recommendations] == [r.experience_id for r in rep2.recommendations]
    assert rep1.recommendations[0].problem_id == spec.id  # Exact match ranks higher than general pattern


# 11. Top-K limit enforcement
def test_11_top_k_limit(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    plan = AlgorithmPlanner().plan(spec)
    vr = make_dummy_verification_report(spec.id, is_verified=True)

    for i in range(10):
        s = SelfCorrectionSession(
            session_id=f"run_topk_{i}",
            problem_id=f"two-sum-variant-{i}",
            language=SupportedLanguage.PYTHON,
            final_state=AgentState.VERIFIED,
            is_verified=True,
            verified_code=f"code_{i}",
            plan=plan,
            verification_report=vr,
        )
        temp_db.learn_from_session(spec, s)

    report = temp_db.retrieve_relevant_experiences(spec, dsa_pattern=DSAPattern.HASH_TABLE, top_k=3)
    assert len(report.recommendations) == 3
    assert report.top_k_limit == 3


# 12. Pattern-based retrieval
def test_12_pattern_based_retrieval(temp_db):
    spec_bs = to_problem_spec(BENCHMARK_REGISTRY["binary-search"])
    plan_bs = AlgorithmPlanner().plan(spec_bs)
    vr = make_dummy_verification_report(spec_bs.id, is_verified=True)
    session = SelfCorrectionSession(
        session_id="run_test_12",
        problem_id=spec_bs.id,
        language=SupportedLanguage.PYTHON,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="code_bs",
        plan=plan_bs,
        verification_report=vr,
    )
    temp_db.learn_from_session(spec_bs, session)

    report = temp_db.retrieve_relevant_experiences(spec_bs, dsa_pattern=DSAPattern.BINARY_SEARCH)
    assert len(report.recommendations) > 0
    assert report.recommendations[0].pattern == DSAPattern.BINARY_SEARCH


# 13. Constraint-aware retrieval
def test_13_constraint_aware_retrieval(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    plan = AlgorithmPlanner().plan(spec)
    vr = make_dummy_verification_report(spec.id, is_verified=True)
    session = SelfCorrectionSession(
        session_id="run_test_13",
        problem_id=spec.id,
        language=SupportedLanguage.PYTHON,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="code",
        plan=plan,
        verification_report=vr,
    )
    temp_db.learn_from_session(spec, session)

    report = temp_db.retrieve_relevant_experiences(spec, dsa_pattern=DSAPattern.HASH_TABLE)
    rec = report.recommendations[0]
    assert "Matching constraint profile" in rec.useful_reason


# 14. Language-aware retrieval preserves language field
def test_14_language_aware_retrieval(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    plan = AlgorithmPlanner().plan(spec)
    vr = make_dummy_verification_report(spec.id, is_verified=True)
    session = SelfCorrectionSession(
        session_id="run_test_14",
        problem_id=spec.id,
        language=SupportedLanguage.JAVA,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="class Solution {}",
        plan=plan,
        verification_report=vr,
    )
    temp_db.learn_from_session(spec, session)

    report = temp_db.retrieve_relevant_experiences(spec, dsa_pattern=DSAPattern.HASH_TABLE)
    rec = report.recommendations[0]
    assert rec.language == SupportedLanguage.JAVA


# 15. Algorithm experience vs language bug separation
def test_15_algorithm_vs_language_bug_separation(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["valid-parentheses"])
    plan = AlgorithmPlanner().plan(spec)
    attempt = RepairAttempt(
        attempt_number=1,
        state_at_start=AgentState.COMPILING,
        source_hash_before="before",
        source_code_before="stack<char> s; s.push()",
        source_hash_after="after",
        source_code_after="std::stack<char> s; s.push('(');",
        failure_addressed=FailureReport(
            failure_id="fail_cpp",
            failure_category=FailureCategory.COMPILE_ERROR,
            error_message="missing std:: namespace qualifier",
        ),
        patch_summary="Added missing std namespace qualifier in C++",
        tests_passed=5,
        tests_failed=0,
        resulting_state=AgentState.VERIFIED,
    )
    vr = make_dummy_verification_report(spec.id, is_verified=True)
    session = SelfCorrectionSession(
        session_id="run_test_15",
        problem_id=spec.id,
        language=SupportedLanguage.CPP,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="code",
        plan=plan,
        attempt_history=[attempt],
        verification_report=vr,
    )
    temp_db.learn_from_session(spec, session)

    # Query from Java
    report = temp_db.retrieve_relevant_experiences(spec, dsa_pattern=DSAPattern.STACK)
    assert len(report.recommendations) == 1
    rec = report.recommendations[0]
    # Algorithm knowledge is retained as verified
    assert rec.verified is True
    # The language repair is recorded as an insight
    assert "Added missing std namespace qualifier in C++" in rec.repair_insights[0]


# 16. Memory-aware planning
def test_16_memory_aware_planning():
    planner = AlgorithmPlanner()
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    rec = ExperienceRecommendation(
        experience_id="exp_123",
        problem_id="two-sum",
        relevance_score=0.95,
        pattern=DSAPattern.HASH_TABLE,
        algorithm="Single-Pass Hash Map",
        language=SupportedLanguage.PYTHON,
        verified=True,
        status="VERIFIED",
        useful_reason="Exact match",
    )
    plan = planner.plan(spec, retrieved_experiences=[rec])
    assert any("Memory recommendation" in note for note in plan.assumptions_and_notes)
    assert plan.selected_approach.name == "Single-Pass Hash Map"


# 17. Memory does not override current constraints
def test_17_memory_does_not_override_constraints():
    planner = AlgorithmPlanner()
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    # Modify constraints to small memory limit or brute-force only requirement
    spec_constrained = spec.model_copy(update={"constraints": ["1 <= nums.length <= 10^5"]})

    # Memory says use Brute Force Nested Loop (which is O(N^2))
    bad_rec = ExperienceRecommendation(
        experience_id="exp_bad",
        problem_id="two-sum",
        relevance_score=0.99,
        pattern=DSAPattern.HASH_TABLE,
        algorithm="Brute Force Nested Loop",
        language=SupportedLanguage.PYTHON,
        verified=True,
        status="VERIFIED",
        useful_reason="Force bad approach",
    )
    plan = planner.plan(spec_constrained, retrieved_experiences=[bad_rec])
    # Brute force nested loop must be REJECTED for N=10^5 because it violates the 10^8 ops limit!
    assert plan.selected_approach.name != "Brute Force Nested Loop"
    assert plan.selected_approach.satisfies_constraints is True


# 18. Memory cannot directly certify a solution
def test_18_memory_cannot_directly_certify_solution(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    # Verify in memory
    vr = make_dummy_verification_report(spec.id, is_verified=True)
    plan = AlgorithmPlanner().plan(spec)
    session = SelfCorrectionSession(
        session_id="run_test_18",
        problem_id=spec.id,
        language=SupportedLanguage.PYTHON,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="def twoSum(nums, target): return [0, 1]",
        plan=plan,
        verification_report=vr,
    )
    temp_db.learn_from_session(spec, session)

    # Running a flawed solution must STILL fail tests and NOT be certified
    orchestrator = SelfCorrectionOrchestrator(memory_service=temp_db, max_attempts=1)
    flawed_code = "def twoSum(nums, target): return [-999, -999]"
    res = orchestrator.solve(spec, language=SupportedLanguage.PYTHON, override_initial_code=flawed_code)
    # Must NOT be verified simply because memory had a verified record!
    assert res.is_verified is False
    assert res.final_state in (AgentState.FAILED, AgentState.MAX_ATTEMPTS_REACHED)


# 19. Memory retrieval failure fallback
def test_19_memory_retrieval_failure_fallback(temp_db):
    class FaultyMemoryService(MemoryService):
        def retrieve_relevant_experiences(self, problem, dsa_pattern=None, top_k=5):
            raise RuntimeError("Database disk failure simulated!")

    faulty_service = FaultyMemoryService(store=temp_db.store)
    orchestrator = SelfCorrectionOrchestrator(memory_service=faulty_service, max_attempts=1)
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    # Solve should gracefully proceed without crashing
    session = orchestrator.solve(spec, language=SupportedLanguage.PYTHON)
    assert session is not None
    assert session.plan is not None



# 20. Duplicate experience handling
def test_20_duplicate_experience_handling(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    plan = AlgorithmPlanner().plan(spec)
    vr = make_dummy_verification_report(spec.id, is_verified=True)
    session = SelfCorrectionSession(
        session_id="run_dup_1",
        problem_id=spec.id,
        language=SupportedLanguage.PYTHON,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="code",
        plan=plan,
        verification_report=vr,
    )
    rec1 = temp_db.learn_from_session(spec, session)
    # Updating existing record with same ID does not throw error
    rec1_updated = rec1.model_copy(update={"tests_passed": 10})
    temp_db.store_experience(rec1_updated)
    loaded = temp_db.get_experience(rec1.experience_id)
    assert loaded.tests_passed == 10


# 21. Persistence across restart
def test_21_persistence_across_restart(tmp_path):
    db_file = tmp_path / "persistent_restart.db"
    store1 = SQLiteMemoryStore(db_path=str(db_file))
    svc1 = MemoryService(store=store1)

    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    plan = AlgorithmPlanner().plan(spec)
    vr = make_dummy_verification_report(spec.id, is_verified=True)
    s = SelfCorrectionSession(
        session_id="run_p",
        problem_id=spec.id,
        language=SupportedLanguage.PYTHON,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="code",
        plan=plan,
        verification_report=vr,
    )
    rec = svc1.learn_from_session(spec, s)
    svc1.close()

    # Re-open in a fresh service instance
    store2 = SQLiteMemoryStore(db_path=str(db_file))
    svc2 = MemoryService(store=store2)
    loaded = svc2.get_experience(rec.experience_id)
    assert loaded is not None
    assert loaded.problem_id == spec.id
    assert loaded.is_verified is True
    svc2.close()


# 22. Verified evidence requirement
def test_22_verified_evidence_requirement(temp_db):
    exp = ExperienceRecord(
        experience_id="exp_unverified",
        problem_id="some-problem",
        problem_fingerprint="fp123",
        normalized_title="Unverified Problem",
        dsa_pattern=DSAPattern.STACK,
        algorithm_name="Dummy Stack",
        language=SupportedLanguage.PYTHON,
        status="FAILED",
        is_verified=False,
    )
    temp_db.store_experience(exp)

    spec = to_problem_spec(BENCHMARK_REGISTRY["valid-parentheses"])
    report = temp_db.retrieve_relevant_experiences(spec, dsa_pattern=DSAPattern.STACK)
    # An unverified record with no useful failure warnings is rejected
    assert report.retrieval_status == "NO_RELEVANT_EXPERIENCE"
    assert report.rejected_count >= 1


# 23. Bad memory isolation
def test_23_bad_memory_isolation():
    planner = AlgorithmPlanner()
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    # Irrelevant memory recommending dynamic programming
    bad_rec = ExperienceRecommendation(
        experience_id="exp_bad",
        problem_id="unrelated",
        relevance_score=0.2,
        pattern=DSAPattern.DYNAMIC_PROGRAMMING,
        algorithm="Bottom-Up DP",
        language=SupportedLanguage.PYTHON,
        verified=True,
        status="VERIFIED",
        useful_reason="Wrong advice",
    )
    plan = planner.plan(spec, retrieved_experiences=[bad_rec])
    # The planner must reject DP and choose Hash Table for Two Sum
    assert DSAPattern.HASH_TABLE in plan.identified_patterns
    assert "Hash Map" in plan.selected_approach.name


# 24. Current solution independently verified
def test_24_current_solution_independently_verified(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    # Populate memory
    vr = make_dummy_verification_report(spec.id, is_verified=True)
    plan = AlgorithmPlanner().plan(spec)
    s = SelfCorrectionSession(
        session_id="run_24",
        problem_id=spec.id,
        language=SupportedLanguage.PYTHON,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="def twoSum(nums, target): return [0, 1]",
        plan=plan,
        verification_report=vr,
    )
    temp_db.learn_from_session(spec, s)

    # Solve Two Sum with correct code; verifier must run real tests
    orchestrator = SelfCorrectionOrchestrator(memory_service=temp_db, max_attempts=2)
    session = orchestrator.solve(spec, language=SupportedLanguage.PYTHON)
    assert session.is_verified is True
    assert session.verification_report is not None
    assert session.verification_report.tests_passed > 0


# 25. Learning after successful repair
def test_25_learning_after_successful_repair(temp_db):
    from agent.benchmarking.multi_language_runner import INTENTIONAL_FLAWS
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    py_flaw, _ = INTENTIONAL_FLAWS[("two-sum", SupportedLanguage.PYTHON)]

    orchestrator = SelfCorrectionOrchestrator(memory_service=temp_db, max_attempts=3)
    session = orchestrator.solve(spec, language=SupportedLanguage.PYTHON, override_initial_code=py_flaw)
    assert session.is_verified is True
    assert session.total_attempts > 1

    # Check that repair experience was persisted
    exps = temp_db.store.list_all_experiences(only_verified=True)
    assert len(exps) >= 1
    found_repair = any(len(e.repair_actions) > 0 for e in exps)
    assert found_repair is True



# 26. Retrieval of previous failure pattern
def test_26_retrieval_of_previous_failure_pattern(temp_db):
    exp = ExperienceRecord(
        experience_id="exp_failure_warning",
        problem_id="binary-search",
        problem_fingerprint="fp_bs",
        normalized_title="Binary Search",
        dsa_pattern=DSAPattern.BINARY_SEARCH,
        algorithm_name="Binary Search on Monotonic Space",
        language=SupportedLanguage.PYTHON,
        status="MAX_ATTEMPTS_REACHED",
        is_verified=False,
        failure_categories=["WRONG_ANSWER"],
        failure_hypotheses=["Off-by-one boundary condition"],
        repair_actions=["Use left <= right"],
    )
    temp_db.store_experience(exp)

    spec = to_problem_spec(BENCHMARK_REGISTRY["binary-search"])
    report = temp_db.retrieve_relevant_experiences(spec, dsa_pattern=DSAPattern.BINARY_SEARCH)
    assert report.retrieval_status == "SUCCESS"
    assert len(report.recommendations) >= 1
    rec = report.recommendations[0]
    assert any("WRONG_ANSWER" in w for w in rec.warning_notes)
    assert "Use left <= right" in rec.repair_insights


# 27. No chain-of-thought persistence
def test_27_no_chain_of_thought_persistence(temp_db):
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    plan = AlgorithmPlanner().plan(spec)
    vr = make_dummy_verification_report(spec.id, is_verified=True)
    session = SelfCorrectionSession(
        session_id="run_27",
        problem_id=spec.id,
        language=SupportedLanguage.PYTHON,
        final_state=AgentState.VERIFIED,
        is_verified=True,
        verified_code="code",
        plan=plan,
        verification_report=vr,
    )
    rec = temp_db.learn_from_session(spec, session)
    # Check that model attributes only contain structured data, no private prompt traces or raw CoT
    raw_dict = rec.model_dump()
    for key, val in raw_dict.items():
        assert "chain_of_thought" not in key
        assert "private_reasoning" not in key


# 28. End-to-end memory-assisted solving
def test_28_end_to_end_memory_assisted_solving(temp_db):
    # Phase A: Solve Problem 1 (Two Sum) to seed memory
    spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    orchestrator = SelfCorrectionOrchestrator(memory_service=temp_db, max_attempts=2)
    session1 = orchestrator.solve(spec, language=SupportedLanguage.PYTHON)
    assert session1.is_verified is True

    # Phase B: Solve Problem 2 with populated memory
    session2 = orchestrator.solve(spec, language=SupportedLanguage.PYTHON)
    assert session2.is_verified is True
    # Verify that plan included memory recommendation
    assert any("Memory recommendation" in n for n in session2.plan.assumptions_and_notes)
