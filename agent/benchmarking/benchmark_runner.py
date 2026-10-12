"""Runner and evaluator for the multi-DSA benchmark suite."""

import time
from typing import Dict, List, Optional

from agent.benchmarking.benchmark_registry import (
    BENCHMARK_REGISTRY,
    BenchmarkProblem,
    BenchmarkResult,
    to_problem_spec,
)
from agent.core.models import (
    AgentState,
    AlgorithmPlan,
    CandidateApproach,
    ExecutionStatus,
    ProblemSpec,
    SupportedLanguage,
    VerificationStatus,
)
from agent.core.orchestrator import SelfCorrectionOrchestrator
from agent.planning.pattern_classifier import PatternClassifier
from agent.planning.planner import AlgorithmPlanner
from agent.testing.engine import TestingEngine
from agent.verification.verifier import SolutionVerifier


class BenchmarkRunner:
    """Executes benchmark problems through the complete autonomous pipeline."""

    def __init__(
        self,
        testing_engine: Optional[TestingEngine] = None,
        orchestrator: Optional[SelfCorrectionOrchestrator] = None,
    ):
        self.testing_engine = testing_engine or TestingEngine()
        self.planner = AlgorithmPlanner()
        self.verifier = SolutionVerifier(testing_engine=self.testing_engine)
        self.orchestrator = orchestrator or SelfCorrectionOrchestrator(
            planner=self.planner,
            testing_engine=self.testing_engine,
            max_attempts=3,
        )

    def run_problem(
        self,
        problem: BenchmarkProblem,
        use_flawed_start: bool = False,
    ) -> BenchmarkResult:
        """Run a single problem through the complete autonomous pipeline."""
        start_time = time.time()
        spec = to_problem_spec(problem)

        # 1. Pattern Classification
        detected_patterns = PatternClassifier.classify(spec)
        primary_pattern = detected_patterns[0].name if detected_patterns else "UNKNOWN"
        candidate_patterns = [p.name for p in detected_patterns]
        pattern_confidence = 1.0 if detected_patterns else 0.0

        # 2. Algorithm Planning
        plan = self.planner.plan(spec)
        selected_algorithm = plan.selected_approach.name if plan.selected_approach else "UNKNOWN"
        planned_time = plan.selected_approach.time_complexity if plan.selected_approach else "UNKNOWN"
        planned_space = plan.selected_approach.space_complexity if plan.selected_approach else "UNKNOWN"

        # 3. Source Code Selection
        initial_code = (
            problem.intentional_flawed_code
            if (use_flawed_start and problem.intentional_flawed_code)
            else problem.canonical_cpp_code
        )

        initial_failure_category = problem.flaw_category if use_flawed_start else None
        repair_attempts = 0

        # 4. Execution & Verification / Self-Correction
        if use_flawed_start and problem.intentional_flawed_code:
            session = self.orchestrator.solve(
                problem=spec,
                language=SupportedLanguage.CPP,
                override_initial_code=initial_code,
            )
            repair_attempts = len(session.attempt_history)
            final_code = session.verified_code or session.initial_code
            fully_certified = session.is_verified
            final_status = "PASSED" if session.is_verified else "FAILED"
            final_verification_status = session.final_state.value
            
            # Extract test counts from session
            if session.verification_report:
                total_tests = session.verification_report.total_tests_run
                tests_passed = session.verification_report.tests_passed
                tests_failed = session.verification_report.tests_failed
                inferred_time = session.verification_report.complexity_audit.inferred_time_complexity if session.verification_report.complexity_audit else planned_time
                inferred_space = session.verification_report.complexity_audit.inferred_space_complexity if session.verification_report.complexity_audit else planned_space
                warnings = session.verification_report.warnings
            else:
                total_tests = session.attempt_history[-1].tests_passed + session.attempt_history[-1].tests_failed if session.attempt_history else 0
                tests_passed = session.attempt_history[-1].tests_passed if session.attempt_history else 0
                tests_failed = session.attempt_history[-1].tests_failed if session.attempt_history else 0
                inferred_time = planned_time
                inferred_space = planned_space
                warnings = [session.error_summary] if session.error_summary else []

            compile_status = "SUCCESS" if (session.is_verified or total_tests > 0) else "FAILED"
        else:
            # Direct Execution and Stage 10 Verification
            test_report = self.testing_engine.evaluate_solution(
                problem=spec,
                solution_code=initial_code,
                language=SupportedLanguage.CPP,
                expand_suite=True,
                include_stress=False,
            )
            compile_status = "SUCCESS" if test_report.execution_status == ExecutionStatus.SUCCESS else "FAILED"
            total_tests = test_report.total_tests
            tests_passed = test_report.passed_count
            tests_failed = test_report.failed_count

            final_report = self.verifier.verify_solution(
                problem=spec,
                source_code=initial_code,
                language=SupportedLanguage.CPP,
                plan=plan,
                test_report=test_report,
            )
            final_verification_status = final_report.final_verification_status.value
            fully_certified = final_report.is_fully_certified
            final_status = "PASSED" if (tests_failed == 0 and total_tests > 0 and fully_certified) else "FAILED"
            inferred_time = final_report.complexity_audit.inferred_time_complexity if final_report.complexity_audit else "UNKNOWN"
            inferred_space = final_report.complexity_audit.inferred_space_complexity if final_report.complexity_audit else "UNKNOWN"
            warnings = final_report.warnings

        elapsed_ms = (time.time() - start_time) * 1000.0

        return BenchmarkResult(
            problem_id=problem.id,
            title=problem.title,
            category=problem.category.value,
            detected_pattern=primary_pattern,
            pattern_confidence=pattern_confidence,
            candidate_patterns=candidate_patterns,
            selected_algorithm=selected_algorithm,
            language="cpp",
            compile_status=compile_status,
            total_tests=total_tests,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            repair_attempts=repair_attempts,
            initial_failure_category=initial_failure_category,
            final_status=final_status,
            final_verification_status=final_verification_status,
            fully_certified=fully_certified,
            planned_time=planned_time,
            inferred_time=inferred_time,
            planned_space=planned_space,
            inferred_space=inferred_space,
            warnings=warnings,
            execution_time_ms=elapsed_ms,
        )

    def run_suite(
        self,
        problem_ids: Optional[List[str]] = None,
        flawed_problem_ids: Optional[List[str]] = None,
    ) -> List[BenchmarkResult]:
        """Run all or specified benchmark problems."""
        target_ids = problem_ids or list(BENCHMARK_REGISTRY.keys())
        flawed_set = set(flawed_problem_ids or [])
        results = []
        for pid in target_ids:
            prob = BENCHMARK_REGISTRY[pid]
            use_flawed = pid in flawed_set
            res = self.run_problem(prob, use_flawed_start=use_flawed)
            results.append(res)
        return results


if __name__ == "__main__":
    runner = BenchmarkRunner()
    # Run the comprehensive benchmark suite across all DSA categories
    # with self-correction enabled for canonical flawed scenarios
    flawed_targets = [
        "max-subarray",
        "valid-palindrome",
        "binary-search",
        "valid-parentheses",
        "best-time-to-buy-and-sell-stock",
        "longest-substring-without-repeating-characters",
        "reverse-linked-list",
        "maximum-depth-of-binary-tree",
        "number-of-islands",
        "kth-largest-element-in-an-array",
        "subsets",
        "number-of-provinces",
    ]
    print(f"Executing Multi-DSA Autonomous Benchmark across {len(BENCHMARK_REGISTRY)} categories...")
    results = runner.run_suite(flawed_problem_ids=flawed_targets)

    print("\n" + "=" * 125)
    print(f"{'Problem':<32} | {'Category':<15} | {'Pattern':<18} | {'Algorithm':<22} | {'Tests':<8} | {'Repairs':<7} | {'Status'}")
    print("=" * 125)
    total_passed = 0
    total_failed = 0
    total_tests_all = 0
    total_tests_passed_all = 0
    total_tests_failed_all = 0
    total_repairs_all = 0

    for r in results:
        total_tests_all += r.total_tests
        total_tests_passed_all += r.tests_passed
        total_tests_failed_all += r.tests_failed
        total_repairs_all += r.repair_attempts
        if r.final_status == "PASSED":
            total_passed += 1
        else:
            total_failed += 1

        pattern_disp = r.detected_pattern[:18]
        algo_disp = r.selected_algorithm[:22]
        test_disp = f"{r.tests_passed}/{r.total_tests}"
        print(f"{r.problem_id:<32} | {r.category:<15} | {pattern_disp:<18} | {algo_disp:<22} | {test_disp:<8} | {r.repair_attempts:<7} | {r.final_status}")

    print("=" * 125)
    print(f"Summary: {total_passed}/{len(results)} Benchmarks Passed. Total Tests: {total_tests_all} ({total_tests_passed_all} passed, {total_tests_failed_all} failed). Total Repairs: {total_repairs_all}.")

