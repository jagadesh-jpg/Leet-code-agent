"""
Abstract Base Interface for Sandboxed Execution.

Defines the contract for language-agnostic, contained compilation and execution.
All implementations must be capable of failing closed if security properties
cannot be guaranteed by the underlying host.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from agent.execution.sandbox.models import (
    SandboxExecutionResult,
    SandboxPolicy,
)


class BaseSandbox(ABC):
    """
    Abstract containment boundary for untrusted compilers and solution binaries.

    Subclasses implement platform-specific isolation (e.g. OCI container via Docker,
    Windows Job Objects, Linux seccomp/namespaces).
    """

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Returns the unique identifier of the sandbox implementation."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Probes the host environment to verify whether this sandbox backend is available
        and capable of enforcing its security constraints.
        Returns False if required tools, daemon, or kernel capabilities are missing.
        """
        pass

    @abstractmethod
    def execute(
        self,
        command: List[str],
        workspace_dir: Path,
        policy: Optional[SandboxPolicy] = None,
    ) -> SandboxExecutionResult:
        """
        Executes a command within the sandboxed environment.

        Args:
            command: Command and argument vector to execute (e.g. ["python", "harness.py"]).
            workspace_dir: Strictly bounded host directory to mount/bind for workspace I/O.
            policy: Security constraints and resource quotas. Uses default SandboxPolicy if omitted.

        Returns:
            SandboxExecutionResult with exit code, captured outputs, duration, and status.

        Note:
            If the sandbox cannot enforce the requested policy (e.g. network isolation or
            resource bounds are unsupported), it must fail closed and return a result
            with ExecutionStatus.INFRASTRUCTURE_ERROR and FailureCategory.ENVIRONMENT_ERROR.
        """
        pass
