import json
import pytest
from pathlib import Path

import import_batch
import store


@pytest.fixture
def temp_db(tmp_path):
    """Provides an isolated test database for testing batch imports."""
    db_file = tmp_path / "test_batch.db"
    store.init(db_path=db_file)
    return db_file


def test_import_batch_valid_file(temp_db, tmp_path):
    """Test successful import of valid problems with working reference solutions."""
    file_path = tmp_path / "valid.json"
    data = [
        {
            "id": "batch-add-two",
            "title": "Add Two",
            "difficulty": "Easy",
            "description": "Add two numbers",
            "function_name": "addTwo",
            "reference_solution": "class Solution:\n    def addTwo(self, a: int, b: int) -> int:\n        return a + b",
            "tests": [
                {"input": [1, 2], "expected": 3},
                {"input": [0, 0], "expected": 0},
                {"input": [-1, 1], "expected": 0},
                {"input": [10, 20], "expected": 30},
                {"input": [5, -3], "expected": 2},
            ],
        }
    ]
    file_path.write_text(json.dumps(data), encoding="utf-8")

    res = import_batch.import_batch_from_file(file_path, db_path=temp_db)
    assert res["success"] is True
    assert res["imported_count"] == 1
    assert res["rejected_count"] == 0
    assert "batch-add-two" in res["imported"]

    prob = store.get_custom_problem("batch-add-two", db_path=temp_db)
    assert prob is not None
    assert prob["title"] == "Add Two"
    assert len(prob["tests"]) == 5


def test_import_batch_duplicate_id_rejected(temp_db, tmp_path):
    """Test that duplicate problem IDs in the same file or already in DB are rejected."""
    file_path = tmp_path / "duplicates.json"
    data = [
        {
            "id": "dup-prob",
            "title": "Problem Dup 1",
            "difficulty": "Easy",
            "description": "desc",
            "function_name": "solve",
            "reference_solution": "class Solution:\n    def solve(self, x: int) -> int:\n        return x",
            "tests": [{"input": [i], "expected": i} for i in range(5)],
        },
        {
            "id": "dup-prob",
            "title": "Problem Dup 2",
            "difficulty": "Easy",
            "description": "desc",
            "function_name": "solve",
            "reference_solution": "class Solution:\n    def solve(self, x: int) -> int:\n        return x",
            "tests": [{"input": [i], "expected": i} for i in range(5)],
        },
    ]
    file_path.write_text(json.dumps(data), encoding="utf-8")

    res = import_batch.import_batch_from_file(file_path, db_path=temp_db)
    assert res["imported_count"] == 1
    assert res["rejected_count"] == 1
    assert "duplicate" in res["rejected"][0]["reason"].lower()


def test_import_batch_failing_reference_solution_rejected(temp_db, tmp_path):
    """Test that a problem is rejected if its reference solution fails tests."""
    file_path = tmp_path / "failing_ref.json"
    data = [
        {
            "id": "fail-ref-prob",
            "title": "Wrong Solver",
            "difficulty": "Easy",
            "description": "desc",
            "function_name": "wrongSol",
            # Intentionally returns wrong answer
            "reference_solution": "class Solution:\n    def wrongSol(self, x: int) -> int:\n        return -9999",
            "tests": [{"input": [i], "expected": i} for i in range(5)],
        }
    ]
    file_path.write_text(json.dumps(data), encoding="utf-8")

    res = import_batch.import_batch_from_file(file_path, db_path=temp_db)
    assert res["imported_count"] == 0
    assert res["rejected_count"] == 1
    assert "failed local judge" in res["rejected"][0]["reason"]
    assert store.get_custom_problem("fail-ref-prob", db_path=temp_db) is None


def test_import_batch_missing_fields_and_fewer_than_five_tests(temp_db, tmp_path):
    """Test rejection on missing fields, invalid difficulty, and fewer than 5 tests."""
    file_path = tmp_path / "invalid_fields.json"
    data = [
        {
            # Missing id
            "title": "No ID",
            "difficulty": "Easy",
            "description": "desc",
            "function_name": "f",
            "reference_solution": "class Solution:\n    def f(self): pass",
            "tests": [{"input": [i], "expected": i} for i in range(5)],
        },
        {
            "id": "too-few-tests",
            "title": "Too Few Tests",
            "difficulty": "Medium",
            "description": "desc",
            "function_name": "f",
            "reference_solution": "class Solution:\n    def f(self, x): return x",
            # Only 3 tests (minimum required is 5)
            "tests": [{"input": [i], "expected": i} for i in range(3)],
        },
        {
            "id": "bad-diff",
            "title": "Bad Difficulty",
            "difficulty": "SuperHard",
            "description": "desc",
            "function_name": "f",
            "reference_solution": "class Solution:\n    def f(self, x): return x",
            "tests": [{"input": [i], "expected": i} for i in range(5)],
        },
    ]
    file_path.write_text(json.dumps(data), encoding="utf-8")

    res = import_batch.import_batch_from_file(file_path, db_path=temp_db)
    assert res["imported_count"] == 0
    assert res["rejected_count"] == 3
    reasons = [r["reason"] for r in res["rejected"]]
    assert any("Missing required field" in r for r in reasons)
    assert any("at least 5 test cases" in r for r in reasons)
    assert any("Invalid difficulty" in r for r in reasons)
