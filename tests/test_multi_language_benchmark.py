"""
Stage 17 Focused Test Suite: Multi-Language Generalization and Cross-Language Verification.

Verifies:
1. Language registry and adapter binding for C, C++, Java, Python.
2. Real toolchain availability on host.
3. Real C compilation and execution.
4. Real C++ compilation and execution.
5. Real Java compilation and execution.
6. Real Python execution.
7. Same problem across all 4 languages produces identical semantic results.
8. Language-specific code generation adheres to common ProblemSpec.
9. Correctness verification gates across all 4 languages.
10. Complexity verification across all 4 languages.
11. Constraint validation across all 4 languages.
12. Intentional failure detection in C, C++, Java, and Python.
13. Autonomous self-correction loop in C, C++, Java, and Python.
14. Infrastructure failure isolation.
15. Cross-language result consistency and equivalence.
16. Benchmark matrix aggregation.
17. Verifier certification gates prevent false positives.
"""

import os
import pytest
from pathlib import Path

from agent.core.models import (
    AgentState,
    AlgorithmPlan,
    CandidateApproach,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    VerificationStatus,
)
from agent.execution.c_cpp_adapters import CAdapter, CppAdapter
from agent.execution.java_adapter import JavaAdapter
from agent.execution.python_adapter import PythonAdapter
from agent.execution.runner import ExecutionRunner
from agent.planning.pattern_classifier import PatternClassifier
from agent.planning.planner import AlgorithmPlanner
from agent.testing.engine import TestingEngine
from agent.verification.verifier import SolutionVerifier
from agent.core.orchestrator import SelfCorrectionOrchestrator
from agent.benchmarking.benchmark_registry import BENCHMARK_REGISTRY, to_problem_spec
from agent.benchmarking.multi_language_runner import (
    MULTI_LANG_CODE,
    INTENTIONAL_FLAWS,
    MultiLanguageBenchmarkRunner,
)


@pytest.fixture
def two_sum_spec() -> ProblemSpec:
    return to_problem_spec(BENCHMARK_REGISTRY["two-sum"])


@pytest.fixture
def binary_search_spec() -> ProblemSpec:
    return to_problem_spec(BENCHMARK_REGISTRY["binary-search"])


# 1. Language Registry
def test_1_language_registry():
    runner = ExecutionRunner()
    for lang in [SupportedLanguage.C, SupportedLanguage.CPP, SupportedLanguage.JAVA, SupportedLanguage.PYTHON]:
        adapter = runner.get_adapter(lang)
        assert adapter is not None
        assert adapter.language == lang


# 2. Toolchain Availability
def test_2_toolchain_availability():
    c_adapter = CAdapter()
    cpp_adapter = CppAdapter()
    java_adapter = JavaAdapter()
    python_adapter = PythonAdapter()

    assert c_adapter.is_toolchain_available() is True, "C compiler (gcc) must be available on host"
    assert cpp_adapter.is_toolchain_available() is True, "C++ compiler (g++) must be available on host"
    assert java_adapter.is_toolchain_available() is True, "Java toolchain (javac/java) must be available on host"
    assert python_adapter.is_toolchain_available() is True, "Python interpreter must be available on host"


# 3. Real C Compilation & Execution
def test_3_c_compilation_and_execution(binary_search_spec):
    runner = ExecutionRunner(timeout_seconds=5.0)
    code = MULTI_LANG_CODE["binary-search"][SupportedLanguage.C]
    res = runner.run(binary_search_spec, code, SupportedLanguage.C)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.exit_code == 0
    assert len(res.test_results) == len(binary_search_spec.test_cases)
    assert all(t.passed for t in res.test_results)


# 4. Real C++ Compilation & Execution
def test_4_cpp_compilation_and_execution(binary_search_spec):
    runner = ExecutionRunner(timeout_seconds=5.0)
    code = MULTI_LANG_CODE["binary-search"][SupportedLanguage.CPP]
    res = runner.run(binary_search_spec, code, SupportedLanguage.CPP)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.exit_code == 0
    assert len(res.test_results) == len(binary_search_spec.test_cases)
    assert all(t.passed for t in res.test_results)


# 5. Real Java Compilation & Execution
def test_5_java_compilation_and_execution(binary_search_spec):
    runner = ExecutionRunner(timeout_seconds=5.0)
    code = MULTI_LANG_CODE["binary-search"][SupportedLanguage.JAVA]
    res = runner.run(binary_search_spec, code, SupportedLanguage.JAVA)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.exit_code == 0
    assert len(res.test_results) == len(binary_search_spec.test_cases)
    assert all(t.passed for t in res.test_results)


# 6. Real Python Execution
def test_6_python_execution(binary_search_spec):
    runner = ExecutionRunner(timeout_seconds=5.0)
    code = MULTI_LANG_CODE["binary-search"][SupportedLanguage.PYTHON]
    res = runner.run(binary_search_spec, code, SupportedLanguage.PYTHON)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.exit_code == 0
    assert len(res.test_results) == len(binary_search_spec.test_cases)
    assert all(t.passed for t in res.test_results)


# 7. Same Problem Across All Four Languages
def test_7_same_problem_across_four_languages(two_sum_spec):
    runner = ExecutionRunner(timeout_seconds=5.0)
    for lang in [SupportedLanguage.C, SupportedLanguage.CPP, SupportedLanguage.JAVA, SupportedLanguage.PYTHON]:
        code = MULTI_LANG_CODE["two-sum"][lang]
        res = runner.run(two_sum_spec, code, lang)
        assert res.status == ExecutionStatus.SUCCESS, f"Execution failed for language {lang.value}"
        assert res.exit_code == 0
        assert all(t.passed for t in res.test_results)


# 8. Language-Specific Code Generation Adheres to Common Spec
def test_8_language_independent_analysis_and_planning(two_sum_spec):
    # Pattern classification and algorithm planning run once
    patterns = PatternClassifier.classify(two_sum_spec)
    assert len(patterns) > 0
    plan = AlgorithmPlanner().plan(two_sum_spec)
    assert plan.selected_approach is not None
    assert "Hash" in plan.selected_approach.name or "Map" in plan.selected_approach.name
    assert plan.selected_approach.time_complexity in ("O(N)", "O(n)")


# 9. Correctness Verification Across Languages
def test_9_correctness_verification(two_sum_spec):
    te = TestingEngine()
    plan = AlgorithmPlanner().plan(two_sum_spec)
    verifier = SolutionVerifier(te)
    for lang in [SupportedLanguage.C, SupportedLanguage.CPP, SupportedLanguage.JAVA, SupportedLanguage.PYTHON]:
        code = MULTI_LANG_CODE["two-sum"][lang]
        rep = te.evaluate_solution(two_sum_spec, code, lang)
        vr = verifier.verify_solution(two_sum_spec, code, lang, plan, rep)
        assert vr.final_verification_status == VerificationStatus.VERIFIED
        assert vr.is_fully_certified is True
        assert vr.tests_failed == 0


# 10. Complexity Verification Across Languages
def test_10_complexity_verification(binary_search_spec):
    te = TestingEngine()
    plan = AlgorithmPlanner().plan(binary_search_spec)
    verifier = SolutionVerifier(te)
    for lang in [SupportedLanguage.C, SupportedLanguage.CPP, SupportedLanguage.JAVA, SupportedLanguage.PYTHON]:
        code = MULTI_LANG_CODE["binary-search"][lang]
        rep = te.evaluate_solution(binary_search_spec, code, lang)
        vr = verifier.verify_solution(binary_search_spec, code, lang, plan, rep)
        assert vr.complexity_audit.plan_implementation_consistent is True
        assert vr.is_fully_certified is True


# 11. Constraint Verification Across Languages
def test_11_constraint_verification(two_sum_spec):
    verifier = SolutionVerifier()
    plan = AlgorithmPlanner().plan(two_sum_spec)
    for lang in [SupportedLanguage.C, SupportedLanguage.CPP, SupportedLanguage.JAVA, SupportedLanguage.PYTHON]:
        code = MULTI_LANG_CODE["two-sum"][lang]
        audit = verifier.auditor.audit(code, lang, plan, two_sum_spec)
        compat = verifier.auditor.evaluate_constraint_compatibility(audit.inferred_time_complexity, two_sum_spec)
        assert compat.compatible is True


# 12. Intentional Failure Detection Across All 4 Languages
def test_12_intentional_failure_detection():
    te = TestingEngine()
    # C flaw
    bs_spec = to_problem_spec(BENCHMARK_REGISTRY["binary-search"])
    c_flaw, _ = INTENTIONAL_FLAWS[("binary-search", SupportedLanguage.C)]
    c_rep = te.evaluate_solution(bs_spec, c_flaw, SupportedLanguage.C)
    assert not c_rep.all_passed

    # C++ flaw (compile error)
    vp_spec = to_problem_spec(BENCHMARK_REGISTRY["valid-parentheses"])
    cpp_flaw, _ = INTENTIONAL_FLAWS[("valid-parentheses", SupportedLanguage.CPP)]
    cpp_rep = te.evaluate_solution(vp_spec, cpp_flaw, SupportedLanguage.CPP)
    assert not cpp_rep.all_passed
    assert cpp_rep.execution_status == ExecutionStatus.COMPILE_ERROR

    # Java flaw (wrong answer)
    ts_spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    java_flaw, _ = INTENTIONAL_FLAWS[("two-sum", SupportedLanguage.JAVA)]
    java_rep = te.evaluate_solution(ts_spec, java_flaw, SupportedLanguage.JAVA)
    assert not java_rep.all_passed

    # Python flaw (wrong answer)
    py_flaw, _ = INTENTIONAL_FLAWS[("two-sum", SupportedLanguage.PYTHON)]
    py_rep = te.evaluate_solution(ts_spec, py_flaw, SupportedLanguage.PYTHON)
    assert not py_rep.all_passed


# 13. Autonomous Self-Correction Loop in All 4 Languages
def test_13_self_correction_across_four_languages():
    orchestrator = SelfCorrectionOrchestrator(max_attempts=3)

    # C self-correction
    bs_spec = to_problem_spec(BENCHMARK_REGISTRY["binary-search"])
    c_flaw, _ = INTENTIONAL_FLAWS[("binary-search", SupportedLanguage.C)]
    c_session = orchestrator.solve(bs_spec, SupportedLanguage.C, override_initial_code=c_flaw)
    assert c_session.is_verified is True
    assert len(c_session.attempt_history) >= 1

    # C++ self-correction
    vp_spec = to_problem_spec(BENCHMARK_REGISTRY["valid-parentheses"])
    cpp_flaw, _ = INTENTIONAL_FLAWS[("valid-parentheses", SupportedLanguage.CPP)]
    cpp_session = orchestrator.solve(vp_spec, SupportedLanguage.CPP, override_initial_code=cpp_flaw)
    assert cpp_session.is_verified is True
    assert len(cpp_session.attempt_history) >= 1

    # Java self-correction
    ts_spec = to_problem_spec(BENCHMARK_REGISTRY["two-sum"])
    java_flaw, _ = INTENTIONAL_FLAWS[("two-sum", SupportedLanguage.JAVA)]
    java_session = orchestrator.solve(ts_spec, SupportedLanguage.JAVA, override_initial_code=java_flaw)
    assert java_session.is_verified is True
    assert len(java_session.attempt_history) >= 1

    # Python self-correction
    py_flaw, _ = INTENTIONAL_FLAWS[("two-sum", SupportedLanguage.PYTHON)]
    py_session = orchestrator.solve(ts_spec, SupportedLanguage.PYTHON, override_initial_code=py_flaw)
    assert py_session.is_verified is True
    assert len(py_session.attempt_history) >= 1


# 14. Infrastructure Failure Isolation
def test_14_infrastructure_failure_isolation(two_sum_spec):
    # Simulated missing compiler should report INFRASTRUCTURE_ERROR without code repair
    adapter = CppAdapter(compiler_path=r"C:\non_existent_path\fake_g++.exe")
    runner = ExecutionRunner()
    runner.register_adapter(adapter)
    res = runner.run(two_sum_spec, "class Solution {};", SupportedLanguage.CPP)
    assert res.status == ExecutionStatus.INFRASTRUCTURE_ERROR
    assert res.failure_category == FailureCategory.ENVIRONMENT_ERROR


# 15. Cross-Language Result Consistency
def test_15_cross_language_result_consistency(binary_search_spec):
    runner = ExecutionRunner(timeout_seconds=5.0)
    outputs = {}
    for lang in [SupportedLanguage.C, SupportedLanguage.CPP, SupportedLanguage.JAVA, SupportedLanguage.PYTHON]:
        code = MULTI_LANG_CODE["binary-search"][lang]
        res = runner.run(binary_search_spec, code, lang)
        outputs[lang] = [t.actual_output for t in res.test_results]

    # Compare results across all languages
    c_out = outputs[SupportedLanguage.C]
    assert outputs[SupportedLanguage.CPP] == c_out
    assert outputs[SupportedLanguage.JAVA] == c_out
    assert outputs[SupportedLanguage.PYTHON] == c_out


# 16. Benchmark Matrix Aggregation
def test_16_benchmark_matrix_aggregation():
    runner = MultiLanguageBenchmarkRunner()
    # Run a quick 2-problem matrix
    results = runner.run_multi_language_matrix(four_lang_problems=["valid-palindrome", "max-subarray"])
    assert len(results) >= 8
    assert all(r.final_status == "PASSED" for r in results)


# 17. Certification Gates
def test_17_certification_gates_prevent_false_positives(two_sum_spec):
    verifier = SolutionVerifier()
    plan = AlgorithmPlanner().plan(two_sum_spec)
    # Flawed solution that fails
    report = verifier.verify_solution(
        problem=two_sum_spec,
        source_code="""class Solution:
    def twoSum(self, nums, target): return [0, 0]""",
        language=SupportedLanguage.PYTHON,
        plan=plan,
        rerun_regression_if_needed=True,
    )
    assert report.is_fully_certified is False
    assert report.final_verification_status != VerificationStatus.VERIFIED
