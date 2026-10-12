"""Custom exceptions for LeetCode operations (Stage 31).

Hierarchy:
  LeetCodeError
    ├── LeetCodeAuthError
    ├── LeetCodeRateLimitError
    ├── LeetCodeNetworkError
    ├── LeetCodeProblemNotFoundError
    └── LeetCodeUnsupportedOperationError
"""


class LeetCodeError(Exception):
    """Base exception for LeetCode operations."""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class LeetCodeAuthError(LeetCodeError):
    """Raised when authentication credentials (session / csrf) are missing or invalid."""
    pass


class LeetCodeRateLimitError(LeetCodeError):
    """Raised when LeetCode rate limits or throttles requests (HTTP 429)."""
    pass


class LeetCodeNetworkError(LeetCodeError):
    """Raised when connection drops, times out, or fails to connect."""
    pass


class LeetCodeProblemNotFoundError(LeetCodeError):
    """Raised when a requested problem or slug does not exist on LeetCode."""
    pass


class LeetCodeUnsupportedOperationError(LeetCodeError):
    """Raised when an operation is prohibited or unsupported by policy/API constraints."""
    pass
