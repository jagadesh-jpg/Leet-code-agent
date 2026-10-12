"""
Language Adapter Base Interface.
Defines the required contract for executing code across C, C++, Java, and Python.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional
from agent.core.models import (
    SupportedLanguage,
    ProblemSpec,
    TestCase,
    ExecutionResult,
)


class BaseLanguageAdapter(ABC):
    """
    Abstract interface for language-specific compilation and test execution.
    Concrete subclasses implement language semantics for Python, C++, C, Java.
    """

    @property
    @abstractmethod
    def language(self) -> SupportedLanguage:
        """Returns the supported language enum."""
        pass

    @property
    @abstractmethod
    def source_extension(self) -> str:
        """File extension including dot (e.g. '.py', '.cpp', '.java', '.c')."""
        pass

    @abstractmethod
    def is_toolchain_available(self) -> bool:
        """Checks if the required compiler or interpreter exists on the system."""
        pass

    @abstractmethod
    def generate_harness(
        self,
        problem: ProblemSpec,
        solution_code: str,
        test_cases: List[TestCase],
    ) -> str:
        """
        Synthesizes executable source code combining the solution with a deterministic
        test runner that feeds inputs and captures outputs in structured JSON.
        """
        pass

    @abstractmethod
    def compile(self, source_path: Path, output_dir: Path) -> Optional[ExecutionResult]:
        """
        Compiles the source code if required by the language.
        Returns None if compilation is not applicable (e.g. Python),
        or ExecutionResult with status COMPILE_ERROR if compilation failed.
        """
        pass

    @abstractmethod
    def get_run_command(self, source_or_binary_path: Path, output_dir: Path) -> List[str]:
        """Returns command list to execute the compiled binary or script."""
        pass
