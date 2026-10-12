"""
Deterministic Execution Runner.
Coordinates compilation, sandboxed subprocess execution, timeout guards,
and structured output parsing across all supported languages.
"""

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, Optional, Tuple
import psutil

from agent.core.models import (
    SupportedLanguage,
    ProblemSpec,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
    TestCaseResult,
)
from agent.execution.base import BaseLanguageAdapter
from agent.execution.python_adapter import PythonAdapter
from agent.execution.java_adapter import JavaAdapter
from agent.execution.c_cpp_adapters import CppAdapter, CAdapter


class ExecutionRunner:
    """
    Language-agnostic execution orchestrator.
    Manages adapters, workspace creation, timeouts, process trees, and output extraction.
    """

    def __init__(self, timeout_seconds: float = 3.0, max_memory_mb: int = 256):
        self.timeout_seconds = timeout_seconds
        self.max_memory_mb = max_memory_mb
        self._adapters: Dict[SupportedLanguage, BaseLanguageAdapter] = {
            SupportedLanguage.PYTHON: PythonAdapter(),
            SupportedLanguage.CPP: CppAdapter(),
            SupportedLanguage.C: CAdapter(),
            SupportedLanguage.JAVA: JavaAdapter(),
        }

    def register_adapter(self, adapter: BaseLanguageAdapter) -> None:
        """Allows registering or overriding a language adapter dynamically."""
        self._adapters[adapter.language] = adapter

    def get_adapter(self, language: SupportedLanguage) -> BaseLanguageAdapter:
        if language not in self._adapters:
            raise ValueError(f"No adapter registered for language: {language}")
        return self._adapters[language]

    def run(
        self,
        problem: ProblemSpec,
        solution_code: str,
        language: SupportedLanguage = SupportedLanguage.PYTHON,
        override_timeout_sec: Optional[float] = None,
    ) -> ExecutionResult:
        """
        Executes solution against problem test suite with deterministic result capture.
        """
        timeout = override_timeout_sec or self.timeout_seconds
        adapter = self.get_adapter(language)

        # 1. Check Toolchain Availability
        if not adapter.is_toolchain_available():
            return ExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                error_detail=f"Compiler or interpreter toolchain for {language.value} is not installed or not in PATH.",
            )

        # 2. Prepare Isolated Temporary Execution Directory
        with tempfile.TemporaryDirectory(prefix=f"exec_{language.value}_", ignore_cleanup_errors=True) as temp_dir_str:
            work_dir = Path(temp_dir_str)
            source_file = work_dir / f"harness{adapter.source_extension}"

            # 3. Generate Test Harness
            try:
                harness_code = adapter.generate_harness(
                    problem=problem,
                    solution_code=solution_code,
                    test_cases=problem.test_cases,
                )
                source_file.write_text(harness_code, encoding="utf-8")
            except Exception as e:
                return ExecutionResult(
                    status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                    failure_category=FailureCategory.FORMAT_ERROR,
                    error_detail=f"Failed to generate test harness: {str(e)}",
                )

            # 4. Compile (if static compilation language)
            compile_result = adapter.compile(source_file, work_dir)
            if compile_result is not None:
                # Compilation failed or returned infrastructure error
                return compile_result

            # 5. Build Subprocess Execution Command
            run_cmd = adapter.get_run_command(source_file, work_dir)

            # 6. Execute Subprocess with Timeout and Tree-Kill Guard
            exec_res = self._execute_process(run_cmd, work_dir, timeout)
            return exec_res

    def _execute_process(
        self,
        cmd: list,
        cwd: Path,
        timeout_sec: float,
    ) -> ExecutionResult:
        """
        Spawns a process with wall-clock timeout and process-tree termination.
        Captures exit codes, stdout, stderr, and extracts structured test results.
        """
        # Clean sanitized environment: Strip API keys, tokens, AWS keys, credentials
        safe_env = {}
        # Only pass basic path and system essentials needed to run the interpreter/JVM
        for essential in ("PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
            if essential in os.environ:
                safe_env[essential] = os.environ[essential]

        start_time = time.perf_counter()
        process = None

        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=safe_env,
            )

            stdout, stderr = process.communicate(timeout=timeout_sec)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            exit_code = process.returncode

            # Check for Python/interpreter SyntaxError in stderr
            if exit_code != 0 and ("SyntaxError" in stderr or "IndentationError" in stderr):
                return ExecutionResult(
                    status=ExecutionStatus.COMPILE_ERROR,
                    failure_category=FailureCategory.COMPILE_ERROR,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    execution_time_ms=elapsed_ms,
                    error_detail=stderr.strip(),
                )

            # Parse harness output
            test_results, all_passed = self._parse_harness_output(stdout)

            if test_results is not None:
                if all_passed:
                    return ExecutionResult(
                        status=ExecutionStatus.SUCCESS,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                        execution_time_ms=elapsed_ms,
                        test_results=test_results,
                    )
                else:
                    return ExecutionResult(
                        status=ExecutionStatus.WRONG_ANSWER,
                        failure_category=FailureCategory.WRONG_ANSWER,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                        execution_time_ms=elapsed_ms,
                        test_results=test_results,
                    )

            # If no harness payload was produced and exit_code != 0, it is a Runtime Error
            if exit_code != 0:
                return ExecutionResult(
                    status=ExecutionStatus.RUNTIME_ERROR,
                    failure_category=FailureCategory.RUNTIME_ERROR,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    execution_time_ms=elapsed_ms,
                    error_detail=stderr.strip() or stdout.strip(),
                )

            # Empty output without results marker
            return ExecutionResult(
                status=ExecutionStatus.RUNTIME_ERROR,
                failure_category=FailureCategory.EMPTY_OUTPUT,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                execution_time_ms=elapsed_ms,
                error_detail="Process completed but test harness output markers were missing.",
            )

        except subprocess.TimeoutExpired:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            self._kill_process_tree(process)
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT,
                failure_category=FailureCategory.TIME_LIMIT_EXCEEDED,
                exit_code=-1,
                stdout="",
                stderr=f"Execution timed out after {timeout_sec} seconds.",
                execution_time_ms=elapsed_ms,
                error_detail=f"Time limit of {timeout_sec}s exceeded.",
            )
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            if process:
                self._kill_process_tree(process)
            return ExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                execution_time_ms=elapsed_ms,
                error_detail=f"Subprocess runner failed: {str(e)}\n{tb}",
            )

    def _kill_process_tree(self, process: Optional[subprocess.Popen]) -> None:
        """Gracefully and deterministically terminates the process and all child processes."""
        if not process:
            return
        try:
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            parent.kill()
            # Wait up to 1 second for Windows to release file handles
            parent.wait(timeout=1.0)
        except (psutil.NoSuchProcess, Exception):
            try:
                process.kill()
                process.wait(timeout=1.0)
            except Exception:
                pass

    def _parse_harness_output(self, stdout: str) -> Tuple[Optional[list], bool]:
        """Extracts JSON payload wrapped between <<<EXECUTION_RESULTS_START>>> and <<<EXECUTION_RESULTS_END>>>"""
        pattern = r"<<<EXECUTION_RESULTS_START>>>\s*(.*?)\s*<<<EXECUTION_RESULTS_END>>>"
        match = re.search(pattern, stdout, re.DOTALL)
        if not match:
            return None, False

        raw_json = match.group(1).strip()
        try:
            data = json.loads(raw_json)
            raw_results = data.get("results", [])
            all_passed = data.get("all_passed", False)
            results = [TestCaseResult(**r) for r in raw_results]
            return results, all_passed
        except Exception:
            return None, False
