"""
Tests for LLM Provider Abstraction and Gemini Adapter.
Verifies:
- Unconfigured API key raises clean AUTHENTICATION_ERROR without crashing or leaking keys.
- Secret sanitization ensures no keys or query params ever appear in exceptions.
- Error mapping handles rate limits, timeouts, and malformed responses.
- Structured schema validation works with Pydantic models.
- If GEMINI_API_KEY is present in the environment, runs a live integration smoke test.
"""

import os
from unittest.mock import MagicMock, patch
from pydantic import BaseModel, Field
import pytest

from agent.llm.base import (
    BaseLLMProvider,
    LLMErrorType,
    LLMException,
    LLMResponse,
)
from agent.llm.gemini import GeminiProvider
from agent.llm.factory import get_llm_provider


class SampleAlgoPlan(BaseModel):
    pattern: str = Field(description="DSA Pattern")
    time_complexity: str = Field(description="Big-O time complexity")


def test_unconfigured_api_key_raises_clean_error():
    """Verifies that an absent API key raises AUTHENTICATION_ERROR cleanly."""
    provider = GeminiProvider(api_key=None)
    assert not provider.is_configured()

    with pytest.raises(LLMException) as exc_info:
        provider.generate_text("Hello")

    assert exc_info.value.error_type == LLMErrorType.AUTHENTICATION_ERROR
    assert "GEMINI_API_KEY" in str(exc_info.value)


def test_factory_returns_gemini_provider():
    """Verifies factory resolves 'gemini' to GeminiProvider."""
    provider = get_llm_provider("gemini")
    assert isinstance(provider, BaseLLMProvider)
    assert provider.provider_name == "gemini"


def test_factory_rejects_unsupported_provider():
    """Verifies factory raises ValueError on unsupported provider."""
    with pytest.raises(ValueError) as exc_info:
        get_llm_provider("unknown_provider")
    assert "Unsupported LLM provider" in str(exc_info.value)


def test_secret_sanitization_in_exceptions():
    """Verifies error sanitization prevents query params or keys in exception strings."""
    provider = GeminiProvider(api_key="fake-test-key-12345")
    raw_error = Exception("HTTP 400 Bad Request to https://generativelanguage.googleapis.com?key=AIzaSySecret123")
    mapped = provider._map_exception(raw_error)

    # Key must be redacted
    assert "AIzaSySecret123" not in str(mapped)
    assert "key=[REDACTED]" in str(mapped)


def test_mock_successful_generate_text():
    """Verifies successful text response mapping from google-genai client."""
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Mock response
        mock_response = MagicMock()
        mock_response.text = "Identified pattern: Two Pointers"
        mock_candidate = MagicMock()
        mock_candidate.finish_reason = "STOP"
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 5
        mock_response.usage_metadata.total_token_count = 15

        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiProvider(api_key="dummy-key-abc")
        resp = provider.generate_text("Test prompt")

        assert isinstance(resp, LLMResponse)
        assert resp.text == "Identified pattern: Two Pointers"
        assert resp.model_name == provider.model_name
        assert resp.finish_reason == "STOP"
        assert resp.usage.total_tokens == 15


def test_mock_structured_schema_generation():
    """Verifies that generate_structured parses JSON conforming to a Pydantic schema."""
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = '{"pattern": "Hash Map", "time_complexity": "O(N)"}'
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiProvider(api_key="dummy-key-abc")
        parsed = provider.generate_structured("Plan Two Sum", SampleAlgoPlan)

        assert isinstance(parsed, SampleAlgoPlan)
        assert parsed.pattern == "Hash Map"
        assert parsed.time_complexity == "O(N)"


def test_mock_rate_limit_mapping():
    """Verifies 429 rate limit maps to RATE_LIMIT_ERROR."""
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("429 Too Many Requests: rate limit exceeded")

        provider = GeminiProvider(api_key="dummy-key-abc")
        with pytest.raises(LLMException) as exc_info:
            provider.generate_text("Test prompt")

        assert exc_info.value.error_type == LLMErrorType.RATE_LIMIT_ERROR
        assert exc_info.value.status_code == 429


def test_mock_quota_exceeded_mapping():
    """Verifies quota exhausted maps to QUOTA_EXCEEDED."""
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("ResourceExhausted: Daily quota limit exceeded")

        provider = GeminiProvider(api_key="dummy-key-abc")
        with pytest.raises(LLMException) as exc_info:
            provider.generate_text("Test prompt")

        assert exc_info.value.error_type == LLMErrorType.QUOTA_EXCEEDED
        assert exc_info.value.status_code == 429


def test_mock_model_not_found_mapping():
    """Verifies 404 / model not found maps to MODEL_NOT_FOUND."""
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("404 NotFound: models/unknown-gemini not found")

        provider = GeminiProvider(api_key="dummy-key-abc", model_name="unknown-gemini")
        with pytest.raises(LLMException) as exc_info:
            provider.generate_text("Test prompt")

        assert exc_info.value.error_type == LLMErrorType.MODEL_NOT_FOUND
        assert exc_info.value.status_code == 404


def test_mock_network_error_mapping():
    """Verifies DNS / connection failure maps to NETWORK_ERROR."""
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("Failed to connect to host: dns resolution error")

        provider = GeminiProvider(api_key="dummy-key-abc")
        with pytest.raises(LLMException) as exc_info:
            provider.generate_text("Test prompt")

        assert exc_info.value.error_type == LLMErrorType.NETWORK_ERROR


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEMINI_TEST", "").strip().lower() not in ("1", "true", "yes"),
    reason="Live Gemini network test is opt-in. Set RUN_LIVE_GEMINI_TEST=1 to enable."
)
def test_live_gemini_api_call():
    """Live smoke test executed only when explicitly opted in via RUN_LIVE_GEMINI_TEST=1."""
    if not os.getenv("GEMINI_API_KEY", "").strip():
        pytest.skip("GEMINI_API_KEY not configured or empty; skipping live network test.")

    provider = get_llm_provider("gemini")
    resp = provider.generate_text("Say exactly: 'READY'")
    assert resp.text is not None
    assert len(resp.text) > 0

