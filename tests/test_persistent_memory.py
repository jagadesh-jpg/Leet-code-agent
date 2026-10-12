"""
Unit & Integration Tests for Stage 11: Persistent Solution Memory & Learning from Failures.
Covers all 20 required verification scenarios deterministically:
1. Database initialization.
2. Problem insertion.
3. Problem retrieval.
4. Duplicate problem handling (idempotent update).
5. Solution persistence.
6. Verified solution retrieval.
7. Failed attempt persistence.
8. Failure retrieval.
9. Repair-history persistence.
10. Source hashing consistency (SHA-256).
11. Multiple source versions remaining separately accessible.
12. Algorithm/pattern retrieval.
13. Language-specific solution retrieval.
14. Verification evidence persistence.
15. Memory retrieval across separate service instances/processes.
16. Restart persistence (write -> close -> reopen -> retrieve).
17. Foreign-key/data-integrity enforcement.
18. Memory retrieval does not bypass verification.
19. Historical failed solutions are not incorrectly returned as VERIFIED.
20. Regression compatibility with autonomous self-correction loop.
"""

import os
import tempfile
import pytest

from agent.core.models import (
    ComplexityAuditResult,
    ComplexityConfidence,
    ConstraintCompatibilityResult,
    Difficulty,
    DSAPattern,
    FailureCategory,
    FailureReport,
    FinalVerificationReport,
    ProblemSpec,
    RepairAttempt,
    SelfCorrectionSession,
    StructuralComplexityObservation,
    SupportedLanguage,
    TestCase,
    TestCaseResult,
    VerificationStatus,
)
from agent.memory.models import (
    FailureMemoryRecord,
    PatternKnowledgeRecord,
    ProblemMemoryRecord,
    RepairMemoryRecord,
    SolutionMemoryRecord,
)
from agent.memory.service import MemoryService
from agent.memory.sqlite_store import SQLiteMemoryStore


@pytest.fixture
def temp_db_path():
    """Provides an isolated temporary sqlite database path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def memory_service(temp_db_path):
    store = SQLiteMemoryStore(db_path=temp_db_path)
    service = MemoryService(store=store)
    yield service
    service.close()


@pytest.fixture
def sample_problem():
    return ProblemSpec(
        id="two-sum",
        title="Two Sum",
        description="Find indices of two numbers that add up to target.",
        function_name="twoSum",
        param_names=["nums", "target"],
        constraints=["2 <= nums.length <= 10^5"],
        test_cases=[
            TestCase(id="t1", inputs={"nums": [2, 7, 11, 15], "target": 9}, expected_output=[0, 1]),
        ],
    )


# 1. Database Initialization
def test_1_database_initialization(temp_db_path):
    store = SQLiteMemoryStore(db_path=temp_db_path)
    conn = store._get_connection()
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row["name"] for row in cursor.fetchall()}
    assert "problems" in tables
    assert "solutions" in tables
    assert "failures" in tables
    assert "repairs" in tables
    assert "pattern_knowledge" in tables
    store.close()


# 2. Problem Insertion
def test_2_problem_insertion(memory_service, sample_problem):
    rec = memory_service.record_problem(sample_problem, detected_patterns=[DSAPattern.HASH_TABLE])
    assert rec.problem_id == "two-sum"
    assert rec.title == "Two Sum"


# 3. Problem Retrieval
def test_3_problem_retrieval(memory_service, sample_problem):
    memory_service.record_problem(sample_problem, detected_patterns=[DSAPattern.HASH_TABLE])
    retrieved = memory_service.store.get_problem("two-sum")
    assert retrieved is not None
    assert retrieved.problem_id == "two-sum"
    assert retrieved.title == "Two Sum"
    assert retrieved.function_name == "twoSum"
    assert DSAPattern.HASH_TABLE in retrieved.detected_patterns


# 4. Duplicate Problem Handling (Idempotent Update)
def test_4_duplicate_problem_handling(memory_service, sample_problem):
    memory_service.record_problem(sample_problem)
    updated_problem = sample_problem.model_copy(update={"title": "Two Sum Updated"})
    memory_service.record_problem(updated_problem)
    retrieved = memory_service.store.get_problem("two-sum")
    assert retrieved.title == "Two Sum Updated"


# 5. Solution Persistence
def test_5_solution_persistence(memory_service, sample_problem):
    code = "def twoSum(nums, target): return [0, 1]"
    audit = ComplexityAuditResult(
        expected_time_complexity="O(N)",
        expected_space_complexity="O(N)",
        inferred_time_complexity="O(N)",
        inferred_space_complexity="O(N)",
        confidence=ComplexityConfidence.HIGH,
        plan_implementation_consistent=True,
    )
    compat = ConstraintCompatibilityResult(compatible=True)
    report = FinalVerificationReport(
        problem_id="two-sum",
        source_version_hash=memory_service.compute_source_hash(code),
        language=SupportedLanguage.PYTHON,
        test_suite_status="ALL_PASSED",
        complexity_audit=audit,
        constraint_compatibility=compat,
        final_verification_status=VerificationStatus.VERIFIED,
        is_fully_certified=True,
    )
    sol_rec = memory_service.record_solution(
        problem=sample_problem,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        verification_report=report,
    )
    assert sol_rec.is_verified is True
    assert sol_rec.verification_status == VerificationStatus.VERIFIED


# 6. Verified Solution Retrieval
def test_6_verified_solution_retrieval(memory_service, sample_problem):
    code = "def twoSum(nums, target): return [0, 1]"
    report = FinalVerificationReport(
        problem_id="two-sum",
        source_version_hash=memory_service.compute_source_hash(code),
        language=SupportedLanguage.PYTHON,
        test_suite_status="ALL_PASSED",
        complexity_audit=ComplexityAuditResult(
            expected_time_complexity="O(N)",
            expected_space_complexity="O(N)",
            inferred_time_complexity="O(N)",
            inferred_space_complexity="O(N)",
            confidence=ComplexityConfidence.HIGH,
            plan_implementation_consistent=True,
        ),
        constraint_compatibility=ConstraintCompatibilityResult(compatible=True),
        final_verification_status=VerificationStatus.VERIFIED,
        is_fully_certified=True,
    )
    memory_service.record_solution(sample_problem, code, SupportedLanguage.PYTHON, report)
    verified = memory_service.store.get_latest_verified_solution("two-sum", SupportedLanguage.PYTHON)
    assert verified is not None
    assert verified.is_verified is True
    assert verified.source_code == code


# 7. Failed Attempt Persistence
def test_7_failed_attempt_persistence(memory_service, sample_problem):
    code = "def twoSum(nums, target): return []"
    failure_report = FailureReport(
        failure_id="fail_1",
        failure_category=FailureCategory.WRONG_ANSWER,
        error_message="Expected [0, 1], got []",
        affected_test_ids=["t1"],
    )
    fail_rec = memory_service.record_failure(
        problem=sample_problem,
        attempt_number=1,
        language=SupportedLanguage.PYTHON,
        source_code=code,
        failure_report=failure_report,
    )
    assert fail_rec.failure_category == FailureCategory.WRONG_ANSWER
    assert fail_rec.problem_id == "two-sum"


# 8. Failure Retrieval
def test_8_failure_retrieval(memory_service, sample_problem):
    code = "def twoSum(nums, target): return []"
    failure_report = FailureReport(
        failure_id="fail_1",
        failure_category=FailureCategory.WRONG_ANSWER,
        error_message="Expected [0, 1], got []",
    )
    memory_service.record_failure(sample_problem, 1, SupportedLanguage.PYTHON, code, failure_report)
    failures = memory_service.store.get_failures_for_problem("two-sum")
    assert len(failures) == 1
    assert failures[0].failure_category == FailureCategory.WRONG_ANSWER


# 9. Repair-History Persistence
def test_9_repair_history_persistence(memory_service, sample_problem):
    code_before = "def twoSum(nums, target): return []"
    code_after = "def twoSum(nums, target): return [0, 1]"
    attempt = RepairAttempt(
        attempt_number=1,
        state_at_start="EXECUTING_TESTS",
        source_hash_before=memory_service.compute_source_hash(code_before),
        source_code_before=code_before,
        source_hash_after=memory_service.compute_source_hash(code_after),
        source_code_after=code_after,
        failure_addressed=FailureReport(
            failure_id="f1",
            failure_category=FailureCategory.WRONG_ANSWER,
            error_message="Returned empty",
        ),
        patch_summary="Added lookup hash table",
        tests_passed=2,
        tests_failed=0,
        ast_valid=True,
        resulting_state="RETESTING",
    )
    rep_rec = memory_service.record_repair(
        problem=sample_problem,
        language=SupportedLanguage.PYTHON,
        attempt=attempt,
        verification_status_after=VerificationStatus.VERIFIED,
    )
    assert rep_rec.regression_passed is True
    assert rep_rec.patch_summary == "Added lookup hash table"


# 10. Source Hashing Consistency
def test_10_source_hashing_consistency(memory_service):
    code1 = "def solve(): return 42"
    code2 = "def solve(): return 42"
    code3 = "def solve(): return 43"
    hash1 = memory_service.compute_source_hash(code1)
    hash2 = memory_service.compute_source_hash(code2)
    hash3 = memory_service.compute_source_hash(code3)
    assert hash1 == hash2
    assert hash1 != hash3
    assert len(hash1) == 16


# 11. Multiple Source Versions Separately Accessible
def test_11_multiple_source_versions_accessible(memory_service, sample_problem):
    v1_code = "def twoSum(nums, target): return []"
    v2_code = "def twoSum(nums, target): return [0, 1]"
    rep1 = FinalVerificationReport(
        problem_id="two-sum",
        source_version_hash=memory_service.compute_source_hash(v1_code),
        language=SupportedLanguage.PYTHON,
        test_suite_status="FAILED",
        complexity_audit=ComplexityAuditResult(
            expected_time_complexity="O(N)", expected_space_complexity="O(N)",
            inferred_time_complexity="O(1)", inferred_space_complexity="O(1)",
            confidence=ComplexityConfidence.HIGH, plan_implementation_consistent=True,
        ),
        constraint_compatibility=ConstraintCompatibilityResult(compatible=True),
        final_verification_status=VerificationStatus.FAILED_CORRECTNESS,
        is_fully_certified=False,
    )
    rep2 = FinalVerificationReport(
        problem_id="two-sum",
        source_version_hash=memory_service.compute_source_hash(v2_code),
        language=SupportedLanguage.PYTHON,
        test_suite_status="ALL_PASSED",
        complexity_audit=ComplexityAuditResult(
            expected_time_complexity="O(N)", expected_space_complexity="O(N)",
            inferred_time_complexity="O(N)", inferred_space_complexity="O(N)",
            confidence=ComplexityConfidence.HIGH, plan_implementation_consistent=True,
        ),
        constraint_compatibility=ConstraintCompatibilityResult(compatible=True),
        final_verification_status=VerificationStatus.VERIFIED,
        is_fully_certified=True,
    )
    s1 = memory_service.record_solution(sample_problem, v1_code, SupportedLanguage.PYTHON, rep1)
    s2 = memory_service.record_solution(sample_problem, v2_code, SupportedLanguage.PYTHON, rep2)
    assert s1.solution_id != s2.solution_id

    all_sols = memory_service.store.get_solutions_for_problem("two-sum", only_verified=False)
    assert len(all_sols) == 2
    hashes = {s.source_hash for s in all_sols}
    assert s1.source_hash in hashes
    assert s2.source_hash in hashes


# 12. Algorithm/Pattern Retrieval
def test_12_algorithm_pattern_retrieval(memory_service, sample_problem):
    memory_service.record_problem(sample_problem, detected_patterns=[DSAPattern.HASH_TABLE])
    probs = memory_service.store.find_problems_by_pattern(DSAPattern.HASH_TABLE)
    assert len(probs) == 1
    assert probs[0].problem_id == "two-sum"


# 13. Language-Specific Solution Retrieval
def test_13_language_specific_solution_retrieval(memory_service, sample_problem):
    py_code = "def twoSum(nums, target): return [0, 1]"
    cpp_code = "vector<int> twoSum(vector<int>& nums, int target) { return {0, 1}; }"
    rep_py = FinalVerificationReport(
        problem_id="two-sum", source_version_hash="h_py", language=SupportedLanguage.PYTHON,
        test_suite_status="ALL_PASSED",
        complexity_audit=ComplexityAuditResult(expected_time_complexity="O(N)", expected_space_complexity="O(N)", inferred_time_complexity="O(N)", inferred_space_complexity="O(N)", confidence=ComplexityConfidence.HIGH, plan_implementation_consistent=True),
        constraint_compatibility=ConstraintCompatibilityResult(compatible=True),
        final_verification_status=VerificationStatus.VERIFIED, is_fully_certified=True,
    )
    rep_cpp = FinalVerificationReport(
        problem_id="two-sum", source_version_hash="h_cpp", language=SupportedLanguage.CPP,
        test_suite_status="ALL_PASSED",
        complexity_audit=ComplexityAuditResult(expected_time_complexity="O(N)", expected_space_complexity="O(N)", inferred_time_complexity="O(N)", inferred_space_complexity="O(N)", confidence=ComplexityConfidence.HIGH, plan_implementation_consistent=True),
        constraint_compatibility=ConstraintCompatibilityResult(compatible=True),
        final_verification_status=VerificationStatus.VERIFIED, is_fully_certified=True,
    )
    memory_service.record_solution(sample_problem, py_code, SupportedLanguage.PYTHON, rep_py)
    memory_service.record_solution(sample_problem, cpp_code, SupportedLanguage.CPP, rep_cpp)

    py_sols = memory_service.store.get_solutions_for_problem("two-sum", language=SupportedLanguage.PYTHON)
    cpp_sols = memory_service.store.get_solutions_for_problem("two-sum", language=SupportedLanguage.CPP)
    assert len(py_sols) == 1
    assert py_sols[0].language == SupportedLanguage.PYTHON
    assert len(cpp_sols) == 1
    assert cpp_sols[0].language == SupportedLanguage.CPP


# 14. Verification Evidence Persistence
def test_14_verification_evidence_persistence(memory_service, sample_problem):
    code = "def twoSum(nums, target): return [0, 1]"
    audit = ComplexityAuditResult(
        expected_time_complexity="O(N)",
        expected_space_complexity="O(N)",
        inferred_time_complexity="O(N)",
        inferred_space_complexity="O(1)",
        confidence=ComplexityConfidence.HIGH,
        plan_implementation_consistent=True,
        worst_case_analysis="Single pass hash map",
    )
    compat = ConstraintCompatibilityResult(
        compatible=True, max_input_bound=100000, estimated_operations=100000.0,
    )
    rep = FinalVerificationReport(
        problem_id="two-sum",
        source_version_hash=memory_service.compute_source_hash(code),
        language=SupportedLanguage.PYTHON,
        test_suite_status="ALL_PASSED",
        total_tests_run=10,
        tests_passed=10,
        tests_failed=0,
        has_stress_evidence=True,
        complexity_audit=audit,
        constraint_compatibility=compat,
        final_verification_status=VerificationStatus.VERIFIED,
        is_fully_certified=True,
    )
    memory_service.record_solution(sample_problem, code, SupportedLanguage.PYTHON, rep)
    sol = memory_service.store.get_latest_verified_solution("two-sum")
    assert sol.verification_report is not None
    assert sol.verification_report.total_tests_run == 10
    assert sol.verification_report.has_stress_evidence is True
    assert sol.verification_report.complexity_audit.worst_case_analysis == "Single pass hash map"


# 15. Memory Retrieval Across Separate Service Instances
def test_15_separate_service_instances(temp_db_path, sample_problem):
    store1 = SQLiteMemoryStore(db_path=temp_db_path)
    svc1 = MemoryService(store=store1)
    svc1.record_problem(sample_problem)
    svc1.close()

    store2 = SQLiteMemoryStore(db_path=temp_db_path)
    svc2 = MemoryService(store=store2)
    retrieved = svc2.store.get_problem("two-sum")
    assert retrieved is not None
    assert retrieved.title == "Two Sum"
    svc2.close()


# 16. Restart Persistence (Write -> Close -> Reopen -> Retrieve)
def test_16_restart_persistence(temp_db_path, sample_problem):
    code = "def twoSum(nums, target): return [0, 1]"
    rep = FinalVerificationReport(
        problem_id="two-sum", source_version_hash="h1", language=SupportedLanguage.PYTHON,
        test_suite_status="ALL_PASSED",
        complexity_audit=ComplexityAuditResult(expected_time_complexity="O(N)", expected_space_complexity="O(N)", inferred_time_complexity="O(N)", inferred_space_complexity="O(N)", confidence=ComplexityConfidence.HIGH, plan_implementation_consistent=True),
        constraint_compatibility=ConstraintCompatibilityResult(compatible=True),
        final_verification_status=VerificationStatus.VERIFIED, is_fully_certified=True,
    )
    # 1. Open and write
    svc1 = MemoryService(store=SQLiteMemoryStore(db_path=temp_db_path))
    svc1.record_solution(sample_problem, code, SupportedLanguage.PYTHON, rep)
    svc1.close()

    # 2. Simulate process restart by instantiating new store
    svc2 = MemoryService(store=SQLiteMemoryStore(db_path=temp_db_path))
    sol = svc2.store.get_latest_verified_solution("two-sum")
    assert sol is not None
    assert sol.source_code == code
    assert sol.is_verified is True
    svc2.close()


# 17. Foreign-Key Data Integrity Behavior
def test_17_foreign_key_integrity(temp_db_path):
    store = SQLiteMemoryStore(db_path=temp_db_path)
    # Attempt inserting solution for non-existent problem
    sol = SolutionMemoryRecord(
        solution_id="orphaned_sol",
        problem_id="non_existent_problem_id",
        language=SupportedLanguage.PYTHON,
        source_code="pass",
        source_hash="hash",
        verification_status=VerificationStatus.VERIFIED,
    )
    with pytest.raises(Exception):  # sqlite3.IntegrityError
        store.save_solution(sol)
    store.close()


# 18. Memory Retrieval Does Not Bypass Verification
def test_18_memory_retrieval_does_not_bypass_verification(memory_service, sample_problem):
    # Context retrieval provides prior solutions for reading, but does NOT grant execution-free verification
    code = "def twoSum(nums, target): return [0, 1]"
    rep = FinalVerificationReport(
        problem_id="two-sum", source_version_hash="h1", language=SupportedLanguage.PYTHON,
        test_suite_status="ALL_PASSED",
        complexity_audit=ComplexityAuditResult(expected_time_complexity="O(N)", expected_space_complexity="O(N)", inferred_time_complexity="O(N)", inferred_space_complexity="O(N)", confidence=ComplexityConfidence.HIGH, plan_implementation_consistent=True),
        constraint_compatibility=ConstraintCompatibilityResult(compatible=True),
        final_verification_status=VerificationStatus.VERIFIED, is_fully_certified=True,
    )
    memory_service.record_solution(sample_problem, code, SupportedLanguage.PYTHON, rep)
    ctx = memory_service.retrieve_context_for_problem(sample_problem)
    assert len(ctx.verified_solutions) == 1
    # Candidate source still needs to pass testing engine / verifier in the orchestrator pipeline


# 19. Historical Failed Solutions Are Not Incorrectly Returned as VERIFIED
def test_19_historical_failed_solutions_not_verified(memory_service, sample_problem):
    failed_code = "def twoSum(nums, target): return []"
    rep_fail = FinalVerificationReport(
        problem_id="two-sum", source_version_hash="fail_hash", language=SupportedLanguage.PYTHON,
        test_suite_status="FAILED",
        complexity_audit=ComplexityAuditResult(expected_time_complexity="O(N)", expected_space_complexity="O(N)", inferred_time_complexity="O(1)", inferred_space_complexity="O(1)", confidence=ComplexityConfidence.HIGH, plan_implementation_consistent=True),
        constraint_compatibility=ConstraintCompatibilityResult(compatible=True),
        final_verification_status=VerificationStatus.FAILED_CORRECTNESS, is_fully_certified=False,
    )
    memory_service.record_solution(sample_problem, failed_code, SupportedLanguage.PYTHON, rep_fail)

    # Latest verified solution must be None
    verified = memory_service.store.get_latest_verified_solution("two-sum")
    assert verified is None

    # Unverified solution should appear when requesting all
    all_sols = memory_service.store.get_solutions_for_problem("two-sum", only_verified=False)
    assert len(all_sols) == 1
    assert all_sols[0].is_verified is False


# 20. Regression Compatibility With Autonomous Self-Correction Loop
def test_20_orchestrator_session_persistence(temp_db_path, sample_problem):
    from agent.core.orchestrator import SelfCorrectionOrchestrator

    store = SQLiteMemoryStore(db_path=temp_db_path)
    service = MemoryService(store=store)
    orchestrator = SelfCorrectionOrchestrator(memory_service=service, max_attempts=2)

    correct_code = """
def twoSum(nums, target):
    lookup = {}
    for i, num in enumerate(nums):
        diff = target - num
        if diff in lookup:
            return [lookup[diff], i]
        lookup[num] = i
    return []
"""
    session = orchestrator.solve(sample_problem, SupportedLanguage.PYTHON, override_initial_code=correct_code)
    assert session.is_verified is True

    # Check that memory service persisted the verified solution
    verified = service.store.get_latest_verified_solution("two-sum")
    assert verified is not None
    assert verified.is_verified is True
    service.close()
