"""
Stub Adapters for C, C++, and Java.
Implements BaseLanguageAdapter for toolchain detection and execution hooks.
"""

import shutil
from pathlib import Path
from typing import List, Optional
from agent.core.models import (
    SupportedLanguage,
    ProblemSpec,
    TestCase,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
)
from agent.execution.base import BaseLanguageAdapter


class CppAdapter(BaseLanguageAdapter):
    """C++ execution adapter supporting GCC, Clang, or MSVC."""

    @property
    def language(self) -> SupportedLanguage:
        return SupportedLanguage.CPP

    @property
    def source_extension(self) -> str:
        return ".cpp"

    def is_toolchain_available(self) -> bool:
        return (
            shutil.which("g++") is not None
            or shutil.which("clang++") is not None
            or shutil.which("cl") is not None
        )

    def generate_harness(
        self,
        problem: ProblemSpec,
        solution_code: str,
        test_cases: List[TestCase],
    ) -> str:
        # Structured C++ harness template placeholder adhering to interface
        return f"// C++ Test Harness for {problem.title}\n{solution_code}\n"

    def compile(self, source_path: Path, output_dir: Path) -> Optional[ExecutionResult]:
        if not self.is_toolchain_available():
            return ExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                error_detail="C++ compiler (g++, clang++, or cl) not found in system PATH.",
            )
        return None

    def get_run_command(self, source_or_binary_path: Path, output_dir: Path) -> List[str]:
        return [str(source_or_binary_path)]


class CAdapter(BaseLanguageAdapter):
    """C execution adapter supporting GCC, Clang, or MSVC."""

    @property
    def language(self) -> SupportedLanguage:
        return SupportedLanguage.C

    @property
    def source_extension(self) -> str:
        return ".c"

    def is_toolchain_available(self) -> bool:
        return (
            shutil.which("gcc") is not None
            or shutil.which("clang") is not None
            or shutil.which("cl") is not None
        )

    def generate_harness(
        self,
        problem: ProblemSpec,
        solution_code: str,
        test_cases: List[TestCase],
    ) -> str:
        return f"/* C Test Harness for {problem.title} */\n{solution_code}\n"

    def compile(self, source_path: Path, output_dir: Path) -> Optional[ExecutionResult]:
        if not self.is_toolchain_available():
            return ExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                error_detail="C compiler (gcc, clang, or cl) not found in system PATH.",
            )
        return None

    def get_run_command(self, source_or_binary_path: Path, output_dir: Path) -> List[str]:
        return [str(source_or_binary_path)]


class JavaAdapter(BaseLanguageAdapter):
    """Java execution adapter supporting JDK (javac/java)."""

    @property
    def language(self) -> SupportedLanguage:
        return SupportedLanguage.JAVA

    @property
    def source_extension(self) -> str:
        return ".java"

    def is_toolchain_available(self) -> bool:
        return (
            shutil.which("javac") is not None
            and shutil.which("java") is not None
        )

    def generate_harness(
        self,
        problem: ProblemSpec,
        solution_code: str,
        test_cases: List[TestCase],
    ) -> str:
        return f"// Java Test Harness for {problem.title}\n{solution_code}\n"

    def compile(self, source_path: Path, output_dir: Path) -> Optional[ExecutionResult]:
        if not self.is_toolchain_available():
            return ExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                error_detail="Java SDK (javac or java) not found in system PATH.",
            )
        return None

    def get_run_command(self, source_or_binary_path: Path, output_dir: Path) -> List[str]:
        return ["java", "-cp", str(output_dir), "SolutionHarness"]
