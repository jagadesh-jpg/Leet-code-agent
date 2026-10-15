"""Dynamic Problem Intake Service (Stage 19).

Coordinates:
- Intake of Raw Text/Markdown, Structured JSON, or ProblemSpec.
- Problem validation & normalization into canonical ProblemSpec.
- Deterministic language selection policy (documented and testable).
- Duplicate detection & re-run policy.
- Dynamic queue item creation and correlation.
- Autonomous execution through existing Stage 18 queue runner and Stages 1-17 pipeline.
- Auditability, SQLite persistence, and Stage 19 Result Contract.
"""

import hashlib
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from agent.core.models import (
    ProblemSpec,
    SupportedLanguage,
    VerificationStatus,
)
from agent.intake.models import (
    DynamicSolveResult,
    IntakeValidationStatus,
    ProblemValidationReport,
    VerificationEvidenceDTO,
)
from agent.intake.validator import ProblemValidator
from agent.queue.models import QueueItem, QueueItemStatus, QueueRunSummary
from agent.queue.queue_runner import AutonomousQueueRunner
from agent.queue.store import SQLiteQueueStore


class ProblemIntakeService:
    """
    Primary orchestration facade for Stage 19 Dynamic Problem Intake.
    """

    def __init__(
        self,
        queue_runner: Optional[AutonomousQueueRunner] = None,
        queue_store: Optional[SQLiteQueueStore] = None,
        db_path: str = "agent_queue.db",
        allow_rerun_duplicates: bool = True,
        memory_service: Optional[Any] = None,
        llm_provider: Optional[Any] = None,
    ):
        self.store = queue_store or SQLiteQueueStore(db_path=db_path)
        self.memory_service = memory_service
        self.llm = llm_provider
        self.runner = queue_runner or AutonomousQueueRunner(
            store=self.store,
            allow_duplicates=allow_rerun_duplicates,
            memory_service=self.memory_service,
            llm_provider=self.llm,
        )
        self.allow_rerun_duplicates = allow_rerun_duplicates


    @staticmethod
    def compute_problem_hash(raw_text: str, title: str = "") -> str:
        """Deterministic content hash to identify duplicates regardless of whitespace differences."""
        normalized = "".join(raw_text.split()).lower()
        title_norm = "".join(title.split()).lower()
        key = f"{title_norm}::{normalized}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def resolve_language_policy(
        preferred_language: Optional[Union[str, SupportedLanguage]] = None,
        statement_text: str = "",
    ) -> SupportedLanguage:
        """
        Deterministic, testable language selection policy:
        1. If explicit preferred_language provided and valid -> return it.
        2. If invalid preferred_language string -> raise ValueError.
        3. If no preferred_language:
           - Check for explicit language markers in code block snippets in the statement.
           - If none, deterministic default: SupportedLanguage.PYTHON.
        """
        if preferred_language is not None:
            if isinstance(preferred_language, SupportedLanguage):
                return preferred_language
            norm = preferred_language.strip().lower()
            if norm in ProblemValidator.SUPPORTED_LANGUAGES:
                return ProblemValidator.SUPPORTED_LANGUAGES[norm]
            raise ValueError(f"Unsupported language policy request: '{preferred_language}'")

        # Heuristic detection from code signatures
        if "vector<int>" in statement_text or "unordered_map" in statement_text or "class Solution {" in statement_text and "public:" in statement_text:
            return SupportedLanguage.CPP
        elif "int*" in statement_text and "malloc" in statement_text:
            return SupportedLanguage.C
        elif "public int" in statement_text or "class Solution {" in statement_text and "public int" in statement_text:
            return SupportedLanguage.JAVA
        elif "def " in statement_text:
            return SupportedLanguage.PYTHON

        # Deterministic standard fallback: Python
        return SupportedLanguage.PYTHON

    def intake_problem(
        self,
        raw_input: Union[str, Dict[str, Any], ProblemSpec],
        preferred_language: Optional[Union[str, SupportedLanguage]] = None,
        priority: int = 0,
        max_attempts: Optional[int] = None,
        initial_flawed_code: Optional[str] = None,
        allow_rerun: Optional[bool] = None,
    ) -> Tuple[Optional[QueueItem], ProblemValidationReport]:
        """
        Intake a single dynamic problem:
        1. Validate
        2. Normalize
        3. Check duplicates
        4. Enqueue into Stage 18 queue
        5. Return (QueueItem, Report)
        """
        # Validate
        report, spec = ProblemValidator.validate(raw_input, preferred_language=preferred_language)
        if report.status == IntakeValidationStatus.INVALID_PROBLEM or not spec:
            return None, report

        raw_str = raw_input if isinstance(raw_input, str) else json.dumps(raw_input if isinstance(raw_input, dict) else raw_input.model_dump())
        p_hash = self.compute_problem_hash(raw_str, title=spec.title)

        # Check duplicate policy
        should_rerun = self.allow_rerun_duplicates if allow_rerun is None else allow_rerun
        existing_items = self.store.list_items()
        for ex in existing_items:
            if (ex.problem_hash == p_hash or (ex.problem_id == spec.id and ex.preferred_language == report.selected_language)):
                if not should_rerun and ex.status in (QueueItemStatus.PENDING, QueueItemStatus.RUNNING, QueueItemStatus.VERIFIED):
                    report.status = IntakeValidationStatus.INVALID_PROBLEM
                    report.issues.append(f"Duplicate problem rejected under policy: hash {p_hash}, item {ex.queue_item_id}")
                    return None, report

        # Create queue item
        item = self.runner.enqueue(
            problem_id=spec.id,
            preferred_language=report.selected_language or SupportedLanguage.PYTHON,
            priority=priority,
            max_attempts=max_attempts,
            initial_flawed_code=initial_flawed_code,
            custom_statement=spec.description,
            custom_title=spec.title,
            spec_json=spec.model_dump_json(),
            raw_problem=raw_str,
            problem_hash=p_hash,
        )

        return item, report

    def intake_batch(
        self,
        problems: List[Union[str, Dict[str, Any], ProblemSpec]],
        default_language: Optional[Union[str, SupportedLanguage]] = None,
    ) -> List[Tuple[Optional[QueueItem], ProblemValidationReport]]:
        """
        Multi-problem dynamic intake with failure isolation.
        Invalid problems do NOT block subsequent valid problems.
        """
        results = []
        for idx, p in enumerate(problems):
            try:
                # If problem is dict and defines preferred_language, let intake_problem pick it up
                item, report = self.intake_problem(
                    raw_input=p,
                    preferred_language=default_language,
                    priority=len(problems) - idx,  # FIFO ordering via priority
                )
                results.append((item, report))
            except Exception as e:
                err_report = ProblemValidationReport(
                    status=IntakeValidationStatus.INVALID_PROBLEM,
                    issues=[f"Intake exception: {str(e)}"],
                    is_acceptable=False,
                )
                results.append((None, err_report))
        return results

    def solve_dynamically(
        self,
        raw_input: Union[str, Dict[str, Any], ProblemSpec],
        preferred_language: Optional[Union[str, SupportedLanguage]] = None,
        max_attempts: Optional[int] = None,
        initial_flawed_code: Optional[str] = None,
    ) -> DynamicSolveResult:
        """
        End-to-End Single-Problem Autonomous Solve:
        RECEIVE -> VALIDATE -> NORMALIZE -> QUEUE -> SOLVE -> PERSIST -> RESULT CONTRACT.
        """
        item, report = self.intake_problem(
            raw_input=raw_input,
            preferred_language=preferred_language,
            max_attempts=max_attempts,
            initial_flawed_code=initial_flawed_code,
        )

        job_uuid = f"dyn_job_{uuid.uuid4().hex[:8]}"

        if not item or report.status == IntakeValidationStatus.INVALID_PROBLEM:
            return DynamicSolveResult(
                problem_id=report.title or "unknown_problem",
                queue_item_id="none",
                job_id=job_uuid,
                status="INVALID_PROBLEM",
                language=report.selected_language.value if report.selected_language else "unknown",
                attempt_count=0,
                tests_total=0,
                tests_passed=0,
                verification=VerificationEvidenceDTO(),
                error_summary="; ".join(report.issues),
                is_verified=False,
            )

        # Transition from PENDING to RUNNING first
        item.transition_to(QueueItemStatus.RUNNING)
        self.store.save_item(item)
        self.store.record_transition(item.queue_item_id, QueueItemStatus.PENDING, QueueItemStatus.RUNNING, item.started_at or "")

        # Process queue item through existing autonomous pipeline
        status, is_verified, attempts, passed, total, err_msg = self.runner._process_item(item)

        item.attempt_count = attempts
        item.tests_passed = passed
        item.tests_total = total
        item.error_message = err_msg

        if status == QueueItemStatus.VERIFIED:
            item.transition_to(QueueItemStatus.VERIFIED)
            item.final_status = "VERIFIED"
            item.verification_status = "VERIFIED"
        elif status == QueueItemStatus.MAX_ATTEMPTS_REACHED:
            item.transition_to(QueueItemStatus.MAX_ATTEMPTS_REACHED)
            item.final_status = "FAILED"
            item.verification_status = "MAX_ATTEMPTS_REACHED"
        elif status == QueueItemStatus.INFRASTRUCTURE_ERROR:
            item.transition_to(QueueItemStatus.INFRASTRUCTURE_ERROR)
            item.final_status = "INFRASTRUCTURE_ERROR"
            item.verification_status = "INFRASTRUCTURE_ERROR"
        else:
            item.transition_to(QueueItemStatus.FAILED)
            item.final_status = "FAILED"
            item.verification_status = "FAILED"

        self.store.save_item(item)
        self.store.record_transition(item.queue_item_id, QueueItemStatus.RUNNING, item.status, item.completed_at or "")

        verification_dto = VerificationEvidenceDTO(
            correctness=is_verified,
            constraints=is_verified,
            complexity=is_verified,
            plan_consistency=is_verified,
        )

        code_str = item.result_reference
        c_hash = hashlib.sha256(code_str.encode("utf-8")).hexdigest()[:16] if code_str else None

        return DynamicSolveResult(
            problem_id=item.problem_id,
            queue_item_id=item.queue_item_id,
            job_id=job_uuid,
            status=status.value,
            language=item.preferred_language.value,
            attempt_count=attempts,
            tests_total=total,
            tests_passed=passed,
            verification=verification_dto,
            error_summary=err_msg,
            code_hash=c_hash,
            problem_hash=item.problem_hash,
            is_verified=is_verified,
        )
