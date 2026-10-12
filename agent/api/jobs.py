"""
Job Manager.
Tracks asynchronous and synchronous solving jobs, prevents duplicate execution via idempotency keys,
and maintains state consistency matching the agent's internal state machine.
"""

import threading
import uuid
from typing import Dict, Optional

from agent.api.models import JobDTO, utc_now_iso
from agent.core.models import (
    AgentState,
    ProblemSpec,
    SupportedLanguage,
)
from agent.core.orchestrator import SelfCorrectionOrchestrator
from agent.memory.service import MemoryService


class JobManager:
    """Thread-safe manager for tracking orchestration jobs and enforcing idempotency."""

    def __init__(self, memory_service: Optional[MemoryService] = None):
        self._jobs: Dict[str, JobDTO] = {}
        self._idempotency_map: Dict[str, str] = {}  # idempotency_key -> job_id
        self._lock = threading.Lock()
        self.memory_service = memory_service

    def get_job(self, job_id: str) -> Optional[JobDTO]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy() if job else None

    def get_job_by_idempotency_key(self, key: str) -> Optional[JobDTO]:
        with self._lock:
            job_id = self._idempotency_map.get(key)
            if job_id and job_id in self._jobs:
                return self._jobs[job_id].model_copy()
            return None

    def create_job(
        self,
        problem_id: str,
        language: SupportedLanguage,
        max_attempts: int,
        idempotency_key: Optional[str] = None,
    ) -> JobDTO:
        with self._lock:
            if idempotency_key and idempotency_key in self._idempotency_map:
                existing_id = self._idempotency_map[idempotency_key]
                if existing_id in self._jobs:
                    return self._jobs[existing_id].model_copy()

            job_id = f"job_{uuid.uuid4().hex[:12]}"
            job = JobDTO(
                job_id=job_id,
                problem_id=problem_id,
                language=language,
                state=AgentState.IDLE,
                max_attempts=max_attempts,
            )
            self._jobs[job_id] = job
            if idempotency_key:
                self._idempotency_map[idempotency_key] = job_id
            return job.model_copy()

    def run_solve_job(
        self,
        job_id: str,
        problem: ProblemSpec,
        language: SupportedLanguage,
        max_attempts: int,
        override_initial_code: Optional[str] = None,
    ) -> JobDTO:
        """Executes the autonomous loop synchronously or in background, updating job state."""
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Job {job_id} not found.")
            self._jobs[job_id].state = AgentState.ANALYZING_PROBLEM
            self._jobs[job_id].updated_at = utc_now_iso()

        orchestrator = SelfCorrectionOrchestrator(
            memory_service=self.memory_service,
            max_attempts=max_attempts,
        )

        session = orchestrator.solve(
            problem=problem,
            language=language,
            override_initial_code=override_initial_code,
        )

        with self._lock:
            job = self._jobs[job_id]
            job.state = session.final_state
            job.attempt_count = session.total_attempts
            job.is_verified = session.is_verified
            job.verified_code = session.verified_code
            job.final_status = session.final_state.value
            job.verification_report = session.verification_report
            job.error_summary = session.error_summary
            job.session_details = session
            if session.plan and any("Memory recommendation" in note for note in session.plan.assumptions_and_notes):
                job.memory_used = True
            job.updated_at = utc_now_iso()
            return job.model_copy()

