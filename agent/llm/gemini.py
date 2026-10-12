"""
Google Gemini Model Provider Implementation.
Uses the official google-genai SDK, respects GEMINI_API_KEY, sanitizes secrets,
and translates vendor-specific errors into standard LLMExceptions.
"""

import json
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel

from agent.config import Config
from agent.llm.base import (
    BaseLLMProvider,
    LLMErrorType,
    LLMException,
    LLMResponse,
    LLMUsage,
)

T = TypeVar("T", bound=BaseModel)


class GeminiProvider(BaseLLMProvider):
    """
    Official Google GenAI SDK integration for Gemini models.
    Safely reads credentials from environment, supports text & structured schemas.
    """

    _DEFAULT_KEY = object()
    def __init__(
        self,
        api_key: Any = _DEFAULT_KEY,
        model_name: Optional[str] = None,
    ):
        self._model_name = model_name or Config.DEFAULT_MODEL
        # If api_key parameter is omitted, fallback to Config.GEMINI_API_KEY
        resolved_key = Config.GEMINI_API_KEY if api_key is self._DEFAULT_KEY else api_key

        if not resolved_key or not resolved_key.strip():
            self._client = None
            self._has_key = False
        else:
            self._has_key = True
            try:
                from google import genai
                # Pass api_key explicitly or rely on client resolution
                self._client = genai.Client(api_key=resolved_key.strip())
            except Exception as e:
                raise self._map_exception(e)

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model_name

    def is_configured(self) -> bool:
        """Returns True if an API key was provided and the client initialized."""
        return self._has_key and self._client is not None

    def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Generates text from Gemini using official google-genai client."""
        if not self.is_configured():
            raise LLMException(
                "Gemini API key is not configured. Set the GEMINI_API_KEY environment variable.",
                error_type=LLMErrorType.AUTHENTICATION_ERROR,
            )

        from google.genai import types

        config_args: Dict[str, Any] = {
            "temperature": temperature,
        }
        if system_instruction:
            config_args["system_instruction"] = system_instruction
        if max_output_tokens:
            config_args["max_output_tokens"] = max_output_tokens

        config = types.GenerateContentConfig(**config_args)

        last_exc = None
        for attempt in range(4):
            try:
                response = self._client.models.generate_content(
                    model=self._model_name,
                    contents=prompt,
                    config=config,
                )
                break
            except Exception as e:
                mapped = self._map_exception(e)
                last_exc = mapped
                if mapped.error_type == LLMErrorType.PROVIDER_UNAVAILABLE and attempt < 3:
                    import time
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise mapped
        else:
            if last_exc:
                raise last_exc

        if not response:
            raise LLMException(
                "Gemini returned an empty response object.",
                error_type=LLMErrorType.MALFORMED_RESPONSE_ERROR,
            )

        text_content = response.text or ""
        finish_reason = None
        usage = None

        if hasattr(response, "candidates") and response.candidates:
            first_candidate = response.candidates[0]
            if hasattr(first_candidate, "finish_reason"):
                finish_reason = str(first_candidate.finish_reason)

        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            usage = LLMUsage(
                prompt_tokens=getattr(meta, "prompt_token_count", None),
                completion_tokens=getattr(meta, "candidates_token_count", None),
                thoughts_tokens=getattr(meta, "thoughts_token_count", None),
                total_tokens=getattr(meta, "total_token_count", None),
            )

        return LLMResponse(
            text=text_content,
            model_name=self._model_name,
            finish_reason=finish_reason,
            usage=usage,
        )

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
    ) -> T:
        """Generates structured output validated against a Pydantic schema."""
        if not self.is_configured():
            raise LLMException(
                "Gemini API key is not configured. Set the GEMINI_API_KEY environment variable.",
                error_type=LLMErrorType.AUTHENTICATION_ERROR,
            )

        from google.genai import types

        config_args: Dict[str, Any] = {
            "temperature": temperature,
            "response_mime_type": "application/json",
            "response_schema": response_schema,
        }
        if system_instruction:
            config_args["system_instruction"] = system_instruction

        config = types.GenerateContentConfig(**config_args)

        last_exc = None
        for attempt in range(4):
            try:
                response = self._client.models.generate_content(
                    model=self._model_name,
                    contents=prompt,
                    config=config,
                )
                break
            except Exception as e:
                mapped = self._map_exception(e)
                last_exc = mapped
                if mapped.error_type == LLMErrorType.PROVIDER_UNAVAILABLE and attempt < 3:
                    import time
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise mapped
        else:
            if last_exc:
                raise last_exc

        if not response or not response.text:
            raise LLMException(
                "Model returned empty or non-text response for structured generation.",
                error_type=LLMErrorType.MALFORMED_RESPONSE_ERROR,
            )

        try:
            parsed_data = json.loads(response.text)
            return response_schema.model_validate(parsed_data)
        except Exception as e:
            raise LLMException(
                f"Failed to validate model response against schema {response_schema.__name__}: {str(e)}",
                error_type=LLMErrorType.MALFORMED_RESPONSE_ERROR,
            )

    def _map_exception(self, exc: Exception) -> LLMException:
        """
        Maps underlying google-genai / HTTP exceptions to clean, sanitized LLMExceptions.
        Ensures raw keys or sensitive URLs are never exposed.
        """
        exc_str = str(exc)
        # Check known error classes / patterns
        lower_msg = exc_str.lower()

        if "api_key" in lower_msg or "unauthenticated" in lower_msg or "401" in lower_msg or "403" in lower_msg:
            return LLMException(
                "Authentication failure communicating with Gemini API. Check your GEMINI_API_KEY.",
                error_type=LLMErrorType.AUTHENTICATION_ERROR,
                status_code=401,
            )

        if "not found" in lower_msg or "404" in lower_msg or "model not found" in lower_msg:
            return LLMException(
                f"Requested model '{self._model_name}' not found: {self._sanitize(exc_str)}",
                error_type=LLMErrorType.MODEL_NOT_FOUND,
                status_code=404,
            )

        if "rate limit" in lower_msg or "rate_limit" in lower_msg or "too many requests" in lower_msg:
            return LLMException(
                "Gemini rate limit exceeded.",
                error_type=LLMErrorType.RATE_LIMIT_ERROR,
                status_code=429,
            )

        if "resource_exhausted" in lower_msg or "quota" in lower_msg:
            return LLMException(
                "Gemini quota exceeded.",
                error_type=LLMErrorType.QUOTA_EXCEEDED,
                status_code=429,
            )

        if "429" in lower_msg:
            return LLMException(
                "Gemini rate limit exceeded (429).",
                error_type=LLMErrorType.RATE_LIMIT_ERROR,
                status_code=429,
            )

        if "deadline_exceeded" in lower_msg or "timed out" in lower_msg or "timeout" in lower_msg:
            return LLMException(
                "Request to Gemini API timed out.",
                error_type=LLMErrorType.TIMEOUT_ERROR,
                status_code=504,
            )

        if "connection" in lower_msg or "network" in lower_msg or "dns" in lower_msg or "failed to connect" in lower_msg:
            return LLMException(
                f"Network failure communicating with Gemini API: {self._sanitize(exc_str)}",
                error_type=LLMErrorType.NETWORK_ERROR,
            )

        if "invalid_argument" in lower_msg or "bad request" in lower_msg or "400" in lower_msg:
            return LLMException(
                f"Invalid request sent to Gemini: {self._sanitize(exc_str)}",
                error_type=LLMErrorType.INVALID_REQUEST_ERROR,
                status_code=400,
            )

        if "unavailable" in lower_msg or "503" in lower_msg:
            return LLMException(
                "Gemini API service temporarily unavailable.",
                error_type=LLMErrorType.PROVIDER_UNAVAILABLE,
                status_code=503,
            )

        return LLMException(
            f"Gemini API error: {self._sanitize(exc_str)}",
            error_type=LLMErrorType.UNKNOWN_ERROR,
        )

    def _sanitize(self, msg: str) -> str:
        """Strips potential API keys or query params from error messages."""
        # Generic redaction of potential keys
        import re
        return re.sub(r'key=[A-Za-z0-9_\-]+', 'key=[REDACTED]', msg)
