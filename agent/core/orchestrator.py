"""
Autonomous Self-Correction Loop Orchestrator.
Orchestrates:
ProblemSpec -> Plan -> Generate -> Validate -> Execute -> Test -> Diagnose -> Repair -> Retest -> Verify.
Bounded by MAX_ATTEMPTS with deterministic state transitions.
"""

import hashlib
import uuid
from typing import Any, List, Optional, Set
from agent.llm.base import BaseLLMProvider
from agent.core.models import (
    AgentState,
    AlgorithmPlan,
    FailureCategory,
    FailureReport,
    FailureSeverity,
    OracleType,
    ProblemSpec,
    RepairAttempt,
    SelfCorrectionSession,
    SupportedLanguage,
    TestCase,
    TestCategory,
    VerificationStatus,
)
from agent.debugging.failure_analyzer import FailureAnalyzer
from agent.debugging.repairer import CodeRepairer
from agent.debugging.root_cause_localizer import RootCauseLocalizer
from agent.generation.generator import CodeGenerator
from agent.generation.validator import CodeValidator
from agent.planning.planner import AlgorithmPlanner
from agent.strategy.models import StrategyBundle, StrategyDecision
from agent.strategy.selector import StrategySelector
from agent.testing.engine import TestingEngine
from agent.memory.service import MemoryService


class SelfCorrectionOrchestrator:
    """
    Autonomous Problem-Solving & Self-Correction Engine.
    Executes a bounded feedback loop with complete attempt history, state machine observability,
    and persistent memory integration.
    """

    def __init__(
        self,
        planner: Optional[AlgorithmPlanner] = None,
        generator: Optional[CodeGenerator] = None,
        testing_engine: Optional[TestingEngine] = None,
        repairer: Optional[CodeRepairer] = None,
        memory_service: Optional[MemoryService] = None,
        max_attempts: int = 5,
        root_cause_localizer: Optional[RootCauseLocalizer] = None,
        strategy_selector: Optional[StrategySelector] = None,
        strategy_mode: str = "BASELINE",
        llm_provider: Optional[Any] = None,
    ):
        self.llm = llm_provider
        self.planner = planner or AlgorithmPlanner(llm_provider=self.llm)
        self.generator = generator or CodeGenerator(llm_provider=self.llm)
        self.testing_engine = testing_engine or TestingEngine()
        self.repairer = repairer or CodeRepairer(llm_provider=self.llm)
        self.memory_service = memory_service
        self.max_attempts = max_attempts
        self.localizer = root_cause_localizer or RootCauseLocalizer()
        self.strategy_selector = strategy_selector or StrategySelector(mode=strategy_mode)


    def solve(
        self,
        problem: ProblemSpec,
        language: SupportedLanguage = SupportedLanguage.PYTHON,
        override_initial_code: Optional[str] = None,
        max_attempts: Optional[int] = None,
    ) -> SelfCorrectionSession:
        """
        Executes the autonomous cycle until VERIFIED, MAX_ATTEMPTS_REACHED, or INFRASTRUCTURE_ERROR.
        """
        effective_max = max_attempts or self.max_attempts
        session_id = f"run_{uuid.uuid4().hex[:8]}"
        session = SelfCorrectionSession(
            session_id=session_id,
            problem_id=problem.id,
            language=language,
            max_attempts=effective_max,
            final_state=AgentState.ANALYZING_PROBLEM,
        )

        # 1. State: PLANNING_ALGORITHM
        session.final_state = AgentState.PLANNING_ALGORITHM

        # Retrieve relevant prior experiences (Stage 20: Store -> Retrieve -> Use -> Verify -> Learn)
        retrieved_experiences = []
        if self.memory_service:
            try:
                # Classify pattern to provide retrieval signal
                from agent.planning.pattern_classifier import PatternClassifier
                initial_patterns = PatternClassifier.classify(problem)
                primary_pattern = initial_patterns[0] if initial_patterns else None
                retrieval_report = self.memory_service.retrieve_relevant_experiences(
                    problem=problem,
                    dsa_pattern=primary_pattern,
                    top_k=5,
                )
                retrieved_experiences = retrieval_report.recommendations
            except Exception as e:
                # Memory retrieval failure must NEVER abort the solve (fallback to independent solving)
                pass

        plan = self.planner.plan(problem, retrieved_experiences=retrieved_experiences)
        session.plan = plan

        # Stage 23: Strategy Selection Bundle (Algorithm & Initial Test Budget)
        from agent.planning.constraint_evaluator import ConstraintEvaluator
        max_n = ConstraintEvaluator.extract_max_n(problem.constraints)
        algo_choice, algo_decision = self.strategy_selector.select_algorithm_strategy(
            problem=problem,
            candidates=plan.candidate_approaches,
            patterns=plan.identified_patterns,
            max_n=max_n,
            retrieved_memories=retrieved_experiences,
        )
        plan.selected_approach = algo_choice

        test_budget_decision = self.strategy_selector.select_test_budget_strategy(
            problem=problem,
            language=language,
            retrieved_memories=retrieved_experiences,
        )

        strategy_bundle = StrategyBundle(
            session_id=session_id,
            problem_id=problem.id,
            language=language,
            mode=self.strategy_selector.mode,
            algorithm_strategy=algo_decision,
            test_budget_strategy=test_budget_decision,
            decisions_log=[algo_decision, test_budget_decision],
        )
        session.strategy_bundle = strategy_bundle

        # 2. State: GENERATING_CODE
        session.final_state = AgentState.GENERATING_CODE
        if override_initial_code is not None:
            current_code = override_initial_code
            val_res = CodeValidator.validate(current_code, language)
        else:
            gen_obj = self.generator.generate(problem, plan, language)
            current_code = gen_obj.source_code
            val_res = gen_obj.validation_result

        session.initial_code = current_code

        # 3. State: VALIDATING (Initial AST & Security check)
        session.final_state = AgentState.GENERATING_CODE
        if not val_res.is_valid:
            # Code failed static AST/security validation before execution
            pass  # Will enter the repair loop to correct the syntax/policy violation

        attempt_count = 0
        failing_regression_tests: List[TestCase] = []
        failing_tc_ids: Set[str] = set()

        # --- BOUNDED SELF-CORRECTION LOOP ---
        while attempt_count < effective_max:
            attempt_count += 1
            session.total_attempts = attempt_count

            # 4. AST Check
            val_res = CodeValidator.validate(current_code, language)
            if not val_res.is_valid:
                # Syntactic or security error caught prior to execution
                session.final_state = AgentState.ANALYZING_FAILURE
                failure_report = FailureReport(
                    failure_id=f"ast_fail_{session_id}_{attempt_count}",
                    failure_category=FailureCategory.COMPILE_ERROR if val_res.has_syntax_error else FailureCategory.SECURITY_VIOLATION,
                    severity=FailureSeverity.CRITICAL,
                    error_message="; ".join(val_res.violation_details),
                )

                # Attempt repair
                session.final_state = AgentState.REPAIRING
                repaired_code, patch_summary = self.repairer.repair(
                    problem, plan, current_code, failure_report, language
                )

                # Record attempt
                session.attempt_history.append(RepairAttempt(
                    attempt_number=attempt_count,
                    state_at_start=AgentState.GENERATING_CODE,
                    source_hash_before=self._hash(current_code),
                    source_code_before=current_code,
                    source_hash_after=self._hash(repaired_code),
                    source_code_after=repaired_code,
                    failure_addressed=failure_report,
                    patch_summary=patch_summary,
                    tests_passed=0,
                    tests_failed=0,
                    ast_valid=val_res.is_valid,
                    resulting_state=AgentState.REPAIRING,
                ))

                if repaired_code == current_code:
                    # Repair could not change the code; break to prevent looping
                    break

                current_code = repaired_code
                continue

            # 5. State: EXECUTING_TESTS / RETESTING
            session.final_state = AgentState.RETESTING if attempt_count > 1 else AgentState.EXECUTING_TESTS

            # Task 5: Avoid repeating expensive adaptive/stress suite on every intermediate attempt.
            # On attempt > 1, first test against examples + accumulated failing regression cases.
            if attempt_count > 1 and failing_regression_tests:
                # Combine original examples with accumulated failing test cases (deduplicating by ID)
                seen_ids = set()
                intermediate_suite: List[TestCase] = []
                # Keep examples
                for tc in problem.test_cases:
                    if tc.id not in seen_ids:
                        seen_ids.add(tc.id)
                        intermediate_suite.append(tc)
                # Keep previously failing regression cases
                for tc in failing_regression_tests:
                    if tc.id not in seen_ids:
                        seen_ids.add(tc.id)
                        intermediate_suite.append(tc)

                intermediate_spec = problem.model_copy(update={"test_cases": intermediate_suite})
                test_report = self.testing_engine.evaluate_solution(
                    problem=intermediate_spec,
                    solution_code=current_code,
                    language=language,
                    expand_suite=False,
                    include_stress=False,
                )

                # If candidate code passes the intermediate regression suite, run full adaptive verification
                if test_report.all_passed:
                    test_report = self.testing_engine.evaluate_solution_adaptive(
                        problem=problem,
                        solution_code=current_code,
                        language=language,
                        retrieved_memories=retrieved_experiences,
                    )
            else:
                test_report = self.testing_engine.evaluate_solution_adaptive(
                    problem=problem,
                    solution_code=current_code,
                    language=language,
                    retrieved_memories=retrieved_experiences,
                )

            # Accumulate any newly failing test cases for future regression iterations
            if test_report.failed_test_results:
                for failed_res in test_report.failed_test_results:
                    tc_id = failed_res.test_case_id
                    if tc_id not in failing_tc_ids:
                        failing_tc_ids.add(tc_id)
                        failing_regression_tests.append(TestCase(
                            id=tc_id,
                            inputs=failed_res.input_data,
                            expected_output=failed_res.expected_output,
                            category=failed_res.category or TestCategory.BASIC,
                            oracle_type=failed_res.oracle_type or OracleType.PROBLEM_SPEC,
                        ))

            # 6. Check for INFRASTRUCTURE / TOOLCHAIN FAILURE
            if test_report.execution_status == test_report.execution_status.INFRASTRUCTURE_ERROR:
                session.final_state = AgentState.INFRASTRUCTURE_ERROR
                session.error_summary = test_report.notes[0] if test_report.notes else "Infrastructure failure."
                return session

            session.final_test_report = test_report

            # 7. Check if Solution Passed All Tests -> Conduct Stage 10 Final Verification
            if test_report.all_passed:
                session.final_state = AgentState.VERIFYING
                from agent.verification.verifier import SolutionVerifier
                verifier = SolutionVerifier(testing_engine=self.testing_engine)
                final_report = verifier.verify_solution(
                    problem=problem,
                    source_code=current_code,
                    language=language,
                    plan=plan,
                    test_report=test_report,
                )
                session.verification_report = final_report

                if final_report.final_verification_status in (VerificationStatus.VERIFIED, VerificationStatus.VERIFIED_WITH_WARNINGS):
                    session.final_state = AgentState.VERIFIED
                    session.is_verified = True
                    session.verified_code = current_code
                    if self.memory_service:
                        self.memory_service.record_session_results(problem, session)
                    return session
                else:
                    # Test passed, but failed complexity or constraint compatibility
                    # Do not certify as verified solely because tests passed!
                    session.final_state = AgentState.FAILED
                    session.is_verified = False
                    session.error_summary = (
                        f"Solution passed tests but failed final verification: {final_report.final_verification_status.value}. "
                        + "; ".join(final_report.warnings)
                    )
                    if self.memory_service:
                        self.memory_service.record_session_results(problem, session)
                    return session


            # 8. State: ANALYZING_FAILURE (Stage 22: Root-Cause Localization & Differential Diagnosis)
            session.final_state = AgentState.ANALYZING_FAILURE
            diagnosis = self.localizer.diagnose(
                problem=problem,
                source_code=current_code,
                language=language,
                test_report=test_report,
                attempt_id=f"attempt_{attempt_count}",
                previous_repair_attempts=attempt_count - 1,
                retrieved_memories=retrieved_experiences,
            )

            # Preserve backward-compatible FailureReport
            failure_report = FailureAnalyzer.analyze(
                problem=problem,
                source_code=current_code,
                language=language,
                test_report=test_report,
            )

            # Do not attempt code repair if the failure is infrastructure or oracle related!
            if diagnosis and (diagnosis.is_infrastructure_failure or diagnosis.is_oracle_failure):
                session.final_state = AgentState.INFRASTRUCTURE_ERROR if diagnosis.is_infrastructure_failure else AgentState.FAILED
                session.error_summary = diagnosis.recommended_repair_direction or "Infrastructure or oracle failure prevented code verification."
                if self.memory_service:
                    self.memory_service.record_session_results(problem, session)
                return session

            if failure_report and (failure_report.is_infrastructure_failure or failure_report.failure_category == FailureCategory.ORACLE_ERROR):
                session.final_state = AgentState.INFRASTRUCTURE_ERROR if failure_report.is_infrastructure_failure else AgentState.FAILED
                session.error_summary = failure_report.error_message or "Infrastructure or oracle failure prevented code verification."
                if self.memory_service:
                    self.memory_service.record_session_results(problem, session)
                return session

            # 9. State: REPAIRING (Pass structured diagnosis and failure report)
            session.final_state = AgentState.REPAIRING

            # Stage 23: Strategy Selection for Debugging & Repair
            diag_decision = self.strategy_selector.select_debugging_strategy(
                failure_category=diagnosis.failure_category if diagnosis else (failure_report.failure_category if failure_report else FailureCategory.UNKNOWN_FAILURE),
                language=language,
                observed_stderr=diagnosis.evidence.stderr if diagnosis else None,
            )
            repair_decision = self.strategy_selector.select_repair_tactic(
                failure_category=diagnosis.failure_category if diagnosis else (failure_report.failure_category if failure_report else FailureCategory.UNKNOWN_FAILURE),
                language=language,
                diagnosis_direction=diagnosis.recommended_repair_direction if diagnosis else None,
                retrieved_memories=retrieved_experiences,
            )
            if session.strategy_bundle:
                session.strategy_bundle.debugging_strategy = diag_decision
                session.strategy_bundle.repair_strategy = repair_decision
                session.strategy_bundle.decisions_log.extend([diag_decision, repair_decision])

            repaired_code, patch_summary = self.repairer.repair(
                problem=problem,
                plan=plan,
                current_code=current_code,
                failure_report=failure_report,
                language=language,
                diagnosis=diagnosis,
            )

            # Record attempt in session history
            attempt_rec = RepairAttempt(
                attempt_number=attempt_count,
                state_at_start=AgentState.EXECUTING_TESTS,
                source_hash_before=self._hash(current_code),
                source_code_before=current_code,
                source_hash_after=self._hash(repaired_code),
                source_code_after=repaired_code,
                failure_addressed=failure_report,
                patch_summary=patch_summary,
                tests_passed=test_report.passed_count,
                tests_failed=test_report.failed_count,
                ast_valid=True,
                resulting_state=AgentState.RETESTING,
            )
            session.attempt_history.append(attempt_rec)

            # Check if repair made no changes or repeated identical source
            if repaired_code == current_code:
                # No progress possible; break loop
                session.final_state = AgentState.MAX_ATTEMPTS_REACHED
                session.is_verified = False
                session.error_summary = (
                    f"Reached maximum viable repair progress ({attempt_count}/{effective_max} attempts): patch engine made no changes to source code "
                    f"({'model unavailable' if not (self.llm and self.llm.is_configured()) else 'no applicable patch'})."
                )
                if self.memory_service:
                    self.memory_service.record_session_results(problem, session)
                return session

            current_code = repaired_code

        # If loop exited after completing all attempts without reaching VERIFIED
        session.final_state = AgentState.MAX_ATTEMPTS_REACHED
        session.is_verified = False
        session.error_summary = f"Reached maximum allowed repair attempts ({effective_max}) without full verification."
        if self.memory_service:
            self.memory_service.record_session_results(problem, session)
        return session


    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
