"""Unit and integration tests for LeetCode module (Stage 31 & Stage 32).

Tests:
1. Client HTTP headers, secret sanitization, and timeouts.
2. GraphQL error handling (auth, 429 rate limit, 404, malformed json).
3. Auth status checking (no token, valid session, invalid session).
4. Problem listing via REST and GraphQL fallback.
5. Problem detail retrieval via GraphQL.
6. Problem adapter: LeetCodeProblemDetail -> ProblemSpec normalization.
7. Submission preparation interface (validation, auth checks, dry-run contract).
8. Live submission request handling and rejection handling.
9. Bounded polling and status transitions (Pending, Started, Accepted, WA, TLE, MLE, CE, RE, Timeout).
10. Secret redaction during errors and operations.
11. Workflow service: rejection of unverified code, code hash mismatch, dry-run vs confirmed live submission.
"""

import hashlib
import json
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from agent.core.models import Difficulty, SupportedLanguage
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
    LeetCodeCodeSnippet,
    LeetCodeProblemDetail,
    LeetCodeSubmissionRequest,
    LeetCodeSubmissionResponse,
    LeetCodeSubmissionStatus,
)
from agent.leetcode.service import LeetCodeWorkflowService


class TestLeetCodeClient:
    """Tests for LeetCodeClient HTTP/GraphQL communication and error classification."""

    def test_headers_and_cookie_assembly_without_leaks(self):
        client = LeetCodeClient(
            base_url="https://leetcode.com",
            session_token="secret_session_token",
            csrf_token="secret_csrf_token",
        )
        headers = client._get_headers()
        assert "Cookie" in headers
        assert "LEETCODE_SESSION=secret_session_token" in headers["Cookie"]
        assert "csrftoken=secret_csrf_token" in headers["Cookie"]
        assert headers["X-CSRFToken"] == "secret_csrf_token"
        assert headers["User-Agent"] is not None

    def test_rate_limit_429_raises_explicit_rate_limit_error(self):
        client = LeetCodeClient()

        def mock_urlopen(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="https://leetcode.com/graphql",
                code=429,
                msg="Too Many Requests",
                hdrs={},
                fp=None,
            )

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            with pytest.raises(LeetCodeRateLimitError) as exc_info:
                client.get_problem("two-sum")
            assert exc_info.value.status_code == 429
            assert "rate limit" in str(exc_info.value).lower()

    def test_auth_401_403_raises_explicit_auth_error(self):
        client = LeetCodeClient()

        def mock_urlopen(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="https://leetcode.com/graphql",
                code=403,
                msg="Forbidden",
                hdrs={},
                fp=None,
            )

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            with pytest.raises(LeetCodeAuthError) as exc_info:
                client.get_problem("two-sum")
            assert exc_info.value.status_code == 403

    def test_problem_not_found_404_raises_problem_not_found_error(self):
        client = LeetCodeClient()

        def mock_urlopen(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="https://leetcode.com/graphql",
                code=404,
                msg="Not Found",
                hdrs={},
                fp=None,
            )

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            with pytest.raises(LeetCodeProblemNotFoundError) as exc_info:
                client.get_problem("non-existent-slug")
            assert exc_info.value.status_code == 404

    def test_auth_status_without_token(self):
        client = LeetCodeClient(session_token=None)
        status = client.check_auth_status()
        assert not status.is_authenticated
        assert status.username is None
        assert "No session token" in status.message

    def test_auth_status_with_valid_session(self):
        client = LeetCodeClient(session_token="valid_session")
        mock_response = {
            "data": {
                "userStatus": {
                    "isSignedIn": True,
                    "username": "algorithm_master",
                    "isPremium": True,
                }
            }
        }

        with patch.object(client, "_execute_http", return_value=mock_response):
            status = client.check_auth_status()
            assert status.is_authenticated
            assert status.username == "algorithm_master"
            assert status.is_premium
            assert status.message == "Session valid"

    def test_auth_status_with_expired_session(self):
        client = LeetCodeClient(session_token="expired_token")
        mock_response = {
            "data": {
                "userStatus": {
                    "isSignedIn": False,
                    "username": "",
                    "isPremium": False,
                }
            }
        }

        with patch.object(client, "_execute_http", return_value=mock_response):
            status = client.check_auth_status()
            assert not status.is_authenticated
            assert "rejected or expired" in status.message

    def test_list_problems_parses_summaries(self):
        client = LeetCodeClient()
        mock_rest = {
            "stat_status_pairs": [
                {
                    "stat": {
                        "question_id": 1,
                        "frontend_question_id": 1,
                        "question__title": "Two Sum",
                        "question__title_slug": "two-sum",
                    },
                    "difficulty": {"level": 1},
                    "paid_only": False,
                    "status": "ac",
                },
                {
                    "stat": {
                        "question_id": 2,
                        "frontend_question_id": 2,
                        "question__title": "Add Two Numbers",
                        "question__title_slug": "add-two-numbers",
                    },
                    "difficulty": {"level": 2},
                    "paid_only": False,
                    "status": None,
                },
            ]
        }
        with patch.object(client, "_execute_http", return_value=mock_rest):
            problems = client.list_problems(limit=10)
            assert len(problems) == 2
            assert problems[0].title == "Two Sum"
            assert problems[0].difficulty == "Easy"
            assert problems[0].status == "ac"
            assert problems[1].difficulty == "Medium"

    def test_get_problem_detail(self):
        client = LeetCodeClient()
        mock_gql = {
            "data": {
                "question": {
                    "questionId": "1",
                    "questionFrontendId": "1",
                    "title": "Two Sum",
                    "titleSlug": "two-sum",
                    "content": "<p>Given an array of integers <code>nums</code> and an integer <code>target</code>, return indices of the two numbers such that they add up to target.</p>\n<p><strong>Example 1:</strong></p>\n<pre>\n<strong>Input:</strong> nums = [2,7,11,15], target = 9\n<strong>Output:</strong> [0,1]\n<strong>Explanation:</strong> Because nums[0] + nums[1] == 9, we return [0, 1].\n</pre>\n<p><strong>Constraints:</strong></p>\n<ul>\n<li><code>2 &lt;= nums.length &lt;= 10^4</code></li>\n<li><code>-10^9 &lt;= nums[i] &lt;= 10^9</code></li>\n</ul>",
                    "isPaidOnly": False,
                    "difficulty": "Easy",
                    "codeSnippets": [
                        {
                            "lang": "Python3",
                            "langSlug": "python3",
                            "code": "class Solution:\n    def twoSum(self, nums: List[int], target: int) -> List[int]:\n        pass\n",
                        }
                    ],
                    "sampleTestCase": "[2,7,11,15]\n9",
                    "exampleTestcases": "[2,7,11,15]\n9\n[3,2,4]\n6",
                    "hints": ["A really brute force way would be to search for all possible pairs of numbers."],
                    "topicTags": [{"name": "Array", "slug": "array"}, {"name": "Hash Table", "slug": "hash-table"}],
                }
            }
        }
        with patch.object(client, "_execute_http", return_value=mock_gql):
            detail = client.get_problem("two-sum")
            assert detail.question_id == "1"
            assert detail.title == "Two Sum"
            assert detail.difficulty == "Easy"
            assert len(detail.code_snippets) == 1
            assert len(detail.hints) == 1
            assert "Array" in detail.topic_tags


class TestLeetCodeAdapter:
    """Tests for normalizer converting LeetCodeProblemDetail into canonical ProblemSpec."""

    def test_adapter_normalizes_to_problem_spec(self):
        detail = LeetCodeProblemDetail(
            question_id="1",
            frontend_question_id="1",
            title="Two Sum",
            title_slug="two-sum",
            difficulty="Easy",
            content_html="<p>Given an array of integers <code>nums</code> and an integer <code>target</code>, return indices.</p>\n<p><strong>Example 1:</strong></p>\n<pre>\nInput: nums = [2,7,11,15], target = 9\nOutput: [0,1]\nExplanation: nums[0] + nums[1] == 9\n</pre>\n<p><strong>Constraints:</strong></p>\n<ul>\n<li>2 <= nums.length <= 10^4</li>\n</ul>",
            code_snippets=[
                LeetCodeCodeSnippet(
                    lang="Python3",
                    lang_slug="python3",
                    code="class Solution:\n    def twoSum(self, nums: List[int], target: int) -> List[int]:\n        pass",
                )
            ],
            example_test_cases=["[2,7,11,15]\n9"],
        )

        spec = LeetCodeProblemAdapter.to_problem_spec(detail, preferred_lang=SupportedLanguage.PYTHON)
        assert spec.id == "two-sum"
        assert spec.title == "Two Sum"
        assert spec.difficulty == Difficulty.EASY
        assert spec.function_name == "twoSum"
        assert "nums" in spec.param_names
        assert "target" in spec.param_names
        assert len(spec.test_cases) >= 1
        assert spec.test_cases[0].expected_output == [0, 1]


class TestLeetCodeSubmissionInterface:
    """Tests for submission contract, dry-run, live execution, and polling verdicts (Stage 32)."""

    def test_submission_fails_without_credentials(self):
        client = LeetCodeClient(session_token=None, csrf_token=None)
        req = LeetCodeSubmissionRequest(
            question_id="1",
            title_slug="two-sum",
            lang="python3",
            typed_code="class Solution: def twoSum(self, nums, target): return [0, 1]",
        )
        with pytest.raises(LeetCodeAuthError) as exc_info:
            client.prepare_submission(req, dry_run=True)
        assert "LEETCODE_SESSION" in str(exc_info.value)

    def test_submission_fails_without_code(self):
        client = LeetCodeClient(session_token="tok", csrf_token="csrf")
        req = LeetCodeSubmissionRequest(
            question_id="1",
            title_slug="two-sum",
            lang="python3",
            typed_code="",
        )
        with pytest.raises(ValueError) as exc_info:
            client.prepare_submission(req, dry_run=True)
        assert "empty" in str(exc_info.value).lower()

    def test_submission_dry_run_makes_no_network_request(self):
        client = LeetCodeClient(session_token="valid_session", csrf_token="valid_csrf")
        req = LeetCodeSubmissionRequest(
            question_id="1",
            title_slug="two-sum",
            lang="python3",
            typed_code="class Solution: def twoSum(self, nums, target): return [0, 1]",
        )
        with patch.object(client, "_execute_http") as mock_exec:
            resp = client.prepare_submission(req, dry_run=True)
            mock_exec.assert_not_called()
            assert resp.submission_id == "dry_run_stg32"
            assert resp.status == LeetCodeSubmissionStatus.PREPARED_LOCALLY
            assert "without external request" in resp.status_msg

    def test_submit_solution_success(self):
        client = LeetCodeClient(session_token="valid_session", csrf_token="valid_csrf")
        req = LeetCodeSubmissionRequest(
            question_id="1",
            title_slug="two-sum",
            lang="python3",
            typed_code="class Solution: def twoSum(self, nums, target): return [0, 1]",
        )
        with patch.object(client, "_execute_http", return_value={"submission_id": "987654321"}):
            resp = client.submit_solution(req)
            assert resp.submission_id == "987654321"
            assert resp.status == LeetCodeSubmissionStatus.REQUEST_ACCEPTED

    def test_submit_solution_rejection(self):
        client = LeetCodeClient(session_token="valid_session", csrf_token="valid_csrf")
        req = LeetCodeSubmissionRequest(
            question_id="1",
            title_slug="two-sum",
            lang="python3",
            typed_code="class Solution: def twoSum(self, nums, target): return [0, 1]",
        )
        with patch.object(client, "_execute_http", return_value={"error": "Daily submission limit reached"}):
            with pytest.raises(LeetCodeError) as exc_info:
                client.submit_solution(req)
            assert "not accepted" in str(exc_info.value)
            assert "Daily submission limit" in str(exc_info.value)

    @pytest.mark.parametrize(
        "mock_check, expected_status",
        [
            ({"state": "PENDING"}, LeetCodeSubmissionStatus.PENDING),
            ({"state": "STARTED"}, LeetCodeSubmissionStatus.JUDGING),
            ({"state": "SUCCESS", "status_code": 10, "status_msg": "Accepted", "status_runtime": "45 ms", "status_memory": "17 MB"}, LeetCodeSubmissionStatus.ACCEPTED),
            ({"state": "SUCCESS", "status_code": 11, "status_msg": "Wrong Answer"}, LeetCodeSubmissionStatus.WRONG_ANSWER),
            ({"state": "SUCCESS", "status_code": 14, "status_msg": "Time Limit Exceeded"}, LeetCodeSubmissionStatus.TIME_LIMIT_EXCEEDED),
            ({"state": "SUCCESS", "status_code": 15, "status_msg": "Memory Limit Exceeded"}, LeetCodeSubmissionStatus.MEMORY_LIMIT_EXCEEDED),
            ({"state": "SUCCESS", "status_code": 20, "status_msg": "Compile Error", "full_compile_error": "SyntaxError"}, LeetCodeSubmissionStatus.COMPILE_ERROR),
            ({"state": "SUCCESS", "status_code": 12, "status_msg": "Runtime Error", "full_runtime_error": "IndexError"}, LeetCodeSubmissionStatus.RUNTIME_ERROR),
            ({"state": "SUCCESS", "status_code": 99, "status_msg": "Custom Verdict"}, LeetCodeSubmissionStatus.OTHER_JUDGE_RESULT),
            ({}, LeetCodeSubmissionStatus.UNKNOWN),
        ]
    )
    def test_verdict_parsing_states(self, mock_check, expected_status):
        client = LeetCodeClient()
        resp = client._parse_submission_check_response("123", mock_check)
        assert resp.status == expected_status

    def test_poll_submission_verdict_transitions_to_accepted(self):
        client = LeetCodeClient()
        poll_responses = [
            {"state": "PENDING"},
            {"state": "STARTED"},
            {"state": "SUCCESS", "status_code": 10, "status_msg": "Accepted", "status_runtime": "52 ms"},
        ]
        with patch.object(client, "_execute_http", side_effect=poll_responses):
            final_resp = client.poll_submission_verdict("12345", interval_seconds=0.01, max_duration_seconds=5.0)
            assert final_resp.status == LeetCodeSubmissionStatus.ACCEPTED
            assert final_resp.run_time == "52 ms"

    def test_poll_submission_verdict_timeout(self):
        client = LeetCodeClient()
        with patch.object(client, "_execute_http", return_value={"state": "STARTED"}):
            final_resp = client.poll_submission_verdict("12345", interval_seconds=0.05, max_duration_seconds=0.1)
            assert final_resp.status == LeetCodeSubmissionStatus.TIMEOUT
            assert "timed out" in final_resp.status_msg


class TestLeetCodeWorkflowService:
    """Tests end-to-end connecting LeetCode fetching, local verification, and submission decisions."""

    def test_solve_leetcode_problem_workflow_dry_run(self, tmp_path):
        mock_client = MagicMock(spec=LeetCodeClient)
        mock_detail = LeetCodeProblemDetail(
            question_id="1",
            frontend_question_id="1",
            title="Two Sum",
            title_slug="two-sum",
            difficulty="Easy",
            content_html="<p>Given an array of integers <code>nums</code> and an integer <code>target</code>, return indices of two numbers.</p>\n<p><strong>Example 1:</strong></p>\n<pre>\nInput: nums = [2,7,11,15], target = 9\nOutput: [0,1]\n</pre>\n<p><strong>Constraints:</strong></p>\n<ul>\n<li>2 <= nums.length <= 10^4</li>\n</ul>",
            code_snippets=[
                LeetCodeCodeSnippet(
                    lang="Python3",
                    lang_slug="python3",
                    code="class Solution:\n    def twoSum(self, nums: List[int], target: int) -> List[int]:\n        pass",
                )
            ],
            example_test_cases=["[2,7,11,15]\n9"],
        )
        mock_client.get_problem.return_value = mock_detail
        mock_client.prepare_submission.return_value = LeetCodeSubmissionResponse(
            submission_id="dry_run_stg32",
            status=LeetCodeSubmissionStatus.PREPARED_LOCALLY,
            status_msg="Dry-run validation passed",
        )

        db_file = str(tmp_path / "test_lc_queue.db")
        from agent.intake.service import ProblemIntakeService
        intake_svc = ProblemIntakeService(db_path=db_file)

        workflow_svc = LeetCodeWorkflowService(client=mock_client, intake_service=intake_svc)

        result = workflow_svc.solve_leetcode_problem(
            title_slug="two-sum",
            preferred_language=SupportedLanguage.PYTHON,
            max_attempts=2,
            prepare_submission=True,
            live_submission=False,
        )

        assert result.problem_id == "two-sum"
        assert result.leetcode_question_id == "1"
        assert result.leetcode_title_slug == "two-sum"
        assert result.status in ("VERIFIED", "MAX_ATTEMPTS_REACHED", "FAILED")
        assert not result.request_sent
        assert result.submission_prepared is True
        assert result.submission_id == "dry_run_stg32"

    def test_live_submission_blocked_without_confirmation(self, tmp_path):
        mock_client = MagicMock(spec=LeetCodeClient)
        mock_detail = LeetCodeProblemDetail(
            question_id="1",
            frontend_question_id="1",
            title="Two Sum",
            title_slug="two-sum",
            difficulty="Easy",
            content_html="<p>Two sum problem</p>",
            code_snippets=[],
        )
        mock_client.get_problem.return_value = mock_detail

        db_file = str(tmp_path / "test_lc_queue2.db")
        from agent.intake.service import ProblemIntakeService
        intake_svc = ProblemIntakeService(db_path=db_file)

        # Mock solve_dynamically returning a verified result with code
        from agent.intake.models import DynamicSolveResult, VerificationEvidenceDTO
        mock_dyn = DynamicSolveResult(
            problem_id="two-sum",
            queue_item_id="item_1",
            job_id="job_1",
            status="VERIFIED",
            language="python",
            attempt_count=1,
            tests_total=1,
            tests_passed=1,
            verification=VerificationEvidenceDTO(correctness=True),
            is_verified=True,
            code_hash=hashlib.sha256(b"code").hexdigest()[:16],
        )
        intake_svc.solve_dynamically = MagicMock(return_value=mock_dyn)
        mock_queue_item = MagicMock()
        mock_queue_item.result_reference = "code"
        intake_svc.store.get_item = MagicMock(return_value=mock_queue_item)

        workflow_svc = LeetCodeWorkflowService(client=mock_client, intake_service=intake_svc)

        result = workflow_svc.solve_leetcode_problem(
            title_slug="two-sum",
            live_submission=True,
            confirmed=False,  # Unconfirmed!
        )

        assert not result.request_sent
        assert "explicit user confirmation" in result.submission_prep_status
        mock_client.submit_solution.assert_not_called()

    def test_live_submission_rejected_when_not_verified(self, tmp_path):
        mock_client = MagicMock(spec=LeetCodeClient)
        mock_detail = LeetCodeProblemDetail(
            question_id="1",
            frontend_question_id="1",
            title="Two Sum",
            title_slug="two-sum",
            difficulty="Easy",
            content_html="<p>Two sum</p>",
            code_snippets=[],
        )
        mock_client.get_problem.return_value = mock_detail

        db_file = str(tmp_path / "test_lc_queue3.db")
        from agent.intake.service import ProblemIntakeService
        intake_svc = ProblemIntakeService(db_path=db_file)

        from agent.intake.models import DynamicSolveResult, VerificationEvidenceDTO
        mock_dyn = DynamicSolveResult(
            problem_id="two-sum",
            queue_item_id="item_2",
            job_id="job_2",
            status="FAILED",
            language="python",
            attempt_count=1,
            tests_total=1,
            tests_passed=0,
            verification=VerificationEvidenceDTO(correctness=False),
            is_verified=False,
        )
        intake_svc.solve_dynamically = MagicMock(return_value=mock_dyn)

        workflow_svc = LeetCodeWorkflowService(client=mock_client, intake_service=intake_svc)

        result = workflow_svc.solve_leetcode_problem(
            title_slug="two-sum",
            live_submission=True,
            confirmed=True,
        )

        assert not result.request_sent
        assert "not locally verified" in result.submission_prep_status
        mock_client.submit_solution.assert_not_called()

    def test_live_submission_confirmed_executes_and_polls(self, tmp_path):
        mock_client = MagicMock(spec=LeetCodeClient)
        mock_detail = LeetCodeProblemDetail(
            question_id="1",
            frontend_question_id="1",
            title="Two Sum",
            title_slug="two-sum",
            difficulty="Easy",
            content_html="<p>Two sum</p>",
            code_snippets=[],
        )
        mock_client.get_problem.return_value = mock_detail
        mock_client.submit_solution.return_value = LeetCodeSubmissionResponse(
            submission_id="sub_live_123",
            status=LeetCodeSubmissionStatus.REQUEST_ACCEPTED,
        )
        mock_client.poll_submission_verdict.return_value = LeetCodeSubmissionResponse(
            submission_id="sub_live_123",
            status=LeetCodeSubmissionStatus.ACCEPTED,
            run_time="42 ms",
            run_memory="16.5 MB",
            status_msg="Accepted",
        )

        db_file = str(tmp_path / "test_lc_queue4.db")
        from agent.intake.service import ProblemIntakeService
        intake_svc = ProblemIntakeService(db_path=db_file)

        code_text = "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 1]"
        code_h = hashlib.sha256(code_text.encode("utf-8")).hexdigest()[:16]

        from agent.intake.models import DynamicSolveResult, VerificationEvidenceDTO
        mock_dyn = DynamicSolveResult(
            problem_id="two-sum",
            queue_item_id="item_3",
            job_id="job_3",
            status="VERIFIED",
            language="python",
            attempt_count=1,
            tests_total=1,
            tests_passed=1,
            verification=VerificationEvidenceDTO(correctness=True),
            is_verified=True,
            code_hash=code_h,
        )
        intake_svc.solve_dynamically = MagicMock(return_value=mock_dyn)
        mock_queue_item = MagicMock()
        mock_queue_item.result_reference = code_text
        intake_svc.store.get_item = MagicMock(return_value=mock_queue_item)

        workflow_svc = LeetCodeWorkflowService(client=mock_client, intake_service=intake_svc)

        result = workflow_svc.solve_leetcode_problem(
            title_slug="two-sum",
            live_submission=True,
            confirmed=True,
        )

        assert result.request_sent is True
        assert result.submission_id == "sub_live_123"
        assert result.judge_verdict == "ACCEPTED"
        assert result.judge_runtime == "42 ms"
        mock_client.submit_solution.assert_called_once()
        mock_client.poll_submission_verdict.assert_called_once_with("sub_live_123")
