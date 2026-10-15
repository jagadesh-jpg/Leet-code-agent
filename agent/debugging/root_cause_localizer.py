"""
Stage 22: Evidence-Driven Root-Cause Localizer & Diagnostic Engine.
Synthesizes compiler diagnostics, runtime traces, structural code analysis,
adaptive test outcomes, and historical memory into ranked diagnostic hypotheses.
Calculates documented confidence scores and isolates infrastructure/oracle errors.
"""

import re
from typing import List, Optional, Tuple

from agent.core.models import (
    ConfidenceLevel,
    DSAPattern,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
    FailureSeverity,
    ProblemSpec,
    SupportedLanguage,
    TestSuiteReport,
)
from agent.debugging.evidence_collector import EvidenceCollector
from agent.debugging.differential_diagnostician import DifferentialDiagnostician
from agent.debugging.localization_models import (
    DiagnosticHypothesis,
    DifferentialTestOutcome,
    FailureEvidence,
    RootCauseDiagnosis,
)
from agent.memory.models import ExperienceRecommendation


class RootCauseLocalizer:
    """
    Evidence-driven diagnostic engine for Stage 22.
    Locally identifies faulty code regions, formulates ranked hypotheses,
    scores confidence via an explicit rubric, and provides clear repair directions.
    """

    def __init__(
        self,
        differential_diagnostician: Optional[DifferentialDiagnostician] = None,
    ):
        self.differential_engine = differential_diagnostician or DifferentialDiagnostician()

    def diagnose(
        self,
        problem: ProblemSpec,
        source_code: str,
        language: SupportedLanguage,
        test_report: Optional[TestSuiteReport] = None,
        exec_result: Optional[ExecutionResult] = None,
        attempt_id: str = "attempt_1",
        previous_repair_attempts: int = 0,
        retrieved_memories: Optional[List[ExperienceRecommendation]] = None,
        regression_results: Optional[List[str]] = None,
    ) -> Optional[RootCauseDiagnosis]:
        """
        Main diagnostic entrypoint.
        Returns None if all tests passed and no failure was observed.
        """
        # If all passed, no failure to diagnose
        if test_report and test_report.all_passed:
            return None
        if exec_result and exec_result.status == ExecutionStatus.SUCCESS:
            return None

        # 1. Collect empirical evidence
        memory_failures = []
        if retrieved_memories:
            for rec in retrieved_memories:
                memory_failures.extend(rec.warning_notes or [])

        evidence = EvidenceCollector.collect(
            problem=problem,
            source_code=source_code,
            language=language,
            attempt_id=attempt_id,
            previous_repair_attempts=previous_repair_attempts,
            test_report=test_report,
            exec_result=exec_result,
            regression_results=regression_results,
            memory_prior_failures=memory_failures,
        )

        # 2. Infrastructure & Oracle Isolation
        if evidence.is_infrastructure_failure:
            return self._diagnose_infrastructure(problem, language, evidence)

        if evidence.is_oracle_failure:
            return self._diagnose_oracle(problem, language, evidence)

        # 3. Compilation & Syntax Failure
        raw_res = (test_report.raw_execution_result if test_report else None) or exec_result
        if raw_res and raw_res.status == ExecutionStatus.COMPILE_ERROR:
            return self._diagnose_compilation(problem, source_code, language, evidence)

        # 4. Timeout / Infinite Loop / Complexity
        if evidence.is_timeout or (raw_res and raw_res.status == ExecutionStatus.TIMEOUT):
            return self._diagnose_timeout(problem, source_code, language, evidence)

        # 5. Memory-Limit Exceeded
        if evidence.is_memory_limit:
            return self._diagnose_memory_limit(problem, source_code, language, evidence)

        # 6. Runtime Exception / Crash / Segfault
        failed_tests = test_report.failed_test_results if test_report else (raw_res.test_results if raw_res else [])
        runtime_failures = [t for t in failed_tests if t.error_message]
        if runtime_failures or (raw_res and raw_res.status == ExecutionStatus.RUNTIME_ERROR):
            return self._diagnose_runtime(problem, source_code, language, evidence, runtime_failures)

        # 7. Wrong Answer / Output Mismatch
        mismatch_tests = [t for t in failed_tests if not t.passed and not t.error_message]
        if mismatch_tests or (raw_res and raw_res.status == ExecutionStatus.WRONG_ANSWER):
            return self._diagnose_wrong_answer(problem, source_code, language, evidence, mismatch_tests)

        # 8. Fallback / Unknown
        return self._diagnose_unknown(problem, language, evidence)

    # -------------------------------------------------------------------------
    # DIAGNOSIS CATEGORY HANDLERS
    # -------------------------------------------------------------------------

    def _diagnose_infrastructure(
        self, problem: ProblemSpec, language: SupportedLanguage, evidence: FailureEvidence
    ) -> RootCauseDiagnosis:
        hyp = DiagnosticHypothesis(
            hypothesis_id="hyp_infra_1",
            title="Host Toolchain or Sandbox Environment Unavailable",
            description="The execution environment or compiler runner encountered a system-level failure.",
            fault_category=FailureCategory.ENVIRONMENT_ERROR,
            suspected_region="Host Environment / Execution Runner",
            confidence=1.0,
            confidence_level=ConfidenceLevel.EXPLICIT,
            supporting_evidence=[
                f"Execution status: INFRASTRUCTURE_ERROR",
                f"Error detail: {evidence.stderr or 'Toolchain absent or sandbox error'}",
            ],
            contradictory_evidence=[],
            recommended_repair_direction="Preserve candidate source code; do not modify code. Fix host toolchain or runner configuration.",
        )
        return RootCauseDiagnosis(
            diagnosis_id=f"diag_{problem.id}_infra",
            problem_id=problem.id,
            language=language,
            failure_category=FailureCategory.ENVIRONMENT_ERROR,
            severity=FailureSeverity.CRITICAL,
            evidence=evidence,
            suspected_source_region="Host Toolchain",
            ranked_hypotheses=[hyp],
            confidence=1.0,
            confidence_calculation="Explicit infrastructure failure reported by execution runner: confidence = 1.0",
            recommended_repair_direction="Abort code repair; investigate environment configuration.",
            is_infrastructure_failure=True,
            is_oracle_failure=False,
        )

    def _diagnose_oracle(
        self, problem: ProblemSpec, language: SupportedLanguage, evidence: FailureEvidence
    ) -> RootCauseDiagnosis:
        hyp = DiagnosticHypothesis(
            hypothesis_id="hyp_oracle_1",
            title="Reference Oracle Discrepancy or Exception",
            description="The trusted reference oracle solution failed or threw an exception on generated input.",
            fault_category=FailureCategory.ORACLE_ERROR,
            suspected_region="Testing Oracle Implementation",
            confidence=1.0,
            confidence_level=ConfidenceLevel.EXPLICIT,
            supporting_evidence=["TestSuiteReport indicated oracle_failure_detected = True"],
            contradictory_evidence=[],
            recommended_repair_direction="Preserve candidate source code. Inspect and correct reference oracle logic.",
        )
        return RootCauseDiagnosis(
            diagnosis_id=f"diag_{problem.id}_oracle",
            problem_id=problem.id,
            language=language,
            failure_category=FailureCategory.ORACLE_ERROR,
            severity=FailureSeverity.CRITICAL,
            evidence=evidence,
            suspected_source_region="Reference Oracle",
            ranked_hypotheses=[hyp],
            confidence=1.0,
            confidence_calculation="Explicit oracle failure reported in test suite: confidence = 1.0",
            recommended_repair_direction="Stop candidate repair; fix trusted oracle.",
            is_infrastructure_failure=False,
            is_oracle_failure=True,
        )

    def _diagnose_compilation(
        self, problem: ProblemSpec, source: str, language: SupportedLanguage, evidence: FailureEvidence
    ) -> RootCauseDiagnosis:
        hypotheses: List[DiagnosticHypothesis] = []
        diag_msg = evidence.compiler_diagnostics or evidence.stderr or ""
        suspected_lines = [evidence.source_line] if evidence.source_line is not None else []

        # Analyze compilation diagnostic messages
        if "expected ';'" in diag_msg.lower() or "missing semicolon" in diag_msg.lower():
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_comp_semi",
                title="Missing Semicolon Statement Terminator",
                description="A statement or variable declaration lacks a terminating semicolon.",
                fault_category=FailureCategory.COMPILE_ERROR,
                suspected_region=f"Line {evidence.source_line or 'near syntax error'}",
                suspected_lines=suspected_lines,
                confidence=0.95,
                confidence_level=ConfidenceLevel.EXPLICIT,
                supporting_evidence=[f"Compiler error diagnostic: {diag_msg.splitlines()[0] if diag_msg else ''}"],
                contradictory_evidence=[],
                recommended_repair_direction="Add semicolon terminator to statement.",
            ))
        elif "syntaxerror: invalid syntax" in diag_msg.lower() or "expected ':'" in diag_msg.lower():
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_comp_py_syntax",
                title="Python Syntax Error / Missing Colon",
                description="Function header or control flow statement is missing colon.",
                fault_category=FailureCategory.COMPILE_ERROR,
                suspected_region=f"Line {evidence.source_line or 'in header'}",
                suspected_lines=suspected_lines,
                confidence=0.95,
                confidence_level=ConfidenceLevel.EXPLICIT,
                supporting_evidence=[f"Python syntax diagnostic: {diag_msg.splitlines()[0] if diag_msg else ''}"],
                contradictory_evidence=[],
                recommended_repair_direction="Add colon at end of clause.",
            ))
        else:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_comp_generic",
                title="Language Compilation / Syntax Diagnostics",
                description="Compiler failed to generate object code due to typing or syntax violations.",
                fault_category=FailureCategory.COMPILE_ERROR,
                suspected_region=f"Line {evidence.source_line or 'indicated in compiler log'}",
                suspected_lines=suspected_lines,
                confidence=0.90 if evidence.source_line else 0.75,
                confidence_level=ConfidenceLevel.EXPLICIT if evidence.source_line else ConfidenceLevel.INFERRED,
                supporting_evidence=[f"Compiler stderr: {diag_msg.splitlines()[0] if diag_msg else 'Non-zero exit code'}"],
                contradictory_evidence=[],
                recommended_repair_direction=f"Correct syntax at line {evidence.source_line or 'in compiler diagnostics'}.",
            ))

        conf, calc_str = self._calculate_confidence(hypotheses, has_exact_line=(evidence.source_line is not None))
        return RootCauseDiagnosis(
            diagnosis_id=f"diag_{problem.id}_compile",
            problem_id=problem.id,
            language=language,
            failure_category=FailureCategory.COMPILE_ERROR,
            severity=FailureSeverity.CRITICAL,
            evidence=evidence,
            suspected_source_region=f"Line {evidence.source_line}" if evidence.source_line else "Source File",
            source_line=evidence.source_line,
            source_column=evidence.source_column,
            ranked_hypotheses=hypotheses,
            confidence=conf,
            confidence_calculation=calc_str,
            recommended_repair_direction=hypotheses[0].recommended_repair_direction or "Fix compilation error.",
            unresolved_questions=[] if evidence.source_line else ["Compiler did not provide extractable line number."],
        )

    def _diagnose_timeout(
        self, problem: ProblemSpec, source: str, language: SupportedLanguage, evidence: FailureEvidence
    ) -> RootCauseDiagnosis:
        hypotheses: List[DiagnosticHypothesis] = []

        # Structural inspection: while loop without pointer increment vs nested loops
        has_while = "while " in source or "while(" in source
        has_nested = "for " in source and source.count("for ") >= 2

        if has_while:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_tle_inf_loop",
                title="Infinite Loop: Invariant Update or Boundary Termination Failure",
                description="While-loop conditional guard does not advance termination variables on each step.",
                fault_category=FailureCategory.INFINITE_LOOP,
                suspected_region="While Loop Body / Boundary Progression",
                suspected_lines=[],
                confidence=0.85,
                confidence_level=ConfidenceLevel.INFERRED,
                supporting_evidence=[
                    "Execution watchdog terminated candidate after time limit.",
                    "Source analysis contains while-loop iteration construct.",
                ],
                contradictory_evidence=[],
                recommended_repair_direction="Verify loop advance variables (e.g., left = mid + 1, right = mid - 1) and exit conditions.",
            ))

        if has_nested or not has_while:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_tle_complexity",
                title="Algorithmic Complexity Too Slow for Problem Constraints",
                description="Algorithm operations exceed CPU limits on large inputs (e.g. O(N^2) on N=10^5).",
                fault_category=FailureCategory.ALGORITHM_TOO_SLOW,
                suspected_region="Outer/Inner Iteration Nesting",
                suspected_lines=[],
                confidence=0.75 if has_nested else 0.60,
                confidence_level=ConfidenceLevel.INFERRED,
                supporting_evidence=[
                    "Time limit exceeded during execution.",
                    "Nested loop constructs detected in implementation." if has_nested else "Runtime duration exceeded limit.",
                ],
                contradictory_evidence=[],
                recommended_repair_direction="Optimize algorithm complexity to meet input constraints (e.g. O(N) or O(N log N)).",
            ))

        conf, calc_str = self._calculate_confidence(hypotheses, has_exact_line=False)
        return RootCauseDiagnosis(
            diagnosis_id=f"diag_{problem.id}_timeout",
            problem_id=problem.id,
            language=language,
            failure_category=FailureCategory.TIME_LIMIT_EXCEEDED,
            severity=FailureSeverity.HIGH,
            evidence=evidence,
            suspected_source_region="Loop Control Flow / Asymptotic Complexity",
            source_line=None,
            source_column=None,
            ranked_hypotheses=hypotheses,
            confidence=conf,
            confidence_calculation=calc_str,
            recommended_repair_direction=hypotheses[0].recommended_repair_direction if hypotheses else "Optimize loop or algorithm.",
            unresolved_questions=["Exact line unavailable because execution was halted by external timeout watchdog."],
        )

    def _diagnose_memory_limit(
        self, problem: ProblemSpec, source: str, language: SupportedLanguage, evidence: FailureEvidence
    ) -> RootCauseDiagnosis:
        hyp = DiagnosticHypothesis(
            hypothesis_id="hyp_mem_1",
            title="Excessive Auxiliary Memory Allocation or Unbounded Growth",
            description="Buffer, recursion stack, or data structure size exceeded the memory quota.",
            fault_category=FailureCategory.MEMORY_LIMIT_EXCEEDED,
            suspected_region="Memory Allocation / Buffer Sizing",
            confidence=0.85,
            confidence_level=ConfidenceLevel.INFERRED,
            supporting_evidence=["Runtime environment signaled memory exhaustion."],
            contradictory_evidence=[],
            recommended_repair_direction="Reduce auxiliary space overhead or avoid unbounded buffer growth.",
        )
        conf, calc_str = self._calculate_confidence([hyp], has_exact_line=False)
        return RootCauseDiagnosis(
            diagnosis_id=f"diag_{problem.id}_mem",
            problem_id=problem.id,
            language=language,
            failure_category=FailureCategory.MEMORY_LIMIT_EXCEEDED,
            severity=FailureSeverity.HIGH,
            evidence=evidence,
            suspected_source_region="Auxiliary Buffer Allocation",
            ranked_hypotheses=[hyp],
            confidence=conf,
            confidence_calculation=calc_str,
            recommended_repair_direction=hyp.recommended_repair_direction or "Reduce memory allocations.",
        )

    def _diagnose_runtime(
        self,
        problem: ProblemSpec,
        source: str,
        language: SupportedLanguage,
        evidence: FailureEvidence,
        runtime_failures: List[any],
    ) -> RootCauseDiagnosis:
        err_text = evidence.stderr if evidence.stderr != "NOT_AVAILABLE" else ""
        if not err_text and runtime_failures:
            err_text = getattr(runtime_failures[0], "error_message", "") or ""

        suspected_lines = [evidence.source_line] if evidence.source_line is not None else []
        hypotheses: List[DiagnosticHypothesis] = []

        err_lower = err_text.lower()
        if "indexerror" in err_lower or "arrayindexoutofbounds" in err_lower or "out of range" in err_lower:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_rt_bounds",
                title="Array Index Out of Bounds / Off-By-One Access",
                description="Attempted to access an index outside the valid array or container boundaries.",
                fault_category=FailureCategory.RUNTIME_ERROR,
                suspected_region=f"Line {evidence.source_line or 'indexing expression'}",
                suspected_lines=suspected_lines,
                confidence=0.95 if evidence.source_line else 0.85,
                confidence_level=ConfidenceLevel.EXPLICIT if evidence.source_line else ConfidenceLevel.INFERRED,
                supporting_evidence=[
                    f"Traceback diagnostic: {err_text.splitlines()[0] if err_text else 'Index error'}",
                    f"Verified source line: {evidence.source_line}" if evidence.source_line else "Line not confirmed in stack trace",
                ],
                contradictory_evidence=[],
                recommended_repair_direction="Verify loop upper/lower bounds and check array length before accessing indices.",
            ))
        elif "zerodivisionerror" in err_lower or "arithmeticexception" in err_lower or "division by zero" in err_lower:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_rt_div0",
                title="Division or Modulo by Zero",
                description="Arithmetic operation with a divisor evaluated to zero.",
                fault_category=FailureCategory.RUNTIME_ERROR,
                suspected_region=f"Line {evidence.source_line or 'arithmetic expression'}",
                suspected_lines=suspected_lines,
                confidence=0.95 if evidence.source_line else 0.85,
                confidence_level=ConfidenceLevel.EXPLICIT if evidence.source_line else ConfidenceLevel.INFERRED,
                supporting_evidence=[f"Traceback diagnostic: {err_text.splitlines()[0] if err_text else 'Division by zero'}"],
                contradictory_evidence=[],
                recommended_repair_direction="Guard divisor against zero before performing division or modulo.",
            ))
        elif "nullpointerexception" in err_lower or "'nonetype' object" in err_lower or "segmentation fault" in err_lower:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_rt_null",
                title="Null / NoneType Pointer Dereference or Segfault",
                description="Dereferencing an uninitialized or null pointer / NoneType reference.",
                fault_category=FailureCategory.SEGMENTATION_FAULT if "segmentation" in err_lower else FailureCategory.RUNTIME_ERROR,
                suspected_region=f"Line {evidence.source_line or 'pointer dereference'}",
                suspected_lines=suspected_lines,
                confidence=0.90 if evidence.source_line else 0.80,
                confidence_level=ConfidenceLevel.EXPLICIT if evidence.source_line else ConfidenceLevel.INFERRED,
                supporting_evidence=[f"Runtime crash signal: {err_text.splitlines()[0] if err_text else 'Null dereference'}"],
                contradictory_evidence=[],
                recommended_repair_direction="Add null check or verify pointer initialization.",
            ))
        else:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_rt_unhandled",
                title="Unhandled Runtime Exception or Crash",
                description="Program terminated abnormally with an unhandled runtime error.",
                fault_category=FailureCategory.RUNTIME_ERROR,
                suspected_region=f"Line {evidence.source_line or 'stack trace'}",
                suspected_lines=suspected_lines,
                confidence=0.75,
                confidence_level=ConfidenceLevel.INFERRED,
                supporting_evidence=[f"Stderr: {err_text.splitlines()[0] if err_text else 'Non-zero exit code'}"],
                contradictory_evidence=[],
                recommended_repair_direction="Inspect runtime traceback and guard invalid states.",
            ))

        conf, calc_str = self._calculate_confidence(hypotheses, has_exact_line=(evidence.source_line is not None))
        return RootCauseDiagnosis(
            diagnosis_id=f"diag_{problem.id}_runtime",
            problem_id=problem.id,
            language=language,
            failure_category=hypotheses[0].fault_category,
            severity=FailureSeverity.HIGH,
            evidence=evidence,
            suspected_source_region=f"Line {evidence.source_line}" if evidence.source_line else "Runtime Stack Trace",
            source_line=evidence.source_line,
            source_column=evidence.source_column,
            ranked_hypotheses=hypotheses,
            confidence=conf,
            confidence_calculation=calc_str,
            recommended_repair_direction=hypotheses[0].recommended_repair_direction or "Fix runtime exception.",
            unresolved_questions=[] if evidence.source_line else ["Line number not directly extractable from runtime signal."],
        )

    def _diagnose_wrong_answer(
        self,
        problem: ProblemSpec,
        source: str,
        language: SupportedLanguage,
        evidence: FailureEvidence,
        mismatch_tests: List[any],
    ) -> RootCauseDiagnosis:
        hypotheses: List[DiagnosticHypothesis] = []
        prob_id = problem.id.lower()
        func_name = problem.function_name.lower()

        # Empirical category signals from failing test cases
        failing_categories = set()
        for t in mismatch_tests:
            if getattr(t, "category", None):
                failing_categories.add(t.category.value)

        # 1. DSA-Specific Category Hypotheses
        from agent.planning.pattern_classifier import PatternClassifier
        detected_patterns = PatternClassifier.classify(problem)
        primary_pattern = detected_patterns[0] if detected_patterns else None

        # A. Binary Search
        if primary_pattern == DSAPattern.BINARY_SEARCH or "binary-search" in prob_id or "search" == func_name or "peak" in prob_id:
            if "while (left < right)" in source or "while(left < right)" in source or "left = mid" in source:
                hypotheses.append(DiagnosticHypothesis(
                    hypothesis_id="hyp_bs_boundary",
                    title="Binary Search Interval Update / Boundary Condition",
                    description="Condition 'while (left < right)' or 'left = mid' prevents finding single elements or causes infinite looping on boundary values.",
                    fault_category=FailureCategory.EDGE_CASE_FAILURE,
                    suspected_region="Binary Search Loop Condition / Mid Step Update",
                    suspected_lines=[],
                    confidence=0.88,
                    confidence_level=ConfidenceLevel.INFERRED,
                    supporting_evidence=[
                        f"Source contains 'left < right' or 'left = mid'",
                        f"Expected {evidence.expected_output} but got {evidence.actual_output} on test {evidence.failing_test_id}",
                    ],
                    contradictory_evidence=[],
                    recommended_repair_direction="Change condition to 'while (left <= right)' and step increments to 'left = mid + 1', 'right = mid - 1'.",
                ))

        # B. Two Pointers / Palindrome
        elif primary_pattern == DSAPattern.TWO_POINTERS or "palindrome" in prob_id or "ispalindrome" in func_name:
            if "tolower" not in source.lower() and "s" in problem.param_names:
                hypotheses.append(DiagnosticHypothesis(
                    hypothesis_id="hyp_tp_case",
                    title="Two Pointers Case Sensitivity / Alphanumeric Normalization",
                    description="Characters compared without converting to lower case or filtering non-alphanumeric.",
                    fault_category=FailureCategory.WRONG_ANSWER,
                    suspected_region="Two Pointers Comparison Check",
                    suspected_lines=[],
                    confidence=0.85,
                    confidence_level=ConfidenceLevel.INFERRED,
                    supporting_evidence=[
                        "Source does not call tolower() or lower() on character comparison",
                        f"Failed test case {evidence.failing_test_id}",
                    ],
                    contradictory_evidence=[],
                    recommended_repair_direction="Convert characters to lowercase before equality comparison.",
                ))
            else:
                hypotheses.append(DiagnosticHypothesis(
                    hypothesis_id="hyp_tp_pointer",
                    title="Two Pointers Pointer Movement / Crossing Condition",
                    description="Pointers do not advance properly or crossing condition terminates prematurely.",
                    fault_category=FailureCategory.WRONG_ANSWER,
                    suspected_region="Pointer Increment / Loop Invariant",
                    confidence=0.75,
                    confidence_level=ConfidenceLevel.INFERRED,
                    supporting_evidence=[f"Mismatch on test {evidence.failing_test_id}"],
                    contradictory_evidence=[],
                    recommended_repair_direction="Verify left++ and right-- updates and pointer crossing condition.",
                ))

        # C. Sliding Window
        elif primary_pattern == DSAPattern.SLIDING_WINDOW or "sliding" in prob_id or "substring" in prob_id or "lengthoflongest" in func_name or "minsubarraylen" in func_name:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_sw_shrink",
                title="Sliding Window Shrink Condition / Left Pointer Update",
                description="Window fails to shrink or update left pointer upon encountering duplicate elements or reaching target sum.",
                fault_category=FailureCategory.WRONG_ANSWER,
                suspected_region="Window Shrinking Condition / Map Lookup Update",
                confidence=0.82,
                confidence_level=ConfidenceLevel.INFERRED,
                supporting_evidence=[
                    "Sliding window algorithm fails to dynamically advance boundaries",
                    f"Expected {evidence.expected_output} but actual output was {evidence.actual_output}",
                ],
                contradictory_evidence=[],
                recommended_repair_direction="Contract window left pointer while condition holds and update optimal window metric.",
            ))

        # D. Hash Table / Two Sum / Frequency
        elif primary_pattern == DSAPattern.HASH_TABLE or "two-sum" in prob_id or "twosum" in func_name or "ransom" in prob_id:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_hash_lookup",
                title="Hash Table Lookup / Duplicate Handling / Index Bookkeeping",
                description="Hash map lookups overwrite duplicate values, miscount frequencies, or return invalid indices.",
                fault_category=FailureCategory.WRONG_ANSWER,
                suspected_region="Hash Map Insertion / Frequency Counting",
                confidence=0.85,
                confidence_level=ConfidenceLevel.INFERRED,
                supporting_evidence=[
                    f"Expected {evidence.expected_output} but received {evidence.actual_output}",
                    "Hash table lookup or frequency counting discrepancy observed",
                ],
                contradictory_evidence=[],
                recommended_repair_direction="Track character/value frequencies in hash table and verify count decrements/lookups.",
            ))

        # E. Stack / Valid Parentheses / Adjacent Duplicates
        elif primary_pattern == DSAPattern.STACK or "parentheses" in prob_id or "isvalid" in func_name or "stack" in prob_id or "duplicates" in prob_id:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_stack_access",
                title="Stack Empty Access or Push/Pop Ordering",
                description="Popping from empty stack or adjacent duplicate removal logic discrepancy.",
                fault_category=FailureCategory.WRONG_ANSWER,
                suspected_region="Stack Matching Logic / Stack Pop",
                confidence=0.80,
                confidence_level=ConfidenceLevel.INFERRED,
                supporting_evidence=[f"Failed verification on test {evidence.failing_test_id}"],
                contradictory_evidence=[],
                recommended_repair_direction="Use explicit LIFO stack or string buffer to pop matching elements when top equals current.",
            ))

        # F. Linked List
        elif primary_pattern == DSAPattern.LINKED_LIST or "linked-list" in prob_id or "reverselist" in func_name or "mergetwolists" in func_name:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_ll_pointer",
                title="Linked List Head/Tail Update or Pointer Reversal Manipulation",
                description="Pointer manipulation fails to update head/tail references or order nodes properly.",
                fault_category=FailureCategory.WRONG_ANSWER,
                suspected_region="Pointer Loop / Node Stitching",
                confidence=0.80,
                confidence_level=ConfidenceLevel.INFERRED,
                supporting_evidence=[f"Expected sequence {evidence.expected_output} but got {evidence.actual_output}"],
                contradictory_evidence=[],
                recommended_repair_direction="Merge or reverse nodes sequentially maintaining head and tail pointers.",
            ))

        # G. Tree / BST
        elif primary_pattern == DSAPattern.BINARY_TREE or "depth" in prob_id or "maxdepth" in func_name or "tree" in prob_id or "issymmetric" in func_name:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_tree_traversal",
                title="Tree Traversal Condition / Level Counting Base Case",
                description="Tree traversal computes incorrect leaf base cases, symmetry checks, or level sizes.",
                fault_category=FailureCategory.WRONG_ANSWER,
                suspected_region="Tree Depth / Symmetry Traversal Condition",
                confidence=0.80,
                confidence_level=ConfidenceLevel.INFERRED,
                supporting_evidence=[f"Expected {evidence.expected_output} but got {evidence.actual_output}"],
                contradictory_evidence=[],
                recommended_repair_direction="Execute recursive DFS checking symmetry/depth on left and right subtrees.",
            ))

        # H. Graph / BFS / DFS
        elif primary_pattern == DSAPattern.GRAPH_BFS_DFS or "islands" in prob_id or "provinces" in prob_id or "numislands" in func_name or "canvisitallrooms" in func_name:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_graph_visited",
                title="Graph Traversal Condition / Visited Tracking / Component Counting",
                description="Grid or graph component counting lacks DFS/BFS sink or visited vertex tracking.",
                fault_category=FailureCategory.WRONG_ANSWER,
                suspected_region="DFS Traversal / Visited Array",
                confidence=0.82,
                confidence_level=ConfidenceLevel.INFERRED,
                supporting_evidence=[
                    f"Expected component count {evidence.expected_output} but got {evidence.actual_output}",
                ],
                contradictory_evidence=[],
                recommended_repair_direction="Traverse each unvisited connected component with DFS/BFS and mark visited nodes.",
            ))

        # I. Dynamic Programming
        elif primary_pattern == DSAPattern.DYNAMIC_PROGRAMMING or "climbing-stairs" in prob_id or "climbstairs" in func_name or "dp" in prob_id or "rob" in func_name:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_dp_trans",
                title="Dynamic Programming State Initialization or Transition",
                description="Recurrence relation or base cases (dp[0], dp[1]) incorrectly initialized.",
                fault_category=FailureCategory.WRONG_ANSWER,
                suspected_region="DP Recurrence Step",
                confidence=0.80,
                confidence_level=ConfidenceLevel.INFERRED,
                supporting_evidence=[f"Expected {evidence.expected_output} but got {evidence.actual_output}"],
                contradictory_evidence=[],
                recommended_repair_direction="Verify base cases and recurrence state transitions.",
            ))

        # J. Greedy
        elif primary_pattern == DSAPattern.GREEDY or "stock" in prob_id or "maxprofit" in func_name or "greedy" in prob_id or "lemonade" in prob_id:
            if "min_element" in source and "max_element" in source:
                hypotheses.append(DiagnosticHypothesis(
                    hypothesis_id="hyp_greedy_order",
                    title="Greedy Ordering or Invalid Optimality Assumption",
                    description="Assumes global max - global min without preserving chronological buying/selling order.",
                    fault_category=FailureCategory.WRONG_ANSWER,
                    suspected_region="Temporal Traversal Invariant",
                    confidence=0.90,
                    confidence_level=ConfidenceLevel.INFERRED,
                    supporting_evidence=[
                        "Source computes difference of global extremum without checking index ordering",
                        f"Expected {evidence.expected_output} but got {evidence.actual_output}",
                    ],
                    contradictory_evidence=[],
                    recommended_repair_direction="Maintain running minimum price seen so far and update maximum profit at each chronological step.",
                ))
            else:
                hypotheses.append(DiagnosticHypothesis(
                    hypothesis_id="hyp_greedy_gen",
                    title="Greedy Decision Invariant Failure",
                    description="Locally optimal choice violates global optimality constraints.",
                    fault_category=FailureCategory.WRONG_ANSWER,
                    suspected_region="Greedy Selection Step",
                    confidence=0.75,
                    confidence_level=ConfidenceLevel.INFERRED,
                    supporting_evidence=[f"Failed on test {evidence.failing_test_id}"],
                    contradictory_evidence=[],
                    recommended_repair_direction="Verify greedy exchange argument or sorting order.",
                ))

        # K. Arrays / Kadane's / Negative Numbers
        elif "max-subarray" in prob_id or "maxsubarray" in func_name:
            if "max_so_far = 0" in source:
                hypotheses.append(DiagnosticHypothesis(
                    hypothesis_id="hyp_kadane_init",
                    title="State Initialization Error (All Negative Numbers)",
                    description="Initializing max_so_far to 0 causes failure on arrays containing only negative values.",
                    fault_category=FailureCategory.EDGE_CASE_FAILURE,
                    suspected_region="Initialization Line: int max_so_far = 0",
                    confidence=0.92,
                    confidence_level=ConfidenceLevel.INFERRED,
                    supporting_evidence=[
                        "Source initializes maximum sum to 0 instead of nums[0]",
                        f"Fails for negative input values: expected {evidence.expected_output} but got {evidence.actual_output}",
                    ],
                    contradictory_evidence=[],
                    recommended_repair_direction="Initialize max_so_far and curr_max to nums[0].",
                ))

        # L. Fallback General Logic Hypotheses
        if not hypotheses:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_wa_logic",
                title="Logical Calculation or Return Mapping Error",
                description="Algorithm computes incorrect return value for provided input arguments.",
                fault_category=FailureCategory.WRONG_ANSWER,
                suspected_region="Core Algorithmic Calculation",
                confidence=0.70,
                confidence_level=ConfidenceLevel.INFERRED,
                supporting_evidence=[f"Expected {evidence.expected_output} but got {evidence.actual_output}"],
                contradictory_evidence=[],
                recommended_repair_direction="Trace execution against failing input fixture to identify computation discrepancy.",
            ))

        # Always add a secondary boundary hypothesis if there are boundary test failures
        if "boundary" in failing_categories or "single_element" in failing_categories or "duplicate" in failing_categories:
            hypotheses.append(DiagnosticHypothesis(
                hypothesis_id="hyp_wa_boundary_competing",
                title="Edge-Case / Boundary Size Guard Failure",
                description="Special-case sizes (length <= 1) or duplicate inputs not handled correctly.",
                fault_category=FailureCategory.EDGE_CASE_FAILURE,
                suspected_region="Boundary Guard Condition",
                confidence=0.65,
                confidence_level=ConfidenceLevel.INFERRED,
                supporting_evidence=[f"Failed tests fall into categories: {failing_categories}"],
                contradictory_evidence=[],
                recommended_repair_direction="Add boundary guards for small or degenerate input sizes.",
            ))

        # Differential diagnosis: execute discriminating tests if competing hypotheses exist
        diff_outcomes: List[DifferentialTestOutcome] = []
        if len(hypotheses) > 1:
            diff_outcomes = self.differential_engine.differentiate(
                problem=problem,
                source_code=source,
                language=language,
                evidence=evidence,
                hypotheses=hypotheses,
            )
            # Update hypotheses based on differential evidence
            for outcome in diff_outcomes:
                if not outcome.passed:
                    hypotheses[0].supporting_evidence.append(
                        f"Discriminating test {outcome.test_id} confirmed failure on target: {outcome.discriminating_target}"
                    )
                else:
                    hypotheses[0].contradictory_evidence.append(
                        f"Discriminating test {outcome.test_id} passed, narrowing hypothesis scope."
                    )

        conf, calc_str = self._calculate_confidence(hypotheses, has_exact_line=False)
        return RootCauseDiagnosis(
            diagnosis_id=f"diag_{problem.id}_wa",
            problem_id=problem.id,
            language=language,
            failure_category=hypotheses[0].fault_category,
            severity=FailureSeverity.MEDIUM,
            evidence=evidence,
            suspected_source_region=hypotheses[0].suspected_region or "Algorithmic Logic",
            source_line=None,
            source_column=None,
            ranked_hypotheses=hypotheses,
            confidence=conf,
            confidence_calculation=calc_str,
            recommended_repair_direction=hypotheses[0].recommended_repair_direction or "Correct logical discrepancy.",
            unresolved_questions=[] if len(hypotheses) == 1 else ["Exact fault line requires manual trace step."],
            differential_tests_run=diff_outcomes,
        )

    def _diagnose_unknown(
        self, problem: ProblemSpec, language: SupportedLanguage, evidence: FailureEvidence
    ) -> RootCauseDiagnosis:
        hyp = DiagnosticHypothesis(
            hypothesis_id="hyp_unknown_1",
            title="Insufficient Diagnostic Evidence to Classify Failure",
            description="Process terminated with non-zero exit code but without actionable compiler or runtime signals.",
            fault_category=FailureCategory.UNKNOWN_FAILURE,
            suspected_region="Unknown",
            confidence=0.20,
            confidence_level=ConfidenceLevel.UNKNOWN,
            supporting_evidence=["Non-zero exit code with empty or unavailable stderr"],
            contradictory_evidence=[],
            recommended_repair_direction="Run with increased logging or verify environment stability.",
        )
        return RootCauseDiagnosis(
            diagnosis_id=f"diag_{problem.id}_unknown",
            problem_id=problem.id,
            language=language,
            failure_category=FailureCategory.UNKNOWN_FAILURE,
            severity=FailureSeverity.LOW,
            evidence=evidence,
            suspected_source_region="Unknown",
            ranked_hypotheses=[hyp],
            confidence=0.20,
            confidence_calculation="No actionable diagnostic output available: confidence = 0.20 (UNKNOWN)",
            recommended_repair_direction="Increase runner logging verbosity.",
            unresolved_questions=["Missing stderr, compiler messages, and test outputs."],
        )

    # -------------------------------------------------------------------------
    # CONFIDENCE SCORING RUBRIC & CALCULATION
    # -------------------------------------------------------------------------

    @classmethod
    def _calculate_confidence(
        cls, hypotheses: List[DiagnosticHypothesis], has_exact_line: bool
    ) -> Tuple[float, str]:
        """
        Calculates a calibrated overall diagnostic confidence score.
        Rubric:
        - Top hypothesis base confidence (0.6 - 0.95)
        - Exact line verified from compiler/trace: +0.05 bonus
        - Multiple competing hypotheses without differential confirmation: -0.05 penalty
        - Contradictory evidence present: -0.10 penalty
        - Bounded strictly to [0.10, 1.00]
        """
        if not hypotheses:
            return 0.1, "No hypotheses formulated: default confidence = 0.10"

        top = hypotheses[0]
        score = top.confidence

        explanation_parts = [f"Base score from top hypothesis '{top.title}': {top.confidence:.2f}"]

        if has_exact_line:
            score += 0.05
            explanation_parts.append("Verified line number available from diagnostic trace: +0.05")

        if len(hypotheses) > 1 and len(top.contradictory_evidence) > 0:
            score -= 0.10
            explanation_parts.append(f"Contradictory evidence present ({len(top.contradictory_evidence)} items): -0.10")

        score = max(0.10, min(1.00, score))
        calc_str = "; ".join(explanation_parts) + f"; Final calibrated confidence: {score:.2f}"
        return round(score, 2), calc_str
