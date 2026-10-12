"""Data models for LeetCode integration (Stage 31).

Defines:
- LeetCodeProblemSummary: basic problem metadata in lists
- LeetCodeProblemDetail: rich problem details (title, slug, questionId, content, constraints, code snippets, etc.)
- LeetCodeAuthStatus: session validation report
- LeetCodeSubmissionRequest / LeetCodeSubmissionResponse: submission contracts
- LeetCodeException / Error hierarchy
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LeetCodeDifficulty(str, Enum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"
    UNKNOWN = "Unknown"


class LeetCodeProblemSummary(BaseModel):
    """Metadata summary for problems in problem list."""
    frontend_question_id: str
    title: str
    title_slug: str
    difficulty: str
    paid_only: bool = False
    status: Optional[str] = None  # "ac", "notac", None


class LeetCodeCodeSnippet(BaseModel):
    """Starter code snippet for a specific programming language."""
    lang: str
    lang_slug: str
    code: str


class LeetCodeProblemDetail(BaseModel):
    """Comprehensive problem representation retrieved from LeetCode."""
    question_id: str
    frontend_question_id: str
    title: str
    title_slug: str
    difficulty: str
    content_html: str = ""
    content_text: str = ""
    is_paid_only: bool = False
    code_snippets: List[LeetCodeCodeSnippet] = Field(default_factory=list)
    sample_test_case: Optional[str] = None
    example_test_cases: List[str] = Field(default_factory=list)
    hints: List[str] = Field(default_factory=list)
    topic_tags: List[str] = Field(default_factory=list)
    raw_data: Dict[str, Any] = Field(default_factory=dict)


class LeetCodeAuthStatus(BaseModel):
    """Status check for LeetCode session authentication."""
    is_authenticated: bool = False
    username: Optional[str] = None
    is_premium: bool = False
    checked_at: str = ""
    message: str = ""


class LeetCodeSubmissionStatus(str, Enum):
    PREPARED_LOCALLY = "PREPARED_LOCALLY"
    REQUEST_ACCEPTED = "REQUEST_ACCEPTED"
    PENDING = "PENDING"
    JUDGING = "JUDGING"
    ACCEPTED = "ACCEPTED"
    WRONG_ANSWER = "WRONG_ANSWER"
    TIME_LIMIT_EXCEEDED = "TIME_LIMIT_EXCEEDED"
    MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    COMPILE_ERROR = "COMPILE_ERROR"
    OTHER_JUDGE_RESULT = "OTHER_JUDGE_RESULT"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class LeetCodeSubmissionRequest(BaseModel):
    """Defined contract for submitting code to LeetCode."""
    question_id: str
    title_slug: str
    lang: str  # e.g., 'python3', 'cpp', 'java', 'c'
    typed_code: str
    code_hash: Optional[str] = None
    is_locally_verified: bool = False


class LeetCodeSubmissionResponse(BaseModel):
    """Response contract when polling or receiving submission status."""
    submission_id: Optional[str] = None
    status: LeetCodeSubmissionStatus = LeetCodeSubmissionStatus.PREPARED_LOCALLY
    status_code: Optional[int] = None
    status_msg: Optional[str] = None
    state: Optional[str] = None  # e.g., 'PENDING', 'STARTED', 'SUCCESS'
    run_time: Optional[str] = None
    run_memory: Optional[str] = None
    total_correct: Optional[int] = None
    total_testcases: Optional[int] = None
    compile_error_msg: Optional[str] = None
    runtime_error_msg: Optional[str] = None
    raw_result: Dict[str, Any] = Field(default_factory=dict)
