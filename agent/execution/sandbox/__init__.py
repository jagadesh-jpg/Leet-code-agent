"""
Sandbox Execution Package.

Provides contracts, resource quotas, and security policies for contained
compilation and execution of untrusted code.
"""

from agent.execution.sandbox.base import BaseSandbox
from agent.execution.sandbox.models import (
    ResourceLimits,
    SandboxExecutionResult,
    SandboxPolicy,
)

__all__ = [
    "BaseSandbox",
    "ResourceLimits",
    "SandboxExecutionResult",
    "SandboxPolicy",
]
