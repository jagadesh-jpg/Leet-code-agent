"""SQLite-backed Queue Persistence Store (Stage 18).

Provides durable, restart-safe persistence for:
- queue items
- state transitions
- execution references and attempt history
- idempotency checks and restart recovery
Does NOT store secrets or API keys.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import List, Optional

from agent.core.models import SupportedLanguage
from agent.queue.models import QueueItem, QueueItemStatus


class SQLiteQueueStore:
    """Persistent SQLite database store for problem queue items and transitions."""

    def __init__(self, db_path: str = "agent_queue.db"):
        self.db_path = str(Path(db_path).resolve())
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self.initialize()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON;")
        return self._conn

    def initialize(self) -> None:
        """Idempotently creates queue tables and indexes."""
        conn = self._get_connection()
        with conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS queue_items (
                queue_item_id TEXT PRIMARY KEY,
                problem_id TEXT NOT NULL,
                title TEXT,
                problem_statement TEXT,
                preferred_language TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                final_status TEXT,
                verification_status TEXT,
                failure_category TEXT,
                result_reference TEXT,
                initial_flawed_code TEXT,
                tests_passed INTEGER NOT NULL DEFAULT 0,
                tests_total INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                category TEXT,
                spec_json TEXT,
                raw_problem TEXT,
                problem_hash TEXT
            );
            """)

            # Add columns if migrating from earlier schema
            for col, col_type in [("spec_json", "TEXT"), ("raw_problem", "TEXT"), ("problem_hash", "TEXT")]:
                try:
                    conn.execute(f"ALTER TABLE queue_items ADD COLUMN {col} {col_type};")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_queue_status_prio ON queue_items (status, priority DESC, created_at ASC);
            """)
            conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_queue_hash ON queue_items (problem_hash);
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS queue_transitions (
                transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
                queue_item_id TEXT NOT NULL,
                old_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                transition_time TEXT NOT NULL,
                FOREIGN KEY (queue_item_id) REFERENCES queue_items(queue_item_id) ON DELETE CASCADE
            );
            """)

    def save_item(self, item: QueueItem) -> None:
        """Inserts or replaces a queue item in the database."""
        conn = self._get_connection()
        with conn:
            conn.execute("""
            INSERT OR REPLACE INTO queue_items (
                queue_item_id, problem_id, title, problem_statement,
                preferred_language, priority, status, attempt_count,
                max_attempts, created_at, started_at, completed_at,
                final_status, verification_status, failure_category,
                result_reference, initial_flawed_code, tests_passed,
                tests_total, error_message, category, spec_json, raw_problem, problem_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                item.queue_item_id,
                item.problem_id,
                item.title,
                item.problem_statement,
                item.preferred_language.value,
                item.priority,
                item.status.value,
                item.attempt_count,
                item.max_attempts,
                item.created_at,
                item.started_at,
                item.completed_at,
                item.final_status,
                item.verification_status,
                item.failure_category,
                item.result_reference,
                item.initial_flawed_code,
                item.tests_passed,
                item.tests_total,
                item.error_message,
                item.category,
                item.spec_json,
                item.raw_problem,
                item.problem_hash,
            ))

    def get_item(self, queue_item_id: str) -> Optional[QueueItem]:
        """Fetches a queue item by unique ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM queue_items WHERE queue_item_id = ?", (queue_item_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_item(row)

    def get_next_pending(self, use_priority: bool = True) -> Optional[QueueItem]:
        """Selects next eligible pending item deterministically (FIFO or priority)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        if use_priority:
            order_clause = "ORDER BY priority DESC, created_at ASC"
        else:
            order_clause = "ORDER BY created_at ASC"

        query = f"SELECT * FROM queue_items WHERE status = 'PENDING' {order_clause} LIMIT 1"
        cursor.execute(query)
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_item(row)

    def list_items(self, status: Optional[QueueItemStatus] = None) -> List[QueueItem]:
        """Lists queue items optionally filtered by status."""
        conn = self._get_connection()
        cursor = conn.cursor()
        if status:
            cursor.execute("SELECT * FROM queue_items WHERE status = ? ORDER BY priority DESC, created_at ASC", (status.value,))
        else:
            cursor.execute("SELECT * FROM queue_items ORDER BY priority DESC, created_at ASC")
        return [self._row_to_item(r) for r in cursor.fetchall()]

    def record_transition(self, queue_item_id: str, old_status: QueueItemStatus, new_status: QueueItemStatus, timestamp: str) -> None:
        """Records an explicit audit log entry for a state transition."""
        conn = self._get_connection()
        with conn:
            conn.execute("""
            INSERT INTO queue_transitions (queue_item_id, old_status, new_status, transition_time)
            VALUES (?, ?, ?, ?);
            """, (queue_item_id, old_status.value, new_status.value, timestamp))

    def reset_in_progress_to_pending(self) -> int:
        """Crash / restart recovery: resets RUNNING or VERIFYING items to PENDING."""
        conn = self._get_connection()
        with conn:
            cursor = conn.execute("""
            UPDATE queue_items
            SET status = 'PENDING'
            WHERE status IN ('RUNNING', 'VERIFYING');
            """)
            return cursor.rowcount

    def clear(self) -> None:
        """Truncates all queue data."""
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM queue_transitions;")
            conn.execute("DELETE FROM queue_items;")

    def close(self) -> None:
        """Closes the underlying SQLite connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _row_to_item(self, row: sqlite3.Row) -> QueueItem:
        return QueueItem(
            queue_item_id=row["queue_item_id"],
            problem_id=row["problem_id"],
            title=row["title"] or "",
            problem_statement=row["problem_statement"] or "",
            preferred_language=SupportedLanguage(row["preferred_language"]),
            priority=row["priority"],
            status=QueueItemStatus(row["status"]),
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            final_status=row["final_status"],
            verification_status=row["verification_status"],
            failure_category=row["failure_category"],
            result_reference=row["result_reference"],
            initial_flawed_code=row["initial_flawed_code"],
            tests_passed=row["tests_passed"],
            tests_total=row["tests_total"],
            error_message=row["error_message"],
            category=row["category"],
            spec_json=row["spec_json"] if "spec_json" in row.keys() else None,
            raw_problem=row["raw_problem"] if "raw_problem" in row.keys() else None,
            problem_hash=row["problem_hash"] if "problem_hash" in row.keys() else None,
        )
