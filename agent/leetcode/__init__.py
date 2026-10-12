"""LeetCode Integration Module (Stage 31).

Provides modular client, models, adapter, and service for interacting with
LeetCode permitted GraphQL and REST APIs.
"""

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
    LeetCodeAuthStatus,
    LeetCodeCodeSnippet,
    LeetCodeDifficulty,
    LeetCodeProblemDetail,
    LeetCodeProblemSummary,
    LeetCodeSubmissionRequest,
    LeetCodeSubmissionResponse,
    LeetCodeSubmissionStatus,
)
from agent.leetcode.service import (
    LeetCodeSolveResult,
    LeetCodeWorkflowService,
)

__all__ = [
    "LeetCodeClient",
    "LeetCodeProblemAdapter",
    "LeetCodeWorkflowService",
    "LeetCodeSolveResult",
    "LeetCodeAuthStatus",
    "LeetCodeCodeSnippet",
    "LeetCodeDifficulty",
    "LeetCodeProblemDetail",
    "LeetCodeProblemSummary",
    "LeetCodeSubmissionRequest",
    "LeetCodeSubmissionResponse",
    "LeetCodeSubmissionStatus",
    "LeetCodeError",
    "LeetCodeAuthError",
    "LeetCodeRateLimitError",
    "LeetCodeNetworkError",
    "LeetCodeProblemNotFoundError",
    "LeetCodeUnsupportedOperationError",
]
