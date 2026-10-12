"""
Stage 22: Differential Diagnosis & Discriminating Test Engine.
When multiple competing hypotheses exist, executes safe discriminating tests
through the existing testing engine to compare observed results and disambiguate.
"""

from typing import List, Optional
from agent.core.models import (
    OracleType,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCategory,
)
from agent.debugging.localization_models import (
    DiagnosticHypothesis,
    DifferentialTestOutcome,
    FailureEvidence,
)
from agent.testing.engine import TestingEngine


class DifferentialDiagnostician:
    """
    Formulates and executes bounded discriminating tests via the existing testing engine.
    Compares observed results against competing hypotheses to update rank and confidence.
    """

    def __init__(self, testing_engine: Optional[TestingEngine] = None, max_differential_tests: int = 3):
        self.testing_engine = testing_engine or TestingEngine()
        self.max_differential_tests = max_differential_tests

    def differentiate(
        self,
        problem: ProblemSpec,
        source_code: str,
        language: SupportedLanguage,
        evidence: FailureEvidence,
        hypotheses: List[DiagnosticHypothesis],
    ) -> List[DifferentialTestOutcome]:
        """
        Executes bounded discriminating tests against candidate source code in sandbox.
        """
        # If <= 1 hypothesis or failure is compilation/infrastructure, no need for differential test
        if len(hypotheses) <= 1 or evidence.is_infrastructure_failure or evidence.is_oracle_failure:
            return []

        outcomes: List[DifferentialTestOutcome] = []

        # Discriminate between Boundary vs General Logic
        has_boundary_hyp = any("boundary" in h.title.lower() or "boundary" in h.description.lower() for h in hypotheses)
        has_duplicate_hyp = any("duplicate" in h.title.lower() or "duplicate" in h.description.lower() for h in hypotheses)

        candidate_tests: List[TestCase] = []

        # Find existing problem test cases that test boundary or duplicate
        for tc in problem.test_cases:
            if has_boundary_hyp and (tc.category in (TestCategory.BOUNDARY, TestCategory.SINGLE_ELEMENT) or tc.is_edge_case):
                candidate_tests.append(tc)
            elif has_duplicate_hyp and tc.category == TestCategory.DUPLICATE:
                candidate_tests.append(tc)

        # Cap by configured limit
        candidate_tests = candidate_tests[: self.max_differential_tests]

        for idx, test_case in enumerate(candidate_tests):
            sub_prob = problem.model_copy(update={"test_cases": [test_case]})
            runner = getattr(self.testing_engine, "runner", None)
            if not runner:
                from agent.execution.runner import ExecutionRunner
                runner = ExecutionRunner(timeout_seconds=3.0)

            run_res = runner.run(
                problem=sub_prob,
                solution_code=source_code,
                language=language,
            )
            passed = False
            actual_val = None
            if run_res.test_results:
                passed = run_res.test_results[0].passed
                actual_val = run_res.test_results[0].actual_output

            # Analyze which hypothesis is supported or contradicted
            target = "Boundary/Edge Hypothesis" if test_case.is_edge_case else "Algorithmic Behavior"
            if passed:
                obs = f"Discriminating test {test_case.id} passed; weakens pure edge-case crash hypothesis."
            else:
                obs = f"Discriminating test {test_case.id} failed with actual output {actual_val}; confirms boundary discrepancy."

            outcome = DifferentialTestOutcome(
                test_id=test_case.id,
                input_data=test_case.inputs,
                expected_output=test_case.expected_output,
                actual_output=actual_val,
                passed=passed,
                discriminating_target=target,
                observation=obs,
            )
            outcomes.append(outcome)

        return outcomes
