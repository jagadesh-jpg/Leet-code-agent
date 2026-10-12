"""
Tests for Stage 1 Sandbox Contract & Models.

Verifies:
1. ResourceLimits defaults and validation bounds (memory, CPU, timeout, output).
2. SandboxPolicy security defaults (network disabled, non-root, read-only root, caps dropped).
3. SandboxPolicy rejection of root execution.
4. SandboxExecutionResult field assignments and schema consistency with ExecutionStatus / FailureCategory.
5. JSON serialization and deserialization roundtrips.
6. Abstract BaseSandbox contract compliance.
"""

from pathlib import Path
from typing import List, Optional
import pytest
from pydantic import ValidationError

from agent.core.models import ExecutionStatus, FailureCategory
from agent.execution.sandbox import (
    BaseSandbox,
    ResourceLimits,
    SandboxExecutionResult,
    SandboxPolicy,
)


class DummySandbox(BaseSandbox):
    """Minimal implementation to verify contract instantiation and method signatures."""

    def __init__(self, available: bool = True):
        self._available = available

    @property
    def backend_name(self) -> str:
        return "dummy"

    def is_available(self) -> bool:
        return self._available

    def execute(
        self,
        command: List[str],
        workspace_dir: Path,
        policy: Optional[SandboxPolicy] = None,
    ) -> SandboxExecutionResult:
        eff_policy = policy or SandboxPolicy()
        if not self.is_available():
            return SandboxExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                exit_code=-1,
                error_detail="Dummy sandbox is marked unavailable.",
                sandbox_backend=self.backend_name,
            )
        return SandboxExecutionResult(
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout="dummy ok",
            sandbox_backend=self.backend_name,
        )


def test_resource_limits_defaults():
    """Verifies standard resource defaults match project configuration."""
    limits = ResourceLimits()
    assert limits.max_memory_mb == 256
    assert limits.max_cpu_cores == 1.0
    assert limits.max_processes == 32
    assert limits.max_output_bytes == 65536
    assert limits.timeout_seconds == 5.0


def test_resource_limits_validation_bounds():
    """Verifies ResourceLimits rejects values outside safe operating bounds."""
    # Memory below minimum (16 MB)
    with pytest.raises(ValidationError):
        ResourceLimits(max_memory_mb=8)

    # CPU cores <= 0
    with pytest.raises(ValidationError):
        ResourceLimits(max_cpu_cores=0.0)

    # Max processes < 1
    with pytest.raises(ValidationError):
        ResourceLimits(max_processes=0)

    # Max output bytes < 1024
    with pytest.raises(ValidationError):
        ResourceLimits(max_output_bytes=512)

    # Timeout <= 0
    with pytest.raises(ValidationError):
        ResourceLimits(timeout_seconds=0.0)


def test_sandbox_policy_security_defaults():
    """Verifies SandboxPolicy enforces safe containment defaults."""
    policy = SandboxPolicy()
    assert policy.allow_network is False
    assert policy.read_only_root_fs is True
    assert policy.workspace_read_write is True
    assert policy.run_as_user == "1000:1000"
    assert policy.drop_all_capabilities is True
    assert isinstance(policy.resources, ResourceLimits)


def test_sandbox_policy_rejects_root_user():
    """Verifies SandboxPolicy rejects root user or UID 0 execution across formats."""
    for root_identifier in ("0", "0:0", "0:1000", "root", "ROOT", "root:root"):
        with pytest.raises(ValidationError) as exc_info:
            SandboxPolicy(run_as_user=root_identifier)
        assert "rejects root execution" in str(exc_info.value)



def test_sandbox_policy_run_as_user_validation():
    """Verifies numeric UID / UID:GID requirements and rejection of malformed IDs."""
    # Valid numeric formats
    valid_p1 = SandboxPolicy(run_as_user="1000")
    assert valid_p1.run_as_user == "1000"

    valid_p2 = SandboxPolicy(run_as_user="1000:1000")
    assert valid_p2.run_as_user == "1000:1000"

    valid_p3 = SandboxPolicy(run_as_user="65534:65534")
    assert valid_p3.run_as_user == "65534:65534"

    # Non-zero UID with GID 0 (e.g. 1000:0) is allowed syntactically, but UID 0 is blocked
    valid_gid_zero = SandboxPolicy(run_as_user="1000:0")
    assert valid_gid_zero.run_as_user == "1000:0"

    # UID 0 with nonzero GID must be rejected
    with pytest.raises(ValidationError) as exc_info:
        SandboxPolicy(run_as_user="0:1000")
    assert "UID cannot be 0" in str(exc_info.value)

    # Negative IDs
    for neg_val in ("-1", "-1000", "1000:-1", "-1:1000"):
        with pytest.raises(ValidationError):
            SandboxPolicy(run_as_user=neg_val)

    # Empty and whitespace
    for empty_val in ("", "   "):
        with pytest.raises(ValidationError):
            SandboxPolicy(run_as_user=empty_val)

    # Malformed / non-numeric strings
    for malformed in ("nobody", "user:group", "1000:abc", "abc:1000", "1000:1000:1000", "1000;1000"):
        with pytest.raises(ValidationError):
            SandboxPolicy(run_as_user=malformed)

    # Unicode non-ASCII digits (e.g. Arabic-Indic \u0661\u0660\u0660\u0660, Devanagari \u0967\u0966\u0966\u0966, Fullwidth \uff11\uff10\uff10\uff10)
    for unicode_digit in ("١٠٠٠", "१०००", "１０００", "1000:१०००"):
        assert all(part.isdigit() for part in unicode_digit.split(":")), "Sanity check: str.isdigit() accepts these Unicode digits"
        with pytest.raises(ValidationError) as exc_info:
            SandboxPolicy(run_as_user=unicode_digit)
        assert "ASCII decimal" in str(exc_info.value)





def test_sandbox_execution_result_fields():
    """Verifies result mapping and default values."""
    res = SandboxExecutionResult(
        status=ExecutionStatus.SUCCESS,
        exit_code=0,
        stdout="Hello World",
        stderr="",
        execution_time_ms=12.5,
        sandbox_backend="test_backend",
    )
    assert res.status == ExecutionStatus.SUCCESS
    assert res.failure_category is None
    assert res.exit_code == 0
    assert res.stdout == "Hello World"
    assert res.timed_out is False
    assert res.output_truncated is False
    assert res.sandbox_backend == "test_backend"


def test_sandbox_execution_result_infrastructure_failure_mapping():
    """Verifies result representation of fail-closed environment failures."""
    res = SandboxExecutionResult(
        status=ExecutionStatus.INFRASTRUCTURE_ERROR,
        failure_category=FailureCategory.ENVIRONMENT_ERROR,
        exit_code=-1,
        error_detail="Docker daemon not found.",
        sandbox_backend="docker",
    )
    assert res.status == ExecutionStatus.INFRASTRUCTURE_ERROR
    assert res.failure_category == FailureCategory.ENVIRONMENT_ERROR
    assert res.error_detail == "Docker daemon not found."


def test_models_json_serialization_roundtrip():
    """Verifies that all sandbox models serialize and deserialize without loss."""
    policy = SandboxPolicy(
        allow_network=False,
        resources=ResourceLimits(max_memory_mb=512, timeout_seconds=10.0),
    )
    data = policy.model_dump()
    reconstituted = SandboxPolicy.model_validate(data)
    assert reconstituted.resources.max_memory_mb == 512
    assert reconstituted.resources.timeout_seconds == 10.0

    result = SandboxExecutionResult(
        status=ExecutionStatus.TIMEOUT,
        failure_category=FailureCategory.TIME_LIMIT_EXCEEDED,
        exit_code=-1,
        timed_out=True,
        sandbox_backend="docker",
    )
    data_res = result.model_dump()
    reconstituted_res = SandboxExecutionResult.model_validate(data_res)
    assert reconstituted_res.status == ExecutionStatus.TIMEOUT
    assert reconstituted_res.timed_out is True


def test_dummy_sandbox_contract(tmp_path):
    """Verifies BaseSandbox interface execution and unavailable fail-closed behavior."""
    sandbox = DummySandbox(available=True)
    assert sandbox.backend_name == "dummy"
    assert sandbox.is_available() is True

    res = sandbox.execute(["echo", "hello"], tmp_path)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.stdout == "dummy ok"

    unavail_sandbox = DummySandbox(available=False)
    assert unavail_sandbox.is_available() is False
    unavail_res = unavail_sandbox.execute(["echo", "hello"], tmp_path)
    assert unavail_res.status == ExecutionStatus.INFRASTRUCTURE_ERROR
    assert unavail_res.failure_category == FailureCategory.ENVIRONMENT_ERROR
