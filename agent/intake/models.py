"""Models and contracts for Dynamic Problem Intake & Validation (Stage 19).

Defines:
- IntakeValidationStatus: VALID, INVALID_PROBLEM, INCOMPLETE_PROBLEM.
- ProblemValidationReport: Detailed diagnostics on intake validity.
- DynamicIntakeRequest: Normalized incoming problem payload.
- DynamicSolveResult: Structured contract for single/multi problem execution.
- DuplicatePolicy: REJECT, ALLOW_RERUN.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agent.core.models import SupportedLanguage


class IntakeValidationStatus(str, Enum):
    """Validation states for dynamically submitted DSA problems."""
    VALID = "VALID"
    INVALID_PROBLEM = "INVALID_PROBLEM"
    INCOMPLETE_PROBLEM = "INCOMPLETE_PROBLEM"


class ProblemValidationReport(BaseModel):
    """Structured audit report for intake validation."""
    status: IntakeValidationStatus
    title: str = ""
    has_statement: bool = False
    has_input_format: bool = False
    has_output_format: bool = False
    has_examples: bool = False
    has_constraints: bool = False
    language_valid: bool = True
    selected_language: Optional[SupportedLanguage] = None
    issues: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    is_acceptable: bool = False


class VerificationEvidenceDTO(BaseModel):
    """Structured verification gate evidence."""
    correctness: bool = False
    constraints: bool = False
    complexity: bool = False
    plan_consistency: bool = False


class DynamicSolveResult(BaseModel):
    """Stage 19 Result Contract: unambiguous outcome for dynamic execution."""
    problem_id: str
    queue_item_id: str
    job_id: str
    status: str  # VERIFIED, FAILED, MAX_ATTEMPTS_REACHED, INFRASTRUCTURE_ERROR, INVALID_PROBLEM
    language: str
    attempt_count: int = 0
    tests_total: int = 0
    tests_passed: int = 0
    verification: VerificationEvidenceDTO = Field(default_factory=VerificationEvidenceDTO)
    error_summary: Optional[str] = None
    code_hash: Optional[str] = None
    problem_hash: Optional[str] = None
    is_verified: bool = False
