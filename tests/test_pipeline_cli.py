"""Unit and Integration Tests for pipeline_cli.py (Milestone 6.3.2).

Verifies:
1. Offline demonstration starts successfully and runs without live network/API calls.
2. Two demonstration problems are processed.
3. One correction cycle (Wrong Answer -> passing fix) is demonstrated.
4. Immediate passing solution (Attempt 1 success) is demonstrated.
5. Isolated temporary database is used by default (production progress.db untouched).
6. Custom demo database path is respected when specified.
7. CLI summary and returned accounting report zero API requests.
"""

from pathlib import Path
import sqlite3
import pytest

from pipeline import FailureCategory
import pipeline_cli
import store


@pytest.fixture
def temp_demo_db(tmp_path):
    return tmp_path / "test_demo_pipeline.db"


def test_offline_demo_execution_and_summary(temp_demo_db):
    """Verify demo runs end-to-end in an isolated DB with 2 problems, 1 correction cycle, 1 immediate success."""
    result = pipeline_cli.run_offline_demo(
        db_path=temp_demo_db,
        language="python",
        max_attempts=3,
        verbose=False,
    )

    assert result["success"] is True
    assert result["total_problems"] == 2
    assert result["solved_problems"] == 2
    assert result["network_requests"] == 0
    assert result["api_calls_count"] == 0
    assert result["total_attempts"] == 3  # Problem 1 (2 attempts) + Problem 2 (1 attempt)

    results = result["results"]
    assert len(results) == 2

    # Problem 1: demo-two-sum should have had a correction cycle
    p1 = results[0]
    assert p1.problem_id == "demo-two-sum"
    assert p1.passed is True
    assert p1.attempts_used == 2
    assert p1.final_verdict == "locally_verified"
    assert len(p1.history) == 2
    assert p1.history[0]["status"] == "wrong_answer"
    assert p1.history[0]["failure_category"] == "wrong_answer"
    assert p1.history[1]["status"] == "passed"

    # Problem 2: demo-valid-palindrome should be immediate success
    p2 = results[1]
    assert p2.problem_id == "demo-valid-palindrome"
    assert p2.passed is True
    assert p2.attempts_used == 1
    assert p2.final_verdict == "locally_verified"
    assert len(p2.history) == 1
    assert p2.history[0]["status"] == "passed"

    # Verify database persistence in the isolated demo DB
    assert temp_demo_db.exists()
    assert store.is_solved("demo-two-sum", language="python", db_path=temp_demo_db) is True
    assert store.is_solved("demo-valid-palindrome", language="python", db_path=temp_demo_db) is True

    # Check attempt records in the SQLite attempts table
    with store.get_connection(temp_demo_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT problem_id, attempt_no, status FROM attempts ORDER BY id ASC")
        rows = cursor.fetchall()
        assert len(rows) == 3
        assert rows[0]["problem_id"] == "demo-two-sum" and rows[0]["status"] == "wrong_answer"
        assert rows[1]["problem_id"] == "demo-two-sum" and rows[1]["status"] == "passed"
        assert rows[2]["problem_id"] == "demo-valid-palindrome" and rows[2]["status"] == "passed"


def test_offline_demo_default_isolated_temp_db():
    """Verify that when db_path is omitted, a temporary isolated database is created automatically."""
    result = pipeline_cli.run_offline_demo(db_path=None, verbose=False)
    assert result["success"] is True
    assert result["network_requests"] == 0
    assert "pipeline_demo_" in result["db_path"]
    assert Path(result["db_path"]).exists()
    assert "progress.db" not in Path(result["db_path"]).name


def test_cli_argument_parsing(monkeypatch, temp_demo_db):
    """Test CLI entrypoint invocation with --demo and --db-path arguments."""
    test_args = ["pipeline_cli.py", "--demo", "--db-path", str(temp_demo_db), "--quiet"]
    monkeypatch.setattr("sys.argv", test_args)

    with pytest.raises(SystemExit) as exc_info:
        pipeline_cli.main()

    assert exc_info.value.code == 0
    assert store.is_solved("demo-two-sum", language="python", db_path=temp_demo_db) is True
    assert store.is_solved("demo-valid-palindrome", language="python", db_path=temp_demo_db) is True
