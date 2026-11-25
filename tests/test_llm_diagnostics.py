import json
import pytest
from llm import parse_gemini_error, sanitize_error_text, LLMError


class MockAPIException(Exception):
    def __init__(self, message, status_code=None, body=None, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.response = response


class MockResponseObj:
    def __init__(self, text=None, json_data=None, headers=None):
        self._text = text
        self._json_data = json_data
        self.headers = headers or {}

    @property
    def text(self):
        return self._text

    def json(self):
        if self._json_data is not None:
            return self._json_data
        if self._text is not None:
            return json.loads(self._text)
        raise ValueError("No JSON available")


def test_sanitize_error_text():
    raw = "Failed request with key AIza_FAKE_TEST_KEY_FOR_UNIT_TESTING_ONLY and AQ.FAKE_TEST_TOKEN_FOR_UNIT_TESTING"
    clean = sanitize_error_text(raw)
    assert "[REDACTED_API_KEY]" in clean
    assert "AIza_FAKE" not in clean
    assert "AQ.FAKE" not in clean

    raw_bearer = "Authorization: Bearer my-secret-token-xyz"
    clean_bearer = sanitize_error_text(raw_bearer)
    assert "Bearer [REDACTED]" in clean_bearer

    raw_sk = "Call failed with sk-FAKE_TEST_KEY_FOR_UNIT_TESTING_1234567890"
    assert "[REDACTED_API_KEY]" in sanitize_error_text(raw_sk)
    assert "sk-FAKE" not in sanitize_error_text(raw_sk)

    raw_gh = "Token: ghp_FAKE_GITHUB_PERSONAL_ACCESS_TOKEN_TEST"
    assert "[REDACTED_API_KEY]" in sanitize_error_text(raw_gh)

    raw_param = "https://api.example.com/endpoint?password=mySecretPassword123&api_key=secretKeyVal"
    clean_param = sanitize_error_text(raw_param)
    assert "password=[REDACTED]" in clean_param
    assert "api_key=[REDACTED]" in clean_param


def test_parse_gemini_dict_body_rpm():
    body = {
        "error": {
            "code": 429,
            "message": "Resource has been exhausted (e.g. check quota).",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "subject": "GenerateRequestsPerMinutePerProject",
                            "description": "Quota exceeded for quota metric 'GenerateRequestsPerMinutePerProject' and limit '15'",
                        }
                    ],
                }
            ],
        }
    }
    exc = MockAPIException("Error code: 429", status_code=429, body=body)
    parsed = parse_gemini_error(exc)
    assert parsed["error_type"] == "transient_rate_limit"
    assert parsed["quota_type"] == "rpm_limit"
    assert parsed["details"]["quota_metric"] == "GenerateRequestsPerMinutePerProject"
    assert "GenerateRequestsPerMinutePerProject" in parsed["diagnostic_summary"]


def test_parse_gemini_json_string_body():
    body_dict = {
        "error": {
            "code": 429,
            "message": "Rate limit exceeded for tokens per minute.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "subject": "TokensPerMinutePerProject",
                            "description": "Tokens exceeded",
                        }
                    ],
                }
            ],
        }
    }
    # Pass as JSON string directly in exc.body
    exc = MockAPIException("Rate limit 429", status_code=429, body=json.dumps(body_dict))
    parsed = parse_gemini_error(exc)
    assert parsed["error_type"] == "transient_rate_limit"
    assert parsed["quota_type"] == "tpm_limit"
    assert parsed["details"]["google_status"] == "RESOURCE_EXHAUSTED"
    assert parsed["details"]["quota_metric"] == "TokensPerMinutePerProject"


def test_parse_gemini_response_text_fallback():
    body_dict = {
        "error": {
            "code": 429,
            "message": "Resource exhausted",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "21.5s",
                }
            ],
        }
    }
    # exc.body is None, but response.text has the JSON string
    resp = MockResponseObj(text=json.dumps(body_dict))
    exc = MockAPIException("Error code: 429", status_code=429, body=None, response=resp)
    parsed = parse_gemini_error(exc)
    assert parsed["retry_after"] == 21.5
    assert parsed["details"]["retry_delay"] == "21.5s"
    assert parsed["details"]["google_status"] == "RESOURCE_EXHAUSTED"


def test_parse_gemini_regex_metric_extraction():
    # Message mentions metric in text without RPC QuotaFailure
    raw_error = "Error code: 429 - Quota exceeded for quota metric 'GenerateRequestsPerMinutePerProject' and limit '15'"
    exc = MockAPIException(raw_error, status_code=429, body=None)
    parsed = parse_gemini_error(exc)
    assert parsed["error_type"] == "transient_rate_limit"
    assert parsed["quota_type"] == "rpm_limit"
    assert parsed["details"]["quota_metric"] == "GenerateRequestsPerMinutePerProject"


def test_parse_gemini_daily_quota_exhaustion():
    body = {
        "error": {
            "code": 429,
            "message": "Quota exceeded: requests per day limit reached.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "subject": "GenerateRequestsPerDayPerProject",
                            "description": "Daily request cap exhausted for free tier.",
                        }
                    ],
                }
            ],
        }
    }
    exc = MockAPIException("Daily quota exceeded", status_code=429, body=body)
    parsed = parse_gemini_error(exc)
    assert parsed["error_type"] == "daily_quota_exhausted"
    assert parsed["quota_type"] == "daily_quota_exhausted"
    assert "daily_quota_exhausted" in parsed["diagnostic_summary"]


def test_parse_gemini_missing_or_invalid_json():
    # Invalid JSON string in body
    exc_invalid = MockAPIException("Error code: 429 rate limit", status_code=429, body="<html>429 Too Many Requests</html>")
    parsed_invalid = parse_gemini_error(exc_invalid)
    assert parsed_invalid["error_type"] == "transient_rate_limit"
    assert parsed_invalid["details"]["google_status"] is None

    # None body
    exc_none = MockAPIException("Unknown server error", status_code=500, body=None)
    parsed_none = parse_gemini_error(exc_none)
    assert parsed_none["error_type"] == "general"


def test_parse_gemini_embedded_payload_in_exception_string():
    """Verify that when exc.body is None and response is None, but str(exc) contains
    an embedded dict string (common in OpenAI SDK), parse_gemini_error correctly extracts it."""
    # Embedded python dict literal in str(exc)
    raw_str = (
        "Error code: 429 - {'error': {'code': 429, 'message': 'Resource has been exhausted (e.g. check quota).', "
        "'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', "
        "'violations': [{'subject': 'GenerateRequestsPerMinutePerProject', 'description': 'Limit exceeded'}]}, "
        "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '30.0s'}]}}"
    )
    exc = MockAPIException(raw_str, status_code=429, body=None, response=None)
    parsed = parse_gemini_error(exc)
    assert parsed["error_type"] == "transient_rate_limit"
    assert parsed["quota_type"] == "rpm_limit"
    assert parsed["details"]["google_status"] == "RESOURCE_EXHAUSTED"
    assert parsed["details"]["google_message"] == "Resource has been exhausted (e.g. check quota)."
    assert parsed["details"]["quota_metric"] == "GenerateRequestsPerMinutePerProject"
    assert parsed["retry_after"] == 30.0
    assert len(parsed["details"]["violations"]) == 1
    assert parsed["details"]["violations"][0]["subject"] == "GenerateRequestsPerMinutePerProject"


def test_parse_gemini_embedded_json_string_with_sensitive_token():
    """Verify embedded JSON in str(exc) containing sensitive API keys is sanitized upon extraction."""
    raw_str = (
        'Error code: 429 - {"error": {"code": 429, "message": "Failed key AIza_FAKE_TEST_KEY_FOR_UNIT_TESTING_ONLY quota", '
        '"status": "RESOURCE_EXHAUSTED"}}'
    )
    exc = MockAPIException(raw_str, status_code=429, body=None, response=None)
    parsed = parse_gemini_error(exc)
    assert parsed["details"]["google_status"] == "RESOURCE_EXHAUSTED"
    assert "[REDACTED_API_KEY]" in parsed["details"]["google_message"]
    assert "AIza_FAKE" not in parsed["details"]["google_message"]


def test_llm_client_backup_fallback_on_rate_limit(monkeypatch):
    """Verify that LLMClient falls back to backup_client when primary throws 429."""
    from llm import LLMClient

    class FakePrimaryChat:
        def create(self, **kwargs):
            raise MockAPIException("Rate limit 429", status_code=429)

    class FakeBackupChat:
        def create(self, **kwargs):
            class FakeChoice:
                message = type("Msg", (), {"content": "def solve(): return 42"})()
            return type("Resp", (), {"choices": [FakeChoice()]})()

    client = LLMClient(
        base_url="https://fake.url",
        api_key="fake-key",
        model="fake-model",
        delay_seconds=0,
        backup_base_url="https://backup.fake.url",
        backup_api_key="fake-backup-key",
        backup_model="gpt-5-mini",
    )
    # Monkeypatch inner client objects with fake callers
    client.client = type("FakeClient", (), {"chat": type("Chat", (), {"completions": FakePrimaryChat()})()})()
    client.backup_client = type("FakeBackupClient", (), {"chat": type("Chat", (), {"completions": FakeBackupChat()})()})()

    res = client.ask("sys", "user")
    assert res == "def solve(): return 42"
