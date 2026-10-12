"""
Solution Verifier & Certification Pipeline.
Performs the multi-gate certification process:
ProblemSpec -> AlgorithmPlan -> Candidate Source -> Test Evidence -> Correctness -> Complexity Audit -> Constraint Compatibility -> FINAL VERIFICATION
Ensures solutions are NEVER certified solely because test suites passed.
"""

import hashlib
from typing import List, Optional

from agent.core.models import (
    AlgorithmPlan,
    ComplexityConfidence,
    ExecutionStatus,
    FailureCategory,
    FinalVerificationReport,
    ProblemSpec,
    SupportedLanguage,
    TestCategory,
    VerificationStatus,
)
from agent.testing.engine import TestingEngine, TestSuiteReport
from agent.verification.complexity_auditor import ComplexityAuditor


class SolutionVerifier:
    """
    Final Gatekeeper of the Autonomous DSA Coding Agent.
    Evaluates correctness evidence, structural complexity, constraint compatibility,
    and plan adherence before issuing a certified verification status.
    """

    def __init__(self, testing_engine: Optional[TestingEngine] = None):
        self.testing_engine = testing_engine or TestingEngine()
        self.auditor = ComplexityAuditor()

    def verify_solution(
        self,
        problem: ProblemSpec,
        source_code: str,
        language: SupportedLanguage = SupportedLanguage.PYTHON,
        plan: Optional[AlgorithmPlan] = None,
        test_report: Optional[TestSuiteReport] = None,
        rerun_regression_if_needed: bool = True,
    ) -> FinalVerificationReport:
        """
        Executes the final verification pipeline.
        Produces a structured, machine-readable FinalVerificationReport.
        """
        warnings: List[str] = []
        unresolved_uncertainty: List[str] = []

        source_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()[:16]

        # Synthesize problem plan if not explicitly supplied
        if plan is None:
            from agent.planning.planner import AlgorithmPlanner
            try:
                plan = AlgorithmPlanner().plan(problem)
            except Exception:
                plan = None

        # --- STEP 1: TEST EVIDENCE & CORRECTNESS VERIFICATION ---
        # If test_report was not provided or rerun requested when empty, evaluate solution
        if test_report is None:
            if rerun_regression_if_needed:
                test_report = self.testing_engine.evaluate_solution(
                    problem=problem,
                    solution_code=source_code,
                    language=language,
                    expand_suite=True,
                    include_stress=True,
                )
            else:
                # No test evidence provided and not allowed to run
                audit_res = self.auditor.audit(source_code, language, plan, problem)
                compat_res = self.auditor.evaluate_constraint_compatibility(audit_res.inferred_time_complexity, problem)
                return FinalVerificationReport(
                    problem_id=problem.id,
                    source_version_hash=source_hash,
                    language=language,
                    test_suite_status="NO_EVIDENCE",
                    total_tests_run=0,
                    tests_passed=0,
                    tests_failed=0,
                    complexity_audit=audit_res,
                    constraint_compatibility=compat_res,
                    warnings=["No test evidence was provided or executed."],
                    unresolved_uncertainty=["Correctness cannot be verified without deterministic test execution."],
                    final_verification_status=VerificationStatus.INSUFFICIENT_EVIDENCE,
                    is_fully_certified=False,
                )

        # Check for Infrastructure / Host / Compiler Failure
        if test_report.execution_status == ExecutionStatus.INFRASTRUCTURE_ERROR:
            audit_res = self.auditor.audit(source_code, language, plan, problem)
            compat_res = self.auditor.evaluate_constraint_compatibility(audit_res.inferred_time_complexity, problem)
            err_msg = test_report.notes[0] if test_report.notes else "Infrastructure failure during execution."
            return FinalVerificationReport(
                problem_id=problem.id,
                source_version_hash=source_hash,
                language=language,
                test_suite_status="INFRASTRUCTURE_ERROR",
                total_tests_run=test_report.total_tests,
                tests_passed=test_report.passed_count,
                tests_failed=test_report.failed_count,
                complexity_audit=audit_res,
                constraint_compatibility=compat_res,
                warnings=[err_msg],
                unresolved_uncertainty=["Execution environment failed to complete verification suite."],
                final_verification_status=VerificationStatus.INFRASTRUCTURE_ERROR,
                is_fully_certified=False,
            )

        # ZERO-TEST SAFETY GATE: Total tests run == 0 must NEVER result in strong VERIFIED
        if test_report.total_tests == 0 and len(test_report.all_test_results) == 0:
            audit_res = self.auditor.audit(source_code, language, plan, problem)
            compat_res = self.auditor.evaluate_constraint_compatibility(audit_res.inferred_time_complexity, problem)
            return FinalVerificationReport(
                problem_id=problem.id,
                source_version_hash=source_hash,
                language=language,
                test_suite_status="ZERO_TESTS_RUN",
                total_tests_run=0,
                tests_passed=0,
                tests_failed=0,
                complexity_audit=audit_res,
                constraint_compatibility=compat_res,
                warnings=["Zero executable test cases were executed. Cannot certify correctness."],
                unresolved_uncertainty=["Execution evidence is missing; at least one executable test must run."],
                final_verification_status=VerificationStatus.VERIFICATION_INCOMPLETE,
                is_fully_certified=False,
            )

        # Check for Oracle / Reference Failure
        if test_report.oracle_failure_detected or test_report.failure_category == FailureCategory.ORACLE_ERROR:
            audit_res = self.auditor.audit(source_code, language, plan, problem)
            compat_res = self.auditor.evaluate_constraint_compatibility(audit_res.inferred_time_complexity, problem)
            return FinalVerificationReport(
                problem_id=problem.id,
                source_version_hash=source_hash,
                language=language,
                test_suite_status="ORACLE_ERROR",
                total_tests_run=test_report.total_tests,
                tests_passed=test_report.passed_count,
                tests_failed=test_report.failed_count,
                complexity_audit=audit_res,
                constraint_compatibility=compat_res,
                warnings=["Oracle or reference mechanism failed during evaluation. Correctness cannot be certified."],
                unresolved_uncertainty=["Oracle error prevented deterministic evaluation."],
                final_verification_status=VerificationStatus.ORACLE_ERROR,
                is_fully_certified=False,
            )

        # Check if tests failed
        if not test_report.all_passed:
            audit_res = self.auditor.audit(source_code, language, plan, problem)
            compat_res = self.auditor.evaluate_constraint_compatibility(audit_res.inferred_time_complexity, problem)
            return FinalVerificationReport(
                problem_id=problem.id,
                source_version_hash=source_hash,
                language=language,
                test_suite_status=f"FAILED ({test_report.failed_count}/{test_report.total_tests} failed)",
                total_tests_run=test_report.total_tests,
                tests_passed=test_report.passed_count,
                tests_failed=test_report.failed_count,
                complexity_audit=audit_res,
                constraint_compatibility=compat_res,
                warnings=[f"{test_report.failed_count} test cases failed in the verification suite."],
                unresolved_uncertainty=[],
                final_verification_status=VerificationStatus.FAILED_CORRECTNESS,
                is_fully_certified=False,
            )

        # Evidence category classification
        categories_run = {r.category for r in test_report.all_test_results if r.category is not None}
        has_stress = TestCategory.STRESS in categories_run
        has_edge_case = TestCategory.EDGE_CASE in categories_run
        has_boundary = TestCategory.BOUNDARY in categories_run
        has_randomized = TestCategory.RANDOMIZED in categories_run
        has_differential = any(r.oracle_type is not None for r in test_report.all_test_results)

        # --- STEP 2: COMPLEXITY AUDIT ---
        audit_res = self.auditor.audit(
            source_code=source_code,
            language=language,
            plan=plan,
            problem=problem,
        )

        for anomaly in audit_res.detected_anomalies:
            warnings.append(anomaly)

        # --- STEP 3: CONSTRAINT COMPATIBILITY ---
        compat_res = self.auditor.evaluate_constraint_compatibility(
            complexity_str=audit_res.inferred_time_complexity,
            problem=problem,
        )

        if compat_res.constraints_uncertain:
            unresolved_uncertainty.append(compat_res.details)

        # --- STEP 4: FINAL STATUS DETERMINATION ---
        # Rules:
        # 1. Correctness must have passed.
        # 2. If constraints are incompatible (e.g. O(N^2) for N=10^5) -> CONSTRAINT_INCOMPATIBLE or FAILED_COMPLEXITY
        if not compat_res.compatible:
            final_status = VerificationStatus.CONSTRAINT_INCOMPATIBLE
        elif not audit_res.plan_implementation_consistent:
            final_status = VerificationStatus.FAILED_COMPLEXITY
        elif audit_res.confidence == ComplexityConfidence.UNCERTAIN:
            final_status = VerificationStatus.CORRECTNESS_VERIFIED_COMPLEXITY_UNCERTAIN
        elif compat_res.constraints_uncertain:
            # Code is correct, plan is consistent, but constraints are missing or ambiguous
            final_status = VerificationStatus.VERIFIED_WITH_WARNINGS
            warnings.append("Constraints were ambiguous/uncertain, but solution passed all verification tests.")
        elif len(warnings) > 0:
            final_status = VerificationStatus.VERIFIED_WITH_WARNINGS
        else:
            final_status = VerificationStatus.VERIFIED

        is_certified = (final_status == VerificationStatus.VERIFIED)

        return FinalVerificationReport(
            problem_id=problem.id,
            source_version_hash=source_hash,
            language=language,
            test_suite_status="ALL_PASSED",
            total_tests_run=test_report.total_tests,
            tests_passed=test_report.passed_count,
            tests_failed=test_report.failed_count,
            has_stress_evidence=has_stress,
            has_edge_case_evidence=has_edge_case,
            has_boundary_evidence=has_boundary,
            has_randomized_evidence=has_randomized,
            has_differential_evidence=has_differential,
            complexity_audit=audit_res,
            constraint_compatibility=compat_res,
            warnings=warnings,
            unresolved_uncertainty=unresolved_uncertainty,
            final_verification_status=final_status,
            is_fully_certified=is_certified,
        )
