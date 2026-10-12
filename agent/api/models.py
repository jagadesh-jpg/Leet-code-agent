"""
Data models and DTOs for the Python Agent API exposed to n8n and external orchestrators.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agent.core.models import (
    AgentState,
    AlgorithmPlan,
    FinalVerificationReport,
    ProblemSpec,
    SelfCorrectionSession,
    SupportedLanguage,
    VerificationStatus,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- REQUEST SCHEMAS ---

class ProblemInputDTO(BaseModel):
    """Structured or raw problem specification input."""
    problem_id: Optional[str] = Field(default=None, description="Problem identifier slug (e.g. 'two-sum')")
    statement: str = Field(description="Raw markdown, text, or JSON problem statement")
    function_name: Optional[str] = Field(default=None, description="Target function name if known")
    param_names: Optional[List[str]] = Field(default=None, description="Target parameter names if known")
    constraints: Optional[List[str]] = Field(default=None, description="List of constraint strings if known")
    examples: Optional[List[Dict[str, Any]]] = Field(default=None, description="Example test cases if known")


class SolveOptionsDTO(BaseModel):
    """Runtime options for the autonomous self-correction loop."""
    max_attempts: int = Field(default=5, ge=1, le=10, description="Maximum bounded repair iterations")
    timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0, description="Per-execution timeout")


class SolveRequest(BaseModel):
    """Payload for POST /api/v1/problems/solve."""
    problem: ProblemInputDTO
    language: SupportedLanguage = Field(default=SupportedLanguage.PYTHON, description="Target language")
    options: SolveOptionsDTO = Field(default_factory=SolveOptionsDTO)
    override_initial_code: Optional[str] = Field(default=None, description="Optional seed code")
    idempotency_key: Optional[str] = Field(default=None, description="Unique client key to prevent duplicate runs")


class AnalyzeRequest(BaseModel):
    """Payload for POST /api/v1/problems/analyze."""
    problem: ProblemInputDTO


class VerifyRequest(BaseModel):
    """Payload for POST /api/v1/solutions/verify."""
    problem: ProblemInputDTO
    source_code: str
    language: SupportedLanguage = Field(default=SupportedLanguage.PYTHON)


class ProblemIntakeRequestDTO(BaseModel):
    """Payload for POST /api/v1/problems/intake."""
    title: Optional[str] = None
    statement: str
    preferred_language: Optional[str] = None
    priority: int = 0
    max_attempts: Optional[int] = None
    initial_flawed_code: Optional[str] = None
    allow_rerun: bool = True


class ProblemIntakeResponseDTO(BaseModel):
    """Response from POST /api/v1/problems/intake."""
    problem_id: str
    queue_item_id: str
    status: str
    language: str
    is_acceptable: bool = True
    issues: List[str] = Field(default_factory=list)


# --- RESPONSE SCHEMAS ---

class JobDTO(BaseModel):
    """Structured representation of an orchestration job."""
    job_id: str
    problem_id: str
    language: SupportedLanguage
    state: AgentState
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    attempt_count: int = 0
    max_attempts: int = 5
    is_verified: bool = False
    final_status: Optional[str] = None
    verified_code: Optional[str] = None
    verification_report: Optional[FinalVerificationReport] = None
    error_summary: Optional[str] = None
    session_details: Optional[SelfCorrectionSession] = None
    memory_used: bool = False
    retrieved_experience_count: int = 0



class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    timestamp: str = Field(default_factory=utc_now_iso)
    adapters_available: Dict[str, bool] = Field(default_factory=dict)
