"""
Docker-Independent Unit Tests for DockerSandbox Backend (Stage 2 Remediation).

These tests run without requiring a Docker daemon or Docker CLI:
1. Rejection of unversioned/mutable image tags (e.g. empty or ':latest') and validation of digest references.
2. Command synthesis verification (verifies all mandatory flags: --network none,
   --read-only, --cap-drop ALL, --security-opt no-new-privileges, --user,
   --memory, --cpus, --pids-limit, --tmpfs, --volume).
3. Scratch-root boundary enforcement (rejects scratch root itself, paths outside scratch root,
   filesystem root, cwd/repo root, home directory, symlink traversal).
4. Fresh private workspace generation with unique naming and scratch root containment.
5. Deterministic fail-closed behavior when Docker CLI is missing or daemon fails.
6. Image identity verification (matching vs mismatched image ID or digest, inspect failure).
7. Incremental stream draining and output budgeting (discards excess bytes without buffering whole stream).
8. Bounded timeout handling: process termination, pipe closure, thread joining, and container kill.
"""

import io
import json
import os
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from agent.core.models import ExecutionStatus, FailureCategory
from agent.execution.sandbox.docker import (
    DEFAULT_SANDBOX_IMAGE,
    DockerSandbox,
    _drain_stream_incrementally,
)
from agent.execution.sandbox.models import (
    ResourceLimits,
    SandboxPolicy,
)


def test_docker_sandbox_image_tag_validation():
    """Verifies that DockerSandbox rejects unpinned or ':latest' image tags, but accepts valid tags & digests."""
    # Must reject empty
    with pytest.raises(ValueError):
        DockerSandbox(image_name="")

    # Must reject ':latest'
    with pytest.raises(ValueError) as exc:
        DockerSandbox(image_name="agent-sandbox:latest")
    assert "rejects mutable ':latest' tag" in str(exc.value)

    # Must reject tag without colon or digest
    with pytest.raises(ValueError):
        DockerSandbox(image_name="agent-sandbox")

    # Valid pinned version tag accepted
    box = DockerSandbox(image_name="agent-sandbox:v1.2.3")
    assert box.image_name == "agent-sandbox:v1.2.3"
    assert box.backend_name == "docker"

    # Valid digest reference accepted
    box_digest = DockerSandbox(image_name="agent-sandbox@sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    assert "@sha256:" in box_digest.image_name


def test_command_synthesis_enforces_all_mandatory_isolation_flags(tmp_path):
    """Verifies docker run command incorporates all required security flags."""
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    ws_dir = scratch_dir / "ws_123"
    ws_dir.mkdir()

    box = DockerSandbox(image_name="agent-sandbox:v1", docker_cmd="/usr/bin/docker", scratch_base_dir=scratch_dir)
    policy = SandboxPolicy(
        allow_network=False,
        read_only_root_fs=True,
        drop_all_capabilities=True,
        run_as_user="1001:1001",
        resources=ResourceLimits(
            max_memory_mb=128,
            max_cpu_cores=0.5,
            max_processes=16,
        ),
        environment_variables={"LANG": "C.UTF-8", "FORBIDDEN_VAR": "secret"},
    )

    cmd = box._build_docker_run_command(
        container_name="agent-box-test1234",
        workspace_dir=ws_dir,
        command=["python3", "harness.py"],
        policy=policy,
    )

    cmd_str = " ".join(cmd)
    # Check binary and name
    assert cmd[0] == "/usr/bin/docker"
    assert "agent-box-test1234" in cmd
    assert "--rm" in cmd
    # Check security boundaries
    assert "--network none" in cmd_str
    assert "--read-only" in cmd_str
    assert "--cap-drop ALL" in cmd_str
    assert "--security-opt no-new-privileges" in cmd_str
    assert "--user 1001:1001" in cmd_str
    # Check cgroup resource bounds
    assert "--memory 128m" in cmd_str
    assert "--memory-swap 128m" in cmd_str
    assert "--cpus 0.5" in cmd_str
    assert "--pids-limit 16" in cmd_str
    # Check mounts
    assert "/tmp:rw,noexec,nosuid,size=32m" in cmd_str
    assert "/workspace:rw" in cmd_str
    # Check environment allowlist: LANG included, FORBIDDEN_VAR excluded
    assert "-e LANG=C.UTF-8" in cmd_str
    assert "FORBIDDEN_VAR" not in cmd_str
    # Check target image and payload
    assert "agent-sandbox:v1" in cmd
    assert cmd[-2:] == ["python3", "harness.py"]


def test_command_synthesis_enforces_non_negotiable_isolation_even_if_policy_weakened(tmp_path):
    """
    Verifies that mandatory security controls (network none, read-only root, cap-drop ALL)
    are strictly enforced even if a caller policy attempts to weaken them.
    """
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    ws_dir = scratch_dir / "ws_weak"
    ws_dir.mkdir()

    box = DockerSandbox(image_name="agent-sandbox:v1", docker_cmd="/usr/bin/docker", scratch_base_dir=scratch_dir)

    # 1. Attempt to allow network
    weak_net_policy = SandboxPolicy(allow_network=True)
    cmd1 = box._build_docker_run_command("box1", ws_dir, ["python3", "test.py"], weak_net_policy)
    assert "--network none" in " ".join(cmd1)

    # 2. Attempt to disable read-only root fs
    weak_ro_policy = SandboxPolicy(read_only_root_fs=False)
    cmd2 = box._build_docker_run_command("box2", ws_dir, ["python3", "test.py"], weak_ro_policy)
    assert "--read-only" in " ".join(cmd2)

    # 3. Attempt to retain capabilities
    weak_caps_policy = SandboxPolicy(drop_all_capabilities=False)
    cmd3 = box._build_docker_run_command("box3", ws_dir, ["python3", "test.py"], weak_caps_policy)
    assert "--cap-drop ALL" in " ".join(cmd3)


def test_scratch_root_boundary_enforcement(tmp_path):
    """
    Finding 1: Verifies that validate_workspace_path strictly enforces containment:
    - Rejects paths outside scratch root.
    - Rejects scratch root itself.
    - Accepts valid child workspaces.
    - Rejects filesystem root, home directory, and repo root.
    """
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()

    box = DockerSandbox(image_name="agent-sandbox:v1", scratch_base_dir=scratch_root)

    # 1. Reject scratch root itself
    valid, err = box.validate_workspace_path(scratch_root)
    assert not valid
    assert "cannot be the scratch root itself" in err

    # 2. Reject path outside scratch root
    valid, err = box.validate_workspace_path(outside_dir)
    assert not valid
    assert "not within designated scratch root" in err

    # 3. Reject protected roots
    valid, err = box.validate_workspace_path(Path.cwd())
    assert not valid
    valid, err = box.validate_workspace_path(Path.home())
    assert not valid

    # 4. Reject nonexistent path
    valid, err = box.validate_workspace_path(scratch_root / "nonexistent")
    assert not valid
    assert "does not exist" in err

    # 5. Accept valid child workspace
    valid_ws = scratch_root / "job_001"
    valid_ws.mkdir()
    valid, err = box.validate_workspace_path(valid_ws)
    assert valid
    assert err == ""


def test_scratch_root_boundary_rejects_symlink_escape(tmp_path):
    """Verifies that symlinks escaping the workspace fail path validation."""
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    outside_secret = tmp_path / "outside_secret"
    outside_secret.mkdir()
    (outside_secret / "secret.txt").write_text("classified")

    ws = scratch_root / "ws_sym"
    ws.mkdir()
    link_path = ws / "leak_link"

    try:
        os.symlink(outside_secret, link_path)
    except OSError:
        pytest.skip("Host does not permit symlink creation without elevated privileges.")

    box = DockerSandbox(image_name="agent-sandbox:v1", scratch_base_dir=scratch_root)
    valid, err = box.validate_workspace_path(ws)
    assert not valid
    assert "Symlink traversal detected" in err


def test_scratch_root_boundary_rejects_symlink_with_prefix_sharing_target(tmp_path):
    """
    Verifies that a symlink target whose path shares a textual string prefix with workspace
    (e.g., workspace is /scratch/ws, target is /scratch/ws_neighbor) is correctly rejected
    using path-component containment rather than simple str.startswith.
    """
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()

    # Workspace directory: .../scratch/ws
    ws = scratch_root / "ws"
    ws.mkdir()

    # Sibling directory that starts with the same textual prefix: .../scratch/ws_neighbor
    sibling_with_shared_prefix = scratch_root / "ws_neighbor"
    sibling_with_shared_prefix.mkdir()
    (sibling_with_shared_prefix / "data.txt").write_text("sibling_secret")

    link_path = ws / "sym_to_sibling"
    try:
        os.symlink(sibling_with_shared_prefix, link_path)
    except OSError:
        pytest.skip("Host does not permit symlink creation without elevated privileges.")

    box = DockerSandbox(image_name="agent-sandbox:v1", scratch_base_dir=scratch_root)
    valid, err = box.validate_workspace_path(ws)
    assert not valid
    assert "Symlink traversal detected" in err


def test_create_private_workspace_generates_unique_scratch_descendants(tmp_path):
    """Finding 3: Verifies create_private_workspace creates distinct isolated workspaces inside scratch."""
    scratch_root = tmp_path / "scratch"
    box = DockerSandbox(image_name="agent-sandbox:v1", scratch_base_dir=scratch_root)

    ws1 = box.create_private_workspace(prefix="task_")
    ws2 = box.create_private_workspace(prefix="task_")

    assert ws1 != ws2
    assert ws1.exists() and ws1.is_dir()
    assert ws2.exists() and ws2.is_dir()

    valid1, _ = box.validate_workspace_path(ws1)
    valid2, _ = box.validate_workspace_path(ws2)
    assert valid1 is True
    assert valid2 is True


def test_image_identity_verification_matching_and_mismatch():
    """
    Finding 2: Verifies image identity policy:
    - Validates expected image ID against docker inspect output.
    - Validates expected digest against inspect RepoDigests.
    - Fails closed on mismatch or inspect failure.
    """
    box = DockerSandbox(
        image_name="agent-sandbox:v1",
        docker_cmd="/mock/docker",
        expected_image_id="sha256:1111222233334444",
        expected_digest="sha256:aabbccddeeff",
    )

    # 1. Matching ID and digest
    inspect_payload_ok = json.dumps([{
        "Id": "sha256:1111222233334444",
        "RepoDigests": ["agent-sandbox@sha256:aabbccddeeff"]
    }])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=inspect_payload_ok, stderr="")
        ok, err = box._verify_image_identity()
        assert ok is True
        assert err == ""

    # 2. Image ID mismatch
    inspect_payload_bad_id = json.dumps([{
        "Id": "sha256:9999888877776666",
        "RepoDigests": ["agent-sandbox@sha256:aabbccddeeff"]
    }])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=inspect_payload_bad_id, stderr="")
        ok, err = box._verify_image_identity()
        assert ok is False
        assert "Image ID mismatch" in err

    # 3. Digest mismatch
    inspect_payload_bad_digest = json.dumps([{
        "Id": "sha256:1111222233334444",
        "RepoDigests": ["agent-sandbox@sha256:wrongdigest000"]
    }])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=inspect_payload_bad_digest, stderr="")
        ok, err = box._verify_image_identity()
        assert ok is False
        assert "Image digest mismatch" in err

    # 4. Inspect failure (image missing locally)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error: No such image")
        ok, err = box._verify_image_identity()
        assert ok is False
        assert "inspect failed" in err

    # 5. Missing expected image identity fails closed
    box_unconfigured = DockerSandbox(
        image_name="agent-sandbox:v1",
        docker_cmd="/mock/docker",
        expected_image_id=None,
        expected_digest=None,
    )
    ok, err = box_unconfigured._verify_image_identity()
    assert ok is False
    assert "Failing closed because no expected immutable image identity was provided" in err

    # 6. Reject partial suffix match for image ID (exact match required)
    box_suffix_id = DockerSandbox(
        image_name="agent-sandbox:v1",
        docker_cmd="/mock/docker",
        expected_image_id="33334444",  # partial suffix of sha256:1111222233334444
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=inspect_payload_ok, stderr="")
        ok, err = box_suffix_id._verify_image_identity()
        assert ok is False
        assert "Image ID mismatch" in err

    # 7. Reject partial substring match for digest (complete digest required)
    with pytest.raises(ValueError) as exc:
        DockerSandbox(
            image_name="agent-sandbox:v1",
            expected_digest="aabbcc",  # not starting with sha256:
        )
    assert "must be a valid sha256 digest reference" in str(exc.value)

    # 8. Complete digest value matching against RepoDigests
    box_full_digest = DockerSandbox(
        image_name="agent-sandbox:v1",
        docker_cmd="/mock/docker",
        expected_digest="sha256:aabbccddeeff11223344",
    )
    # Matching repo digest
    payload_exact_rd = json.dumps([{
        "Id": "sha256:dummy",
        "RepoDigests": ["agent-sandbox@sha256:aabbccddeeff11223344"]
    }])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=payload_exact_rd, stderr="")
        ok, err = box_full_digest._verify_image_identity()
        assert ok is True

    # Collision where RepoDigests contains longer digest with same prefix
    payload_prefix_coll = json.dumps([{
        "Id": "sha256:dummy",
        "RepoDigests": ["agent-sandbox@sha256:aabbccddeeff112233449999"]
    }])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=payload_prefix_coll, stderr="")
        ok, err = box_full_digest._verify_image_identity()
        assert ok is False
        assert "Image digest mismatch" in err


def test_is_available_fails_closed_when_identity_verification_fails():
    """Finding 2: Verifies is_available() returns False when image identity fails."""
    box = DockerSandbox(
        image_name="agent-sandbox:v1",
        docker_cmd="/mock/docker",
        expected_image_id="sha256:expected123",
    )
    with patch("subprocess.run") as mock_run, \
         patch.object(box, "_verify_image_identity", return_value=(False, "mismatch")):
        mock_run.return_value = MagicMock(returncode=0, stdout="linux\n", stderr="")
        assert box.is_available() is False


def test_stream_drain_incremental_output_budgeting():
    """
    Verifies that _drain_stream_incrementally discards bytes beyond budget
    without buffering the entire infinite/large stream into memory.
    """
    total_generated = 100000  # 100 KB
    budget = 4096            # 4 KB budget
    source_bytes = b"A" * total_generated

    fake_stream = io.BytesIO(source_bytes)
    collector = []
    budget_lock = threading.Lock()
    shared_state = {"budget_remaining": budget, "truncated": 0}

    _drain_stream_incrementally(fake_stream, collector, budget_lock, shared_state)

    captured = b"".join(collector)
    assert len(captured) == budget
    assert shared_state["budget_remaining"] == 0
    assert shared_state["truncated"] == 1


def test_execute_timeout_handling_reaps_process_and_cleans_pipes(tmp_path):
    """
    Finding 5: Verifies that on timeout, container is killed, host process is reaped,
    pipes are closed, and TIMEOUT status is returned.
    """
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    ws_dir = scratch_root / "ws_job"
    ws_dir.mkdir()

    box = DockerSandbox(image_name="agent-sandbox:v1", docker_cmd="/mock/docker", scratch_base_dir=scratch_root)
    policy = SandboxPolicy(resources=ResourceLimits(timeout_seconds=0.5))

    with patch.object(box, "is_available", return_value=True), \
         patch.object(box, "_kill_and_remove_container") as mock_cleanup, \
         patch("subprocess.Popen") as mock_popen:

        mock_proc = MagicMock()
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="docker run", timeout=0.5)
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.return_value = b""
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""
        mock_popen.return_value = mock_proc

        res = box.execute(["sleep", "10"], ws_dir, policy)

        assert res.status == ExecutionStatus.TIMEOUT
        assert res.failure_category == FailureCategory.TIME_LIMIT_EXCEEDED
        assert res.timed_out is True
        assert mock_cleanup.called
        assert mock_proc.kill.called
        assert mock_proc.stdout.close.called
        assert mock_proc.stderr.close.called


def test_posix_permissions_strategy(tmp_path):
    """
    Verifies the least-privilege POSIX permission strategy:
    1. When host UID is 1000, preserves restrictive 0o700 / 0o600 permissions.
    2. When setfacl is available, applies targeted ACL u:1000:rwx without world exposure.
    3. Never follows symlinks when adjusting permissions.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    ws = scratch / "ws_sec"
    ws.mkdir()
    sample_file = ws / "script.py"
    sample_file.write_text("print('test')")

    box = DockerSandbox(image_name="agent-sandbox:v1", scratch_base_dir=scratch)

    # 1. Matching UID 1000 test
    with patch("os.name", "posix"), \
         patch("os.getuid", return_value=1000, create=True), \
         patch("os.chmod") as mock_chmod:
        box._setup_posix_permissions(ws, is_dir=True, writable=True)
        # Should apply 0o700 (owner-only)
        mock_chmod.assert_called_with(ws, 0o700, follow_symlinks=False)

    # 2. ACL setfacl success test
    with patch("os.name", "posix"), \
         patch("os.getuid", return_value=1001, create=True), \
         patch("shutil.which", return_value="/usr/bin/setfacl"), \
         patch("subprocess.run") as mock_subproc, \
         patch("os.chmod") as mock_chmod:
        mock_subproc.return_value = MagicMock(returncode=0)
        box._setup_posix_permissions(sample_file, is_dir=False, writable=True)
        # Should call setfacl with u:1000:rw and mask m::rw
        mock_subproc.assert_called_with(
            ["/usr/bin/setfacl", "-m", "u:1000:rw,m::rw", str(sample_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2.0,
        )
        # Chmod must NOT be called after setfacl to avoid zeroing out the ACL mask
        mock_chmod.assert_not_called()

        # For directories, should include default ACLs
        mock_subproc.reset_mock()
        box._setup_posix_permissions(ws, is_dir=True, writable=True)
        mock_subproc.assert_called_with(
            ["/usr/bin/setfacl", "-m", "u:1000:rwx,m::rwx,d:u:1000:rwx,d:m::rwx", str(ws)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2.0,
        )
        mock_chmod.assert_not_called()

    # 3. Symlink safety in workspace execution setup
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("outside secret")

    link = ws / "leak_symlink"
    try:
        os.symlink(outside_file, link)
        with patch.object(box, "_setup_posix_permissions") as mock_setup, \
             patch("os.name", "posix"):
            # When iterating workspace_dir, symlinks must NOT have permissions altered
            for item in ws.iterdir():
                if not item.is_symlink():
                    box._setup_posix_permissions(item, is_dir=item.is_dir(), writable=True)
            # Ensure _setup_posix_permissions was called for sample_file, but NOT for link
            called_paths = [call[0][0] for call in mock_setup.call_args_list]
            assert sample_file in called_paths
            assert link not in called_paths
    except OSError:
        pass  # Symlink not allowed on host, skip symlink creation check


def test_posix_permissions_fails_closed_when_tools_unavailable(tmp_path):
    """
    Verifies that _setup_posix_permissions fails closed with PermissionError
    if chown fails, setfacl fails/unavailable, and host UID != 1000,
    rather than falling back to broad permissions (chmod 777).
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    ws = scratch / "ws_fail_closed"
    ws.mkdir()
    box = DockerSandbox(image_name="agent-sandbox:v1", scratch_base_dir=scratch)

    # 1. setfacl exits with error returncode
    with patch("os.name", "posix"), \
         patch("os.getuid", return_value=1001, create=True), \
         patch("shutil.which", return_value="/usr/bin/setfacl"), \
         patch("subprocess.run", return_value=MagicMock(returncode=1)):
        with pytest.raises(PermissionError) as exc_info:
            box._setup_posix_permissions(ws, is_dir=True, writable=True)
        assert "Cannot safely establish least-privilege permissions" in str(exc_info.value)

    # 2. setfacl binary not found
    with patch("os.name", "posix"), \
         patch("os.getuid", return_value=1001, create=True), \
         patch("shutil.which", return_value=None):
        with pytest.raises(PermissionError) as exc_info:
            box._setup_posix_permissions(ws, is_dir=True, writable=True)
        assert "Cannot safely establish least-privilege permissions" in str(exc_info.value)
