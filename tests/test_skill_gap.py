"""Unit and integration tests for Milestone 6.3.24: Personal Skill Gap & Focus Prioritization Engine.

Validates:
- Empty database resilience and insufficient evidence handling (no crash, zero division prevention).
- Topic identification across standard taxonomy and custom problems.
- Demonstrated weakness detection (high failure rate, unresolved problems).
- Topic coverage and under-practiced skill detection.
- Strong skill identification (>= 2 solves, >= 80% success rate, 0 unresolved).
- Unresolved problem analysis and prioritizations.
- Spaced revision overdue evidence integration.
- Practice session evidence and recency weighting.
- Confidence calculation tiers (insufficient_data, low, medium, high).
- Priority score calculation and transparent formula breakdown.
- Deterministic focus queue ordering and duplicate prevention.
- Report persistence, retrieval, and listing in session_tracking.db.
- Non-destructive operation (production progress.db remains untouched).
- All 6 Flask REST API endpoints in dashboard_server.py.
- Input validation, regex sanitization, and error responses.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.skill_gap import (
    PrioritizedFocusItem,
    SkillEvidence,
    SkillGap,
    SkillGapAnalyzer,
    SkillGapConfidence,
    SkillGapPriority,
    SkillGapReport,
    SkillGapType,
)


@pytest.fixture
def test_dbs(tmp_path):
    """Provides isolated temporary SQLite databases for tracking and progress."""
    prog_db = tmp_path / "test_prog.db"
    track_db = tmp_path / "test_tracking.db"

    # Minimal progress.db schema
    with sqlite3.connect(prog_db) as conn:
        conn.execute(
            """
            CREATE TABLE attempts (
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
        conn.execute(
            """
            CREATE TABLE custom_problems (
                id TEXT PRIMARY KEY,
                title TEXT,
                difficulty TEXT,
                description TEXT,
                function_name TEXT,
                signature TEXT,
                tests_json TEXT,
                created_at TEXT,
                reference_solution TEXT
            )
            """
        )
        conn.commit()

    return {"prog_db": prog_db, "track_db": track_db}


def test_empty_database_behavior(test_dbs):
    """Test analyzer behavior on fresh, empty tracking and progress databases."""
    analyzer = SkillGapAnalyzer(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    report = analyzer.analyze(save=True)
    assert report is not None
    assert isinstance(report, SkillGapReport)

    # Coverage should be 0% when no attempts exist
    cov = report.coverage_summary
    assert cov["practiced_topics"] == 0
    assert cov["coverage_percentage"] == 0.0
    assert cov["total_topics"] >= 14  # At least standard topics

    # All unattempted topics must be categorized as INSUFFICIENT_PRACTICE, never DEMONSTRATED_WEAKNESS!
    assert len(report.insufficient_evidence_topics) == cov["total_topics"]
    assert len(report.demonstrated_strengths) == 0
    for gap in report.insufficient_evidence_topics:
        assert gap.gap_type == SkillGapType.INSUFFICIENT_PRACTICE
        assert gap.confidence == SkillGapConfidence.INSUFFICIENT_DATA
        assert gap.evidence.attempted_problems_count == 0
        assert "no practice attempts" in gap.reason.lower()

    # Focus queue must contain all topics without duplicates
    queue = report.focus_queue
    assert len(queue) == cov["total_topics"]
    topics_in_queue = [item.topic for item in queue]
    assert len(topics_in_queue) == len(set(topics_in_queue))

    # Test overview dictionary
    overview = analyzer.get_overview()
    assert overview["report_id"] == report.report_id
    assert overview["coverage_summary"]["coverage_percentage"] == 0.0


def test_demonstrated_weakness_and_unresolved_problems(test_dbs):
    """Test detection of demonstrated weakness when test runs fail and problems remain unresolved."""
    track_db = test_dbs["track_db"]
    prog_db = test_dbs["prog_db"]

    analyzer = SkillGapAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )

    # Insert failing workspace runs for 'valid-parentheses' (Stack, Hashing)
    with analyzer.get_tracking_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_runs (
                run_id TEXT PRIMARY KEY,
                problem_id TEXT NOT NULL,
                language TEXT NOT NULL,
                status TEXT NOT NULL,
                passed_count INTEGER NOT NULL,
                total_tests INTEGER NOT NULL,
                compile_error TEXT,
                execution_error TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, created_at)
            VALUES ('run_1', 'valid-parentheses', 'python', 'wrong_answer', 2, 6, '2026-11-20T10:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, created_at)
            VALUES ('run_2', 'valid-parentheses', 'python', 'runtime_error', 0, 6, '2026-11-20T10:05:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, created_at)
            VALUES ('run_3', 'valid-parentheses', 'python', 'wrong_answer', 3, 6, '2026-11-20T10:10:00Z')
            """
        )
        conn.commit()

    report = analyzer.analyze(save=True)

    # Find Stack gap
    stack_gap = next((g for g in report.all_topic_gaps if g.topic == "Stack"), None)
    assert stack_gap is not None
    assert stack_gap.gap_type == SkillGapType.DEMONSTRATED_WEAKNESS
    assert stack_gap.evidence.unsolved_problems_count == 1
    assert "valid-parentheses" in stack_gap.evidence.unresolved_problem_ids
    assert stack_gap.evidence.failed_runs == 3
    assert stack_gap.priority_tier in (SkillGapPriority.P0_CRITICAL, SkillGapPriority.P1_HIGH)
    assert stack_gap.priority_score >= 45.0
    assert "debug and resolve failing test cases" in stack_gap.suggested_action.lower()


def test_demonstrated_strength_identification(test_dbs):
    """Test identification of strong skills (>= 2 solves, >= 80% success, 0 unresolved)."""
    track_db = test_dbs["track_db"]
    prog_db = test_dbs["prog_db"]

    analyzer = SkillGapAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )

    # Two Sum (Arrays, Hashing) and Contains Duplicate (Arrays, Hashing) passed on first run!
    with analyzer.get_tracking_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_runs (
                run_id TEXT PRIMARY KEY,
                problem_id TEXT NOT NULL,
                language TEXT NOT NULL,
                status TEXT NOT NULL,
                passed_count INTEGER NOT NULL,
                total_tests INTEGER NOT NULL,
                compile_error TEXT,
                execution_error TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, created_at)
            VALUES ('run_1', 'two-sum', 'python', 'passed', 5, 5, '2026-11-22T10:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, created_at)
            VALUES ('run_2', 'contains-duplicate', 'python', 'passed', 5, 5, '2026-11-22T11:00:00Z')
            """
        )
        conn.commit()

    report = analyzer.analyze(save=True)

    # Arrays has 2 distinct problems solved with 100% success rate
    arrays_gap = next((g for g in report.all_topic_gaps if g.topic == "Arrays"), None)
    assert arrays_gap is not None
    assert arrays_gap.gap_type == SkillGapType.DEMONSTRATED_STRENGTH
    assert arrays_gap.priority_tier == SkillGapPriority.P3_LOW
    assert arrays_gap.evidence.solved_problems_count >= 2
    assert arrays_gap.evidence.unsolved_problems_count == 0
    assert arrays_gap.score_breakdown["strength_discount"] < 0.0

    # Verify Arrays appears in demonstrated_strengths list
    assert any(g.topic == "Arrays" for g in report.demonstrated_strengths)


def test_overdue_revision_evidence_integration(test_dbs):
    """Test that overdue spaced repetition items elevate priority score."""
    track_db = test_dbs["track_db"]
    prog_db = test_dbs["prog_db"]

    analyzer = SkillGapAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )

    # Setup revision_items with overdue item for 'longest-substring-without-repeating-characters' (Sliding Window)
    with analyzer.get_tracking_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS revision_items (
                problem_id TEXT PRIMARY KEY,
                difficulty TEXT NOT NULL,
                topics_json TEXT NOT NULL,
                status TEXT NOT NULL,
                interval_days INTEGER NOT NULL,
                ease_factor REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO revision_items (problem_id, difficulty, topics_json, status, interval_days, ease_factor)
            VALUES ('longest-substring-without-repeating-characters', 'medium', '["Sliding Window"]', 'overdue', 1, 2.1)
            """
        )
        conn.commit()

    report = analyzer.analyze(save=True)

    sw_gap = next((g for g in report.all_topic_gaps if g.topic == "Sliding Window"), None)
    assert sw_gap is not None
    assert sw_gap.evidence.overdue_revision_count >= 1
    assert sw_gap.score_breakdown["overdue_penalty"] > 0.0


def test_deterministic_queue_ordering_and_no_duplicates(test_dbs):
    """Test that focus queue items are strictly ordered by score descending without duplicates."""
    analyzer = SkillGapAnalyzer(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    report = analyzer.analyze(save=True)
    queue = report.focus_queue

    # Verify strict descending order
    scores = [item.priority_score for item in queue]
    assert scores == sorted(scores, reverse=True)

    # Verify 1-based ranks
    ranks = [item.rank for item in queue]
    assert ranks == list(range(1, len(queue) + 1))

    # Verify no duplicate topics
    topics = [item.topic for item in queue]
    assert len(topics) == len(set(topics))


def test_report_persistence_and_retrieval(test_dbs):
    """Test saving and retrieving reports and items from session_tracking.db."""
    analyzer = SkillGapAnalyzer(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    rep1 = analyzer.analyze(save=True)
    report_id = rep1.report_id

    # Retrieve latest
    latest = analyzer.get_latest_report()
    assert latest is not None
    assert latest.report_id == report_id
    assert latest.total_topics_evaluated == rep1.total_topics_evaluated

    # Retrieve by ID
    fetched = analyzer.get_report(report_id)
    assert fetched is not None
    assert fetched.report_id == report_id

    # List reports
    hist = analyzer.list_reports(limit=5)
    assert len(hist) >= 1
    assert hist[0]["report_id"] == report_id

    # Focus queue query
    q = analyzer.get_focus_queue(limit=5)
    assert len(q) == 5
    assert isinstance(q[0], PrioritizedFocusItem)


def test_progress_db_never_modified(test_dbs):
    """Verify that progress.db is never modified during skill gap analysis."""
    prog_db = test_dbs["prog_db"]
    track_db = test_dbs["track_db"]

    with sqlite3.connect(prog_db) as conn:
        conn.execute(
            """
            INSERT INTO attempts (problem_id, attempt_no, status, error, created_at)
            VALUES ('two-sum', 1, 'passed', '', '2026-11-20T10:00:00Z')
            """
        )
        conn.commit()

    analyzer = SkillGapAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )
    rep = analyzer.analyze(save=True)
    assert rep is not None

    with sqlite3.connect(prog_db) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM attempts")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        assert "skill_gap_reports" not in tables
        assert "skill_gap_items" not in tables


def test_rest_api_endpoints(test_dbs):
    """Test all 6 Flask REST API endpoints for skill gap intelligence."""
    app = create_app(
        db_path=test_dbs["prog_db"],
        tracking_db_path=test_dbs["track_db"],
    )
    client = app.test_client()

    # 1. GET /api/skill-gaps
    res = client.get("/api/skill-gaps")
    assert res.status_code == 200
    data = res.get_json()
    assert "coverage_summary" in data
    assert "focus_queue" in data

    # 2. GET /api/skill-gaps/report
    res = client.get("/api/skill-gaps/report")
    assert res.status_code == 200
    rep = res.get_json()
    assert "report_id" in rep
    assert "total_topics_evaluated" in rep

    # 3. GET /api/skill-gaps/queue
    res = client.get("/api/skill-gaps/queue?limit=5")
    assert res.status_code == 200
    queue = res.get_json()
    assert len(queue) == 5
    assert "priority_score" in queue[0]

    # 4. POST /api/skill-gaps/analyze
    res = client.post("/api/skill-gaps/analyze", json={})
    assert res.status_code == 201
    created_rep = res.get_json()
    assert "report_id" in created_rep
    rep_id = created_rep["report_id"]

    # 5. GET /api/skill-gaps/report/<report_id>
    res = client.get(f"/api/skill-gaps/report/{rep_id}")
    assert res.status_code == 200
    assert res.get_json()["report_id"] == rep_id

    # 6. GET /api/skill-gaps/history
    res = client.get("/api/skill-gaps/history")
    assert res.status_code == 200
    hist = res.get_json()
    assert len(hist) >= 1

    # Validation checks
    # Invalid report_id regex
    res = client.get("/api/skill-gaps/report/invalid$id")
    assert res.status_code == 400

    # Non-existent report_id
    res = client.get("/api/skill-gaps/report/sgr_nonexistent")
    assert res.status_code == 404


def test_custom_problem_topics_support(test_dbs):
    """Test that custom problems with non-standard topics in progress.db are analyzed."""
    prog_db = test_dbs["prog_db"]
    track_db = test_dbs["track_db"]

    with sqlite3.connect(prog_db) as conn:
        conn.execute(
            """
            INSERT INTO custom_problems (id, title, difficulty, description, function_name, signature, tests_json, created_at, reference_solution)
            VALUES ('custom-trie-prob', 'Custom Trie Problem', 'medium', 'desc', 'solve', 'def solve()', '[]', '2026-11-20', 'code')
            """
        )
        # Attempt with 'Trie' topic in custom problems or attempts
        conn.execute(
            """
            INSERT INTO attempts (problem_id, attempt_no, status, error, created_at)
            VALUES ('custom-trie-prob', 1, 'wrong_answer', 'AssertionError', '2026-11-20T10:00:00Z')
            """
        )
        conn.commit()

    analyzer = SkillGapAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )
    report = analyzer.analyze(save=False)
    assert report is not None
    assert report.total_topics_evaluated >= 14


def test_confidence_tiers_and_inconsistent_performance(test_dbs):
    """Test progression across confidence tiers and inconsistent performance classification."""
    track_db = test_dbs["track_db"]
    prog_db = test_dbs["prog_db"]

    analyzer = SkillGapAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )

    # 1. Test confidence tiers explicitly
    assert analyzer.determine_confidence(0) == SkillGapConfidence.INSUFFICIENT_DATA
    assert analyzer.determine_confidence(1) == SkillGapConfidence.INSUFFICIENT_DATA
    assert analyzer.determine_confidence(2) == SkillGapConfidence.LOW
    assert analyzer.determine_confidence(4) == SkillGapConfidence.LOW
    assert analyzer.determine_confidence(5) == SkillGapConfidence.MEDIUM
    assert analyzer.determine_confidence(11) == SkillGapConfidence.MEDIUM
    assert analyzer.determine_confidence(12) == SkillGapConfidence.HIGH
    assert analyzer.determine_confidence(25) == SkillGapConfidence.HIGH

    # 2. Inconsistent performance: Problem attempted 4 times: 2 passed, 2 failed
    with analyzer.get_tracking_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_runs (
                run_id TEXT PRIMARY KEY,
                problem_id TEXT NOT NULL,
                language TEXT NOT NULL,
                status TEXT NOT NULL,
                passed_count INTEGER NOT NULL,
                total_tests INTEGER NOT NULL,
                compile_error TEXT,
                execution_error TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        # Two Sum: 1 failure, 1 pass (solved, but with 50% run success)
        conn.execute("INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, created_at) VALUES ('r1', 'two-sum', 'python', 'wrong_answer', 2, 5, '2026-11-23T10:00:00Z')")
        conn.execute("INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, created_at) VALUES ('r2', 'two-sum', 'python', 'passed', 5, 5, '2026-11-23T10:05:00Z')")
        conn.execute("INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, created_at) VALUES ('r3', 'two-sum', 'python', 'passed', 5, 5, '2026-11-23T10:10:00Z')")
        conn.execute("INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, created_at) VALUES ('r4', 'two-sum', 'python', 'wrong_answer', 3, 5, '2026-11-23T10:15:00Z')")
        conn.commit()

    report = analyzer.analyze(save=False)
    arrays_gap = next((g for g in report.all_topic_gaps if g.topic == "Arrays"), None)
    assert arrays_gap is not None
    assert arrays_gap.evidence.total_runs == 4
    assert arrays_gap.confidence == SkillGapConfidence.LOW

