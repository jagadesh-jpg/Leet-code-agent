from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "progress.db"


def get_connection(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    path = db_path if db_path is not None else DEFAULT_DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init(db_path: Optional[str | Path] = None) -> None:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS progress (
                problem_id TEXT PRIMARY KEY,
                status TEXT,
                attempts INTEGER,
                solved_at TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_id TEXT,
                attempt_no INTEGER,
                code TEXT,
                status TEXT,
                error TEXT,
                created_at TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_problems (
                id TEXT PRIMARY KEY,
                url TEXT,
                title TEXT,
                difficulty TEXT,
                description TEXT,
                function_name TEXT,
                signature TEXT,
                tests_json TEXT,
                created_at TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS official_verdicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_id TEXT,
                verdict TEXT,
                runtime_ms REAL,
                memory_mb REAL,
                notes TEXT,
                submitted_at TEXT
            )
            """
        )
        conn.commit()


def is_solved(problem_id: str, db_path: Optional[str | Path] = None) -> bool:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM progress WHERE problem_id = ?", (problem_id,))
        row = cursor.fetchone()
        return bool(row and row["status"] == "solved")


def log_attempt(
    problem_id: str,
    attempt_no: int,
    code: str,
    status: str,
    error: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO attempts (problem_id, attempt_no, code, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (problem_id, attempt_no, code, status, error, now),
        )
        conn.commit()


def mark_result(
    problem_id: str,
    status: str,
    attempts: int,
    db_path: Optional[str | Path] = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat() if status == "solved" else None
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO progress (problem_id, status, attempts, solved_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(problem_id) DO UPDATE SET
                status = excluded.status,
                attempts = excluded.attempts,
                solved_at = excluded.solved_at
            """,
            (problem_id, status, attempts, now),
        )
        conn.commit()


def summary(
    db_path: Optional[str | Path] = None,
    problems: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT problem_id, status, attempts FROM progress")
        rows = cursor.fetchall()

    solved_count = sum(1 for r in rows if r["status"] == "solved")
    failed_count = sum(1 for r in rows if r["status"] == "failed")
    total_count = len(rows)

    solved_attempts = [r["attempts"] for r in rows if r["status"] == "solved" and r["attempts"] is not None]
    avg_attempts = (sum(solved_attempts) / len(solved_attempts)) if solved_attempts else 0.0

    # Counts by difficulty if problems list is provided
    by_difficulty = {"easy": {"solved": 0, "failed": 0, "total": 0},
                     "medium": {"solved": 0, "failed": 0, "total": 0},
                     "hard": {"solved": 0, "failed": 0, "total": 0}}

    if problems:
        prob_diff_map = {p["id"]: p.get("difficulty", "easy").lower() for p in problems}
        for p in problems:
            diff = p.get("difficulty", "easy").lower()
            if diff in by_difficulty:
                by_difficulty[diff]["total"] += 1

        for r in rows:
            diff = prob_diff_map.get(r["problem_id"])
            if diff in by_difficulty:
                if r["status"] == "solved":
                    by_difficulty[diff]["solved"] += 1
                elif r["status"] == "failed":
                    by_difficulty[diff]["failed"] += 1

    return {
        "solved": solved_count,
        "failed": failed_count,
        "total_attempted": total_count,
        "avg_attempts_solved": round(avg_attempts, 2),
        "by_difficulty": by_difficulty,
    }


def get_attempt_count(problem_id: str, db_path: Optional[str | Path] = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM attempts WHERE problem_id = ?", (problem_id,))
        row = cursor.fetchone()
        return row["count"] if row else 0


def save_custom_problem(
    problem_id: str,
    url: str,
    title: str,
    difficulty: str,
    description: str,
    function_name: str,
    signature: str,
    tests: List[Dict[str, Any]],
    db_path: Optional[str | Path] = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    import json
    tests_json = json.dumps(tests)
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO custom_problems (id, url, title, difficulty, description, function_name, signature, tests_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                url = excluded.url,
                title = excluded.title,
                difficulty = excluded.difficulty,
                description = excluded.description,
                function_name = excluded.function_name,
                signature = excluded.signature,
                tests_json = excluded.tests_json,
                created_at = excluded.created_at
            """,
            (problem_id, url, title, difficulty, description, function_name, signature, tests_json, now),
        )
        conn.commit()


def get_custom_problem(problem_id: str, db_path: Optional[str | Path] = None) -> Optional[Dict[str, Any]]:
    import json
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM custom_problems WHERE id = ?", (problem_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "url": row["url"],
            "title": row["title"],
            "difficulty": row["difficulty"],
            "description": row["description"],
            "function_name": row["function_name"],
            "signature": row["signature"],
            "tests": json.loads(row["tests_json"]),
            "created_at": row["created_at"],
            "compare": "exact",
        }


def list_custom_problems(db_path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    import json
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM custom_problems ORDER BY created_at DESC")
        rows = cursor.fetchall()
        result = []
        for row in rows:
            result.append({
                "id": row["id"],
                "url": row["url"],
                "title": row["title"],
                "difficulty": row["difficulty"],
                "description": row["description"],
                "function_name": row["function_name"],
                "signature": row["signature"],
                "tests": json.loads(row["tests_json"]),
                "created_at": row["created_at"],
            })
        return result


VALID_OFFICIAL_VERDICTS = [
    "Accepted",
    "Wrong Answer",
    "Time Limit Exceeded",
    "Memory Limit Exceeded",
    "Runtime Error",
    "Compile Error",
    "Pending",
]


def record_official_verdict(
    problem_id: str,
    verdict: str,
    runtime_ms: Optional[float] = None,
    memory_mb: Optional[float] = None,
    notes: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    norm_verdict = verdict.strip().title()
    if norm_verdict not in VALID_OFFICIAL_VERDICTS:
        norm_verdict = f"Other ({verdict.strip()})"

    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO official_verdicts (problem_id, verdict, runtime_ms, memory_mb, notes, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (problem_id, norm_verdict, runtime_ms, memory_mb, notes or "", now),
        )
        conn.commit()

    return {
        "problem_id": problem_id,
        "verdict": norm_verdict,
        "runtime_ms": runtime_ms,
        "memory_mb": memory_mb,
        "notes": notes or "",
        "submitted_at": now,
    }


def get_official_verdicts(problem_id: Optional[str] = None, db_path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        if problem_id:
            cursor.execute(
                "SELECT * FROM official_verdicts WHERE problem_id = ? ORDER BY id DESC",
                (problem_id,),
            )
        else:
            cursor.execute("SELECT * FROM official_verdicts ORDER BY id DESC")
        rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "problem_id": r["problem_id"],
                "verdict": r["verdict"],
                "runtime_ms": r["runtime_ms"],
                "memory_mb": r["memory_mb"],
                "notes": r["notes"],
                "submitted_at": r["submitted_at"],
            }
            for r in rows
        ]


def reset(db_path: Optional[str | Path] = None) -> None:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM attempts")
        cursor.execute("DELETE FROM progress")
        cursor.execute("DELETE FROM custom_problems")
        cursor.execute("DELETE FROM official_verdicts")
        conn.commit()
