"""
Integration Tests for DockerSandbox Backend (Stage 2).

These tests run real container operations against an active Docker daemon.
If Docker, Linux containers, or the configured image are not available in the current
environment (e.g. running locally on Windows without Docker Desktop, or CI without daemon),
these tests are explicitly marked and SKIPPED rather than mocked, ensuring no false positives.

Tests verify:
1. Multi-language toolchain compilation & execution:
   - C program (gcc compile + execute)
   - C++ program (g++ compile + execute)
   - Python program (python3 execution)
   - Java program (javac compile + java execute)
2. Network connectivity failure (verifying socket connection cannot escape --network none).
3. Read-only filesystem behavior (verifying write to root / or /etc fails).
4. Controlled process limit enforcement (verifying pids-limit prevents creating excessive threads/processes).
5. Output flooding limit (verifying excess bytes beyond budget are discarded).
6. Execution timeout and container cleanup.
"""

import os
import pytest
from pathlib import Path

from agent.core.models import ExecutionStatus, FailureCategory
from agent.execution.sandbox.docker import DEFAULT_SANDBOX_IMAGE, DockerSandbox
from agent.execution.sandbox.models import ResourceLimits, SandboxPolicy


# Environment variables to support pinned image identity in CI or local verification
IMAGE_NAME = os.environ.get("AGENT_SANDBOX_IMAGE", DEFAULT_SANDBOX_IMAGE).strip()
EXPECTED_IMAGE_ID = os.environ.get("AGENT_SANDBOX_EXPECTED_IMAGE_ID", "").strip() or None
EXPECTED_DIGEST = os.environ.get("AGENT_SANDBOX_EXPECTED_DIGEST", "").strip() or None
REQUIRE_DOCKER = os.environ.get("REQUIRE_DOCKER", "0").lower() in ("1", "true", "yes")

# Check availability once at test module load
_sandbox_probe = DockerSandbox(
    image_name=IMAGE_NAME,
    expected_image_id=EXPECTED_IMAGE_ID,
    expected_digest=EXPECTED_DIGEST,
)
_docker_is_available = _sandbox_probe.is_available()

# If REQUIRE_DOCKER is set, Docker must be available and identity valid, otherwise fail fast
if REQUIRE_DOCKER and not _docker_is_available:
    pytest.fail(
        f"Docker integration tests required (REQUIRE_DOCKER=1) but DockerSandbox is unavailable or image identity mismatch. "
        f"Image='{IMAGE_NAME}', expected_image_id='{EXPECTED_IMAGE_ID}', expected_digest='{EXPECTED_DIGEST}'."
    )

pytestmark = pytest.mark.skipif(
    not _docker_is_available,
    reason=f"Docker daemon or '{IMAGE_NAME}' Linux image unavailable in current environment",
)


@pytest.fixture
def sandbox(tmp_path):
    # Configure sandbox with dedicated scratch root in tmp_path
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    return DockerSandbox(
        image_name=IMAGE_NAME,
        expected_image_id=EXPECTED_IMAGE_ID,
        expected_digest=EXPECTED_DIGEST,
        scratch_base_dir=scratch_dir,
    )


def test_real_container_python_execution(sandbox):
    """Verifies standard benign Python execution produces expected output and exit code 0."""
    ws = sandbox.create_private_workspace()
    script_file = ws / "solution.py"
    script_file.write_text("print('sandbox_py_success_42')\n")

    policy = SandboxPolicy()
    result = sandbox.execute(
        command=["python3", "solution.py"],
        workspace_dir=ws,
        policy=policy,
    )

    assert result.status == ExecutionStatus.SUCCESS
    assert result.exit_code == 0
    assert "sandbox_py_success_42" in result.stdout
    assert result.output_truncated is False


def test_real_container_c_compilation_and_execution(sandbox):
    """Verifies C compilation with gcc and subsequent binary execution inside the container."""
    ws = sandbox.create_private_workspace()
    src_file = ws / "solution.c"
    src_file.write_text(
        "#include <stdio.h>\n"
        "int main() {\n"
        "    printf(\"sandbox_c_success_101\\n\");\n"
        "    return 0;\n"
        "}\n"
    )

    policy = SandboxPolicy()
    # 1. Compile
    compile_res = sandbox.execute(
        command=["gcc", "-O2", "solution.c", "-o", "solution_c"],
        workspace_dir=ws,
        policy=policy,
    )
    assert compile_res.status == ExecutionStatus.SUCCESS
    assert compile_res.exit_code == 0

    # 2. Run
    run_res = sandbox.execute(
        command=["./solution_c"],
        workspace_dir=ws,
        policy=policy,
    )
    assert run_res.status == ExecutionStatus.SUCCESS
    assert run_res.exit_code == 0
    assert "sandbox_c_success_101" in run_res.stdout


def test_real_container_cpp_compilation_and_execution(sandbox):
    """Verifies C++ compilation with g++ and subsequent binary execution inside the container."""
    ws = sandbox.create_private_workspace()
    src_file = ws / "solution.cpp"
    src_file.write_text(
        "#include <iostream>\n"
        "int main() {\n"
        "    std::cout << \"sandbox_cpp_success_202\" << std::endl;\n"
        "    return 0;\n"
        "}\n"
    )

    policy = SandboxPolicy()
    # 1. Compile
    compile_res = sandbox.execute(
        command=["g++", "-O2", "-std=c++17", "solution.cpp", "-o", "solution_cpp"],
        workspace_dir=ws,
        policy=policy,
    )
    assert compile_res.status == ExecutionStatus.SUCCESS
    assert compile_res.exit_code == 0

    # 2. Run
    run_res = sandbox.execute(
        command=["./solution_cpp"],
        workspace_dir=ws,
        policy=policy,
    )
    assert run_res.status == ExecutionStatus.SUCCESS
    assert run_res.exit_code == 0
    assert "sandbox_cpp_success_202" in run_res.stdout


def test_real_container_java_compilation_and_execution(sandbox):
    """Verifies Java compilation with javac and JVM execution inside the container."""
    ws = sandbox.create_private_workspace()
    src_file = ws / "Solution.java"
    src_file.write_text(
        "public class Solution {\n"
        "    public static void main(String[] args) {\n"
        "        System.out.println(\"sandbox_java_success_303\");\n"
        "    }\n"
        "}\n"
    )

    policy = SandboxPolicy()
    # 1. Compile
    compile_res = sandbox.execute(
        command=["javac", "Solution.java"],
        workspace_dir=ws,
        policy=policy,
    )
    assert compile_res.status == ExecutionStatus.SUCCESS
    assert compile_res.exit_code == 0

    # 2. Run
    run_res = sandbox.execute(
        command=["java", "Solution"],
        workspace_dir=ws,
        policy=policy,
    )
    assert run_res.status == ExecutionStatus.SUCCESS
    assert run_res.exit_code == 0
    assert "sandbox_java_success_303" in run_res.stdout


def test_real_container_network_isolation(sandbox):
    """
    Verifies that container cannot establish outward network connections.
    Attempts to connect to a well-known public IP/port (1.1.1.1:80) with a 2-second timeout.
    """
    ws = sandbox.create_private_workspace()
    script_file = ws / "test_net.py"
    script_file.write_text(
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.settimeout(2.0)\n"
        "try:\n"
        "    s.connect(('1.1.1.1', 80))\n"
        "    print('CONNECTED')\n"
        "except Exception as e:\n"
        "    print(f'NETWORK_BLOCKED: {e}')\n"
    )

    policy = SandboxPolicy(allow_network=False)
    result = sandbox.execute(
        command=["python3", "test_net.py"],
        workspace_dir=ws,
        policy=policy,
    )

    assert result.status == ExecutionStatus.SUCCESS
    assert "NETWORK_BLOCKED" in result.stdout
    assert "CONNECTED" not in result.stdout


def test_real_container_read_only_root_filesystem(sandbox):
    """Verifies that attempts to write outside the mounted workspace fail with Read-only file system."""
    ws = sandbox.create_private_workspace()
    script_file = ws / "test_ro.py"
    script_file.write_text(
        "try:\n"
        "    with open('/etc/untrusted_write.txt', 'w') as f:\n"
        "        f.write('bad')\n"
        "    print('WRITTEN')\n"
        "except OSError as e:\n"
        "    print(f'READ_ONLY_ENFORCED: {e}')\n"
    )

    policy = SandboxPolicy(read_only_root_fs=True)
    result = sandbox.execute(
        command=["python3", "test_ro.py"],
        workspace_dir=ws,
        policy=policy,
    )

    assert result.status == ExecutionStatus.SUCCESS
    assert "READ_ONLY_ENFORCED" in result.stdout
    assert "WRITTEN" not in result.stdout


def test_real_container_controlled_process_limit(sandbox):
    """
    Verifies process count (pids-limit) bounds prevent spawning unbounded child processes.
    Uses a controlled test that spawns 25 processes when the limit is set to 8.
    """
    ws = sandbox.create_private_workspace()
    script_file = ws / "test_proc.py"
    script_file.write_text(
        "import multiprocessing, time\n"
        "def worker():\n"
        "    time.sleep(1)\n"
        "if __name__ == '__main__':\n"
        "    procs = []\n"
        "    try:\n"
        "        for i in range(25):\n"
        "            p = multiprocessing.Process(target=worker)\n"
        "            p.start()\n"
        "            procs.append(p)\n"
        "        print('ALL_SPAWNED')\n"
        "    except Exception as e:\n"
        "        print(f'PID_LIMIT_TRIGGERED: {e}')\n"
        "    finally:\n"
        "        for p in procs: p.join()\n"
    )

    policy = SandboxPolicy(
        resources=ResourceLimits(max_processes=8, timeout_seconds=10.0)
    )
    result = sandbox.execute(
        command=["python3", "test_proc.py"],
        workspace_dir=ws,
        policy=policy,
    )

    # Either Python catches the process creation failure or the container process fails
    assert "ALL_SPAWNED" not in result.stdout


def test_real_container_output_flooding(sandbox):
    """Verifies that an infinite/high-volume print loop is safely bounded by max_output_bytes."""
    ws = sandbox.create_private_workspace()
    script_file = ws / "flood.py"
    script_file.write_text(
        "for i in range(50000):\n"
        "    print('FLOOD_OUTPUT_BYTE_PADDING_1234567890')\n"
    )

    budget = 4096
    policy = SandboxPolicy(
        resources=ResourceLimits(max_output_bytes=budget, timeout_seconds=10.0)
    )
    result = sandbox.execute(
        command=["python3", "flood.py"],
        workspace_dir=ws,
        policy=policy,
    )

    assert result.output_truncated is True
    # The output captured in stdout should not exceed the max_output_bytes limit
    assert len(result.stdout.encode("utf-8")) <= budget + 512  # tolerance for chunk boundary


def test_real_container_timeout_and_cleanup(sandbox):
    """Verifies that a command exceeding timeout is terminated and TIMEOUT status returned."""
    ws = sandbox.create_private_workspace()
    script_file = ws / "hang.py"
    script_file.write_text("import time\ntime.sleep(10)\n")

    policy = SandboxPolicy(
        resources=ResourceLimits(timeout_seconds=0.5)
    )
    result = sandbox.execute(
        command=["python3", "hang.py"],
        workspace_dir=ws,
        policy=policy,
    )

    assert result.status == ExecutionStatus.TIMEOUT
    assert result.timed_out is True
    assert result.failure_category == FailureCategory.TIME_LIMIT_EXCEEDED


def test_real_container_non_root_execution(sandbox):
    """Verifies that the container runs under non-root UID/GID (1000:1000 by default)."""
    ws = sandbox.create_private_workspace()
    script_file = ws / "whoami_check.py"
    script_file.write_text(
        "import os\n"
        "uid = os.getuid()\n"
        "gid = os.getgid()\n"
        "print(f'UID={uid},GID={gid}')\n"
    )

    policy = SandboxPolicy(run_as_user="1000:1000")
    result = sandbox.execute(
        command=["python3", "whoami_check.py"],
        workspace_dir=ws,
        policy=policy,
    )

    assert result.status == ExecutionStatus.SUCCESS
    assert result.exit_code == 0
    assert "UID=1000,GID=1000" in result.stdout
    assert "UID=0" not in result.stdout


def test_real_container_workspace_write_access(sandbox):
    """Verifies that writes inside the designated workspace succeed, but writes in ro-mode fail."""
    ws = sandbox.create_private_workspace()
    script_file = ws / "test_ws_write.py"
    script_file.write_text(
        "with open('/workspace/output.txt', 'w') as f:\n"
        "    f.write('workspace_write_ok')\n"
        "print('FILE_WRITTEN')\n"
    )

    # 1. Default policy: workspace_read_write=True
    rw_policy = SandboxPolicy(workspace_read_write=True)
    res_rw = sandbox.execute(
        command=["python3", "test_ws_write.py"],
        workspace_dir=ws,
        policy=rw_policy,
    )
    assert res_rw.status == ExecutionStatus.SUCCESS
    assert "FILE_WRITTEN" in res_rw.stdout
    assert (ws / "output.txt").read_text() == "workspace_write_ok"

    # 2. workspace_read_write=False
    script_ro = ws / "test_ws_ro.py"
    script_ro.write_text(
        "try:\n"
        "    with open('/workspace/output_ro.txt', 'w') as f:\n"
        "        f.write('fail')\n"
        "    print('WRITTEN')\n"
        "except OSError as e:\n"
        "    print(f'WS_RO_ENFORCED: {e}')\n"
    )
    ro_policy = SandboxPolicy(workspace_read_write=False)
    res_ro = sandbox.execute(
        command=["python3", "test_ws_ro.py"],
        workspace_dir=ws,
        policy=ro_policy,
    )
    assert res_ro.status == ExecutionStatus.SUCCESS
    assert "WS_RO_ENFORCED" in res_ro.stdout
    assert "WRITTEN" not in res_ro.stdout


def test_real_container_memory_limit_oom(sandbox):
    """Verifies cgroup memory quota terminates allocations exceeding max_memory_mb."""
    ws = sandbox.create_private_workspace()
    script_file = ws / "oom_alloc.py"
    # Allocate 100MB chunk when limit is set to 32MB
    script_file.write_text(
        "chunks = []\n"
        "for _ in range(100):\n"
        "    chunks.append(b'X' * (1024 * 1024))\n"
        "print('ALLOC_SUCCEEDED')\n"
    )

    policy = SandboxPolicy(
        resources=ResourceLimits(max_memory_mb=32, timeout_seconds=10.0)
    )
    result = sandbox.execute(
        command=["python3", "oom_alloc.py"],
        workspace_dir=ws,
        policy=policy,
    )

    # Process must not complete cleanly
    assert "ALLOC_SUCCEEDED" not in result.stdout
    # Exit code 137 (SIGKILL/OOM) or MemoryError
    assert (
        result.exit_code == 137
        or result.failure_category == FailureCategory.MEMORY_LIMIT_EXCEEDED
        or result.status == ExecutionStatus.RUNTIME_ERROR
    )


def test_real_container_removed_after_execution(sandbox):
    """Verifies container is purged and does not linger in docker ps -a."""
    import subprocess
    import shutil

    docker_bin = shutil.which("docker")
    if not docker_bin:
        pytest.skip("Docker CLI not available on host")

    ws = sandbox.create_private_workspace()
    script_file = ws / "noop.py"
    script_file.write_text("print('noop_done')\n")

    result = sandbox.execute(
        command=["python3", "noop.py"],
        workspace_dir=ws,
        policy=SandboxPolicy(),
    )
    assert result.status == ExecutionStatus.SUCCESS

    # Verify no managed sandbox containers are left running or stopped
    ps_res = subprocess.run(
        [docker_bin, "ps", "-a", "--filter", "label=agent.sandbox.managed=true", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    assert ps_res.returncode == 0
    remaining_names = [line.strip() for line in ps_res.stdout.splitlines() if line.strip()]
    assert len(remaining_names) == 0, f"Found lingering sandbox containers: {remaining_names}"

