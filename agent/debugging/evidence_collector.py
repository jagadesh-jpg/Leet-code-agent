"""
Stage 22: Evidence Collector.
Extracts empirical evidence from compiler, execution, test reports, and attempts.
Missing evidence is explicitly marked UNKNOWN or NOT_AVAILABLE; never fabricated.
"""

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from agent.core.models import (
    ExecutionResult,
    ExecutionStatus,
    ProblemSpec,
    SupportedLanguage,
    TestCaseResult,
    TestSuiteReport,
)
from agent.debugging.localization_models import FailureEvidence


class EvidenceCollector:
    """
    Collects real, unadulterated evidence for a failed solution candidate.
    Extracts line/column numbers only when genuinely provided by the compiler or runtime traceback.
    """

    @classmethod
    def collect(
        cls,
        problem: ProblemSpec,
        source_code: str,
        language: SupportedLanguage,
        attempt_id: str = "attempt_1",
        previous_repair_attempts: int = 0,
        test_report: Optional[TestSuiteReport] = None,
        exec_result: Optional[ExecutionResult] = None,
        regression_results: Optional[List[str]] = None,
        memory_prior_failures: Optional[List[str]] = None,
    ) -> FailureEvidence:
        source_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()[:16]

        raw_res = (test_report.raw_execution_result if test_report else None) or exec_result
        failed_tests = test_report.failed_test_results if test_report else (raw_res.test_results if raw_res else [])
        first_fail: Optional[TestCaseResult] = failed_tests[0] if failed_tests else None

        failing_test_id = first_fail.test_case_id if first_fail else "NOT_AVAILABLE"
        failing_test_cat = (
            first_fail.category.value if (first_fail and first_fail.category) else "UNKNOWN"
        )
        actual_input = first_fail.input_data if first_fail else None
        expected_output = first_fail.expected_output if first_fail else None
        actual_output = first_fail.actual_output if first_fail else None

        # Compiler diagnostics & stderr
        compiler_diag = "NOT_AVAILABLE"
        stderr_val = "NOT_AVAILABLE"
        stdout_val = "NOT_AVAILABLE"
        exit_code = raw_res.exit_code if raw_res else None
        is_timeout = False
        is_memory_limit = False

        if raw_res:
            if raw_res.compile_output:
                compiler_diag = raw_res.compile_output.strip()
            elif raw_res.status == ExecutionStatus.COMPILE_ERROR and raw_res.stderr:
                compiler_diag = raw_res.stderr.strip()

            if raw_res.stderr:
                stderr_val = raw_res.stderr.strip()
            if raw_res.stdout:
                stdout_val = raw_res.stdout.strip()

            if raw_res.status == ExecutionStatus.TIMEOUT:
                is_timeout = True

            if (
                raw_res.status == ExecutionStatus.RUNTIME_ERROR
                and raw_res.error_detail
                and "memory" in raw_res.error_detail.lower()
            ):
                is_memory_limit = True

        # Extract real source line, column, and excerpt
        line_num, col_num = cls._extract_diagnostic_location(
            compiler_diag if compiler_diag != "NOT_AVAILABLE" else stderr_val,
            language,
        )
        excerpt = cls._extract_excerpt(source_code, line_num) if line_num is not None else None

        # Check infrastructure / oracle status
        is_infra = False
        is_oracle = False
        if raw_res and raw_res.status == ExecutionStatus.INFRASTRUCTURE_ERROR:
            is_infra = True
        if test_report and test_report.oracle_failure_detected:
            is_oracle = True

        return FailureEvidence(
            problem_id=problem.id,
            language=language,
            source_code_hash=source_hash,
            attempt_id=attempt_id,
            failing_test_id=failing_test_id,
            failing_test_category=failing_test_cat,
            actual_input=actual_input,
            expected_output=expected_output,
            actual_output=actual_output,
            compiler_diagnostics=compiler_diag,
            stderr=stderr_val,
            stdout=stdout_val,
            exit_code=exit_code,
            is_timeout=is_timeout,
            is_memory_limit=is_memory_limit,
            source_line=line_num,
            source_column=col_num,
            source_excerpt=excerpt,
            previous_repair_attempts=previous_repair_attempts,
            regression_results=regression_results or [],
            memory_prior_failures=memory_prior_failures or [],
            is_infrastructure_failure=is_infra,
            is_oracle_failure=is_oracle,
        )

    @classmethod
    def _extract_diagnostic_location(
        cls, diag_text: str, language: SupportedLanguage
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        Parses genuine line and column from compiler logs or runtime stack traces.
        Never guesses or fabricates locations.
        """
        if not diag_text or diag_text == "NOT_AVAILABLE":
            return None, None

        # GCC / Clang format: file:line:col: error: ...
        gcc_match = re.search(r':(\d+):(\d+):\s*(?:fatal\s+)?error:', diag_text)
        if gcc_match:
            return int(gcc_match.group(1)), int(gcc_match.group(2))

        # Java compiler format: SolutionHarness.java:18: error:
        java_compile_match = re.search(r'\.java:(\d+):\s*error:', diag_text)
        if java_compile_match:
            return int(java_compile_match.group(1)), None

        # Python syntax / traceback format: File "...", line 12, in ...
        py_match = re.search(r'line\s+(\d+)(?:,\s*in|\n|\s|$)', diag_text)
        if py_match:
            return int(py_match.group(1)), None

        # Java runtime stack trace: at Solution.method(Solution.java:25)
        java_rt_match = re.search(r'Solution\.java:(\d+)\)', diag_text)
        if java_rt_match:
            return int(java_rt_match.group(1)), None

        return None, None

    @classmethod
    def _extract_excerpt(
        cls, source: str, line_num: int, context_lines: int = 2
    ) -> Optional[str]:
        lines = source.splitlines()
        if not lines or line_num <= 0 or line_num > len(lines):
            return None

        start = max(0, line_num - 1 - context_lines)
        end = min(len(lines), line_num + context_lines)

        excerpt_lines = []
        for i in range(start, end):
            prefix = "-> " if (i + 1 == line_num) else "   "
            excerpt_lines.append(f"{prefix}{i + 1:3d}: {lines[i]}")
        return "\n".join(excerpt_lines)
