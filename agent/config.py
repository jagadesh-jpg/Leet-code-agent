"""
Configuration management for Autonomous DSA Coding Agent.
Loads settings safely from environment variables and provides sanitized diagnostics.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Base workspace directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env if present (does not error if missing)
load_dotenv(dotenv_path=BASE_DIR / ".env")


class Config:
    """Application configuration loaded from environment variables."""

    # Model settings
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    DEFAULT_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # Execution limits
    MAX_EXECUTION_TIMEOUT_SECONDS: float = float(
        os.getenv("MAX_EXECUTION_TIMEOUT_SECONDS", "5.0")
    )
    MAX_EXECUTION_MEMORY_MB: int = int(
        os.getenv("MAX_EXECUTION_MEMORY_MB", "256")
    )
    MAX_ATTEMPTS: int = int(os.getenv("MAX_ATTEMPTS", "5"))

    # Storage paths
    STORAGE_DIR: Path = BASE_DIR / os.getenv("STORAGE_DIR", "storage")
    SOLUTIONS_DIR: Path = BASE_DIR / os.getenv("SOLUTIONS_DIR", "storage/solutions")
    RUNS_DIR: Path = BASE_DIR / os.getenv("RUNS_DIR", "storage/runs")

    # API / n8n Orchestration Settings
    API_HOST: str = os.getenv("AGENT_API_HOST", "127.0.0.1")
    API_PORT: int = int(os.getenv("AGENT_API_PORT", "8000"))
    API_SECRET_KEY: Optional[str] = os.getenv("AGENT_API_SECRET_KEY", "dev-secret-key-change-me")

    # LeetCode Integration Settings
    LEETCODE_SESSION: Optional[str] = os.getenv("LEETCODE_SESSION")
    LEETCODE_CSRFTOKEN: Optional[str] = os.getenv("LEETCODE_CSRFTOKEN")
    LEETCODE_BASE_URL: str = os.getenv("LEETCODE_BASE_URL", "https://leetcode.com")
    LEETCODE_REQUEST_TIMEOUT_SECONDS: float = float(
        os.getenv("LEETCODE_REQUEST_TIMEOUT_SECONDS", "10.0")
    )
    LEETCODE_POLL_INTERVAL_SECONDS: float = float(
        os.getenv("LEETCODE_POLL_INTERVAL_SECONDS", "2.0")
    )
    LEETCODE_POLL_MAX_DURATION_SECONDS: float = float(
        os.getenv("LEETCODE_POLL_MAX_DURATION_SECONDS", "30.0")
    )


    @classmethod
    def is_api_key_configured(cls) -> bool:
        """Checks whether GEMINI_API_KEY is non-empty without exposing it."""
        return bool(cls.GEMINI_API_KEY and cls.GEMINI_API_KEY.strip())

    @classmethod
    def is_leetcode_authenticated(cls) -> bool:
        """Checks whether LEETCODE_SESSION is set without exposing credentials."""
        return bool(cls.LEETCODE_SESSION and cls.LEETCODE_SESSION.strip())

    @classmethod
    def get_api_key(cls) -> str:
        """Returns the configured API key or raises an explicit ValueError."""
        if not cls.is_api_key_configured():
            raise ValueError(
                "GEMINI_API_KEY is not configured. Please set the GEMINI_API_KEY environment variable."
            )
        return cls.GEMINI_API_KEY.strip()
