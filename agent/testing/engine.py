"""
Testing Engine & Differential Evaluator.
Coordinates test-suite generation, differential execution against reference oracles,
property verification, and structured failure evidence aggregation.
"""

from typing import List, Optional, Set
from pydantic import BaseModel, Field

from agent.core.models import (
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCaseResult,
    TestSuiteReport,
)
from agent.execution.runner import ExecutionRunner
from agent.memory.models import ExperienceRecommendation
from agent.testing.adaptive_generator import (
    AdaptiveTestGenerator,
    compute_test_fingerprint,
)
from agent.testing.generator import TestGenerator
from agent.testing.oracles import ReferenceOracles
from agent.testing.risk_model import TestRiskClassifier


class TestingEngine:
    """
    Evaluates candidate solutions across comprehensive, expanded test suites.
    Supports differential verification, property-based checks, and multi-round adaptive testing.
    """
    __test__ = False

    def __init__(
        self,
        runner: Optional[ExecutionRunner] = None,
        generator: Optional[TestGenerator] = None,
        adaptive_generator: Optional[AdaptiveTestGenerator] = None,
    ):
        self.runner = runner or ExecutionRunner(timeout_seconds=5.0)
        self.generator = generator or TestGenerator()
        self.adaptive_generator = adaptive_generator or AdaptiveTestGenerator()

    def evaluate_solution(
        self,
        problem: ProblemSpec,
        solution_code: str,
        language: SupportedLanguage = SupportedLanguage.PYTHON,
        expand_suite: bool = True,
        include_stress: bool = True,
    ) -> TestSuiteReport:
        """
        1. Expands test suite with boundary, randomized, and edge cases.
        2. Executes solution against expanded suite using isolated ExecutionRunner.
        3. Applies differential or property-based checks on actual outputs.
        4. Compiles structured TestSuiteReport.
        """
        # 1. Expand Test Suite
        if expand_suite:
            test_suite = self.generator.generate_suite(
                problem=problem,
                include_random=True,
                include_stress=include_stress,
            )
        else:
            test_suite = list(problem.test_cases)

        # Prepare ProblemSpec with expanded suite
        eval_spec = problem.model_copy(update={"test_cases": test_suite})

        # 2. Run Candidate Code via Execution Runner
        exec_res = self.runner.run(
            problem=eval_spec,
            solution_code=solution_code,
            language=language,
        )

        # 3. Handle non-execution states (Compilation / Syntax / Infrastructure errors)
        if exec_res.status in (
            ExecutionStatus.COMPILE_ERROR,
            ExecutionStatus.INFRASTRUCTURE_ERROR,
            ExecutionStatus.TIMEOUT,
        ):
            return TestSuiteReport(
                all_passed=False,
                total_tests=len(test_suite),
                passed_count=0,
                failed_count=len(test_suite),
                execution_status=exec_res.status,
                failure_category=exec_res.failure_category,
                raw_execution_result=exec_res,
                notes=[exec_res.error_detail or exec_res.stderr],
            )

        # 4. Analyze Per-Test-Case Results with Property & Differential Checks
        passed_count = 0
        failed_results = []
        all_results = []
        oracle_failure = False

        # Map test cases by ID
        tc_map = {tc.id: tc for tc in test_suite}

        for r in exec_res.test_results:
            tc = tc_map.get(r.test_case_id)
            if tc:
                r.category = tc.category
                r.oracle_type = tc.oracle_type
                r.random_seed = tc.random_seed

            # Check if property verification overrides or refines equality
            if tc:
                test_input = tc.inputs if tc.inputs else r.input_data
                r.input_data = test_input
                try:
                    prop_ok, prop_err = ReferenceOracles.evaluate_property(problem, test_input, r.actual_output)
                    if prop_ok is not None:
                        if r.passed and not prop_ok:
                            r.passed = False
                            r.error_message = f"Property violation: {prop_err}"
                        elif not r.passed and prop_ok:
                            # Valid alternative output satisfying all mathematical / problem invariants
                            r.passed = True
                            r.error_message = None
                except Exception as oe:
                    oracle_failure = True
                    r.passed = False
                    r.error_message = f"Oracle evaluation error: {str(oe)}"

            all_results.append(r)
            if r.passed:
                passed_count += 1
            else:
                failed_results.append(r)

        all_passed = (not oracle_failure) and (len(all_results) > 0) and (len(failed_results) == 0) and (passed_count == len(all_results))

        return TestSuiteReport(
            all_passed=all_passed,
            total_tests=len(all_results),
            passed_count=passed_count,
            failed_count=len(failed_results),
            execution_status=ExecutionStatus.SUCCESS if all_passed else (ExecutionStatus.WRONG_ANSWER if len(all_results) > 0 else exec_res.status),
            failure_category=None if all_passed else (FailureCategory.ORACLE_ERROR if oracle_failure else (exec_res.failure_category or FailureCategory.WRONG_ANSWER)),
            failed_test_results=failed_results,
            all_test_results=all_results,
            raw_execution_result=exec_res,
            oracle_failure_detected=oracle_failure,
        )

    def evaluate_solution_adaptive(
        self,
        problem: ProblemSpec,
        solution_code: str,
        language: SupportedLanguage = SupportedLanguage.PYTHON,
        retrieved_memories: Optional[List[ExperienceRecommendation]] = None,
        max_adaptive_rounds: int = 2,
        max_targeted_per_round: int = 5,
        max_total_budget: int = 30,
        seed: Optional[int] = None,
    ) -> TestSuiteReport:
        """
        Stage 21 Adaptive Testing Feedback Loop:
        1. Run initial test suite.
        2. If initial run fails due to compile/infrastructure, abort immediately.
        3. Perform structured risk analysis (problem, constraints, structural code signals, memory).
        4. In bounded adaptive rounds:
           a. Generate targeted tests for unaddressed risk signals.
           b. Deduplicate tests via deterministic SHA-256 fingerprints.
           c. If a previous test failed, generate failure-driven sibling tests.
           d. Execute newly generated targeted tests.
        5. Run final regression check over all accumulated test cases.
        6. Return comprehensive TestSuiteReport with adaptive metrics.
        """
        existing_fingerprints: Set[str] = set()
        accumulated_suite: List[TestCase] = []

        # 1. Initial Suite
        initial_report = self.evaluate_solution(
            problem=problem,
            solution_code=solution_code,
            language=language,
            expand_suite=True,
            include_stress=False,
        )

        for tc in problem.test_cases:
            existing_fingerprints.add(compute_test_fingerprint(tc.inputs))
            accumulated_suite.append(tc)

        # Early exit on compile / infrastructure error
        if initial_report.execution_status in (
            ExecutionStatus.COMPILE_ERROR,
            ExecutionStatus.INFRASTRUCTURE_ERROR,
            ExecutionStatus.TIMEOUT,
        ):
            initial_report.adaptive_rounds_executed = 0
            initial_report.targeted_tests_generated = 0
            return initial_report

        # 2. Risk Analysis
        risk_analysis = TestRiskClassifier.analyze_risks(
            problem=problem,
            solution_code=solution_code,
            language=language,
            retrieved_memories=retrieved_memories,
        )

        total_targeted_generated = 0
        total_dedup_count = 0
        rounds_executed = 0
        evaluated_signals = [s.signal_id for s in risk_analysis.signals]

        current_report = initial_report

        # 3. Adaptive Rounds
        for round_idx in range(1, max_adaptive_rounds + 1):
            if len(accumulated_suite) >= max_total_budget:
                break

            rounds_executed += 1
            remaining_budget = min(max_targeted_per_round, max_total_budget - len(accumulated_suite))

            # Generate targeted tests from risk signals
            gen_res = self.adaptive_generator.generate_targeted_tests(
                problem=problem,
                risk_analysis=risk_analysis,
                existing_test_fingerprints=existing_fingerprints,
                round_number=round_idx,
                max_tests_to_generate=remaining_budget,
                seed=seed,
            )

            total_dedup_count += gen_res.deduplicated_count
            round_new_tests = list(gen_res.new_tests)

            # Failure-driven test generation if there were failed tests
            if current_report.failed_test_results and len(round_new_tests) < remaining_budget:
                first_failed = current_report.failed_test_results[0]
                failure_tests = self.adaptive_generator.generate_failure_driven_tests(
                    problem=problem,
                    failed_result=first_failed,
                    existing_test_fingerprints=existing_fingerprints,
                    round_number=round_idx,
                    max_tests=remaining_budget - len(round_new_tests),
                    seed=seed,
                )
                round_new_tests.extend(failure_tests)

            if not round_new_tests:
                # No new tests could be generated or needed
                break

            total_targeted_generated += len(round_new_tests)
            accumulated_suite.extend(round_new_tests)

            # Execute round tests against candidate code
            round_spec = problem.model_copy(update={"test_cases": accumulated_suite})
            current_report = self.evaluate_solution(
                problem=round_spec,
                solution_code=solution_code,
                language=language,
                expand_suite=False,
                include_stress=False,
            )

            # If candidate failed, we continue or break depending on strategy
            if not current_report.all_passed:
                # Discovered a real bug! We preserve the evidence
                break

        # Attach Stage 21 adaptive metadata to final report
        current_report.adaptive_rounds_executed = rounds_executed
        current_report.targeted_tests_generated = total_targeted_generated
        current_report.deduplicated_tests_count = total_dedup_count
        current_report.risk_signals_evaluated = evaluated_signals

        return current_report
