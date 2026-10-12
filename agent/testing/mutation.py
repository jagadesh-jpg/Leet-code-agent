"""Controlled Mutation Testing Utility for Stage 21 Test System Validation.

Evaluates test suite sensitivity by generating realistic, controlled syntax/operator
mutations (boundary shifts, off-by-one, comparison reversal, initialization errors).
Strictly used as a benchmark validation tool; does not modify production code permanently.
"""

from dataclasses import dataclass
from typing import Callable, List, Optional
from agent.core.models import (
    ExecutionStatus,
    ProblemSpec,
    SupportedLanguage,
    TestSuiteReport,
)
from agent.testing.engine import TestingEngine


@dataclass
class MutationVariant:
    """A mutant version of candidate source code."""
    mutation_id: str
    description: str
    mutated_code: str
    mutation_type: str  # 'OFF_BY_ONE', 'BOUNDARY_COMPARISON', 'WRONG_OPERATOR', 'INITIALIZATION'


class MutationTester:
    """
    Applies controlled mutations to verified baseline solutions and measures
    whether a test suite detects (kills) the mutants.
    """

    @classmethod
    def create_mutants(cls, original_code: str, language: SupportedLanguage) -> List[MutationVariant]:
        mutants = []

        # 1. Comparison boundary mutation: <= replaced with <
        if "<=" in original_code:
            mutants.append(MutationVariant(
                mutation_id="mut_boundary_lt",
                description="Replace '<=' with '<' (strict inequality off-by-one)",
                mutated_code=original_code.replace("<=", "<", 1),
                mutation_type="BOUNDARY_COMPARISON",
            ))

        # 2. Comparison boundary mutation: >= replaced with >
        if ">=" in original_code:
            mutants.append(MutationVariant(
                mutation_id="mut_boundary_gt",
                description="Replace '>=' with '>' (strict inequality off-by-one)",
                mutated_code=original_code.replace(">=", ">", 1),
                mutation_type="BOUNDARY_COMPARISON",
            ))

        # 3. Off-by-one index arithmetic: + 1 replaced with + 2 or - 1 replaced with - 2
        if "+ 1" in original_code:
            mutants.append(MutationVariant(
                mutation_id="mut_index_plus_two",
                description="Replace '+ 1' with '+ 2' (off-by-one index stride)",
                mutated_code=original_code.replace("+ 1", "+ 2", 1),
                mutation_type="OFF_BY_ONE",
            ))
        elif "- 1" in original_code:
            mutants.append(MutationVariant(
                mutation_id="mut_index_minus_two",
                description="Replace '- 1' with '- 2' (off-by-one boundary shift)",
                mutated_code=original_code.replace("- 1", "- 2", 1),
                mutation_type="OFF_BY_ONE",
            ))

        # 4. Wrong operator: + replaced with -
        if " + " in original_code:
            mutants.append(MutationVariant(
                mutation_id="mut_wrong_operator_sub",
                description="Replace '+' with '-' (arithmetic operator flip)",
                mutated_code=original_code.replace(" + ", " - ", 1),
                mutation_type="WRONG_OPERATOR",
            ))

        # 5. Initialization error: 0 replaced with 1
        if "= 0;" in original_code:
            mutants.append(MutationVariant(
                mutation_id="mut_init_one",
                description="Replace '= 0;' with '= 1;' (faulty accumulator initialization)",
                mutated_code=original_code.replace("= 0;", "= 1;", 1),
                mutation_type="INITIALIZATION",
            ))
        elif "= 0\n" in original_code:
            mutants.append(MutationVariant(
                mutation_id="mut_init_one_py",
                description="Replace '= 0' with '= 1' (faulty accumulator initialization)",
                mutated_code=original_code.replace("= 0\n", "= 1\n", 1),
                mutation_type="INITIALIZATION",
            ))

        return mutants

    @classmethod
    def evaluate_test_suite_against_mutants(
        cls,
        testing_engine: TestingEngine,
        problem: ProblemSpec,
        mutants: List[MutationVariant],
        language: SupportedLanguage,
        use_adaptive: bool = True,
    ) -> dict:
        """
        Executes the test suite against each mutant and calculates the mutation score.
        A mutant is 'killed' if the test suite fails (i.e. all_passed == False).
        """
        total_mutants = len(mutants)
        killed_mutants = 0
        details = []

        for m in mutants:
            if use_adaptive:
                report = testing_engine.evaluate_solution_adaptive(
                    problem=problem,
                    solution_code=m.mutated_code,
                    language=language,
                )
            else:
                report = testing_engine.evaluate_solution(
                    problem=problem,
                    solution_code=m.mutated_code,
                    language=language,
                    expand_suite=False,
                )

            # Mutant is killed if tests fail
            is_killed = not report.all_passed
            if is_killed:
                killed_mutants += 1

            details.append({
                "mutation_id": m.mutation_id,
                "mutation_type": m.mutation_type,
                "description": m.description,
                "killed": is_killed,
                "execution_status": report.execution_status.value,
                "failed_tests_count": report.failed_count,
            })

        score = (killed_mutants / total_mutants) if total_mutants > 0 else 1.0
        return {
            "total_mutants": total_mutants,
            "killed_mutants": killed_mutants,
            "mutation_score": score,
            "details": details,
        }
