"""
Stage 22: Evidence-Driven Debugging & Root-Cause Localization Models.
Strongly typed models for evidence collection, ranked hypotheses,
differential diagnosis, and localized source regions.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agent.core.models import (
    ConfidenceLevel,
    FailureCategory,
    FailureSeverity,
    SupportedLanguage,
)


class DiagnosticHypothesis(BaseModel):
    """
    A single ranked diagnostic hypothesis explaining a solution failure.
    Includes concrete supporting evidence, contradictory evidence, and confidence.
    """
    hypothesis_id: str = Field(description="Unique identifier for this hypothesis")
    title: str = Field(description="Short human-readable title of the hypothesis")
    description: str = Field(description="Detailed explanation of the hypothesized fault mechanism")
    fault_category: FailureCategory = Field(description="Categorical failure classification")
    suspected_region: Optional[str] = Field(
        default=None,
        description="Suspected code construct/region (e.g., 'while loop termination', 'boundary update')"
    )
    suspected_lines: List[int] = Field(
        default_factory=list,
        description="Specific verified source lines if directly available from diagnostics/trace"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Calibrated confidence score between 0.0 and 1.0 based on explicit rubric"
    )
    confidence_level: ConfidenceLevel = Field(
        default=ConfidenceLevel.INFERRED,
        description="Categorical confidence level: explicit, inferred, or unknown"
    )
    supporting_evidence: List[str] = Field(
        default_factory=list,
        description="Empirical observations and facts supporting this hypothesis"
    )
    contradictory_evidence: List[str] = Field(
        default_factory=list,
        description="Observations or test results that weaken this hypothesis"
    )
    recommended_repair_direction: Optional[str] = Field(
        default=None,
        description="Actionable repair instruction for the code repairer"
    )


class DifferentialTestOutcome(BaseModel):
    """Outcome of running a discriminating test to differentiate competing hypotheses."""
    test_id: str
    input_data: Dict[str, Any]
    expected_output: Any
    actual_output: Optional[Any] = None
    passed: bool = False
    discriminating_target: str = Field(description="Which hypothesis or boundary this test was designed to probe")
    observation: str = Field(description="Empirical result and diagnostic deduction")


class FailureEvidence(BaseModel):
    """
    Comprehensive empirical evidence collected for a failed candidate.
    Strictly forbids fabricated data: missing fields are marked UNKNOWN or NOT_AVAILABLE.
    """
    problem_id: str
    language: SupportedLanguage
    source_code_hash: str
    attempt_id: str

    # Failing test information
    failing_test_id: Optional[str] = Field(default="NOT_AVAILABLE")
    failing_test_category: Optional[str] = Field(default="UNKNOWN")
    actual_input: Optional[Dict[str, Any]] = None
    expected_output: Optional[Any] = None
    actual_output: Optional[Any] = None

    # Process execution diagnostics
    compiler_diagnostics: Optional[str] = Field(default="NOT_AVAILABLE")
    stderr: Optional[str] = Field(default="NOT_AVAILABLE")
    stdout: Optional[str] = Field(default="NOT_AVAILABLE")
    exit_code: Optional[int] = None
    is_timeout: bool = False
    is_memory_limit: bool = False

    # Source mapping
    source_line: Optional[int] = None
    source_column: Optional[int] = None
    source_excerpt: Optional[str] = None

    # History & Regression
    previous_repair_attempts: int = 0
    regression_results: List[str] = Field(default_factory=list)
    memory_prior_failures: List[str] = Field(default_factory=list)

    # Infrastructure / Oracle flags
    is_infrastructure_failure: bool = False
    is_oracle_failure: bool = False


class RootCauseDiagnosis(BaseModel):
    """
    Structured diagnosis produced by the root-cause localization engine.
    Supplied to the repair agent and persisted to experience memory.
    """
    diagnosis_id: str
    problem_id: str
    language: SupportedLanguage
    failure_category: FailureCategory
    severity: FailureSeverity = FailureSeverity.MEDIUM

    evidence: FailureEvidence
    suspected_source_region: Optional[str] = None
    source_line: Optional[int] = None
    source_column: Optional[int] = None

    ranked_hypotheses: List[DiagnosticHypothesis] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, description="Overall diagnostic confidence score")
    confidence_calculation: str = Field(description="Documented calculation explanation and rubric")

    recommended_repair_direction: str = Field(description="Actionable repair guideline")
    unresolved_questions: List[str] = Field(default_factory=list)
    differential_tests_run: List[DifferentialTestOutcome] = Field(default_factory=list)

    is_infrastructure_failure: bool = False
    is_oracle_failure: bool = False
