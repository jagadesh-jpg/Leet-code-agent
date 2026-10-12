"""
Stage 23: Adaptive Strategy Selection Models.
Strongly typed data contracts for solving, testing, debugging, and repair strategies.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agent.core.models import (
    CandidateApproach,
    DSAPattern,
    FailureCategory,
    ProblemSpec,
    SupportedLanguage,
)


class StrategyType(str, Enum):
    ALGORITHM_SELECTION = "ALGORITHM_SELECTION"
    TEST_BUDGET = "TEST_BUDGET"
    DEBUGGING_LOCALIZATION = "DEBUGGING_LOCALIZATION"
    REPAIR_TACTIC = "REPAIR_TACTIC"


class StrategyDecision(BaseModel):
    """
    An explicit, typed strategy chosen for a relevant decision point.
    Contains conditions, inputs, expected benefits, resource budget/cost, and outcome.
    """
    strategy_id: str = Field(description="Unique identifier for the chosen strategy (e.g. 'strat_algo_single_pass_hash')")
    strategy_type: StrategyType = Field(description="Category of the strategy decision")
    name: str = Field(description="Human-readable name of the strategy")
    applicability_conditions: List[str] = Field(default_factory=list, description="Explicit conditions satisfied for this strategy to apply")
    inputs_considered: Dict[str, Any] = Field(default_factory=dict, description="Inputs evaluated (pattern, max_n, language, failure, memories)")
    expected_benefit: str = Field(description="Anticipated benefit (e.g., 'O(N) operations, prevents TLE')")
    resource_cost: Dict[str, Any] = Field(default_factory=dict, description="Estimated resource cost (e.g., test budget, time complexity)")
    is_adaptive: bool = Field(default=False, description="True if chosen via historical evidence; False if baseline fallback")
    fallback_reason: Optional[str] = Field(default=None, description="Reason if baseline fallback was applied")
    recorded_outcome: Optional[str] = Field(default=None, description="Result after execution (e.g. 'VERIFIED', 'DEFECT_DETECTED')")


class StrategyBundle(BaseModel):
    """Complete bundle of strategy decisions for a problem-solving session."""
    session_id: str
    problem_id: str
    language: SupportedLanguage
    mode: str = Field(default="BASELINE", description="'BASELINE' or 'ADAPTIVE'")
    algorithm_strategy: StrategyDecision
    test_budget_strategy: StrategyDecision
    debugging_strategy: Optional[StrategyDecision] = None
    repair_strategy: Optional[StrategyDecision] = None
    decisions_log: List[StrategyDecision] = Field(default_factory=list)
