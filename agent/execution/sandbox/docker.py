"""
Production Docker / OCI Sandbox Implementation.

Enforces strict containment for untrusted code execution:
- Non-root execution (`--user <run_as_user>`)
- Complete network isolation (`--network none`)
- Read-only root filesystem (`--read-only`)
- Dropped Linux capabilities (`--cap-drop ALL`)
- No new privileges (`--security-opt no-new-privileges`)
- Strict cgroup resource bounds (memory, CPU, pids/process count)
- Incremental output budgeting with safe excess discarding
- Strict scratch-root containment and path validation against directory traversal
- Deterministic Docker image identity verification (digest or image ID)
- Fresh, private scratch workspaces with re-check before launch
- Explicit, allowlisted environment variables (no host environment leakage)
- Zero mounting of Docker socket, devices, or host filesystem outside workspace
- Bounded termination, pipe closure, thread joining, and label-based cleanup
- Deterministic fail-closed behavior on missing Docker engine, image, or identity mismatch
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from agent.core.models import ExecutionStatus, FailureCategory
from agent.execution.sandbox.base import BaseSandbox
from agent.execution.sandbox.models import (
    ResourceLimits,
    SandboxExecutionResult,
    SandboxPolicy,
)

logger = logging.getLogger(__name__)

# Default controlled sandbox image reference (version-pinned tag or digest)
DEFAULT_SANDBOX_IMAGE = "agent-sandbox:v1"

# Allowed environment variable names that may be passed into the container
PERMITTED_ENV_NAMES: Set[str] = {
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
    "PYTHONUNBUFFERED",
    "JAVA_TOOL_OPTIONS",
}


def _drain_stream_incrementally(
    stream,
    collector: List[bytes],
    budget_lock: threading.Lock,
    shared_state: Dict[str, int],
) -> None:
    """
    Drains a binary stream incrementally.
    Retains bytes up to the shared remaining budget, discarding all excess.
    Exits cleanly when stream hits EOF or is closed.
    """
    chunk_size = 4096
    try:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            with budget_lock:
                remaining = shared_state["budget_remaining"]
                if remaining > 0:
                    take = min(len(chunk), remaining)
                    collector.append(chunk[:take])
                    shared_state["budget_remaining"] -= take
                else:
                    shared_state["truncated"] = 1
    except Exception as e:
        logger.debug(f"Stream drain error: {e}")
    finally:
        try:
            stream.close()
        except Exception:
            pass


class DockerSandbox(BaseSandbox):
    """
    Robust Docker / OCI container sandbox implementing BaseSandbox.
    Fails closed if Docker is absent, image identity mismatches,
    or security constraints cannot be enforced.
    """

    def __init__(
        self,
        image_name: str = DEFAULT_SANDBOX_IMAGE,
        docker_cmd: Optional[str] = None,
        scratch_base_dir: Optional[Path] = None,
        expected_image_id: Optional[str] = None,
        expected_digest: Optional[str] = None,
        require_image_check: bool = True,
    ):
        """
        Initializes the Docker sandbox backend.

        Args:
            image_name: Pinned image tag or digest reference (e.g. 'agent-sandbox:v1' or 'agent-sandbox@sha256:...').
            docker_cmd: Optional explicit path to the Docker binary.
            scratch_base_dir: Base directory where ephemeral scratch workspaces must reside.
            expected_image_id: Optional immutable image ID/hash (e.g. 'sha256:abcd...') expected from docker inspect.
            expected_digest: Optional immutable repo digest expected from docker inspect.
            require_image_check: Whether to verify image availability and identity in is_available().
        """
        self._image_name = image_name.strip()
        if not self._image_name:
            raise ValueError("DockerSandbox image_name cannot be empty.")

        # Check format: must have a tag or digest, and cannot be :latest
        if "@" in self._image_name:
            # Digest reference: e.g. agent-sandbox@sha256:1234...
            repo, digest_part = self._image_name.split("@", 1)
            if not digest_part.startswith("sha256:") or len(digest_part) < 15:
                raise ValueError(
                    f"DockerSandbox digest reference must use a valid sha256 digest, got '{self._image_name}'."
                )
        elif ":" in self._image_name:
            if self._image_name.endswith(":latest"):
                raise ValueError(
                    f"DockerSandbox rejects mutable ':latest' tag; requires a pinned version tag or digest, got '{self._image_name}'."
                )
        else:
            raise ValueError(
                f"DockerSandbox requires a pinned version tag (e.g. 'agent-sandbox:v1') or digest, got '{self._image_name}'."
            )

        self._docker_path = docker_cmd or shutil.which("docker")
        configured_scratch = scratch_base_dir or Path(os.environ.get("AGENT_SCRATCH_DIR", "storage/temp"))
        self._scratch_base_dir = configured_scratch.resolve()

        # Support expected image identity verification
        self._expected_image_id = (
            expected_image_id.strip()
            if expected_image_id
            else os.environ.get("AGENT_SANDBOX_EXPECTED_IMAGE_ID", "").strip() or None
        )
        self._expected_digest = (
            expected_digest.strip()
            if expected_digest
            else os.environ.get("AGENT_SANDBOX_EXPECTED_DIGEST", "").strip() or None
        )
        if self._expected_digest:
            if not self._expected_digest.startswith("sha256:") or len(self._expected_digest) < 15:
                raise ValueError(
                    f"DockerSandbox expected_digest must be a valid sha256 digest reference, got '{self._expected_digest}'."
                )
        self._require_image_check = require_image_check

    @property
    def backend_name(self) -> str:
        return "docker"

    @property
    def image_name(self) -> str:
        return self._image_name

    @property
    def scratch_base_dir(self) -> Path:
        return self._scratch_base_dir

    @property
    def expected_image_id(self) -> Optional[str]:
        return self._expected_image_id

    @property
    def expected_digest(self) -> Optional[str]:
        return self._expected_digest

    def create_private_workspace(self, prefix: str = "ws_") -> Path:
        """
        Creates a fresh, unique, private scratch workspace directory within the scratch base root.
        Applies restrictive directory permissions (0o700 on POSIX).
        """
        self._scratch_base_dir.mkdir(parents=True, exist_ok=True)
        unique_name = f"{prefix}{uuid.uuid4().hex[:12]}"
        ws_dir = self._scratch_base_dir / unique_name
        ws_dir.mkdir(parents=True, exist_ok=False)

        # Apply restrictive permissions on POSIX
        if os.name != "nt":
            try:
                os.chmod(ws_dir, 0o700)
            except OSError as e:
                logger.warning(f"Could not set restrictive permissions on {ws_dir}: {e}")

        return ws_dir.resolve()

    def _verify_image_identity(self) -> Tuple[bool, str]:
        """
        Inspects the local Docker image and verifies that:
        1. An expected cryptographic identity (expected_image_id or expected_digest) is configured.
           Fails closed if neither is configured.
        2. The image exists locally without pulling.
        3. If expected_image_id is specified, the inspected .Id matches exactly.
        4. If expected_digest is specified, .RepoDigests contains the expected digest exactly.
        """
        if not self._expected_image_id and not self._expected_digest:
            return False, (
                f"DockerSandbox requires a configured expected_image_id or expected_digest for '{self._image_name}'. "
                "Failing closed because no expected immutable image identity was provided."
            )

        if not self._docker_path:
            return False, "Docker CLI not found."

        try:
            img_res = subprocess.run(
                [self._docker_path, "image", "inspect", self._image_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3.0,
            )
            if img_res.returncode != 0:
                return False, f"Image '{self._image_name}' inspect failed or image not found locally: {img_res.stderr.strip()}"

            data = json.loads(img_res.stdout)
            if not data or not isinstance(data, list):
                return False, f"Malformed inspect output for image '{self._image_name}'."

            img_info = data[0]
            actual_id = img_info.get("Id", "")
            repo_digests = img_info.get("RepoDigests", [])

            # Verify image ID if configured (exact match required)
            if self._expected_image_id:
                if actual_id != self._expected_image_id:
                    return False, (
                        f"Image ID mismatch for '{self._image_name}': "
                        f"expected '{self._expected_image_id}', got '{actual_id}'."
                    )

            # Verify repo digest if configured (must match complete digest value)
            if self._expected_digest:
                # Expected digest must be of the form sha256:<64-hex>
                digest_val = self._expected_digest
                found_digest = False
                for rd in repo_digests:
                    if rd == digest_val:
                        found_digest = True
                        break
                    if "@" in rd:
                        _, part = rd.split("@", 1)
                        if part == digest_val:
                            found_digest = True
                            break
                if not found_digest:
                    return False, (
                        f"Image digest mismatch for '{self._image_name}': "
                        f"expected digest '{self._expected_digest}', available digests: {repo_digests}."
                    )

            return True, ""
        except Exception as e:
            return False, f"Exception during image identity verification: {e}"

    def is_available(self) -> bool:
        """
        Verifies that:
        1. The Docker CLI exists.
        2. The Docker daemon is actively responding.
        3. The engine is running verified Linux containers.
        4. The required image exists locally and matches configured immutable identity.
        Fails closed on any failure.
        """
        if not self._docker_path:
            return False

        try:
            res = subprocess.run(
                [self._docker_path, "info", "--format", "{{.OSType}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3.0,
            )
            if res.returncode != 0:
                return False

            os_type = res.stdout.strip().lower()
            if os_type != "linux":
                # Only verified Linux containers support all mandatory isolation flags
                return False

            if self._require_image_check:
                valid_identity, _ = self._verify_image_identity()
                if not valid_identity:
                    return False

            return True
        except Exception:
            return False

    def validate_workspace_path(self, workspace_dir: Path) -> Tuple[bool, str]:
        """
        Enforces strict scratch-root boundary containment:
        - Workspace must exist and be a directory.
        - Canonical resolved path must be a strict descendant (child) of self._scratch_base_dir.
        - Must NOT be the scratch root itself.
        - Must NOT be filesystem root, drive root, home directory, or repo directory.
        - Must NOT contain symlink escapes or external symlinks.
        """
        try:
            resolved = workspace_dir.resolve()
        except Exception as e:
            return False, f"Failed to resolve workspace path: {e}"

        if not resolved.exists():
            return False, f"Workspace path does not exist: '{resolved}'."
        if not resolved.is_dir():
            return False, f"Workspace path is not a directory: '{resolved}'."

        # Scratch base root check
        try:
            resolved_scratch = self._scratch_base_dir.resolve()
        except Exception as e:
            return False, f"Failed to resolve scratch root: {e}"

        if not resolved_scratch.exists():
            return False, f"Scratch root directory does not exist: '{resolved_scratch}'."

        # Workspace must be a strict descendant of scratch root (cannot be scratch root itself)
        try:
            rel = resolved.relative_to(resolved_scratch)
            if str(rel) in (".", ""):
                return False, f"Workspace cannot be the scratch root itself: '{resolved}'."
        except ValueError:
            return False, (
                f"Workspace path '{resolved}' is not within designated scratch root '{resolved_scratch}'."
            )

        # Explicitly check and reject dangerous roots regardless of scratch path configuration
        dangerous_roots = {
            Path("/").resolve(),
            Path.home().resolve(),
            Path.cwd().resolve(),
        }
        if os.name == "nt":
            try:
                drive_root = Path(resolved.drive + "\\").resolve()
                dangerous_roots.add(drive_root)
            except Exception:
                pass

        if resolved in dangerous_roots:
            return False, f"Rejecting mount of protected host root: '{resolved}'."

        # Check for symlink traversal within workspace using proper path-component containment
        for root, dirs, files in os.walk(resolved, followlinks=False):
            for item in dirs + files:
                p = Path(root) / item
                if p.is_symlink():
                    try:
                        target = p.resolve()
                        target.relative_to(resolved)
                    except ValueError:
                        return False, f"Symlink traversal detected: '{p}' points outside workspace to '{target}'."
                    except Exception as e:
                        return False, f"Symlink resolution failed: {e}"

        return True, ""

    def _convert_path_for_docker_mount(self, p: Path) -> str:
        """
        Formats path for Docker bind-mount. On Windows hosts running Docker Desktop,
        converts backslashes and drive syntax safely.
        """
        resolved = str(p.resolve())
        # If running on Windows, convert 'C:\path\to' to 'c:/path/to' for Linux OCI volume mapping
        if os.name == "nt" and len(resolved) >= 2 and resolved[1] == ":":
            drive = resolved[0].lower()
            rest = resolved[2:].replace("\\", "/")
            return f"/{drive}{rest}"
        return resolved

    def _build_docker_run_command(
        self,
        container_name: str,
        workspace_dir: Path,
        command: List[str],
        policy: SandboxPolicy,
    ) -> List[str]:
        """Constructs the hardened docker run command line."""
        docker_bin = self._docker_path or "docker"
        docker_mount_path = self._convert_path_for_docker_mount(workspace_dir)

        cmd = [
            docker_bin,
            "run",
            "--name", container_name,
            "--label", "agent.sandbox.managed=true",
            "--label", f"agent.sandbox.container={container_name}",
            "--rm",
        ]

        # 1. Network isolation (non-negotiable containment)
        cmd.extend(["--network", "none"])

        # 2. Filesystem protection (non-negotiable containment)
        cmd.append("--read-only")

        # 3. Privilege constraints (non-negotiable containment)
        cmd.extend(["--cap-drop", "ALL"])
        cmd.extend(["--security-opt", "no-new-privileges"])

        # 4. User context (non-root)
        cmd.extend(["--user", policy.run_as_user])

        # 5. Resource quotas
        res = policy.resources
        cmd.extend([
            "--memory", f"{res.max_memory_mb}m",
            "--memory-swap", f"{res.max_memory_mb}m",
            "--cpus", str(res.max_cpu_cores),
            "--pids-limit", str(res.max_processes),
        ])

        # 6. Storage isolation: Mount strictly the workspace and a constrained tmpfs
        mount_mode = "rw" if policy.workspace_read_write else "ro"
        cmd.extend([
            "--volume", f"{docker_mount_path}:/workspace:{mount_mode}",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
            "--workdir", "/workspace",
        ])

        # 7. Explicit allowlisted environment variables only
        for k, v in policy.environment_variables.items():
            if k in PERMITTED_ENV_NAMES:
                cmd.extend(["-e", f"{k}={v}"])

        # Image and user command
        cmd.append(self._image_name)
        cmd.extend(command)

        return cmd

    def _kill_and_remove_container(self, container_name: str) -> None:
        """
        Issues bounded kill and removal for the specific container.
        Only targets containers matching the unique container_name.
        """
        docker_bin = self._docker_path or "docker"
        try:
            subprocess.run(
                [docker_bin, "kill", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
            )
        except Exception:
            pass

        try:
            subprocess.run(
                [docker_bin, "rm", "-f", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
            )
        except Exception:
            pass

    def execute(
        self,
        command: List[str],
        workspace_dir: Path,
        policy: Optional[SandboxPolicy] = None,
    ) -> SandboxExecutionResult:
        """
        Executes a command inside the hardened Docker container.
        Fails closed with INFRASTRUCTURE_ERROR if security constraints cannot be met.
        """
        eff_policy = policy or SandboxPolicy()

        # Fail closed immediately if Docker engine is unavailable or unverified
        if not self.is_available():
            return SandboxExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                exit_code=-1,
                error_detail=(
                    f"DockerSandbox unavailable: Docker CLI not found or daemon not running Linux containers with image '{self._image_name}'."
                ),
                sandbox_backend=self.backend_name,
            )

        # Fail closed on invalid command
        if not command or not any(c.strip() for c in command):
            return SandboxExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.FORMAT_ERROR,
                exit_code=-1,
                error_detail="Cannot execute empty command vector.",
                sandbox_backend=self.backend_name,
            )

        # Validate workspace directory security (canonical scratch descendant check)
        is_valid_path, path_err = self.validate_workspace_path(workspace_dir)
        if not is_valid_path:
            return SandboxExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                exit_code=-1,
                error_detail=f"Workspace path validation failed: {path_err}",
                sandbox_backend=self.backend_name,
            )

        # Generate unique container ID
        run_uuid = uuid.uuid4().hex[:12]
        container_name = f"agent-box-{run_uuid}"

        # Re-check canonical path condition immediately before launch
        is_rechecked, recheck_err = self.validate_workspace_path(workspace_dir)
        if not is_rechecked:
            return SandboxExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                exit_code=-1,
                error_detail=f"Workspace re-check failed immediately before launch: {recheck_err}",
                sandbox_backend=self.backend_name,
            )

        docker_run_cmd = self._build_docker_run_command(
            container_name=container_name,
            workspace_dir=workspace_dir,
            command=command,
            policy=eff_policy,
        )

        timeout_sec = eff_policy.resources.timeout_seconds
        max_output_bytes = eff_policy.resources.max_output_bytes

        stdout_chunks: List[bytes] = []
        stderr_chunks: List[bytes] = []
        budget_lock = threading.Lock()
        shared_state: Dict[str, int] = {
            "budget_remaining": max_output_bytes,
            "truncated": 0,
        }

        start_time = time.perf_counter()
        process = None
        t_out = None
        t_err = None

        try:
            # Launch host-side Docker CLI client
            process = subprocess.Popen(
                docker_run_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Drain stdout and stderr incrementally in worker threads
            t_out = threading.Thread(
                target=_drain_stream_incrementally,
                args=(process.stdout, stdout_chunks, budget_lock, shared_state),
                daemon=True,
            )
            t_err = threading.Thread(
                target=_drain_stream_incrementally,
                args=(process.stderr, stderr_chunks, budget_lock, shared_state),
                daemon=True,
            )
            t_out.start()
            t_err.start()

            # Wait for host process completion within timeout
            exit_code = process.wait(timeout=timeout_sec)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            # Safely close pipes and join drain threads within bounded cleanup time
            if process.stdout:
                try:
                    process.stdout.close()
                except Exception:
                    pass
            if process.stderr:
                try:
                    process.stderr.close()
                except Exception:
                    pass

            t_out.join(timeout=1.0)
            t_err.join(timeout=1.0)

            stdout_text = b"".join(stdout_chunks).decode("utf-8", errors="replace")
            stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")
            was_truncated = bool(shared_state["truncated"])

            if exit_code == 0:
                return SandboxExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    exit_code=0,
                    stdout=stdout_text,
                    stderr=stderr_text,
                    execution_time_ms=elapsed_ms,
                    output_truncated=was_truncated,
                    sandbox_backend=self.backend_name,
                )
            elif exit_code == 137:
                # Exit code 137 typically indicates SIGKILL / Out-Of-Memory termination
                return SandboxExecutionResult(
                    status=ExecutionStatus.RUNTIME_ERROR,
                    failure_category=FailureCategory.MEMORY_LIMIT_EXCEEDED,
                    exit_code=137,
                    stdout=stdout_text,
                    stderr=stderr_text or "Process killed (OOM or SIGKILL).",
                    execution_time_ms=elapsed_ms,
                    output_truncated=was_truncated,
                    sandbox_backend=self.backend_name,
                    error_detail="Process exceeded memory limit or was terminated by SIGKILL (exit code 137).",
                )
            else:
                return SandboxExecutionResult(
                    status=ExecutionStatus.RUNTIME_ERROR,
                    failure_category=FailureCategory.RUNTIME_ERROR,
                    exit_code=exit_code,
                    stdout=stdout_text,
                    stderr=stderr_text,
                    execution_time_ms=elapsed_ms,
                    output_truncated=was_truncated,
                    sandbox_backend=self.backend_name,
                    error_detail=f"Container process exited with code {exit_code}.",
                )

        except subprocess.TimeoutExpired:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            # Forcefully terminate both container and host subprocess
            self._kill_and_remove_container(container_name)
            if process:
                try:
                    process.kill()
                    process.wait(timeout=1.0)
                except Exception:
                    pass

            # Close pipes to unblock any drain threads
            if process:
                if process.stdout:
                    try:
                        process.stdout.close()
                    except Exception:
                        pass
                if process.stderr:
                    try:
                        process.stderr.close()
                    except Exception:
                        pass

            if t_out:
                t_out.join(timeout=1.0)
            if t_err:
                t_err.join(timeout=1.0)

            return SandboxExecutionResult(
                status=ExecutionStatus.TIMEOUT,
                failure_category=FailureCategory.TIME_LIMIT_EXCEEDED,
                exit_code=-1,
                stderr=f"Execution timed out after {timeout_sec} seconds.",
                execution_time_ms=elapsed_ms,
                timed_out=True,
                sandbox_backend=self.backend_name,
                error_detail=f"Execution exceeded configured timeout limit of {timeout_sec}s.",
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            self._kill_and_remove_container(container_name)
            if process:
                try:
                    process.kill()
                    process.wait(timeout=1.0)
                except Exception:
                    pass
                if process.stdout:
                    try:
                        process.stdout.close()
                    except Exception:
                        pass
                if process.stderr:
                    try:
                        process.stderr.close()
                    except Exception:
                        pass

            if t_out:
                t_out.join(timeout=1.0)
            if t_err:
                t_err.join(timeout=1.0)

            return SandboxExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                exit_code=-1,
                execution_time_ms=elapsed_ms,
                error_detail=f"DockerSandbox execution failed: {str(e)}",
                sandbox_backend=self.backend_name,
            )
        finally:
            # Ensure container is purged regardless of state
            self._kill_and_remove_container(container_name)
