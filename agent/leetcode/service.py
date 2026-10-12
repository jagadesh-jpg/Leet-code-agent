"""LeetCode Problem Intake and Solving Integration Service (Stage 31).

Connects LeetCode problems directly into the existing Agent solving pipeline:
1. Fetch problem via LeetCodeClient GraphQL.
2. Normalize problem to ProblemSpec via LeetCodeProblemAdapter.
3. Validate and enqueue via ProblemIntakeService.
4. Execute via existing Gemini planning, code generation, testing, repair, verification.
5. Prepare submission payload without executing live external submission.
"""

from typing import Any, Dict, Optional, Union
from agent.core.models import SupportedLanguage
from agent.intake.models import DynamicSolveResult
from agent.intake.service import ProblemIntakeService
import hashlib
from agent.leetcode.adapter import LeetCodeProblemAdapter
from agent.leetcode.client import LeetCodeClient
from agent.leetcode.exceptions import (
    LeetCodeAuthError,
    LeetCodeError,
    LeetCodeNetworkError,
    LeetCodeProblemNotFoundError,
    LeetCodeRateLimitError,
    LeetCodeUnsupportedOperationError,
)
from agent.leetcode.models import (
    LeetCodeProblemDetail,
    LeetCodeSubmissionRequest,
    LeetCodeSubmissionResponse,
    LeetCodeSubmissionStatus,
)


class LeetCodeSolveResult(DynamicSolveResult):
    """Extension of DynamicSolveResult carrying LeetCode metadata, submission prep, and real judge verdict."""
    leetcode_question_id: Optional[str] = None
    leetcode_title_slug: Optional[str] = None
    generated_solution_code: Optional[str] = None
    submission_prepared: bool = False
    submission_prep_status: Optional[str] = None
    request_sent: bool = False
    submission_id: Optional[str] = None
    judge_verdict: Optional[str] = None
    judge_runtime: Optional[str] = None
    judge_memory: Optional[str] = None
    judge_details: Dict[str, Any] = {}


class LeetCodeWorkflowService:
    """End-to-End Orchestrator for LeetCode problem fetching, solving, submission, and verdict retrieval."""

    def __init__(
        self,
        client: Optional[LeetCodeClient] = None,
        intake_service: Optional[ProblemIntakeService] = None,
    ):
        self.client = client or LeetCodeClient()
        self.intake = intake_service or ProblemIntakeService()

    def solve_leetcode_problem(
        self,
        title_slug: str,
        preferred_language: Optional[Union[str, SupportedLanguage]] = None,
        max_attempts: Optional[int] = None,
        prepare_submission: bool = True,
        live_submission: bool = False,
        confirmed: bool = False,
    ) -> LeetCodeSolveResult:
        """
        Executes end-to-end LeetCode problem solve:
        1. Query LeetCode GraphQL for question details.
        2. Normalize question details into canonical ProblemSpec.
        3. Pass through dynamic intake solver (Gemini plan, generate, test, repair, verify).
        4. Validate submission preconditions (verified status, matching code hash, auth).
        5. In dry-run mode (default), prepare payload without sending external request.
        6. In live mode with explicit user confirmation, perform submission and bounded verdict polling.
        """
        # Step 1: Fetch problem detail
        detail: LeetCodeProblemDetail = self.client.get_problem(title_slug)

        # Step 2: Language determination
        target_lang = self.intake.resolve_language_policy(
            preferred_language=preferred_language,
            statement_text=detail.content_text or detail.content_html,
        )

        # Step 3: Normalize to canonical ProblemSpec
        spec = LeetCodeProblemAdapter.to_problem_spec(detail, preferred_lang=target_lang)

        # Step 4: Solve via ProblemIntakeService
        dynamic_res = self.intake.solve_dynamically(
            raw_input=spec,
            preferred_language=target_lang,
            max_attempts=max_attempts,
        )

        # Step 5: Extract generated code if solved/verified
        solution_code = None
        if dynamic_res.is_verified or dynamic_res.status == "VERIFIED":
            queue_item = self.intake.store.get_item(dynamic_res.queue_item_id)
            if queue_item:
                solution_code = queue_item.result_reference

        # Step 6: Submission validation and execution
        submission_prep_ok = False
        prep_msg = None
        request_sent = False
        sub_id = None
        judge_verdict = None
        judge_rt = None
        judge_mem = None
        judge_meta: Dict[str, Any] = {}

        if prepare_submission or live_submission:
            lang_code_map = {
                SupportedLanguage.PYTHON: "python3",
                SupportedLanguage.CPP: "cpp",
                SupportedLanguage.JAVA: "java",
                SupportedLanguage.C: "c",
            }
            sub_lang = lang_code_map.get(target_lang, "python3")

            # Validate preconditions
            if not dynamic_res.is_verified:
                prep_msg = f"Submission rejected: solution was not locally verified (status: {dynamic_res.status})."
            elif not solution_code or not solution_code.strip():
                prep_msg = "Submission rejected: no solution code generated."
            else:
                # Check code hash consistency
                current_hash = hashlib.sha256(solution_code.encode("utf-8")).hexdigest()[:16]
                if dynamic_res.code_hash and current_hash != dynamic_res.code_hash:
                    prep_msg = f"Submission rejected: code hash mismatch (computed {current_hash} != result {dynamic_res.code_hash})."
                else:
                    sub_req = LeetCodeSubmissionRequest(
                        question_id=detail.question_id,
                        title_slug=detail.title_slug,
                        lang=sub_lang,
                        typed_code=solution_code,
                        code_hash=current_hash,
                        is_locally_verified=dynamic_res.is_verified,
                    )

                    if live_submission:
                        if not confirmed:
                            prep_msg = "Live submission blocked: explicit user confirmation flag (--confirm-live-submission) is required."
                        else:
                            try:
                                sub_resp = self.client.submit_solution(sub_req)
                                request_sent = True
                                sub_id = sub_resp.submission_id
                                prep_msg = f"Live submission sent (ID {sub_id}). Polling judge..."

                                # Poll boundedly for verdict
                                verdict_resp = self.client.poll_submission_verdict(sub_id)
                                judge_verdict = verdict_resp.status.value
                                judge_rt = verdict_resp.run_time
                                judge_mem = verdict_resp.run_memory
                                judge_meta = verdict_resp.raw_result
                                prep_msg = f"Verdict retrieved: {judge_verdict} ({verdict_resp.status_msg})"
                                submission_prep_ok = True
                            except Exception as e:
                                prep_msg = f"Live submission error: {str(e)}"
                    else:
                        # Dry-run validation (default)
                        try:
                            dry_resp = self.client.prepare_submission(sub_req, dry_run=True)
                            submission_prep_ok = True
                            sub_id = dry_resp.submission_id
                            prep_msg = dry_resp.status_msg
                        except Exception as e:
                            prep_msg = f"Dry-run preparation notice: {str(e)}"

        return LeetCodeSolveResult(
            problem_id=dynamic_res.problem_id,
            queue_item_id=dynamic_res.queue_item_id,
            job_id=dynamic_res.job_id,
            status=dynamic_res.status,
            language=dynamic_res.language,
            attempt_count=dynamic_res.attempt_count,
            tests_total=dynamic_res.tests_total,
            tests_passed=dynamic_res.tests_passed,
            verification=dynamic_res.verification,
            error_summary=dynamic_res.error_summary,
            code_hash=dynamic_res.code_hash,
            problem_hash=dynamic_res.problem_hash,
            is_verified=dynamic_res.is_verified,
            leetcode_question_id=detail.question_id,
            leetcode_title_slug=detail.title_slug,
            generated_solution_code=solution_code,
            submission_prepared=submission_prep_ok,
            submission_prep_status=prep_msg,
            request_sent=request_sent,
            submission_id=sub_id,
            judge_verdict=judge_verdict,
            judge_runtime=judge_rt,
            judge_memory=judge_mem,
            judge_details=judge_meta,
        )
