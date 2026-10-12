"""
Memory Models for Persistent Solution Memory Subsystem.
Strongly typed schemas for problems, solutions, failures, patterns, and repairs.
Never stores secrets, API keys, or fabricated data.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agent.core.models import (
    Difficulty,
    DSAPattern,
    FailureCategory,
    FailureReport,
    FinalVerificationReport,
    ProblemSpec,
    SupportedLanguage,
    VerificationStatus,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProblemMemoryRecord(BaseModel):
    """Persistent representation of a normalized problem."""
    problem_id: str
    title: Optional[str] = None
    description: str
    difficulty: Optional[Difficulty] = None
    function_name: Optional[str] = None
    param_names: List[str] = Field(default_factory=list)
    return_type: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    detected_patterns: List[DSAPattern] = Field(default_factory=list)
    raw_statement: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class SolutionMemoryRecord(BaseModel):
    """Persistent representation of a candidate or verified solution."""
    solution_id: str
    problem_id: str
    language: SupportedLanguage
    source_code: str
    source_hash: str
    algorithm_name: Optional[str] = None
    data_structures_used: List[str] = Field(default_factory=list)
    claimed_time_complexity: Optional[str] = None
    claimed_space_complexity: Optional[str] = None
    inferred_time_complexity: Optional[str] = None
    inferred_space_complexity: Optional[str] = None
    verification_status: VerificationStatus
    verification_report: Optional[FinalVerificationReport] = None
    is_verified: bool = False
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class FailureMemoryRecord(BaseModel):
    """Persistent record of an execution, AST, or test failure."""
    failure_id: str
    problem_id: str
    attempt_number: int
    language: SupportedLanguage
    source_code: str
    source_hash: str
    failure_category: FailureCategory
    likely_root_cause: Optional[str] = None
    error_message: Optional[str] = None
    affected_test_ids: List[str] = Field(default_factory=list)
    raw_failure_report: Optional[FailureReport] = None
    repair_performed: Optional[str] = None
    repair_succeeded: bool = False
    created_at: str = Field(default_factory=utc_now_iso)


class PatternKnowledgeRecord(BaseModel):
    """Structured knowledge regarding a DSA pattern or algorithmic approach."""
    pattern: DSAPattern
    description: str
    common_data_structures: List[str] = Field(default_factory=list)
    typical_time_complexity: Optional[str] = None
    typical_space_complexity: Optional[str] = None
    applicable_constraints_note: Optional[str] = None
    known_strengths: List[str] = Field(default_factory=list)
    known_weaknesses: List[str] = Field(default_factory=list)
    common_pitfalls: List[str] = Field(default_factory=list)
    related_problem_ids: List[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utc_now_iso)


class RepairMemoryRecord(BaseModel):
    """Structured audit trail of a successful code correction."""
    repair_id: str
    problem_id: str
    language: SupportedLanguage
    original_failure_category: FailureCategory
    root_cause: str
    source_hash_before: str
    source_code_before: str
    source_hash_after: str
    source_code_after: str
    patch_summary: str
    tests_passed_after: int = 0
    tests_failed_after: int = 0
    verification_status_after: VerificationStatus
    regression_passed: bool = True
    created_at: str = Field(default_factory=utc_now_iso)


class RetrievedProblemContext(BaseModel):
    """Bounded, structured historical context retrieved prior to planning/repair."""
    problem: Optional[ProblemMemoryRecord] = None
    verified_solutions: List[SolutionMemoryRecord] = Field(default_factory=list)
    recent_failures: List[FailureMemoryRecord] = Field(default_factory=list)
    successful_repairs: List[RepairMemoryRecord] = Field(default_factory=list)
    pattern_notes: List[PatternKnowledgeRecord] = Field(default_factory=list)


# =====================================================================
# STAGE 20: STRUCTURED EXPERIENCE & INTELLIGENT RETRIEVAL MODELS
# =====================================================================

class ExperienceRecord(BaseModel):
    """
    Structured representation of problem-solving experience (Stage 20).
    Captures verified facts, diagnostic inferences, repair sequences, and algorithm recommendations.
    Enforces: Never contains API keys, passwords, or hidden chain-of-thought.
    """
    experience_id: str
    problem_id: str
    problem_fingerprint: str
    normalized_title: str
    dsa_pattern: DSAPattern
    algorithm_name: str
    candidate_algorithms: List[str] = Field(default_factory=list)
    language: SupportedLanguage
    complexity_expected_time: Optional[str] = None
    complexity_expected_space: Optional[str] = None
    complexity_observed_time: Optional[str] = None
    complexity_observed_space: Optional[str] = None
    constraints_summary: List[str] = Field(default_factory=list)
    status: str  # VERIFIED, FAILED, MAX_ATTEMPTS_REACHED, INFRASTRUCTURE_ERROR
    is_verified: bool = False
    failure_categories: List[str] = Field(default_factory=list)
    failure_hypotheses: List[str] = Field(default_factory=list)  # Diagnostic inferences explicitly separated from facts
    repair_actions: List[str] = Field(default_factory=list)
    attempt_count: int = 1
    tests_passed: int = 0
    tests_total: int = 0
    source_hash: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ExperienceRecommendation(BaseModel):
    """
    Structured, bounded experience recommendation delivered to Algorithm Planning (Stage 20).
    Relevance is calculated using multi-signal deterministic matching.
    """
    experience_id: str
    problem_id: str
    relevance_score: float  # Deterministically computed in [0.0, 1.0]
    pattern: DSAPattern
    algorithm: str
    language: SupportedLanguage
    verified: bool
    status: str  # e.g. VERIFIED, MAX_ATTEMPTS_REACHED, FAILED
    useful_reason: str
    complexity_time: Optional[str] = None
    complexity_space: Optional[str] = None
    warning_notes: List[str] = Field(default_factory=list)
    repair_insights: List[str] = Field(default_factory=list)


class MemoryRetrievalReport(BaseModel):
    """Observability report for memory retrieval and ranking."""
    query_problem_id: str
    query_fingerprint: str
    query_pattern: Optional[DSAPattern] = None
    retrieval_status: str  # SUCCESS, NO_RELEVANT_EXPERIENCE, MEMORY_RETRIEVAL_ERROR
    total_candidates_inspected: int = 0
    retrieved_count: int = 0
    top_k_limit: int = 5
    recommendations: List[ExperienceRecommendation] = Field(default_factory=list)
    rejected_count: int = 0
    rejection_reasons: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)

