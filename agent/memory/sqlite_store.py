"""
SQLite Implementation of Persistent Memory Store.
Provides deterministic relational persistence with foreign keys, indexes, transactions,
safe parameter binding (no SQL injection), and automatic restart survival.
Does NOT store secrets or API keys.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import List, Optional

from agent.core.models import (
    Difficulty,
    DSAPattern,
    FailureCategory,
    FailureReport,
    FinalVerificationReport,
    SupportedLanguage,
    VerificationStatus,
)
from agent.memory.models import (
    ExperienceRecord,
    FailureMemoryRecord,
    PatternKnowledgeRecord,
    ProblemMemoryRecord,
    RepairMemoryRecord,
    SolutionMemoryRecord,
)
from agent.memory.repository import BaseMemoryStore


class SQLiteMemoryStore(BaseMemoryStore):
    """
    Robust SQLite persistent store for DSA problems, verified solutions, failures, and repairs.
    """

    def __init__(self, db_path: str = "agent_memory.db"):
        self.db_path = str(Path(db_path).resolve())
        # Ensure parent directory exists
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self.initialize()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            # Enforce foreign key constraints
            self._conn.execute("PRAGMA foreign_keys = ON;")
        return self._conn


    def initialize(self) -> None:
        """Creates tables, foreign keys, and indexes idempotently."""
        conn = self._get_connection()
        with conn:
            # 1. Problems table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS problems (
                problem_id TEXT PRIMARY KEY,
                title TEXT,
                description TEXT NOT NULL,
                difficulty TEXT,
                function_name TEXT,
                param_names_json TEXT NOT NULL,
                return_type TEXT,
                constraints_json TEXT NOT NULL,
                detected_patterns_json TEXT NOT NULL,
                raw_statement TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)

            # 2. Solutions table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS solutions (
                solution_id TEXT PRIMARY KEY,
                problem_id TEXT NOT NULL,
                language TEXT NOT NULL,
                source_code TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                algorithm_name TEXT,
                data_structures_json TEXT NOT NULL,
                claimed_time_complexity TEXT,
                claimed_space_complexity TEXT,
                inferred_time_complexity TEXT,
                inferred_space_complexity TEXT,
                verification_status TEXT NOT NULL,
                verification_report_json TEXT,
                is_verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (problem_id) REFERENCES problems(problem_id) ON DELETE CASCADE
            );
            """)

            # 3. Failures table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS failures (
                failure_id TEXT PRIMARY KEY,
                problem_id TEXT NOT NULL,
                attempt_number INTEGER NOT NULL,
                language TEXT NOT NULL,
                source_code TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                failure_category TEXT NOT NULL,
                likely_root_cause TEXT,
                error_message TEXT,
                affected_test_ids_json TEXT NOT NULL,
                raw_failure_report_json TEXT,
                repair_performed TEXT,
                repair_succeeded INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (problem_id) REFERENCES problems(problem_id) ON DELETE CASCADE
            );
            """)

            # 4. Repairs table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS repairs (
                repair_id TEXT PRIMARY KEY,
                problem_id TEXT NOT NULL,
                language TEXT NOT NULL,
                original_failure_category TEXT NOT NULL,
                root_cause TEXT NOT NULL,
                source_hash_before TEXT NOT NULL,
                source_code_before TEXT NOT NULL,
                source_hash_after TEXT NOT NULL,
                source_code_after TEXT NOT NULL,
                patch_summary TEXT NOT NULL,
                tests_passed_after INTEGER NOT NULL DEFAULT 0,
                tests_failed_after INTEGER NOT NULL DEFAULT 0,
                verification_status_after TEXT NOT NULL,
                regression_passed INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (problem_id) REFERENCES problems(problem_id) ON DELETE CASCADE
            );
            """)

            # 5. Pattern Knowledge table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS pattern_knowledge (
                pattern TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                common_data_structures_json TEXT NOT NULL,
                typical_time_complexity TEXT,
                typical_space_complexity TEXT,
                applicable_constraints_note TEXT,
                known_strengths_json TEXT NOT NULL,
                known_weaknesses_json TEXT NOT NULL,
                common_pitfalls_json TEXT NOT NULL,
                related_problem_ids_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)

            # 6. Experiences table (Stage 20)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS experiences (
                experience_id TEXT PRIMARY KEY,
                problem_id TEXT NOT NULL,
                problem_fingerprint TEXT NOT NULL,
                normalized_title TEXT NOT NULL,
                dsa_pattern TEXT NOT NULL,
                algorithm_name TEXT NOT NULL,
                candidate_algorithms_json TEXT NOT NULL,
                language TEXT NOT NULL,
                complexity_expected_time TEXT,
                complexity_expected_space TEXT,
                complexity_observed_time TEXT,
                complexity_observed_space TEXT,
                constraints_summary_json TEXT NOT NULL,
                status TEXT NOT NULL,
                is_verified INTEGER NOT NULL DEFAULT 0,
                failure_categories_json TEXT NOT NULL,
                failure_hypotheses_json TEXT NOT NULL,
                repair_actions_json TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 1,
                tests_passed INTEGER NOT NULL DEFAULT 0,
                tests_total INTEGER NOT NULL DEFAULT 0,
                source_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)

            # 7. Adaptive Test Evidence table (Stage 21)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS adaptive_test_evidence (
                evidence_id TEXT PRIMARY KEY,
                problem_id TEXT NOT NULL,
                test_fingerprint TEXT NOT NULL,
                category TEXT NOT NULL,
                generation_reason TEXT NOT NULL,
                risk_signal TEXT NOT NULL,
                memory_influence TEXT,
                seed INTEGER,
                passed INTEGER NOT NULL,
                error_message TEXT,
                adaptive_round INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (problem_id) REFERENCES problems(problem_id) ON DELETE CASCADE
            );
            """)

            # Indexes for efficient bounded queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_solutions_problem_verified ON solutions(problem_id, is_verified);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_solutions_language ON solutions(language);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_solutions_hash ON solutions(source_hash);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_failures_problem ON failures(problem_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_failures_category ON failures(failure_category);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_repairs_category ON repairs(original_failure_category);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_pattern ON experiences(dsa_pattern);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_fingerprint ON experiences(problem_fingerprint);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_verified ON experiences(is_verified);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_problem ON experiences(problem_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_adapt_prob ON adaptive_test_evidence(problem_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_adapt_fp ON adaptive_test_evidence(test_fingerprint);")


    def close(self) -> None:
        """Safely closes connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- PROBLEM METHODS ---
    def save_problem(self, problem: ProblemMemoryRecord) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute("""
            INSERT INTO problems (
                problem_id, title, description, difficulty, function_name,
                param_names_json, return_type, constraints_json,
                detected_patterns_json, raw_statement, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(problem_id) DO UPDATE SET
                title=excluded.title,
                description=excluded.description,
                difficulty=excluded.difficulty,
                function_name=excluded.function_name,
                param_names_json=excluded.param_names_json,
                return_type=excluded.return_type,
                constraints_json=excluded.constraints_json,
                detected_patterns_json=excluded.detected_patterns_json,
                raw_statement=excluded.raw_statement,
                updated_at=excluded.updated_at;
            """, (
                problem.problem_id,
                problem.title,
                problem.description,
                problem.difficulty.value if problem.difficulty else None,
                problem.function_name,
                json.dumps(problem.param_names),
                problem.return_type,
                json.dumps(problem.constraints),
                json.dumps([p.value for p in problem.detected_patterns]),
                problem.raw_statement,
                problem.created_at,
                problem.updated_at,
            ))

    def get_problem(self, problem_id: str) -> Optional[ProblemMemoryRecord]:
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM problems WHERE problem_id = ?;", (problem_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_problem(row)

    def find_problems_by_pattern(self, pattern: DSAPattern, limit: int = 10) -> List[ProblemMemoryRecord]:
        conn = self._get_connection()
        # Query matching JSON array containing pattern.value
        cursor = conn.execute("""
            SELECT * FROM problems
            WHERE detected_patterns_json LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?;
        """, (f"%{pattern.value}%", limit))
        return [self._row_to_problem(row) for row in cursor.fetchall()]

    # --- SOLUTION METHODS ---
    def save_solution(self, solution: SolutionMemoryRecord) -> None:
        conn = self._get_connection()
        report_json = solution.verification_report.model_dump_json() if solution.verification_report else None
        with conn:
            conn.execute("""
            INSERT INTO solutions (
                solution_id, problem_id, language, source_code, source_hash,
                algorithm_name, data_structures_json, claimed_time_complexity,
                claimed_space_complexity, inferred_time_complexity,
                inferred_space_complexity, verification_status,
                verification_report_json, is_verified, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(solution_id) DO UPDATE SET
                source_code=excluded.source_code,
                source_hash=excluded.source_hash,
                algorithm_name=excluded.algorithm_name,
                data_structures_json=excluded.data_structures_json,
                claimed_time_complexity=excluded.claimed_time_complexity,
                claimed_space_complexity=excluded.claimed_space_complexity,
                inferred_time_complexity=excluded.inferred_time_complexity,
                inferred_space_complexity=excluded.inferred_space_complexity,
                verification_status=excluded.verification_status,
                verification_report_json=excluded.verification_report_json,
                is_verified=excluded.is_verified,
                updated_at=excluded.updated_at;
            """, (
                solution.solution_id,
                solution.problem_id,
                solution.language.value,
                solution.source_code,
                solution.source_hash,
                solution.algorithm_name,
                json.dumps(solution.data_structures_used),
                solution.claimed_time_complexity,
                solution.claimed_space_complexity,
                solution.inferred_time_complexity,
                solution.inferred_space_complexity,
                solution.verification_status.value,
                report_json,
                1 if solution.is_verified else 0,
                solution.created_at,
                solution.updated_at,
            ))

    def get_solution(self, solution_id: str) -> Optional[SolutionMemoryRecord]:
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM solutions WHERE solution_id = ?;", (solution_id,))
        row = cursor.fetchone()
        return self._row_to_solution(row) if row else None

    def get_solutions_for_problem(
        self,
        problem_id: str,
        only_verified: bool = False,
        language: Optional[SupportedLanguage] = None,
        limit: int = 10,
    ) -> List[SolutionMemoryRecord]:
        conn = self._get_connection()
        query = "SELECT * FROM solutions WHERE problem_id = ?"
        params: list = [problem_id]
        if only_verified:
            query += " AND is_verified = 1"
        if language:
            query += " AND language = ?"
            params.append(language.value)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, tuple(params))
        return [self._row_to_solution(row) for row in cursor.fetchall()]

    def get_latest_verified_solution(
        self,
        problem_id: str,
        language: Optional[SupportedLanguage] = None,
    ) -> Optional[SolutionMemoryRecord]:
        results = self.get_solutions_for_problem(
            problem_id=problem_id,
            only_verified=True,
            language=language,
            limit=1,
        )
        return results[0] if results else None

    # --- FAILURE METHODS ---
    def save_failure(self, failure: FailureMemoryRecord) -> None:
        conn = self._get_connection()
        report_json = failure.raw_failure_report.model_dump_json() if failure.raw_failure_report else None
        with conn:
            conn.execute("""
            INSERT INTO failures (
                failure_id, problem_id, attempt_number, language, source_code,
                source_hash, failure_category, likely_root_cause, error_message,
                affected_test_ids_json, raw_failure_report_json, repair_performed,
                repair_succeeded, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(failure_id) DO UPDATE SET
                repair_performed=excluded.repair_performed,
                repair_succeeded=excluded.repair_succeeded;
            """, (
                failure.failure_id,
                failure.problem_id,
                failure.attempt_number,
                failure.language.value,
                failure.source_code,
                failure.source_hash,
                failure.failure_category.value,
                failure.likely_root_cause,
                failure.error_message,
                json.dumps(failure.affected_test_ids),
                report_json,
                failure.repair_performed,
                1 if failure.repair_succeeded else 0,
                failure.created_at,
            ))

    def get_failures_for_problem(
        self,
        problem_id: str,
        limit: int = 10,
    ) -> List[FailureMemoryRecord]:
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT * FROM failures
            WHERE problem_id = ?
            ORDER BY created_at DESC
            LIMIT ?;
        """, (problem_id, limit))
        return [self._row_to_failure(row) for row in cursor.fetchall()]

    def get_failures_by_category(
        self,
        category: FailureCategory,
        limit: int = 10,
    ) -> List[FailureMemoryRecord]:
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT * FROM failures
            WHERE failure_category = ?
            ORDER BY created_at DESC
            LIMIT ?;
        """, (category.value, limit))
        return [self._row_to_failure(row) for row in cursor.fetchall()]

    # --- REPAIR METHODS ---
    def save_repair(self, repair: RepairMemoryRecord) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute("""
            INSERT INTO repairs (
                repair_id, problem_id, language, original_failure_category,
                root_cause, source_hash_before, source_code_before,
                source_hash_after, source_code_after, patch_summary,
                tests_passed_after, tests_failed_after, verification_status_after,
                regression_passed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(repair_id) DO NOTHING;
            """, (
                repair.repair_id,
                repair.problem_id,
                repair.language.value,
                repair.original_failure_category.value,
                repair.root_cause,
                repair.source_hash_before,
                repair.source_code_before,
                repair.source_hash_after,
                repair.source_code_after,
                repair.patch_summary,
                repair.tests_passed_after,
                repair.tests_failed_after,
                repair.verification_status_after.value,
                1 if repair.regression_passed else 0,
                repair.created_at,
            ))

    def get_repairs_for_problem(
        self,
        problem_id: str,
        limit: int = 10,
    ) -> List[RepairMemoryRecord]:
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT * FROM repairs
            WHERE problem_id = ?
            ORDER BY created_at DESC
            LIMIT ?;
        """, (problem_id, limit))
        return [self._row_to_repair(row) for row in cursor.fetchall()]

    def get_repairs_for_failure_category(
        self,
        category: FailureCategory,
        limit: int = 10,
    ) -> List[RepairMemoryRecord]:
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT * FROM repairs
            WHERE original_failure_category = ?
            ORDER BY created_at DESC
            LIMIT ?;
        """, (category.value, limit))
        return [self._row_to_repair(row) for row in cursor.fetchall()]

    # --- PATTERN KNOWLEDGE METHODS ---
    def save_pattern_knowledge(self, knowledge: PatternKnowledgeRecord) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute("""
            INSERT INTO pattern_knowledge (
                pattern, description, common_data_structures_json,
                typical_time_complexity, typical_space_complexity,
                applicable_constraints_note, known_strengths_json,
                known_weaknesses_json, common_pitfalls_json,
                related_problem_ids_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pattern) DO UPDATE SET
                description=excluded.description,
                common_data_structures_json=excluded.common_data_structures_json,
                typical_time_complexity=excluded.typical_time_complexity,
                typical_space_complexity=excluded.typical_space_complexity,
                applicable_constraints_note=excluded.applicable_constraints_note,
                known_strengths_json=excluded.known_strengths_json,
                known_weaknesses_json=excluded.known_weaknesses_json,
                common_pitfalls_json=excluded.common_pitfalls_json,
                related_problem_ids_json=excluded.related_problem_ids_json,
                updated_at=excluded.updated_at;
            """, (
                knowledge.pattern.value,
                knowledge.description,
                json.dumps(knowledge.common_data_structures),
                knowledge.typical_time_complexity,
                knowledge.typical_space_complexity,
                knowledge.applicable_constraints_note,
                json.dumps(knowledge.known_strengths),
                json.dumps(knowledge.known_weaknesses),
                json.dumps(knowledge.common_pitfalls),
                json.dumps(knowledge.related_problem_ids),
                knowledge.updated_at,
            ))

    def get_pattern_knowledge(self, pattern: DSAPattern) -> Optional[PatternKnowledgeRecord]:
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM pattern_knowledge WHERE pattern = ?;", (pattern.value,))
        row = cursor.fetchone()
        if not row:
            return None
        return PatternKnowledgeRecord(
            pattern=DSAPattern(row["pattern"]),
            description=row["description"],
            common_data_structures=json.loads(row["common_data_structures_json"]),
            typical_time_complexity=row["typical_time_complexity"],
            typical_space_complexity=row["typical_space_complexity"],
            applicable_constraints_note=row["applicable_constraints_note"],
            known_strengths=json.loads(row["known_strengths_json"]),
            known_weaknesses=json.loads(row["known_weaknesses_json"]),
            common_pitfalls=json.loads(row["common_pitfalls_json"]),
            related_problem_ids=json.loads(row["related_problem_ids_json"]),
            updated_at=row["updated_at"],
        )

    # --- SERIALIZATION HELPERS ---
    def _row_to_problem(self, row: sqlite3.Row) -> ProblemMemoryRecord:
        return ProblemMemoryRecord(
            problem_id=row["problem_id"],
            title=row["title"],
            description=row["description"],
            difficulty=Difficulty(row["difficulty"]) if row["difficulty"] else None,
            function_name=row["function_name"],
            param_names=json.loads(row["param_names_json"]),
            return_type=row["return_type"],
            constraints=json.loads(row["constraints_json"]),
            detected_patterns=[DSAPattern(p) for p in json.loads(row["detected_patterns_json"]) if p in [m.value for m in DSAPattern]],
            raw_statement=row["raw_statement"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_solution(self, row: sqlite3.Row) -> SolutionMemoryRecord:
        report = None
        if row["verification_report_json"]:
            try:
                report = FinalVerificationReport.model_validate_json(row["verification_report_json"])
            except Exception:
                report = None
        return SolutionMemoryRecord(
            solution_id=row["solution_id"],
            problem_id=row["problem_id"],
            language=SupportedLanguage(row["language"]),
            source_code=row["source_code"],
            source_hash=row["source_hash"],
            algorithm_name=row["algorithm_name"],
            data_structures_used=json.loads(row["data_structures_json"]),
            claimed_time_complexity=row["claimed_time_complexity"],
            claimed_space_complexity=row["claimed_space_complexity"],
            inferred_time_complexity=row["inferred_time_complexity"],
            inferred_space_complexity=row["inferred_space_complexity"],
            verification_status=VerificationStatus(row["verification_status"]),
            verification_report=report,
            is_verified=bool(row["is_verified"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_failure(self, row: sqlite3.Row) -> FailureMemoryRecord:
        report = None
        if row["raw_failure_report_json"]:
            try:
                report = FailureReport.model_validate_json(row["raw_failure_report_json"])
            except Exception:
                report = None
        return FailureMemoryRecord(
            failure_id=row["failure_id"],
            problem_id=row["problem_id"],
            attempt_number=row["attempt_number"],
            language=SupportedLanguage(row["language"]),
            source_code=row["source_code"],
            source_hash=row["source_hash"],
            failure_category=FailureCategory(row["failure_category"]),
            likely_root_cause=row["likely_root_cause"],
            error_message=row["error_message"],
            affected_test_ids=json.loads(row["affected_test_ids_json"]),
            raw_failure_report=report,
            repair_performed=row["repair_performed"],
            repair_succeeded=bool(row["repair_succeeded"]),
            created_at=row["created_at"],
        )

    def _row_to_repair(self, row: sqlite3.Row) -> RepairMemoryRecord:
        return RepairMemoryRecord(
            repair_id=row["repair_id"],
            problem_id=row["problem_id"],
            language=SupportedLanguage(row["language"]),
            original_failure_category=FailureCategory(row["original_failure_category"]),
            root_cause=row["root_cause"],
            source_hash_before=row["source_hash_before"],
            source_code_before=row["source_code_before"],
            source_hash_after=row["source_hash_after"],
            source_code_after=row["source_code_after"],
            patch_summary=row["patch_summary"],
            tests_passed_after=row["tests_passed_after"],
            tests_failed_after=row["tests_failed_after"],
            verification_status_after=VerificationStatus(row["verification_status_after"]),
            regression_passed=bool(row["regression_passed"]),
            created_at=row["created_at"],
        )

    # --- EXPERIENCE METHODS (STAGE 20) ---
    def save_experience(self, exp: ExperienceRecord) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute("""
            INSERT INTO experiences (
                experience_id, problem_id, problem_fingerprint, normalized_title,
                dsa_pattern, algorithm_name, candidate_algorithms_json, language,
                complexity_expected_time, complexity_expected_space,
                complexity_observed_time, complexity_observed_space,
                constraints_summary_json, status, is_verified,
                failure_categories_json, failure_hypotheses_json, repair_actions_json,
                attempt_count, tests_passed, tests_total, source_hash,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(experience_id) DO UPDATE SET
                problem_fingerprint=excluded.problem_fingerprint,
                normalized_title=excluded.normalized_title,
                dsa_pattern=excluded.dsa_pattern,
                algorithm_name=excluded.algorithm_name,
                candidate_algorithms_json=excluded.candidate_algorithms_json,
                language=excluded.language,
                complexity_expected_time=excluded.complexity_expected_time,
                complexity_expected_space=excluded.complexity_expected_space,
                complexity_observed_time=excluded.complexity_observed_time,
                complexity_observed_space=excluded.complexity_observed_space,
                constraints_summary_json=excluded.constraints_summary_json,
                status=excluded.status,
                is_verified=excluded.is_verified,
                failure_categories_json=excluded.failure_categories_json,
                failure_hypotheses_json=excluded.failure_hypotheses_json,
                repair_actions_json=excluded.repair_actions_json,
                attempt_count=excluded.attempt_count,
                tests_passed=excluded.tests_passed,
                tests_total=excluded.tests_total,
                source_hash=excluded.source_hash,
                updated_at=excluded.updated_at;
            """, (
                exp.experience_id,
                exp.problem_id,
                exp.problem_fingerprint,
                exp.normalized_title,
                exp.dsa_pattern.value,
                exp.algorithm_name,
                json.dumps(exp.candidate_algorithms),
                exp.language.value,
                exp.complexity_expected_time,
                exp.complexity_expected_space,
                exp.complexity_observed_time,
                exp.complexity_observed_space,
                json.dumps(exp.constraints_summary),
                exp.status,
                1 if exp.is_verified else 0,
                json.dumps(exp.failure_categories),
                json.dumps(exp.failure_hypotheses),
                json.dumps(exp.repair_actions),
                exp.attempt_count,
                exp.tests_passed,
                exp.tests_total,
                exp.source_hash,
                exp.created_at,
                exp.updated_at,
            ))

    def get_experience(self, experience_id: str) -> Optional[ExperienceRecord]:
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM experiences WHERE experience_id = ?;", (experience_id,))
        row = cursor.fetchone()
        return self._row_to_experience(row) if row else None

    def find_experiences_by_pattern(
        self,
        pattern: DSAPattern,
        only_verified: bool = False,
        limit: int = 10,
    ) -> List[ExperienceRecord]:
        conn = self._get_connection()
        query = "SELECT * FROM experiences WHERE dsa_pattern = ?"
        params: list = [pattern.value]
        if only_verified:
            query += " AND is_verified = 1"
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, tuple(params))
        return [self._row_to_experience(row) for row in cursor.fetchall()]

    def list_all_experiences(
        self,
        only_verified: bool = False,
        limit: int = 100,
    ) -> List[ExperienceRecord]:
        conn = self._get_connection()
        query = "SELECT * FROM experiences"
        params: list = []
        if only_verified:
            query += " WHERE is_verified = 1"
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, tuple(params))
        return [self._row_to_experience(row) for row in cursor.fetchall()]

    def _row_to_experience(self, row: sqlite3.Row) -> ExperienceRecord:
        return ExperienceRecord(
            experience_id=row["experience_id"],
            problem_id=row["problem_id"],
            problem_fingerprint=row["problem_fingerprint"],
            normalized_title=row["normalized_title"],
            dsa_pattern=DSAPattern(row["dsa_pattern"]),
            algorithm_name=row["algorithm_name"],
            candidate_algorithms=json.loads(row["candidate_algorithms_json"]),
            language=SupportedLanguage(row["language"]),
            complexity_expected_time=row["complexity_expected_time"],
            complexity_expected_space=row["complexity_expected_space"],
            complexity_observed_time=row["complexity_observed_time"],
            complexity_observed_space=row["complexity_observed_space"],
            constraints_summary=json.loads(row["constraints_summary_json"]),
            status=row["status"],
            is_verified=bool(row["is_verified"]),
            failure_categories=json.loads(row["failure_categories_json"]),
            failure_hypotheses=json.loads(row["failure_hypotheses_json"]),
            repair_actions=json.loads(row["repair_actions_json"]),
            attempt_count=row["attempt_count"],
            tests_passed=row["tests_passed"],
            tests_total=row["tests_total"],
            source_hash=row["source_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- ADAPTIVE TEST EVIDENCE METHODS (Stage 21) ---
    def save_adaptive_test_evidence(
        self,
        evidence_id: str,
        problem_id: str,
        test_fingerprint: str,
        category: str,
        generation_reason: str,
        risk_signal: str,
        memory_influence: Optional[str] = None,
        seed: Optional[int] = None,
        passed: bool = True,
        error_message: Optional[str] = None,
        adaptive_round: int = 1,
    ) -> None:
        conn = self._get_connection()
        from agent.memory.models import utc_now_iso
        now = utc_now_iso()
        with conn:
            conn.execute("""
            INSERT INTO adaptive_test_evidence (
                evidence_id, problem_id, test_fingerprint, category,
                generation_reason, risk_signal, memory_influence, seed,
                passed, error_message, adaptive_round, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_id) DO UPDATE SET
                passed=excluded.passed,
                error_message=excluded.error_message;
            """, (
                evidence_id,
                problem_id,
                test_fingerprint,
                category,
                generation_reason,
                risk_signal,
                memory_influence,
                seed,
                1 if passed else 0,
                error_message,
                adaptive_round,
                now,
            ))

    def get_adaptive_test_evidence(self, problem_id: str) -> List[dict]:
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT * FROM adaptive_test_evidence WHERE problem_id = ? ORDER BY adaptive_round ASC, created_at ASC;",
            (problem_id,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

