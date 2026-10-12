"""
Stage 23: Adaptive Strategy Selector.
Selects explicit, typed solving, testing, debugging, and repair strategies
using ProblemSpec, constraints, language, verified memories, and observed failures.
Falls back safely to baseline on empty/irrelevant/contradictory memory.
"""

from typing import Any, Dict, List, Optional, Tuple

from agent.core.models import (
    CandidateApproach,
    DSAPattern,
    FailureCategory,
    ProblemSpec,
    SupportedLanguage,
)
from agent.memory.models import ExperienceRecommendation
from agent.planning.constraint_evaluator import ConstraintEvaluator
from agent.planning.pattern_classifier import PatternClassifier
from agent.strategy.models import StrategyDecision, StrategyType


class StrategySelector:
    """
    Measurable Strategy Selection engine for Stage 23.
    Operates in BASELINE or ADAPTIVE mode.
    Guarantees determinism, cold-start safety, and constraint override.
    """

    def __init__(self, mode: str = "BASELINE"):
        """
        mode: 'BASELINE' or 'ADAPTIVE'
        """
        self.mode = mode.upper()

    def select_algorithm_strategy(
        self,
        problem: ProblemSpec,
        candidates: List[CandidateApproach],
        patterns: List[DSAPattern],
        max_n: Optional[int],
        retrieved_memories: Optional[List[ExperienceRecommendation]] = None,
    ) -> Tuple[CandidateApproach, StrategyDecision]:
        """
        Selects algorithm approach.
        In ADAPTIVE mode, consults eligible, verified historical experiences whose constraints match.
        In BASELINE mode (or upon fallback), selects the standard lowest-operation viable candidate.
        Current problem constraints ALWAYS override memory.
        """
        viable_candidates = [c for c in candidates if c.satisfies_constraints]
        if not viable_candidates:
            viable_candidates = candidates

        is_adaptive = False
        fallback_reason = None
        selected = None
        matched_rec = None

        if self.mode == "ADAPTIVE" and retrieved_memories:
            # Filter memory for verified, non-infrastructure outcomes matching pattern
            eligible_recs = []
            for rec in retrieved_memories:
                # Exclude unverified, failed, or infrastructure outcomes
                if not rec.verified or rec.status in ("FAILED", "INFRASTRUCTURE_ERROR"):
                    continue
                # Check pattern relevance
                rec_pattern_val = rec.pattern.value if hasattr(rec.pattern, "value") else str(rec.pattern)
                for p in patterns:
                    if p.value == rec_pattern_val:
                        eligible_recs.append(rec)
                        break

            if not eligible_recs:
                fallback_reason = "No eligible verified memory matching current problem pattern and constraints"
            else:
                # Sort deterministically by relevance score descending
                eligible_recs.sort(key=lambda r: r.relevance_score, reverse=True)
                top_rec = eligible_recs[0]

                # Find candidate matching recommended algorithm
                for cand in viable_candidates:
                    if top_rec.algorithm.lower() in cand.name.lower() or cand.name.lower() in top_rec.algorithm.lower():
                        selected = cand
                        matched_rec = top_rec
                        is_adaptive = True
                        break

                if not selected:
                    fallback_reason = f"Verified memory algorithm '{top_rec.algorithm}' violated constraints or unavailable in candidates"
        else:
            fallback_reason = "Baseline mode configured" if self.mode == "BASELINE" else "Cold start: empty memory store"

        # Baseline fallback: pick minimum estimated operations viable candidate
        if not selected:
            selected = min(
                viable_candidates,
                key=lambda c: ConstraintEvaluator.estimate_operations(c.time_complexity, max_n or 1000) or float("inf"),
            )

        strategy_id = f"strat_algo_{selected.name.lower().replace(' ', '_').replace('-', '_')}"
        decision = StrategyDecision(
            strategy_id=strategy_id,
            strategy_type=StrategyType.ALGORITHM_SELECTION,
            name=f"Algorithm Approach: {selected.name}",
            applicability_conditions=[
                f"Pattern classified as: {', '.join(p.value for p in patterns)}",
                f"Candidate satisfies constraints: {selected.satisfies_constraints}",
            ],
            inputs_considered={
                "problem_id": problem.id,
                "max_n": max_n,
                "patterns": [p.value for p in patterns],
                "retrieved_memories_count": len(retrieved_memories) if retrieved_memories else 0,
            },
            expected_benefit=f"Expected complexity {selected.time_complexity} prevents TLE under max_n={max_n}",
            resource_cost={
                "time_complexity": selected.time_complexity,
                "space_complexity": selected.space_complexity,
            },
            is_adaptive=is_adaptive,
            fallback_reason=fallback_reason if not is_adaptive else None,
        )

        return selected, decision

    def select_test_budget_strategy(
        self,
        problem: ProblemSpec,
        language: SupportedLanguage,
        retrieved_memories: Optional[List[ExperienceRecommendation]] = None,
    ) -> StrategyDecision:
        """
        Selects test budget and expansion strategy.
        In ADAPTIVE mode, if memory indicates frequent edge-case or boundary failures for this pattern/language,
        allocates a focused high-budget adaptive test suite.
        Otherwise allocates standard baseline test budget.
        """
        is_adaptive = False
        fallback_reason = None
        has_edge_warnings = False

        if self.mode == "ADAPTIVE" and retrieved_memories:
            for rec in retrieved_memories:
                if rec.warning_notes or rec.repair_insights:
                    has_edge_warnings = True
                    is_adaptive = True
                    break
            if not is_adaptive:
                fallback_reason = "No historical failure risks recorded for problem family"
        else:
            fallback_reason = "Baseline test budget configured" if self.mode == "BASELINE" else "Cold start: empty memory"

        if is_adaptive and has_edge_warnings:
            budget = {"max_tests": 12, "adaptive_rounds": 2, "include_stress": True}
            benefit = "Elevated test budget to catch historical edge-case and boundary vulnerabilities"
            strat_id = "strat_test_elevated_edge_focused"
            strat_name = "Targeted Adaptive Multi-Round Test Budget"
        else:
            budget = {"max_tests": 6, "adaptive_rounds": 1, "include_stress": False}
            benefit = "Standard baseline test coverage with minimal execution overhead"
            strat_id = "strat_test_standard_baseline"
            strat_name = "Standard Baseline Test Budget"

        return StrategyDecision(
            strategy_id=strat_id,
            strategy_type=StrategyType.TEST_BUDGET,
            name=strat_name,
            applicability_conditions=[
                f"Language: {language.value}",
                f"Historical risk signals observed: {has_edge_warnings}",
            ],
            inputs_considered={
                "language": language.value,
                "memory_warning_signals": has_edge_warnings,
            },
            expected_benefit=benefit,
            resource_cost=budget,
            is_adaptive=is_adaptive,
            fallback_reason=fallback_reason if not is_adaptive else None,
        )

    def select_debugging_strategy(
        self,
        failure_category: FailureCategory,
        language: SupportedLanguage,
        observed_stderr: Optional[str] = None,
    ) -> StrategyDecision:
        """
        Selects diagnostic and root-cause localization strategy based on failure category and language.
        """
        if failure_category == FailureCategory.COMPILE_ERROR:
            strat_id = "strat_diag_compiler_log_parsing"
            name = "Compiler Diagnostic AST & Line Parsing"
            benefit = "Extract exact syntax line and column from compiler diagnostics without guessing"
        elif failure_category in (FailureCategory.RUNTIME_ERROR, FailureCategory.SEGMENTATION_FAULT):
            strat_id = "strat_diag_traceback_exception_mapping"
            name = "Runtime Traceback Deep-Stack Analysis"
            benefit = "Isolate exception origin (out of bounds, div 0, null dereference) via call stack"
        elif failure_category in (FailureCategory.TIME_LIMIT_EXCEEDED, FailureCategory.INFINITE_LOOP):
            strat_id = "strat_diag_loop_watchdog_inspection"
            name = "Loop Invariant & Step Advancement Inspection"
            benefit = "Verify loop termination invariants and pointer increments to halt runaway loops"
        elif failure_category == FailureCategory.ENVIRONMENT_ERROR:
            strat_id = "strat_diag_infrastructure_isolation"
            name = "Host Toolchain Environment Quarantining"
            benefit = "Isolate host execution runner or missing toolchain without modifying candidate code"
        elif failure_category == FailureCategory.ORACLE_ERROR:
            strat_id = "strat_diag_oracle_quarantine"
            name = "Test Oracle Integrity Verification"
            benefit = "Isolate reference solution exception without blaming candidate code"
        else:
            strat_id = "strat_diag_differential_oracle_comparison"
            name = "Differential Test Disambiguation"
            benefit = "Differentiate boundary condition vs general algorithmic logic mismatch"

        return StrategyDecision(
            strategy_id=strat_id,
            strategy_type=StrategyType.DEBUGGING_LOCALIZATION,
            name=name,
            applicability_conditions=[f"Failure classified as: {failure_category.value}"],
            inputs_considered={
                "failure_category": failure_category.value,
                "language": language.value,
            },
            expected_benefit=benefit,
            resource_cost={"max_differential_tests": 2},
            is_adaptive=False,
        )

    def select_repair_tactic(
        self,
        failure_category: FailureCategory,
        language: SupportedLanguage,
        diagnosis_direction: Optional[str] = None,
        retrieved_memories: Optional[List[ExperienceRecommendation]] = None,
    ) -> StrategyDecision:
        """
        Selects targeted repair tactic based on diagnosis and verified repair memory insights.
        """
        is_adaptive = False
        fallback_reason = None
        historical_repair = None

        if self.mode == "ADAPTIVE" and retrieved_memories:
            for rec in retrieved_memories:
                if rec.repair_insights and rec.verified:
                    historical_repair = rec.repair_insights[0]
                    is_adaptive = True
                    break
            if not is_adaptive:
                fallback_reason = "No verified repair patterns recorded in memory"
        else:
            fallback_reason = "Baseline repair rules configured" if self.mode == "BASELINE" else "Cold start: empty memory"

        if is_adaptive and historical_repair:
            strat_id = "strat_repair_memory_informed"
            name = f"Memory-Informed Patch: {historical_repair[:40]}..."
            benefit = "Apply proven historical patch strategy verified on identical problem family"
        else:
            strat_id = f"strat_repair_deterministic_{failure_category.value.lower()}"
            name = f"Deterministic Rule Repair for {failure_category.value}"
            benefit = f"Targeted structural patch resolving {failure_category.value} while preserving intent"

        return StrategyDecision(
            strategy_id=strat_id,
            strategy_type=StrategyType.REPAIR_TACTIC,
            name=name,
            applicability_conditions=[
                f"Failure category: {failure_category.value}",
                f"Language: {language.value}",
            ],
            inputs_considered={
                "failure_category": failure_category.value,
                "diagnosis_direction": diagnosis_direction,
                "historical_insight": historical_repair,
            },
            expected_benefit=benefit,
            resource_cost={"patch_attempts_budget": 1},
            is_adaptive=is_adaptive,
            fallback_reason=fallback_reason if not is_adaptive else None,
        )
