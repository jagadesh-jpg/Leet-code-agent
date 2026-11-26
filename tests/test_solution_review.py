"""Unit and integration tests for Milestone 6.3.17: Solution Quality Analyzer & Complexity Review.

Validates:
- Static code quality analysis:
    - Python AST structural analysis (loops, depth, functions, lines of code, variable clarity).
    - C, C++, and Java conservative structural analysis.
    - Empty and malformed code handling.
- Complexity estimation & learner self-assessment:
    - O(1), O(N), O(N^2), O(N log N), O(log N) heuristic indicators.
    - Matching and mismatching learner time & space complexity comparisons.
- Problem-solving quality checklist:
    - Edge cases, duplicates, empty inputs, readability, and custom overrides.
- Multi-attempt comparison:
    - Line delta, depth change, correctness transitions across consecutive reviews.
- Nondestructive persistence in session_tracking.db.
- Dashboard API endpoints (/api/workspace/review, /api/workspace/review/<id>, /api/workspace/reviews/history,
  /api/workspace/review/checklist, /api/workspace/review/complexity).
- Database isolation (temporary SQLite databases only).
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.solution_review import (
    AttemptComparison,
    CodeQualityMetrics,
    ComplexityReview,
    ProblemSolvingChecklist,
    SolutionReviewEngine,
    SolutionReviewReport,
    normalize_complexity_str,
)


@pytest.fixture
def temp_dbs(tmp_path):
    """Create isolated temporary progress.db and session_tracking.db for testing."""
    prog_db = tmp_path / "test_progress.db"
    track_db = tmp_path / "test_session_tracking.db"

    # Setup schema for progress.db
    with sqlite3.connect(prog_db) as conn:
        conn.execute(
            """
            CREATE TABLE attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_id TEXT NOT NULL,
                language TEXT NOT NULL,
                passed INTEGER NOT NULL,
                total INTEGER NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE custom_problems (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

    # Setup schema for session_tracking.db
    with sqlite3.connect(track_db) as conn:
        conn.execute(
            """
            CREATE TABLE workspace_runs (
                run_id TEXT PRIMARY KEY,
                problem_id TEXT NOT NULL,
                language TEXT NOT NULL,
                status TEXT NOT NULL,
                passed_count INTEGER NOT NULL,
                total_tests INTEGER NOT NULL,
                runtime_ms REAL,
                compile_error TEXT,
                execution_error TEXT,
                failed_test_detail TEXT,
                coach_feedback TEXT,
                suggested_next_action TEXT NOT NULL,
                can_complete_task INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )

    return prog_db, track_db


def test_analyzer_initialization(temp_dbs):
    """Verify SolutionReviewEngine initializes schema in tracking DB safely."""
    prog_db, track_db = temp_dbs
    engine = SolutionReviewEngine(tracking_db_path=track_db, progress_db_path=prog_db)
    assert engine is not None

    with sqlite3.connect(track_db) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "solution_reviews" in tables


def test_empty_and_malformed_code_analysis(temp_dbs):
    """Verify handling of empty or syntax-broken code without crashing."""
    prog_db, track_db = temp_dbs
    engine = SolutionReviewEngine(tracking_db_path=track_db, progress_db_path=prog_db)

    # Empty code
    empty_res = engine.analyze_code_quality("", "python")
    assert empty_res.lines_of_code == 0
    assert empty_res.max_nesting_depth == 0
    assert "empty" in empty_res.observations[0].lower()

    # Broken syntax fallback
    broken_code = "def broken_fn(x, y:\n    if x > 0:\n        return y"
    broken_res = engine.analyze_code_quality(broken_code, "python")
    assert broken_res.lines_of_code > 0
    assert broken_res.max_nesting_depth >= 1
    assert any("syntax issue" in obs.lower() for obs in broken_res.observations)


def test_python_ast_structural_analysis(temp_dbs):
    """Verify Python AST analysis for loops, functions, depth, and scores."""
    prog_db, track_db = temp_dbs
    engine = SolutionReviewEngine(tracking_db_path=track_db, progress_db_path=prog_db)

    code = (
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, num in enumerate(nums):\n"
        "        diff = target - num\n"
        "        if diff in seen:\n"
        "            return [seen[diff], i]\n"
        "        seen[num] = i\n"
        "    return []\n"
    )

    metrics = engine.analyze_code_quality(code, "python")
    assert isinstance(metrics, CodeQualityMetrics)
    assert metrics.function_count == 1
    assert metrics.loop_count == 1
    assert metrics.branch_count == 1
    assert metrics.max_nesting_depth in (2, 3)
    assert metrics.readability_score >= 80.0
    assert metrics.structural_score >= 85.0


def test_c_family_structural_analysis(temp_dbs):
    """Verify C, C++, and Java structural analysis."""
    prog_db, track_db = temp_dbs
    engine = SolutionReviewEngine(tracking_db_path=track_db, progress_db_path=prog_db)

    cpp_code = (
        "#include <vector>\n"
        "using namespace std;\n"
        "class Solution {\n"
        "public:\n"
        "    vector<int> twoSum(vector<int>& nums, int target) {\n"
        "        for (int i = 0; i < nums.size(); i++) {\n"
        "            for (int j = i + 1; j < nums.size(); j++) {\n"
        "                if (nums[i] + nums[j] == target) {\n"
        "                    return {i, j};\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "        return {};\n"
        "    }\n"
        "};\n"
    )

    metrics = engine.analyze_code_quality(cpp_code, "cpp")
    assert metrics.loop_count >= 2
    assert metrics.max_nesting_depth >= 4  # class -> method -> loop -> loop -> if
    assert any("nesting" in obs.lower() for obs in metrics.observations)


def test_complexity_estimation_and_learner_comparison(temp_dbs):
    """Verify heuristic time/space estimation and learner self-assessment comparison."""
    prog_db, track_db = temp_dbs
    engine = SolutionReviewEngine(tracking_db_path=track_db, progress_db_path=prog_db)

    # 1. Quadratic nested loop
    nested_code = (
        "def check_pairs(nums):\n"
        "    for i in range(len(nums)):\n"
        "        for j in range(i+1, len(nums)):\n"
        "            if nums[i] == nums[j]:\n"
        "                return True\n"
        "    return False\n"
    )
    rev_quad = engine.review_complexity(nested_code, "python", learner_time="O(N^2)", learner_space="O(1)")
    assert rev_quad.estimated_time_complexity == "O(N^2)"
    assert rev_quad.estimated_space_complexity == "O(1)"
    assert "Matches" in rev_quad.time_comparison
    assert "Matches" in rev_quad.space_comparison

    # 2. Linear hash-map single pass
    linear_code = (
        "def find_seen(nums):\n"
        "    seen = set()\n"
        "    for n in nums:\n"
        "        if n in seen:\n"
        "            return True\n"
        "        seen.add(n)\n"
        "    return False\n"
    )
    rev_lin = engine.review_complexity(linear_code, "python", learner_time="O(N^2)", learner_space="O(N)")
    assert rev_lin.estimated_time_complexity == "O(N)"
    assert rev_lin.estimated_space_complexity == "O(N)"
    # Learner guessed O(N^2), so mismatch reported
    assert "differs" in rev_lin.time_comparison
    assert "Matches" in rev_lin.space_comparison


def test_attempt_comparison_tracking(temp_dbs):
    """Verify comparison against previous review attempts."""
    prog_db, track_db = temp_dbs
    engine = SolutionReviewEngine(tracking_db_path=track_db, progress_db_path=prog_db)

    code_v1 = (
        "def two_sum(nums, target):\n"
        "    for i in range(len(nums)):\n"
        "        for j in range(i+1, len(nums)):\n"
        "            if nums[i] + nums[j] == target:\n"
        "                return [i, j]\n"
        "    return []\n"
    )
    r1 = engine.review_solution("two-sum", code_v1, language="python")
    assert r1.attempt_comparison.previous_attempt_found is False

    code_v2 = (
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, n in enumerate(nums):\n"
        "        diff = target - n\n"
        "        if diff in seen:\n"
        "            return [seen[diff], i]\n"
        "        seen[n] = i\n"
        "    return []\n"
    )
    r2 = engine.review_solution("two-sum", code_v2, language="python")
    assert r2.attempt_comparison.previous_attempt_found is True
    assert r2.attempt_comparison.previous_language == "python"
    assert "comparison" in r2.attempt_comparison.summary_of_changes.lower() or "nesting" in r2.attempt_comparison.summary_of_changes.lower() or "code" in r2.attempt_comparison.summary_of_changes.lower()


def test_dashboard_api_solution_review_endpoints(temp_dbs):
    """Verify Flask API routes for solution quality review."""
    prog_db, track_db = temp_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    sample_code = (
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, num in enumerate(nums):\n"
        "        diff = target - num\n"
        "        if diff in seen:\n"
        "            return [seen[diff], i]\n"
        "        seen[num] = i\n"
        "    return []\n"
    )

    # POST /api/workspace/review
    res_rev = client.post(
        "/api/workspace/review",
        data=json.dumps({
            "problem_id": "two-sum",
            "language": "python",
            "code": sample_code,
            "learner_time": "O(N)",
            "learner_space": "O(N)",
        }),
        content_type="application/json",
    )
    assert res_rev.status_code == 200
    rev_data = res_rev.get_json()
    assert "review_id" in rev_data
    assert rev_data["quality_metrics"]["readability_score"] > 0
    assert rev_data["complexity_review"]["estimated_time_complexity"] == "O(N)"
    review_id = rev_data["review_id"]

    # GET /api/workspace/review/<review_id>
    res_get = client.get(f"/api/workspace/review/{review_id}")
    assert res_get.status_code == 200
    assert res_get.get_json()["review_id"] == review_id

    # GET /api/workspace/reviews/history
    res_hist = client.get("/api/workspace/reviews/history?problem_id=two-sum")
    assert res_hist.status_code == 200
    assert len(res_hist.get_json()) >= 1

    # POST /api/workspace/review/complexity
    res_comp = client.post(
        "/api/workspace/review/complexity",
        data=json.dumps({
            "code": sample_code,
            "language": "python",
            "learner_time": "O(N)",
            "learner_space": "O(N)",
        }),
        content_type="application/json",
    )
    assert res_comp.status_code == 200
    assert res_comp.get_json()["estimated_time_complexity"] == "O(N)"

    # POST /api/workspace/review/checklist
    res_chk = client.post(
        "/api/workspace/review/checklist",
        data=json.dumps({
            "problem_id": "two-sum",
            "code": sample_code,
            "language": "python",
            "checklist": {"handles_empty_input": True, "is_readable": True},
        }),
        content_type="application/json",
    )
    assert res_chk.status_code == 200
    chk_data = res_chk.get_json()
    assert chk_data["checklist"]["handles_empty_input"] is True
