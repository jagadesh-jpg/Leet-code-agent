"""
Model Provider Abstraction Layer.
Defines provider-independent interfaces, standard exceptions, and structured response types.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Type, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class LLMErrorType(str, Enum):
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    RATE_LIMIT_ERROR = "RATE_LIMIT_ERROR"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    INVALID_REQUEST_ERROR = "INVALID_REQUEST_ERROR"
    MALFORMED_RESPONSE_ERROR = "MALFORMED_RESPONSE_ERROR"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class LLMException(Exception):
    """Base exception for all model provider errors. Sanitizes any secret exposure."""

    def __init__(self, message: str, error_type: LLMErrorType, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.status_code = status_code

    def __str__(self) -> str:
        return f"[{self.error_type.value}] {self.message}"


class LLMUsage(BaseModel):
    """Token usage metadata."""
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    thoughts_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class LLMResponse(BaseModel):
    """Provider-independent text generation response."""
    text: str = Field(description="Generated textual content")
    model_name: str = Field(description="Name of the model that generated this response")
    finish_reason: Optional[str] = Field(default=None, description="Stop/finish reason")
    usage: Optional[LLMUsage] = Field(default=None, description="Token consumption metrics")
    raw_metadata: Dict[str, Any] = Field(default_factory=dict, description="Safe provider-specific metadata")


class BaseLLMProvider(ABC):
    """
    Abstract interface for all model providers (Gemini, OpenAI, Anthropic, local).
    Decouples the agent reasoning core completely from any vendor API.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g. 'gemini', 'openai')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Active model identifier (e.g. 'gemini-2.5-flash')."""
        pass

    def is_configured(self) -> bool:
        """Returns True if the provider has valid credentials and is ready for inference."""
        return False

    @abstractmethod
    def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """
        Generates standard text completion.
        Raises LLMException on failure.
        """
        pass

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
    ) -> T:
        """
        Generates deterministic structured data strictly adhering to a Pydantic schema.
        Raises LLMException on failure.
        """
        pass
