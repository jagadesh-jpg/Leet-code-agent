"""
Sandbox Data Models and Security Policy Specifications.

Defines the contract for contained compilation and execution.
Reuses existing ExecutionStatus and FailureCategory enums from agent.core.models
to prevent conflicting error taxonomies.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from agent.core.models import ExecutionStatus, FailureCategory


class ResourceLimits(BaseModel):
    """Resource constraints for sandboxed process execution."""

    max_memory_mb: int = Field(
        default=256,
        ge=16,
        le=8192,
        description="Memory limit in megabytes.",
    )
    max_cpu_cores: float = Field(
        default=1.0,
        gt=0.0,
        le=16.0,
        description="Maximum CPU cores allocated.",
    )
    max_processes: int = Field(
        default=32,
        ge=1,
        le=512,
        description="Maximum process/thread count (pids-limit) to block fork bombs.",
    )
    max_output_bytes: int = Field(
        default=65536,
        ge=1024,
        le=10485760,
        description="Maximum captured stdout/stderr bytes (default 64KB) to prevent output flooding.",
    )
    timeout_seconds: float = Field(
        default=5.0,
        gt=0.1,
        le=300.0,
        description="Maximum execution wall-clock time before forced termination.",
    )


class SandboxPolicy(BaseModel):
    """
    Security policy defining constraints for sandboxed execution.

    By default, strictly fails closed:
    - Network is disabled.
    - Root filesystem is read-only.
    - User is non-root (1000:1000).
    - Capabilities are dropped.
    """

    allow_network: bool = Field(
        default=False,
        description="Whether network egress/ingress is permitted. Must remain False for untrusted code.",
    )
    read_only_root_fs: bool = Field(
        default=True,
        description="Whether base container/system root filesystem is mounted read-only.",
    )
    workspace_read_write: bool = Field(
        default=True,
        description="Whether the designated temporary workspace directory is mounted read-write.",
    )
    run_as_user: str = Field(
        default="1000:1000",
        description="Execution user ID and group ID (non-root by default).",
    )
    drop_all_capabilities: bool = Field(
        default=True,
        description="Whether all Linux/container capabilities are dropped (e.g. --cap-drop=ALL).",
    )
    environment_variables: Dict[str, str] = Field(
        default_factory=dict,
        description="Explicitly allowlisted environment variables passed to the contained process.",
    )
    resources: ResourceLimits = Field(
        default_factory=ResourceLimits,
        description="Resource quotas and limits applied to execution.",
    )

    @field_validator("run_as_user")
    @classmethod
    def validate_non_root(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("SandboxPolicy run_as_user must be a string.")
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("SandboxPolicy run_as_user cannot be empty.")

        # Disallow root string aliases explicitly
        if cleaned.lower() in ("root", "root:root"):
            raise ValueError(
                "SandboxPolicy rejects root execution: run_as_user cannot be root or UID 0."
            )

        # Require strict numeric UID or UID:GID format
        parts = cleaned.split(":")
        if len(parts) > 2:
            raise ValueError(
                f"SandboxPolicy run_as_user must be in 'UID' or 'UID:GID' format, got '{cleaned}'."
            )

        for idx, part in enumerate(parts):
            part_str = part.strip()
            # Explicit ASCII decimal check: reject Unicode digits or empty parts
            if not part_str or not all("0" <= c <= "9" for c in part_str):
                raise ValueError(
                    f"SandboxPolicy run_as_user components must be non-negative ASCII decimal integers, got '{part_str}' in '{cleaned}'."
                )
            val = int(part_str)
            if idx == 0 and val == 0:
                raise ValueError(
                    "SandboxPolicy rejects root execution: UID cannot be 0."
                )

        return cleaned



class SandboxExecutionResult(BaseModel):
    """
    Deterministic result emitted by a Sandbox implementation.

    Carries exit codes, captured streams, execution duration, and resource
    measurements. Translates directly into ExecutionResult in the runner.
    """

    status: ExecutionStatus = Field(
        description="Execution status mapped from sandbox runtime observation."
    )
    failure_category: Optional[FailureCategory] = Field(
        default=None,
        description="Specific failure category if execution was unsuccessful.",
    )
    exit_code: int = Field(
        default=0,
        description="Process exit code (e.g. 0 on success, -1 on timeout/signal).",
    )
    stdout: str = Field(
        default="",
        description="Captured standard output (truncated to max_output_bytes if exceeded).",
    )
    stderr: str = Field(
        default="",
        description="Captured standard error (truncated to max_output_bytes if exceeded).",
    )
    execution_time_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Wall-clock execution duration in milliseconds.",
    )
    memory_peak_bytes: Optional[int] = Field(
        default=None,
        description="Peak memory consumed during sandboxed execution in bytes.",
    )
    timed_out: bool = Field(
        default=False,
        description="Whether execution terminated due to exceeding timeout_seconds.",
    )
    output_truncated: bool = Field(
        default=False,
        description="Whether captured stdout or stderr was truncated due to output limit.",
    )
    sandbox_backend: str = Field(
        default="none",
        description="Identifier of the sandbox backend that performed execution.",
    )
    error_detail: Optional[str] = Field(
        default=None,
        description="Internal or infrastructure error diagnostic details.",
    )
