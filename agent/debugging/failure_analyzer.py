"""
Deterministic Failure Analyzer & Root-Cause Classifier.
Parses compiler, runtime, timeout, and test failure evidence to produce
strongly typed, verifiable FailureReport objects.
"""

import re
from typing import List, Optional, Tuple
from agent.core.models import (
    ConfidenceLevel,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
    FailureReport,
    FailureSeverity,
    ProblemSpec,
    RootCauseHypothesis,
    SupportedLanguage,
    TestCaseResult,
    TestSuiteReport,
)



class FailureAnalyzer:
    """
    Deterministic failure diagnostics engine.
    Extracts line numbers, maps error traces, separates infrastructure/oracle bugs from
    solution bugs, and formulates ranked hypotheses based on concrete evidence.
    """

    @classmethod
    def analyze(
        cls,
        problem: ProblemSpec,
        source_code: str,
        language: SupportedLanguage,
        test_report: Optional[TestSuiteReport] = None,
        exec_result: Optional[ExecutionResult] = None,
    ) -> Optional[FailureReport]:
        """
        Main analysis entrypoint.
        Returns None if all tests passed and no failure was observed.
        """
        # 1. Check if all tests passed
        if test_report and test_report.all_passed:
            return None
        if exec_result and exec_result.status == ExecutionStatus.SUCCESS:
            return None

        # Prefer test_report raw execution result if available
        raw_res = (test_report.raw_execution_result if test_report else None) or exec_result
        failed_tests = test_report.failed_test_results if test_report else (raw_res.test_results if raw_res else [])

        # 2. Check for INFRASTRUCTURE or ORACLE failure
        if raw_res and raw_res.status == ExecutionStatus.INFRASTRUCTURE_ERROR:
            return cls._analyze_infrastructure_failure(problem, raw_res)

        if test_report and test_report.oracle_failure_detected:
            return cls._analyze_oracle_failure(problem, test_report)

        # 3. Check for COMPILATION / SYNTAX failure
        if raw_res and raw_res.status == ExecutionStatus.COMPILE_ERROR:
            return cls._analyze_compilation_failure(problem, source_code, language, raw_res)

        # 4. Check for TIMEOUT / TLE
        if raw_res and raw_res.status == ExecutionStatus.TIMEOUT:
            return cls._analyze_timeout_failure(problem, source_code, raw_res, failed_tests)

        # 5. Check for RUNTIME / EXCEPTION failure
        runtime_failures = [t for t in failed_tests if t.error_message]
        if runtime_failures or (raw_res and raw_res.status == ExecutionStatus.RUNTIME_ERROR):
            return cls._analyze_runtime_failure(problem, source_code, language, raw_res, runtime_failures)

        # 6. Check for WRONG ANSWER / Output Mismatch
        mismatch_tests = [t for t in failed_tests if not t.passed and not t.error_message]
        if mismatch_tests:
            return cls._analyze_wrong_answer(problem, source_code, mismatch_tests)

        # 7. Fallback: Insufficient Evidence
        return FailureReport(
            failure_id=f"fail_{problem.id}_unknown",
            failure_category=FailureCategory.UNKNOWN_FAILURE,
            severity=FailureSeverity.LOW,
            affected_test_ids=[t.test_case_id for t in failed_tests],
            uncertainty_notes=["Execution failed but output did not contain actionable compiler, runtime, or test discrepancy data."],
            ranked_hypotheses=[
                RootCauseHypothesis(
                    hypothesis="Insufficient diagnostic evidence available to classify failure",
                    confidence=ConfidenceLevel.UNKNOWN,
                    supporting_evidence=["Non-zero exit code with empty stderr and stdout"],
                )
            ],
            recommended_diagnostic_direction="Run with increased logging or verify environment stability.",
        )

    # --- INFRASTRUCTURE & ORACLE DIAGNOSTICS ---
    @classmethod
    def _analyze_infrastructure_failure(cls, problem: ProblemSpec, res: ExecutionResult) -> FailureReport:
        return FailureReport(
            failure_id=f"fail_{problem.id}_infra",
            failure_category=FailureCategory.ENVIRONMENT_ERROR,
            severity=FailureSeverity.CRITICAL,
            is_infrastructure_failure=True,
            error_message=res.error_detail or res.stderr,
            exit_code=res.exit_code,
            ranked_hypotheses=[
                RootCauseHypothesis(
                    hypothesis="Host execution environment or toolchain is unavailable or misconfigured",
                    confidence=ConfidenceLevel.EXPLICIT,
                    supporting_evidence=[res.error_detail or "Toolchain absent from PATH"],
                )
            ],
            recommended_diagnostic_direction="Install or configure the missing compiler/runtime toolchain.",
        )

    @classmethod
    def _analyze_oracle_failure(cls, problem: ProblemSpec, report: TestSuiteReport) -> FailureReport:
        return FailureReport(
            failure_id=f"fail_{problem.id}_oracle",
            failure_category=FailureCategory.ORACLE_ERROR,
            severity=FailureSeverity.CRITICAL,
            is_infrastructure_failure=True,
            error_message="Reference solution or oracle failed during evaluation.",
            ranked_hypotheses=[
                RootCauseHypothesis(
                    hypothesis="Trusted reference algorithm threw an unhandled exception on generated input",
                    confidence=ConfidenceLevel.EXPLICIT,
                    supporting_evidence=report.notes,
                )
            ],
            recommended_diagnostic_direction="Inspect and patch the reference oracle implementation.",
        )

    # --- COMPILATION DIAGNOSTICS ---
    @classmethod
    def _analyze_compilation_failure(
        cls, problem: ProblemSpec, source: str, lang: SupportedLanguage, res: ExecutionResult
    ) -> FailureReport:
        line_num, err_msg = cls._extract_compiler_line(res.stderr or res.stdout or "", lang)
        excerpt = cls._extract_excerpt(source, line_num) if line_num else None

        hypotheses = [
            RootCauseHypothesis(
                hypothesis="Syntax or compilation typing error preventing binary/bytecode generation",
                confidence=ConfidenceLevel.EXPLICIT,
                supporting_evidence=[f"Compiler reported: {err_msg}" if err_msg else "Non-zero compiler exit code"],
            )
        ]

        return FailureReport(
            failure_id=f"fail_{problem.id}_compile",
            failure_category=FailureCategory.COMPILE_ERROR,
            severity=FailureSeverity.CRITICAL,
            error_message=err_msg or res.error_detail,
            exit_code=res.exit_code,
            source_line=line_num,
            source_excerpt=excerpt,
            ranked_hypotheses=hypotheses,
            recommended_diagnostic_direction=f"Fix syntax error at line {line_num or 'indicated in compiler log'}.",
        )

    # --- TIMEOUT DIAGNOSTICS ---
    @classmethod
    def _analyze_timeout_failure(
        cls, problem: ProblemSpec, source: str, res: ExecutionResult, failed_tests: List[TestCaseResult]
    ) -> FailureReport:
        hypotheses = [
            RootCauseHypothesis(
                hypothesis="Infinite loop: while/for loop condition fails to terminate",
                confidence=ConfidenceLevel.INFERRED,
                supporting_evidence=[f"Process was terminated by watchdog after {res.execution_time_ms:.0f}ms"],
            ),
            RootCauseHypothesis(
                hypothesis="Asymptotic complexity too slow: algorithm performs more operations than CPU time permits",
                confidence=ConfidenceLevel.INFERRED,
                supporting_evidence=["Execution timed out under active input limits"],
            ),
        ]

        return FailureReport(
            failure_id=f"fail_{problem.id}_timeout",
            failure_category=FailureCategory.TIME_LIMIT_EXCEEDED,
            severity=FailureSeverity.HIGH,
            error_message=res.error_detail or "Time limit exceeded.",
            exit_code=res.exit_code,
            ranked_hypotheses=hypotheses,
            affected_test_ids=[t.test_case_id for t in failed_tests],
            recommended_diagnostic_direction="Check loop invariant updates (e.g. pointer increments) or optimize complexity.",
        )

    # --- RUNTIME DIAGNOSTICS ---
    @classmethod
    def _analyze_runtime_failure(
        cls,
        problem: ProblemSpec,
        source: str,
        lang: SupportedLanguage,
        res: Optional[ExecutionResult],
        failures: List[TestCaseResult],
    ) -> FailureReport:
        first_fail = failures[0] if failures else None
        err_text = (first_fail.error_message if first_fail else "") or (res.stderr if res else "")

        line_num = cls._extract_runtime_line(err_text, lang)
        excerpt = cls._extract_excerpt(source, line_num) if line_num else None

        # Determine exception category
        hypotheses = []
        if "IndexError" in err_text or "ArrayIndexOutOfBoundsException" in err_text:
            hypotheses.append(RootCauseHypothesis(
                hypothesis="Array index out of bounds (off-by-one or unchecked array size)",
                confidence=ConfidenceLevel.EXPLICIT,
                supporting_evidence=[err_text.splitlines()[0]],
            ))
        elif "ZeroDivisionError" in err_text or "ArithmeticException" in err_text:
            hypotheses.append(RootCauseHypothesis(
                hypothesis="Division or modulo by zero",
                confidence=ConfidenceLevel.EXPLICIT,
                supporting_evidence=[err_text.splitlines()[0]],
            ))
        elif "NullPointerException" in err_text or "AttributeError: 'NoneType'" in err_text:
            hypotheses.append(RootCauseHypothesis(
                hypothesis="Dereferencing null pointer or NoneType object",
                confidence=ConfidenceLevel.EXPLICIT,
                supporting_evidence=[err_text.splitlines()[0]],
            ))
        else:
            if not err_text or not err_text.strip():
                return FailureReport(
                    failure_id=f"fail_{problem.id}_unknown",
                    failure_category=FailureCategory.UNKNOWN_FAILURE,
                    severity=FailureSeverity.LOW,
                    uncertainty_notes=["Process exited with non-zero exit code but without stderr or diagnostic traceback."],
                    ranked_hypotheses=[
                        RootCauseHypothesis(
                            hypothesis="Insufficient diagnostic evidence available to classify failure",
                            confidence=ConfidenceLevel.UNKNOWN,
                            supporting_evidence=["Non-zero exit code with empty stderr and stdout"],
                        )
                    ],
                    recommended_diagnostic_direction="Run with increased logging or verify environment stability.",
                )
            hypotheses.append(RootCauseHypothesis(
                hypothesis="Unhandled runtime exception",
                confidence=ConfidenceLevel.INFERRED,
                supporting_evidence=[err_text.splitlines()[0]],
            ))

        return FailureReport(
            failure_id=f"fail_{problem.id}_runtime",
            failure_category=FailureCategory.RUNTIME_ERROR,
            severity=FailureSeverity.HIGH,
            affected_test_ids=[t.test_case_id for t in failures],
            sample_failing_input=first_fail.input_data if first_fail else None,
            expected_output=first_fail.expected_output if first_fail else None,
            actual_output=None,
            error_message=err_text,
            source_line=line_num,
            source_excerpt=excerpt,
            ranked_hypotheses=hypotheses,
            recommended_diagnostic_direction=f"Inspect line {line_num or 'stack trace'} and add boundary or null checks.",
        )

    # --- WRONG ANSWER DIAGNOSTICS ---
    @classmethod
    def _analyze_wrong_answer(
        cls, problem: ProblemSpec, source: str, mismatch_tests: List[TestCaseResult]
    ) -> FailureReport:
        first = mismatch_tests[0]
        hypotheses: List[RootCauseHypothesis] = []

        # Multi-test comparison: inspect if failure is tied to specific category
        categories = {t.category.value for t in mismatch_tests if t.category}

        if "duplicate" in categories:
            hypotheses.append(RootCauseHypothesis(
                hypothesis="Duplicate values handling: duplicate elements overwrite or collide in lookup table",
                confidence=ConfidenceLevel.INFERRED,
                supporting_evidence=["Fails on test cases with duplicate values"],
            ))
        elif "boundary" in categories or "single_element" in categories:
            hypotheses.append(RootCauseHypothesis(
                hypothesis="Boundary condition handling: edge-case array size (e.g. minimum size) not correctly guarded",
                confidence=ConfidenceLevel.INFERRED,
                supporting_evidence=["Fails on boundary array sizes"],
            ))
        else:
            hypotheses.append(RootCauseHypothesis(
                hypothesis="Logical calculation or return mapping error: algorithm produces wrong output value",
                confidence=ConfidenceLevel.INFERRED,
                supporting_evidence=[f"Expected {first.expected_output} but got {first.actual_output}"],
            ))
            hypotheses.append(RootCauseHypothesis(
                hypothesis="Off-by-one indexing error in pointer manipulation or loop boundaries",
                confidence=ConfidenceLevel.INFERRED,
                supporting_evidence=["Common source of index discrepancies in arrays"],
            ))

        return FailureReport(
            failure_id=f"fail_{problem.id}_wa",
            failure_category=FailureCategory.WRONG_ANSWER,
            severity=FailureSeverity.MEDIUM,
            affected_test_ids=[t.test_case_id for t in mismatch_tests],
            sample_failing_input=first.input_data,
            expected_output=first.expected_output,
            actual_output=first.actual_output,
            ranked_hypotheses=hypotheses,
            recommended_diagnostic_direction="Compare logic against failing input fixture and check boundary conditions.",
        )

    # --- DETERMINISTIC LINE & EXCERPT EXTRACTION ---
    @classmethod
    def _extract_compiler_line(cls, text: str, lang: SupportedLanguage) -> Tuple[Optional[int], Optional[str]]:
        """Extracts (line_number, error_message) from compiler stderr."""
        # Python: File "...", line 12
        py_match = re.search(r'line\s+(\d+)(?:,\s*in|\n|\s)', text)
        if py_match:
            return int(py_match.group(1)), text.strip()

        # GCC / Clang: file.cpp:14:5: error: ...
        gcc_match = re.search(r':(\d+):\d+:\s*(?:fatal\s+)?error:\s*(.*)', text)
        if gcc_match:
            return int(gcc_match.group(1)), gcc_match.group(2).strip()

        # Java: SolutionHarness.java:18: error: ...
        java_match = re.search(r'\.java:(\d+):\s*error:\s*(.*)', text)
        if java_match:
            return int(java_match.group(1)), java_match.group(2).strip()

        return None, text.strip() if text else None

    @classmethod
    def _extract_runtime_line(cls, text: str, lang: SupportedLanguage) -> Optional[int]:
        """Extracts source line from runtime traceback."""
        matches = re.findall(r'line\s+(\d+)', text)
        if matches:
            # Return last line in stack trace (deepest call)
            return int(matches[-1])

        java_matches = re.findall(r'Solution\.java:(\d+)', text)
        if java_matches:
            return int(java_matches[-1])

        return None

    @classmethod
    def _extract_excerpt(cls, source: str, line_num: int, context_lines: int = 2) -> str:
        """Extracts code excerpt centered at line_num with line prefixes."""
        lines = source.splitlines()
        start = max(0, line_num - 1 - context_lines)
        end = min(len(lines), line_num + context_lines)

        excerpt_lines = []
        for i in range(start, end):
            prefix = "-> " if (i + 1 == line_num) else "   "
            excerpt_lines.append(f"{prefix}{i + 1:3d}: {lines[i]}")
        return "\n".join(excerpt_lines)
