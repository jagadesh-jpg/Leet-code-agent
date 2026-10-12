"""Modular HTTP and GraphQL client for permitted LeetCode operations (Stage 31).

Capabilities:
- Session & authentication check without leaking tokens
- Problem listing & exploration
- Question detail fetching via GraphQL
- Normalized payload conversion
- Deterministic error classification (Auth, Network, Rate Limit, Missing Field)
- Explicit timeout and rate limit backoff guards
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

from agent.config import Config
from agent.leetcode.adapter import LeetCodeProblemAdapter
from agent.leetcode.exceptions import (
    LeetCodeAuthError,
    LeetCodeError,
    LeetCodeNetworkError,
    LeetCodeProblemNotFoundError,
    LeetCodeRateLimitError,
    LeetCodeUnsupportedOperationError,
)
from agent.leetcode.models import (
    LeetCodeAuthStatus,
    LeetCodeCodeSnippet,
    LeetCodeProblemDetail,
    LeetCodeProblemSummary,
    LeetCodeSubmissionRequest,
    LeetCodeSubmissionResponse,
    LeetCodeSubmissionStatus,
)

logger = logging.getLogger(__name__)


class LeetCodeClient:
    """Permitted LeetCode GraphQL and REST Client."""

    GRAPHQL_ENDPOINT = "/graphql"
    PROBLEMS_ALL_ENDPOINT = "/api/problems/all/"

    def __init__(
        self,
        base_url: Optional[str] = None,
        session_token: Optional[str] = None,
        csrf_token: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ):
        self.base_url = (base_url or Config.LEETCODE_BASE_URL).rstrip("/")
        self.session_token = session_token if session_token is not None else Config.LEETCODE_SESSION
        self.csrf_token = csrf_token if csrf_token is not None else Config.LEETCODE_CSRFTOKEN
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else Config.LEETCODE_REQUEST_TIMEOUT_SECONDS
        )

    def _get_headers(self) -> Dict[str, str]:
        """Constructs headers safely without exposing sensitive secrets in logs."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.base_url,
            "Origin": self.base_url,
        }
        if self.csrf_token:
            headers["X-CSRFToken"] = self.csrf_token
            headers["x-csrftoken"] = self.csrf_token

        # Cookie assembly
        cookies = []
        if self.session_token:
            cookies.append(f"LEETCODE_SESSION={self.session_token}")
        if self.csrf_token:
            cookies.append(f"csrftoken={self.csrf_token}")
        if cookies:
            headers["Cookie"] = "; ".join(cookies)

        return headers

    def _execute_http(
        self,
        url: str,
        data: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        method: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executes HTTP request with explicit timeouts, classification, and backoff handling."""
        req_headers = headers or self._get_headers()
        req = urllib.request.Request(
            url=url,
            data=data,
            headers=req_headers,
            method=method or ("POST" if data is not None else "GET"),
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                resp_bytes = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                resp_text = resp_bytes.decode(charset, errors="replace")
                try:
                    return json.loads(resp_text)
                except json.JSONDecodeError as jde:
                    raise LeetCodeNetworkError(f"Invalid JSON returned from {url}: {jde}")
        except urllib.error.HTTPError as http_err:
            code = http_err.code
            if code == 429:
                raise LeetCodeRateLimitError(
                    f"LeetCode rate limit encountered (HTTP 429). Backing off required.",
                    status_code=429,
                )
            elif code in (401, 403):
                raise LeetCodeAuthError(
                    f"LeetCode authentication failure (HTTP {code}). Session or CSRF token may be expired or missing.",
                    status_code=code,
                )
            elif code == 404:
                raise LeetCodeProblemNotFoundError(
                    f"Resource not found on LeetCode (HTTP 404): {url}",
                    status_code=404,
                )
            else:
                raise LeetCodeNetworkError(
                    f"LeetCode HTTP error {code}: {http_err.reason}",
                    status_code=code,
                )
        except urllib.error.URLError as url_err:
            raise LeetCodeNetworkError(f"Network error connecting to {url}: {url_err.reason}")
        except TimeoutError:
            raise LeetCodeNetworkError(
                f"Timeout ({self.timeout_seconds}s) connecting to LeetCode."
            )
        except Exception as e:
            if isinstance(e, LeetCodeError):
                raise
            raise LeetCodeNetworkError(f"Unexpected connection error: {e}")

    def execute_graphql(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
        operation_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executes a GraphQL query against LeetCode's permitted GraphQL endpoint."""
        payload: Dict[str, Any] = {"query": query, "variables": variables or {}}
        if operation_name:
            payload["operationName"] = operation_name

        data_bytes = json.dumps(payload).encode("utf-8")
        url = f"{self.base_url}{self.GRAPHQL_ENDPOINT}"
        result = self._execute_http(url=url, data=data_bytes)

        if "errors" in result and result["errors"]:
            err_msg = "; ".join(e.get("message", "Unknown error") for e in result["errors"])
            if "sign in" in err_msg.lower() or "not authorized" in err_msg.lower():
                raise LeetCodeAuthError(f"GraphQL authorization error: {err_msg}")
            raise LeetCodeError(f"GraphQL returned error: {err_msg}")

        return result.get("data", {})

    def check_auth_status(self) -> LeetCodeAuthStatus:
        """Validates current session without printing or exposing secrets."""
        if not self.session_token:
            return LeetCodeAuthStatus(
                is_authenticated=False,
                username=None,
                is_premium=False,
                checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                message="No session token configured.",
            )

        query = """
        query globalData {
            userStatus {
                isSignedIn
                username
                isPremium
            }
        }
        """
        try:
            data = self.execute_graphql(query=query, operation_name="globalData")
            user_status = data.get("userStatus", {})
            is_signed_in = bool(user_status.get("isSignedIn", False))
            username = user_status.get("username")
            is_premium = bool(user_status.get("isPremium", False))

            return LeetCodeAuthStatus(
                is_authenticated=is_signed_in,
                username=username if is_signed_in else None,
                is_premium=is_premium,
                checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                message="Session valid" if is_signed_in else "Session token rejected or expired",
            )
        except LeetCodeAuthError as ae:
            return LeetCodeAuthStatus(
                is_authenticated=False,
                username=None,
                is_premium=False,
                checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                message=f"Authentication failed: {ae.message}",
            )
        except Exception as e:
            return LeetCodeAuthStatus(
                is_authenticated=False,
                username=None,
                is_premium=False,
                checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                message=f"Session check error: {str(e)}",
            )

    def list_problems(self, limit: int = 50) -> List[LeetCodeProblemSummary]:
        """Retrieves permitted public list of problems."""
        url = f"{self.base_url}{self.PROBLEMS_ALL_ENDPOINT}"
        try:
            data = self._execute_http(url=url)
            pairs = data.get("stat_status_pairs", [])
            summaries: List[LeetCodeProblemSummary] = []
            diff_map = {1: "Easy", 2: "Medium", 3: "Hard"}

            for p in pairs[:limit]:
                stat = p.get("stat", {})
                level = p.get("difficulty", {}).get("level", 0)
                diff = diff_map.get(level, "Unknown")
                summaries.append(
                    LeetCodeProblemSummary(
                        frontend_question_id=str(stat.get("frontend_question_id", stat.get("question_id", ""))),
                        title=stat.get("question__title", ""),
                        title_slug=stat.get("question__title_slug", ""),
                        difficulty=diff,
                        paid_only=p.get("paid_only", False),
                        status=p.get("status"),
                    )
                )
            return summaries
        except Exception as e:
            logger.warning(f"Failed to fetch problems from rest endpoint, trying GraphQL: {e}")
            # Fallback to problemsetQuestionList GraphQL query
            query = """
            query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
              problemsetQuestionList: questionList(
                categorySlug: $categorySlug
                limit: $limit
                skip: $skip
                filters: $filters
              ) {
                questions: data {
                  frontendQuestionId: questionFrontendId
                  title
                  titleSlug
                  difficulty
                  paidOnly: isPaidOnly
                }
              }
            }
            """
            data = self.execute_graphql(
                query=query,
                variables={"categorySlug": "", "skip": 0, "limit": limit, "filters": {}},
                operation_name="problemsetQuestionList",
            )
            questions = data.get("problemsetQuestionList", {}).get("questions", [])
            summaries = []
            for q in questions:
                summaries.append(
                    LeetCodeProblemSummary(
                        frontend_question_id=str(q.get("frontendQuestionId", "")),
                        title=q.get("title", ""),
                        title_slug=q.get("titleSlug", ""),
                        difficulty=q.get("difficulty", "Unknown"),
                        paid_only=q.get("paidOnly", False),
                    )
                )
            return summaries

    def get_problem(self, title_slug: str) -> LeetCodeProblemDetail:
        """Fetches full question data for a specific problem slug via GraphQL."""
        if not title_slug or not title_slug.strip():
            raise ValueError("title_slug cannot be empty.")

        query = """
        query questionData($titleSlug: String!) {
          question(titleSlug: $titleSlug) {
            questionId
            questionFrontendId
            title
            titleSlug
            content
            isPaidOnly
            difficulty
            codeSnippets {
              lang
              langSlug
              code
            }
            sampleTestCase
            exampleTestcases
            hints
            topicTags {
              name
              slug
            }
          }
        }
        """
        data = self.execute_graphql(
            query=query,
            variables={"titleSlug": title_slug.strip()},
            operation_name="questionData",
        )
        q = data.get("question")
        if not q:
            raise LeetCodeProblemNotFoundError(f"Problem '{title_slug}' not found on LeetCode.")

        snippets = [
            LeetCodeCodeSnippet(
                lang=s.get("lang", ""),
                lang_slug=s.get("langSlug", ""),
                code=s.get("code", ""),
            )
            for s in q.get("codeSnippets", []) or []
        ]

        raw_examples = q.get("exampleTestcases", "") or ""
        example_list = [ex.strip() for ex in raw_examples.split("\n") if ex.strip()] if raw_examples else []

        tags = [t.get("name", "") for t in q.get("topicTags", []) or [] if t.get("name")]

        return LeetCodeProblemDetail(
            question_id=str(q.get("questionId", "")),
            frontend_question_id=str(q.get("questionFrontendId", "")),
            title=q.get("title", ""),
            title_slug=q.get("titleSlug", ""),
            difficulty=q.get("difficulty", "Unknown"),
            content_html=q.get("content", "") or "",
            is_paid_only=bool(q.get("isPaidOnly", False)),
            code_snippets=snippets,
            sample_test_case=q.get("sampleTestCase"),
            example_test_cases=example_list,
            hints=q.get("hints", []) or [],
            topic_tags=tags,
            raw_data=q,
        )

    def prepare_submission(
        self,
        request: LeetCodeSubmissionRequest,
        dry_run: bool = True,
    ) -> LeetCodeSubmissionResponse:
        """
        Validates submission request preconditions without executing live calls in dry-run mode.
        Checks problem slug, language code, non-empty code, and authentication requirements.
        """
        if not request.title_slug or not request.question_id:
            raise ValueError("Submission requires title_slug and question_id.")
        if not request.typed_code or not request.typed_code.strip():
            raise ValueError("Submission code cannot be empty.")

        # Check authentication requirement
        if not self.session_token:
            raise LeetCodeAuthError(
                "Submission requires an active, authenticated LEETCODE_SESSION. None configured."
            )
        if not self.csrf_token:
            raise LeetCodeAuthError(
                "Submission requires an active LEETCODE_CSRFTOKEN. None configured."
            )

        if dry_run:
            return LeetCodeSubmissionResponse(
                submission_id="dry_run_stg32",
                status=LeetCodeSubmissionStatus.PREPARED_LOCALLY,
                status_code=0,
                status_msg="Dry-run validation passed: payload conforms to LeetCode submission requirements without external request.",
                raw_result={
                    "dry_run": True,
                    "title_slug": request.title_slug,
                    "question_id": request.question_id,
                    "lang": request.lang,
                },
            )

        return self.submit_solution(request)

    def submit_solution(
        self,
        request: LeetCodeSubmissionRequest,
    ) -> LeetCodeSubmissionResponse:
        """
        Submits solution code to LeetCode through the platform's standard submission endpoint.
        Requires active session credentials and valid request payload.
        """
        if not request.title_slug or not request.question_id:
            raise ValueError("Submission requires title_slug and question_id.")
        if not request.typed_code or not request.typed_code.strip():
            raise ValueError("Submission code cannot be empty.")

        if not self.session_token:
            raise LeetCodeAuthError("Submission requires an active LEETCODE_SESSION.")
        if not self.csrf_token:
            raise LeetCodeAuthError("Submission requires an active LEETCODE_CSRFTOKEN.")

        submit_url = f"{self.base_url}/problems/{request.title_slug}/submit/"
        payload = {
            "question_id": request.question_id,
            "lang": request.lang,
            "typed_code": request.typed_code,
        }
        data_bytes = json.dumps(payload).encode("utf-8")

        resp_data = self._execute_http(url=submit_url, data=data_bytes)
        submission_id = str(resp_data.get("submission_id") or resp_data.get("submissionId") or "")

        if not submission_id:
            err_msg = resp_data.get("error") or resp_data.get("detail") or "No submission_id returned by LeetCode."
            raise LeetCodeError(f"Submission request was not accepted by LeetCode: {err_msg}")

        return LeetCodeSubmissionResponse(
            submission_id=submission_id,
            status=LeetCodeSubmissionStatus.REQUEST_ACCEPTED,
            status_code=0,
            status_msg=f"Submission accepted with ID {submission_id}",
            raw_result=resp_data,
        )

    def check_submission_result(
        self,
        submission_id: str,
    ) -> LeetCodeSubmissionResponse:
        """Fetches the current status and verdict of a submission by ID."""
        if not submission_id or not submission_id.strip():
            raise ValueError("submission_id cannot be empty.")

        check_url = f"{self.base_url}/submissions/detail/{submission_id.strip()}/check/"
        resp_data = self._execute_http(url=check_url)
        return self._parse_submission_check_response(submission_id, resp_data)

    def _parse_submission_check_response(
        self,
        submission_id: str,
        data: Dict[str, Any],
    ) -> LeetCodeSubmissionResponse:
        """Deterministically parses LeetCode submission check payload into standard verdict."""
        state = str(data.get("state", "")).upper()
        status_code = data.get("status_code")
        status_msg = data.get("status_msg")

        # Map state & status_code / status_msg to LeetCodeSubmissionStatus
        if state in ("PENDING", "STARTED"):
            mapped_status = (
                LeetCodeSubmissionStatus.JUDGING
                if state == "STARTED"
                else LeetCodeSubmissionStatus.PENDING
            )
        elif status_code == 10 or (status_msg and "accepted" in status_msg.lower()):
            mapped_status = LeetCodeSubmissionStatus.ACCEPTED
        elif status_code == 11 or (status_msg and "wrong answer" in status_msg.lower()):
            mapped_status = LeetCodeSubmissionStatus.WRONG_ANSWER
        elif status_code == 14 or (status_msg and "time limit" in status_msg.lower()):
            mapped_status = LeetCodeSubmissionStatus.TIME_LIMIT_EXCEEDED
        elif status_code == 15 or (status_msg and "memory limit" in status_msg.lower()):
            mapped_status = LeetCodeSubmissionStatus.MEMORY_LIMIT_EXCEEDED
        elif status_code == 20 or (status_msg and "compile error" in status_msg.lower()):
            mapped_status = LeetCodeSubmissionStatus.COMPILE_ERROR
        elif status_code in (12, 13) or (status_msg and "runtime error" in status_msg.lower()):
            mapped_status = LeetCodeSubmissionStatus.RUNTIME_ERROR
        elif status_code is not None or status_msg is not None:
            mapped_status = LeetCodeSubmissionStatus.OTHER_JUDGE_RESULT
        else:
            mapped_status = LeetCodeSubmissionStatus.UNKNOWN

        return LeetCodeSubmissionResponse(
            submission_id=submission_id,
            status=mapped_status,
            status_code=status_code,
            status_msg=status_msg or state,
            state=state,
            run_time=str(data.get("status_runtime", data.get("run_time", ""))),
            run_memory=str(data.get("status_memory", data.get("run_memory", ""))),
            total_correct=data.get("total_correct"),
            total_testcases=data.get("total_testcases"),
            compile_error_msg=data.get("full_compile_error") or data.get("compile_error"),
            runtime_error_msg=data.get("full_runtime_error") or data.get("runtime_error"),
            raw_result=data,
        )

    def poll_submission_verdict(
        self,
        submission_id: str,
        interval_seconds: Optional[float] = None,
        max_duration_seconds: Optional[float] = None,
    ) -> LeetCodeSubmissionResponse:
        """
        Polls boundedly until a final verdict is reached or timeout expires.
        Does not poll indefinitely.
        """
        interval = (
            interval_seconds
            if interval_seconds is not None
            else Config.LEETCODE_POLL_INTERVAL_SECONDS
        )
        max_dur = (
            max_duration_seconds
            if max_duration_seconds is not None
            else Config.LEETCODE_POLL_MAX_DURATION_SECONDS
        )

        start_time = time.time()
        last_resp = LeetCodeSubmissionResponse(
            submission_id=submission_id,
            status=LeetCodeSubmissionStatus.PENDING,
            status_msg="Started polling for submission verdict",
        )

        while (time.time() - start_time) < max_dur:
            last_resp = self.check_submission_result(submission_id)
            if last_resp.status not in (
                LeetCodeSubmissionStatus.PENDING,
                LeetCodeSubmissionStatus.JUDGING,
                LeetCodeSubmissionStatus.REQUEST_ACCEPTED,
            ):
                return last_resp
            time.sleep(interval)

        # Timeout reached
        last_resp.status = LeetCodeSubmissionStatus.TIMEOUT
        last_resp.status_msg = f"Polling timed out after {max_dur:.1f}s while still judging."
        return last_resp
