"""
Storage Interface for Persistent Memory Subsystem.
Defines abstract persistence contracts so the storage backend (SQLite, Postgres, etc.)
can be swapped without rewriting the agent or memory services.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from agent.core.models import DSAPattern, FailureCategory, SupportedLanguage
from agent.memory.models import (
    ExperienceRecord,
    FailureMemoryRecord,
    PatternKnowledgeRecord,
    ProblemMemoryRecord,
    RepairMemoryRecord,
    SolutionMemoryRecord,
)


class BaseMemoryStore(ABC):
    """Abstract Repository Interface for Persistent DSA Memory."""

    @abstractmethod
    def initialize(self) -> None:
        """Initializes tables, indexes, and schema idempotently."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Safely closes connections and releases database resources."""
        pass

    # --- PROBLEM REPOSITORY ---
    @abstractmethod
    def save_problem(self, problem: ProblemMemoryRecord) -> None:
        """Saves or updates a problem record."""
        pass

    @abstractmethod
    def get_problem(self, problem_id: str) -> Optional[ProblemMemoryRecord]:
        """Retrieves a problem record by problem_id."""
        pass

    @abstractmethod
    def find_problems_by_pattern(self, pattern: DSAPattern, limit: int = 10) -> List[ProblemMemoryRecord]:
        """Retrieves problems tagged with the specified DSA pattern."""
        pass

    # --- SOLUTION REPOSITORY ---
    @abstractmethod
    def save_solution(self, solution: SolutionMemoryRecord) -> None:
        """Saves a candidate or verified solution record."""
        pass

    @abstractmethod
    def get_solution(self, solution_id: str) -> Optional[SolutionMemoryRecord]:
        """Retrieves a specific solution by solution_id."""
        pass

    @abstractmethod
    def get_solutions_for_problem(
        self,
        problem_id: str,
        only_verified: bool = False,
        language: Optional[SupportedLanguage] = None,
        limit: int = 10,
    ) -> List[SolutionMemoryRecord]:
        """Retrieves solutions for a problem, optionally filtered by language or verification."""
        pass

    @abstractmethod
    def get_latest_verified_solution(
        self,
        problem_id: str,
        language: Optional[SupportedLanguage] = None,
    ) -> Optional[SolutionMemoryRecord]:
        """Retrieves the most recent verified solution for a problem."""
        pass

    # --- FAILURE REPOSITORY ---
    @abstractmethod
    def save_failure(self, failure: FailureMemoryRecord) -> None:
        """Saves a failure attempt."""
        pass

    @abstractmethod
    def get_failures_for_problem(
        self,
        problem_id: str,
        limit: int = 10,
    ) -> List[FailureMemoryRecord]:
        """Retrieves historical failures for a problem."""
        pass

    @abstractmethod
    def get_failures_by_category(
        self,
        category: FailureCategory,
        limit: int = 10,
    ) -> List[FailureMemoryRecord]:
        """Retrieves historical failures belonging to a specific failure category."""
        pass

    # --- REPAIR REPOSITORY ---
    @abstractmethod
    def save_repair(self, repair: RepairMemoryRecord) -> None:
        """Saves a successful repair event."""
        pass

    @abstractmethod
    def get_repairs_for_problem(
        self,
        problem_id: str,
        limit: int = 10,
    ) -> List[RepairMemoryRecord]:
        """Retrieves historical successful repairs for a problem."""
        pass

    @abstractmethod
    def get_repairs_for_failure_category(
        self,
        category: FailureCategory,
        limit: int = 10,
    ) -> List[RepairMemoryRecord]:
        """Retrieves historical successful repairs resolving a specific failure category."""
        pass

    # --- PATTERN KNOWLEDGE REPOSITORY ---
    @abstractmethod
    def save_pattern_knowledge(self, knowledge: PatternKnowledgeRecord) -> None:
        """Saves or updates reusable pattern knowledge."""
        pass

    @abstractmethod
    def get_pattern_knowledge(self, pattern: DSAPattern) -> Optional[PatternKnowledgeRecord]:
        """Retrieves pattern knowledge for a DSA pattern."""
        pass

    # --- EXPERIENCE REPOSITORY (STAGE 20) ---
    @abstractmethod
    def save_experience(self, experience: "ExperienceRecord") -> None:
        """Saves or updates a structured experience record."""
        pass

    @abstractmethod
    def get_experience(self, experience_id: str) -> Optional["ExperienceRecord"]:
        """Retrieves an experience record by experience_id."""
        pass

    @abstractmethod
    def find_experiences_by_pattern(
        self,
        pattern: DSAPattern,
        only_verified: bool = False,
        limit: int = 10,
    ) -> List["ExperienceRecord"]:
        """Retrieves experiences for a given DSA pattern."""
        pass

    @abstractmethod
    def list_all_experiences(
        self,
        only_verified: bool = False,
        limit: int = 100,
    ) -> List["ExperienceRecord"]:
        """Lists stored experiences ordered by recency."""
        pass

