import pytest
from llm import LLMError, parse_gemini_error
import autonomous
import store


class FakeRateLimitException(Exception):
    def __init__(self, message="Error code: 429 - rate limit exceeded", status_code=429):
        super().__init__(message)
        self.status_code = status_code


class FakeDailyQuotaException(Exception):
    def __init__(self, message="Daily quota limit exceeded: 0 requests remaining per day"):
        super().__init__(message)
        self.status_code = 429


def test_parse_gemini_error_categories():
    # 1. Transient RPM/TPM
    transient_exc = FakeRateLimitException("Error code: 429 - 15 RPM limit reached. Please retry after 4.2s")
    res = parse_gemini_error(transient_exc)
    assert res["error_type"] == "transient_rate_limit"
    assert res["retry_after"] == 4.2

    # 2. Daily Quota / Billing
    daily_exc = FakeDailyQuotaException()
    res_daily = parse_gemini_error(daily_exc)
    assert res_daily["error_type"] == "daily_quota_exhausted"


class QuotaFailingLLM:
    def ask(self, system_prompt: str, user_prompt: str) -> str:
        raise LLMError("Daily quota exhausted for Gemini", error_type="daily_quota_exhausted")


def test_autonomous_queue_pauses_on_quota_exhausted(tmp_path):
    test_db = tmp_path / "test_quota.db"
    store.init(db_path=test_db)

    # Save a problem
    store.save_custom_problem(
        problem_id="test-quota-prob",
        url="https://leetcode.com/problems/test-quota-prob/",
        title="Test Quota Prob",
        difficulty="easy",
        description="description",
        function_name="test_fn",
        signature="def test_fn():",
        tests=[{"input": [], "expected": 1}],
        db_path=test_db,
    )

    llm = QuotaFailingLLM()

    # Run queue with QuotaFailingLLM
    run_res = autonomous.run_autonomous_queue(
        max_problems=1,
        llm_client=llm,
        db_path=test_db,
    )

    # Must be paused safely, NOT marked locally_verified
    assert run_res["status"] == "paused"
    assert store.is_solved("test-quota-prob", db_path=test_db) is False

    # Check that item remains in queued state in the checkpoint so it can be resumed later
    items = store.get_autonomous_queue_items(run_res["run_id"], db_path=test_db)
    assert len(items) == 1
    assert items[0]["status"] == "queued"
    assert "Quota" in items[0]["error"]
