"""
Sandbox Execution Package.

Provides contracts, resource quotas, and security policies for contained
compilation and execution of untrusted code.
"""

from agent.execution.sandbox.base import BaseSandbox
from agent.execution.sandbox.docker import DEFAULT_SANDBOX_IMAGE, DockerSandbox
from agent.execution.sandbox.models import (
    ResourceLimits,
    SandboxExecutionResult,
    SandboxPolicy,
)

__all__ = [
    "BaseSandbox",
    "DEFAULT_SANDBOX_IMAGE",
    "DockerSandbox",
    "ResourceLimits",
    "SandboxExecutionResult",
    "SandboxPolicy",
]
