"""
LLM Provider Factory.
Provides a single entry point to instantiate configured model providers without tight coupling.
"""

from typing import Optional
from agent.config import Config
from agent.llm.base import BaseLLMProvider
from agent.llm.gemini import GeminiProvider


def get_llm_provider(
    provider_name: str = "gemini",
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
) -> BaseLLMProvider:
    """
    Factory function to obtain a BaseLLMProvider instance.
    Enables swapping Gemini for OpenAI, Anthropic, or local runners without modifying callers.
    """
    normalized = provider_name.strip().lower()
    if normalized == "gemini":
        return GeminiProvider(
            api_key=api_key or Config.GEMINI_API_KEY,
            model_name=model_name or Config.DEFAULT_MODEL,
        )
    raise ValueError(f"Unsupported LLM provider: '{provider_name}'. Supported: ['gemini']")
