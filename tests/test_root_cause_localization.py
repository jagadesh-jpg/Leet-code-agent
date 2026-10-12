"""
Tests for Stage 22: Evidence-Driven Debugging & Root-Cause Localization.
Validates:
- compiler-error localization
- wrong-answer diagnosis
- runtime failure diagnosis
- timeout diagnosis
- boundary errors
- algorithmic complexity risks
- language-specific implementation errors
- multiple competing hypotheses
- confidence scoring
- missing or contradictory evidence
- irrelevant memory rejection
- infrastructure-error isolation
- oracle-error isolation
- bounded diagnostic attempts
- repair integration
- regression after repair
- C, C++, Java, and Python compatibility
- persistence and restart behavior
- idempotency and security boundaries
"""

import os
import pytest

from agent.core.models import (
    ConfidenceLevel,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCaseResult,
    TestCategory,
    TestSuiteReport,
)
from agent.debugging.evidence_collector import EvidenceCollector
from agent.debugging.localization_models import (
    DiagnosticHypothesis,
    FailureEvidence,
    RootCauseDiagnosis,
)
from agent.debugging.differential_diagnostician import DifferentialDiagnostician
from agent.debugging.repairer import CodeRepairer
from agent.debugging.root_cause_localizer import RootCauseLocalizer
from agent.memory.models import ExperienceRecommendation
from agent.memory.service import MemoryService
from agent.memory.sqlite_store import SQLiteMemoryStore
from agent.testing.engine import TestingEngine
from agent.core.orchestrator import SelfCorrectionOrchestrator


@pytest.fixture
def sample_problem():
    return ProblemSpec(
        id="two-sum",
        title="Two Sum",
        description="Find indices of two numbers that add up to target.",
        function_name="twoSum",
        param_names=["nums", "target"],
        return_type="List[int]",
        constraints=["2 <= nums.length <= 10^4"],
        test_cases=[
            TestCase(
                id="tc_1",
                inputs={"nums": [2, 7, 11, 15], "target": 9},
                expected_output=[0, 1],
                category=TestCategory.BASIC,
            ),
            TestCase(
                id="tc_edge",
                inputs={"nums": [3, 3], "target": 6},
                expected_output=[0, 1],
                category=TestCategory.DUPLICATE,
                is_edge_case=True,
            ),
        ],
    )


@pytest.fixture
def localizer():
    return RootCauseLocalizer()


# 1. Compiler-error localization
def test_compiler_error_localization(sample_problem, localizer):
    code = "class Solution:\n    def twoSum(self, nums, target)\n        return []\n"
    res = ExecutionResult(
        status=ExecutionStatus.COMPILE_ERROR,
        stderr='  File "solution.py", line 2\n    def twoSum(self, nums, target)\n                                  ^\nSyntaxError: expected \':\'',
        exit_code=1,
    )
    diag = localizer.diagnose(
        problem=sample_problem,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        exec_result=res,
    )
    assert diag is not None
    assert diag.failure_category == FailureCategory.COMPILE_ERROR
    assert diag.source_line == 2
    assert "Line 2" in diag.suspected_source_region
    assert diag.confidence >= 0.85
    assert len(diag.ranked_hypotheses) >= 1
    assert "Colon" in diag.ranked_hypotheses[0].title or "Syntax" in diag.ranked_hypotheses[0].title


# 2. Wrong-answer diagnosis
def test_wrong_answer_diagnosis(sample_problem, localizer):
    code = "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 0]\n"
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=2,
        passed_count=0,
        failed_count=2,
        execution_status=ExecutionStatus.WRONG_ANSWER,
        failed_test_results=[
            TestCaseResult(
                test_case_id="tc_1",
                passed=False,
                input_data={"nums": [2, 7, 11, 15], "target": 9},
                expected_output=[0, 1],
                actual_output=[0, 0],
                category=TestCategory.BASIC,
            ),
            TestCaseResult(
                test_case_id="tc_edge",
                passed=False,
                input_data={"nums": [3, 3], "target": 6},
                expected_output=[0, 1],
                actual_output=[0, 0],
                category=TestCategory.DUPLICATE,
            ),
        ],
    )
    diag = localizer.diagnose(
        problem=sample_problem,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        test_report=test_report,
    )
    assert diag is not None
    assert diag.failure_category in (FailureCategory.WRONG_ANSWER, FailureCategory.EDGE_CASE_FAILURE)
    assert diag.source_line is None  # Never fabricated when not provided
    assert len(diag.ranked_hypotheses) >= 1
    assert "Hash Table" in diag.ranked_hypotheses[0].title or "Logical" in diag.ranked_hypotheses[0].title


# 3. Runtime failure diagnosis
def test_runtime_failure_diagnosis(sample_problem, localizer):
    code = "class Solution:\n    def twoSum(self, nums, target):\n        return [nums[100], 0]\n"
    res = ExecutionResult(
        status=ExecutionStatus.RUNTIME_ERROR,
        stderr='Traceback (most recent call last):\n  File "solution.py", line 3, in twoSum\n    return [nums[100], 0]\nIndexError: list index out of range',
        exit_code=1,
    )
    diag = localizer.diagnose(
        problem=sample_problem,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        exec_result=res,
    )
    assert diag is not None
    assert diag.failure_category == FailureCategory.RUNTIME_ERROR
    assert diag.source_line == 3
    assert "Index Out of Bounds" in diag.ranked_hypotheses[0].title


# 4. Timeout diagnosis
def test_timeout_diagnosis(sample_problem, localizer):
    code = "class Solution:\n    def twoSum(self, nums, target):\n        while True:\n            pass\n"
    res = ExecutionResult(
        status=ExecutionStatus.TIMEOUT,
        execution_time_ms=2000.0,
        exit_code=-9,
    )
    diag = localizer.diagnose(
        problem=sample_problem,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        exec_result=res,
    )
    assert diag is not None
    assert diag.failure_category == FailureCategory.TIME_LIMIT_EXCEEDED
    assert diag.source_line is None
    assert "Infinite Loop" in diag.ranked_hypotheses[0].title


# 5. Boundary errors
def test_boundary_error_diagnosis(localizer):
    bs_prob = ProblemSpec(
        id="binary-search",
        title="Binary Search",
        description="Search target in sorted array.",
        function_name="search",
        param_names=["nums", "target"],
        return_type="int",
        test_cases=[],
    )
    code = """int search(int* nums, int numsSize, int target) {
    int left = 0, right = numsSize - 1;
    while (left < right) {
        int mid = (left + right) / 2;
        if (nums[mid] < target) left = mid;
        else right = mid;
    }
    return -1;
}"""
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=1,
        passed_count=0,
        failed_count=1,
        execution_status=ExecutionStatus.WRONG_ANSWER,
        failed_test_results=[
            TestCaseResult(
                test_case_id="tc_b1",
                passed=False,
                input_data={"nums": [5], "target": 5},
                expected_output=0,
                actual_output=-1,
                category=TestCategory.BOUNDARY,
            )
        ],
    )
    diag = localizer.diagnose(
        problem=bs_prob,
        source_code=code,
        language=SupportedLanguage.C,
        test_report=test_report,
    )
    assert diag is not None
    assert diag.failure_category == FailureCategory.EDGE_CASE_FAILURE
    assert "Binary Search Interval Update" in diag.ranked_hypotheses[0].title


# 6. Algorithmic complexity risks
def test_algorithmic_complexity_diagnosis(sample_problem, localizer):
    code = """class Solution:
    def twoSum(self, nums, target):
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                if nums[i] + nums[j] == target:
                    return [i, j]
        return []
"""
    res = ExecutionResult(
        status=ExecutionStatus.TIMEOUT,
        execution_time_ms=2500.0,
        exit_code=-9,
    )
    diag = localizer.diagnose(
        problem=sample_problem,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        exec_result=res,
    )
    assert diag is not None
    assert any("Complexity" in h.title for h in diag.ranked_hypotheses)


# 7. Language-specific implementation errors (C++ semicolon)
def test_cpp_semicolon_localization(localizer):
    prob = ProblemSpec(
        id="valid-parentheses",
        title="Valid Parentheses",
        description="Validate brackets.",
        function_name="isValid",
        param_names=["s"],
        return_type="bool",
        test_cases=[],
    )
    code = "#include <stack>\nusing namespace std;\nbool isValid(string s) {\n    stack<char> st\n    return true;\n}"
    res = ExecutionResult(
        status=ExecutionStatus.COMPILE_ERROR,
        compile_output="solution.cpp:4:19: error: expected ';' before 'return'",
        exit_code=1,
    )
    diag = localizer.diagnose(
        problem=prob,
        source_code=code,
        language=SupportedLanguage.CPP,
        exec_result=res,
    )
    assert diag is not None
    assert diag.source_line == 4
    assert diag.source_column == 19
    assert "Semicolon" in diag.ranked_hypotheses[0].title


# 8. Multiple competing hypotheses & Differential diagnosis
def test_competing_hypotheses_differential(sample_problem, localizer):
    code = "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 1]\n"
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=2,
        passed_count=1,
        failed_count=1,
        execution_status=ExecutionStatus.WRONG_ANSWER,
        failed_test_results=[
            TestCaseResult(
                test_case_id="tc_edge",
                passed=False,
                input_data={"nums": [3, 3], "target": 6},
                expected_output=[0, 1],
                actual_output=[0, 0],
                category=TestCategory.DUPLICATE,
            )
        ],
    )
    diag = localizer.diagnose(
        problem=sample_problem,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        test_report=test_report,
    )
    assert len(diag.ranked_hypotheses) >= 2


# 9. Confidence scoring calculation
def test_confidence_scoring_calculation(sample_problem, localizer):
    code = "class Solution:\n    def twoSum(self, nums, target):\n        1/0\n"
    res = ExecutionResult(
        status=ExecutionStatus.RUNTIME_ERROR,
        stderr='  File "sol.py", line 3, in twoSum\n    1/0\nZeroDivisionError: division by zero',
        exit_code=1,
    )
    diag = localizer.diagnose(
        problem=sample_problem,
        source_code=code,
        language=SupportedLanguage.PYTHON,
        exec_result=res,
    )
    assert 0.0 <= diag.confidence <= 1.0
    assert "Base score" in diag.confidence_calculation
    assert "Verified line" in diag.confidence_calculation


# 10. Missing or contradictory evidence
def test_missing_evidence_marking(sample_problem):
    ev = EvidenceCollector.collect(
        problem=sample_problem,
        source_code="pass",
        language=SupportedLanguage.PYTHON,
    )
    assert ev.compiler_diagnostics == "NOT_AVAILABLE"
    assert ev.failing_test_id == "NOT_AVAILABLE"
    assert ev.source_line is None


# 11. Irrelevant memory rejection
def test_irrelevant_memory_rejection(sample_problem, localizer):
    irrelevant_rec = ExperienceRecommendation(
        experience_id="exp_irr_1",
        problem_id="graph-shortest-path",
        relevance_score=0.1,
        pattern="Graph Traversal (BFS/DFS)",
        algorithm="Dijkstra's Algorithm",
        language=SupportedLanguage.PYTHON,
        verified=True,
        status="VERIFIED",
        useful_reason="Not related to two-sum",
        warning_notes=["Dijkstra edge weight must be positive"],
    )
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=1,
        passed_count=0,
        failed_count=1,
        execution_status=ExecutionStatus.WRONG_ANSWER,
        failed_test_results=[
            TestCaseResult(
                test_case_id="tc_1",
                passed=False,
                input_data={"nums": [2, 7], "target": 9},
                expected_output=[0, 1],
                actual_output=[0, 0],
            )
        ],
    )
    diag = localizer.diagnose(
        problem=sample_problem,
        source_code="def twoSum(): return [0, 0]",
        language=SupportedLanguage.PYTHON,
        test_report=test_report,
        retrieved_memories=[irrelevant_rec],
    )
    # Memory does not force a graph diagnosis onto two sum!
    assert "Dijkstra" not in diag.ranked_hypotheses[0].title


# 12. Infrastructure-error isolation
def test_infrastructure_error_isolation(sample_problem, localizer):
    res = ExecutionResult(
        status=ExecutionStatus.INFRASTRUCTURE_ERROR,
        stderr="Docker container socket connection refused",
        exit_code=127,
    )
    diag = localizer.diagnose(
        problem=sample_problem,
        source_code="pass",
        language=SupportedLanguage.PYTHON,
        exec_result=res,
    )
    assert diag.is_infrastructure_failure is True
    assert diag.failure_category == FailureCategory.ENVIRONMENT_ERROR
    assert "Host Toolchain" in diag.suspected_source_region
    assert diag.confidence == 1.0


# 13. Oracle-error isolation
def test_oracle_error_isolation(sample_problem, localizer):
    test_report = TestSuiteReport(
        all_passed=False,
        total_tests=1,
        passed_count=0,
        failed_count=1,
        execution_status=ExecutionStatus.RUNTIME_ERROR,
        oracle_failure_detected=True,
    )
    diag = localizer.diagnose(
        problem=sample_problem,
        source_code="pass",
        language=SupportedLanguage.PYTHON,
        test_report=test_report,
    )
    assert diag.is_oracle_failure is True
    assert diag.failure_category == FailureCategory.ORACLE_ERROR
    assert "Reference Oracle" in diag.suspected_source_region


# 14. Bounded diagnostic attempts
def test_bounded_diagnostic_attempts(sample_problem):
    diff_engine = DifferentialDiagnostician(max_differential_tests=2)
    hypotheses = [
        DiagnosticHypothesis(
            hypothesis_id="h1",
            title="Boundary Hypothesis",
            description="Boundary error",
            fault_category=FailureCategory.EDGE_CASE_FAILURE,
            confidence=0.8,
        ),
        DiagnosticHypothesis(
            hypothesis_id="h2",
            title="General Logic",
            description="General logic error",
            fault_category=FailureCategory.WRONG_ANSWER,
            confidence=0.7,
        ),
    ]
    ev = EvidenceCollector.collect(
        problem=sample_problem,
        source_code="def twoSum(): pass",
        language=SupportedLanguage.PYTHON,
    )
    outcomes = diff_engine.differentiate(
        problem=sample_problem,
        source_code="class Solution:\n    def twoSum(self, nums, target):\n        return []\n",
        language=SupportedLanguage.PYTHON,
        evidence=ev,
        hypotheses=hypotheses,
    )
    assert len(outcomes) <= 2


# 15. Repair integration
def test_repair_integration_with_diagnosis(sample_problem):
    repairer = CodeRepairer()
    code = "class Solution:\n    def twoSum(self, nums, target)\n        return []\n"
    from agent.core.models import AlgorithmPlan, CandidateApproach, DSAPattern
    plan = AlgorithmPlan(
        problem_id=sample_problem.id,
        identified_patterns=[DSAPattern.HASH_TABLE],
        candidate_approaches=[],
        selected_approach=CandidateApproach(
            name="Hash Map",
            data_structures=["dict"],
            time_complexity="O(N)",
            space_complexity="O(N)",
            description="One pass hash table",
            satisfies_constraints=True,
        ),
        justification="optimal",
        constraints_validated=True,
    )
    localizer = RootCauseLocalizer()
    res = ExecutionResult(
        status=ExecutionStatus.COMPILE_ERROR,
        stderr='  File "solution.py", line 2\n    def twoSum(self, nums, target)\nSyntaxError: invalid syntax',
        exit_code=1,
    )
    diag = localizer.diagnose(sample_problem, code, SupportedLanguage.PYTHON, exec_result=res)
    fixed_code, summary = repairer.repair(
        problem=sample_problem,
        plan=plan,
        current_code=code,
        failure_report=diag,
        language=SupportedLanguage.PYTHON,
        diagnosis=diag,
    )
    assert "def twoSum(self, nums, target):" in fixed_code
    assert "colon" in summary.lower()


# 16. Regression after repair in orchestrator
def test_regression_after_repair(sample_problem):
    orchestrator = SelfCorrectionOrchestrator(max_attempts=2)
    flawed_code = "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 0]\n"
    session = orchestrator.solve(
        problem=sample_problem,
        language=SupportedLanguage.PYTHON,
        override_initial_code=flawed_code,
        max_attempts=2,
    )
    assert session.is_verified is True
    assert len(session.attempt_history) >= 1


# 17. Multi-language compatibility (C, C++, Java, Python)
@pytest.mark.parametrize("lang", [SupportedLanguage.C, SupportedLanguage.CPP, SupportedLanguage.JAVA, SupportedLanguage.PYTHON])
def test_multilanguage_compatibility(sample_problem, localizer, lang):
    code = "// dummy"
    res = ExecutionResult(
        status=ExecutionStatus.COMPILE_ERROR,
        stderr=f"Error compiling in {lang.value}",
        exit_code=1,
    )
    diag = localizer.diagnose(sample_problem, code, lang, exec_result=res)
    assert diag.language == lang


# 18. Persistence and restart behavior
def test_persistence_restart_behavior(tmp_path):
    db_file = str(tmp_path / "test_memory.db")
    store = SQLiteMemoryStore(db_path=db_file)
    mem_service = MemoryService(store=store)

    prob = ProblemSpec(
        id="p1",
        title="Title",
        description="Desc",
        function_name="fn",
        param_names=["x"],
    )
    mem_service.record_problem(prob)

    # Re-instantiate from disk
    store2 = SQLiteMemoryStore(db_path=db_file)
    loaded = store2.get_problem("p1")
    assert loaded is not None
    assert loaded.problem_id == "p1"


# 19. Idempotency and security boundaries
def test_idempotency_and_security(sample_problem, localizer):
    code = "import os; os.system('ls')"
    # Code with security violation caught by validator
    from agent.generation.validator import CodeValidator
    val = CodeValidator.validate(code, SupportedLanguage.PYTHON)
    assert val.has_security_violation is True

    # Diagnosis on same input gives identical idempotent result
    res = ExecutionResult(status=ExecutionStatus.COMPILE_ERROR, stderr="syntax error", exit_code=1)
    d1 = localizer.diagnose(sample_problem, code, SupportedLanguage.PYTHON, exec_result=res)
    d2 = localizer.diagnose(sample_problem, code, SupportedLanguage.PYTHON, exec_result=res)
    assert d1.confidence == d2.confidence
    assert d1.ranked_hypotheses[0].hypothesis_id == d2.ranked_hypotheses[0].hypothesis_id
