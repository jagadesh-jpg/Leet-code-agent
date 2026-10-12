"""Data models for Autonomous Problem Queue & Continuous Solving (Stage 18).

Defines:
- QueueItemStatus: explicit lifecycle states (PENDING, RUNNING, VERIFYING, VERIFIED, FAILED, MAX_ATTEMPTS_REACHED, INFRASTRUCTURE_ERROR, CANCELLED, SKIPPED).
- Valid state transitions.
- QueueItem: individual queued problem job.
- QueueRunSummary: aggregated outcome statistics.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agent.core.models import (
    FailureCategory,
    SupportedLanguage,
    VerificationStatus,
)


class QueueItemStatus(str, Enum):
    """Explicit lifecycle states for queued problem items."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    MAX_ATTEMPTS_REACHED = "MAX_ATTEMPTS_REACHED"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


# Deterministic state machine transition rules
VALID_QUEUE_TRANSITIONS: Dict[QueueItemStatus, List[QueueItemStatus]] = {
    QueueItemStatus.PENDING: [
        QueueItemStatus.RUNNING,
        QueueItemStatus.CANCELLED,
        QueueItemStatus.SKIPPED,
    ],
    QueueItemStatus.RUNNING: [
        QueueItemStatus.VERIFYING,
        QueueItemStatus.VERIFIED,
        QueueItemStatus.FAILED,
        QueueItemStatus.MAX_ATTEMPTS_REACHED,
        QueueItemStatus.INFRASTRUCTURE_ERROR,
        QueueItemStatus.CANCELLED,
    ],
    QueueItemStatus.VERIFYING: [
        QueueItemStatus.VERIFIED,
        QueueItemStatus.FAILED,
        QueueItemStatus.MAX_ATTEMPTS_REACHED,
        QueueItemStatus.INFRASTRUCTURE_ERROR,
    ],
    QueueItemStatus.VERIFIED: [],  # Terminal state
    QueueItemStatus.FAILED: [
        QueueItemStatus.PENDING,  # Re-enqueue / retry
    ],
    QueueItemStatus.MAX_ATTEMPTS_REACHED: [
        QueueItemStatus.PENDING,  # Re-enqueue with reset
    ],
    QueueItemStatus.INFRASTRUCTURE_ERROR: [
        QueueItemStatus.PENDING,  # Re-enqueue after infrastructure fixed
    ],
    QueueItemStatus.CANCELLED: [],  # Terminal state
    QueueItemStatus.SKIPPED: [
        QueueItemStatus.PENDING,  # Re-enqueue skipped item
    ],
}


class QueueItem(BaseModel):
    """Structured job model representing an autonomous problem queue item."""
    queue_item_id: str = Field(description="Unique correlation ID for this queue item")
    problem_id: str = Field(description="Problem identifier matching benchmark or specification")
    title: str = Field(default="", description="Human-readable problem title")
    problem_statement: str = Field(default="", description="Full problem description statement")
    preferred_language: SupportedLanguage = Field(default=SupportedLanguage.PYTHON, description="Target language")
    priority: int = Field(default=0, description="Priority integer (higher number = higher priority)")
    status: QueueItemStatus = Field(default=QueueItemStatus.PENDING, description="Current lifecycle state")
    attempt_count: int = Field(default=0, description="Number of execution / repair attempts performed")
    max_attempts: int = Field(default=3, description="Configured upper limit for attempts")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    final_status: Optional[str] = None
    verification_status: Optional[str] = None
    failure_category: Optional[str] = None
    result_reference: Optional[str] = None
    initial_flawed_code: Optional[str] = None
    tests_passed: int = 0
    tests_total: int = 0
    error_message: Optional[str] = None
    category: Optional[str] = None
    spec_json: Optional[str] = Field(default=None, description="Serialized ProblemSpec JSON for dynamic problems")
    raw_problem: Optional[str] = Field(default=None, description="Original raw problem text / payload")
    problem_hash: Optional[str] = Field(default=None, description="SHA256 content hash of problem for deduplication")

    def transition_to(self, new_status: QueueItemStatus) -> None:
        """Transitions state deterministically; rejects invalid transitions."""
        allowed = VALID_QUEUE_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Invalid queue state transition from {self.status.value} to {new_status.value}. "
                f"Allowed transitions: {[s.value for s in allowed]}"
            )
        self.status = new_status
        now = datetime.utcnow().isoformat()
        if new_status == QueueItemStatus.RUNNING and not self.started_at:
            self.started_at = now
        elif new_status in (
            QueueItemStatus.VERIFIED,
            QueueItemStatus.FAILED,
            QueueItemStatus.MAX_ATTEMPTS_REACHED,
            QueueItemStatus.INFRASTRUCTURE_ERROR,
            QueueItemStatus.CANCELLED,
            QueueItemStatus.SKIPPED,
        ):
            self.completed_at = now


class QueueRunSummary(BaseModel):
    """Structured summary statistics for a queue run."""
    queue_run_id: str
    total_items: int = 0
    pending: int = 0
    running: int = 0
    verified: int = 0
    failed: int = 0
    max_attempts_reached: int = 0
    infrastructure_errors: int = 0
    cancelled: int = 0
    skipped: int = 0
    total_attempts: int = 0
    total_tests: int = 0
    total_tests_passed: int = 0
    total_tests_failed: int = 0
    languages_used: List[str] = Field(default_factory=list)
    categories_used: List[str] = Field(default_factory=list)
    item_results: List[Dict[str, Any]] = Field(default_factory=list)
    execution_time_ms: float = 0.0
