"""Unit and integration tests for Milestone 6.3.23: Personal Coding Behavior Intelligence.

Validates:
- Empty database resilience and insufficient_data handling (zero division prevention).
- Attempt patterns analysis (first-attempt pass rate, attempts-per-problem, persistence rate).
- Debugging patterns analysis (error distributions, dominant error, compile vs runtime ratio).
- Problem-solving progression (difficulty distribution, topic fluency, complexity awareness).
- Session behavior metrics (completion vs abandonment, duration, pause pacing).
- Revision behavior metrics (adherence rate, overdue count, ease factor).
- Mock interview metrics (average scores, time management, consistency).
- Deterministic pattern detection (e.g. High First-Attempt Accuracy, Tenacious Debugger, Syntax Iteration).
- Insight generation with severity categorization and recommended actions.
- Previewable practice recommendations.
- Profile and report persistence, retrieval, and listing in session_tracking.db.
- Non-destructive operation (progress.db remains completely untouched).
- All 6 Flask REST API endpoints in dashboard_server.py.
- Input validation and regex sanitization.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.coding_behavior import (
    BehaviorAnalysisReport,
    BehaviorCategory,
    BehaviorEvidence,
    CodingBehaviorAnalyzer,
    CodingBehaviorInsight,
    CodingBehaviorPattern,
    CodingBehaviorProfile,
    InsightSeverity,
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
        conn.commit()

    return {"prog_db": prog_db, "track_db": track_db}


def test_empty_database_resilience(test_dbs):
    """Test analyzer behavior on a fresh, empty tracking and progress database."""
    analyzer = CodingBehaviorAnalyzer(
        tracking_db_path=test_dbs["track_db"],
        progress_db_path=test_dbs["prog_db"],
    )

    report = analyzer.analyze(save=True)
    assert report is not None
    assert isinstance(report, BehaviorAnalysisReport)

    profile = report.profile
    assert profile.total_evidence_events == 0
    assert profile.sample_adequate is False
    assert profile.confidence == "insufficient_data"
    assert profile.attempt_patterns["first_attempt_pass_rate"] == 0.0
    assert profile.attempt_patterns["avg_attempts_per_problem"] == 0.0
    assert profile.debugging_patterns["total_failures"] == 0
    assert profile.session_behavior["completion_rate"] == 0.0
    assert len(profile.limitations) > 0
    assert any("below the minimum threshold" in lim.lower() for lim in profile.limitations)

    # Check baseline insight generated
    assert len(report.insights) == 1
    assert report.insights[0].severity == InsightSeverity.INFO
    assert "baseline" in report.insights[0].title.lower()

    # Verify overview works
    overview = analyzer.get_overview()
    assert overview["confidence"] == "insufficient_data"
    assert overview["total_evidence_events"] == 0


def test_attempt_and_debugging_patterns(test_dbs):
    """Test attempt patterns and error distribution calculations."""
    track_db = test_dbs["track_db"]
    prog_db = test_dbs["prog_db"]

    analyzer = CodingBehaviorAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )

    # Insert test workspace runs in tracking DB
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
        # Problem 1: Two Sum -> passes on first attempt
        conn.execute(
            """
            INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, suggested_next_action, created_at)
            VALUES ('run_1', 'two-sum', 'python', 'passed', 5, 5, 'done', '2026-11-20T10:00:00Z')
            """
        )
        # Problem 2: Reverse Linked List -> compile error, then wrong answer, then passed (persisted!)
        conn.execute(
            """
            INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, suggested_next_action, created_at)
            VALUES ('run_2', 'reverse-linked-list', 'python', 'compile_error', 0, 5, 'fix syntax', '2026-11-20T11:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, suggested_next_action, created_at)
            VALUES ('run_3', 'reverse-linked-list', 'python', 'wrong_answer', 3, 5, 'fix edge case', '2026-11-20T11:05:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, suggested_next_action, created_at)
            VALUES ('run_4', 'reverse-linked-list', 'python', 'passed', 5, 5, 'done', '2026-11-20T11:10:00Z')
            """
        )
        # Problem 3: Valid Palindrome -> compile error, then compile error (unresolved)
        conn.execute(
            """
            INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, suggested_next_action, created_at)
            VALUES ('run_5', 'valid-palindrome', 'python', 'compile_error', 0, 5, 'fix syntax', '2026-11-20T12:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, suggested_next_action, created_at)
            VALUES ('run_6', 'valid-palindrome', 'python', 'compile_error', 0, 5, 'fix syntax', '2026-11-20T12:05:00Z')
            """
        )
        conn.commit()

    report = analyzer.analyze(save=True)
    prof = report.profile

    assert prof.total_evidence_events >= 6
    assert prof.sample_adequate is True

    # 3 distinct problems attempted
    att = prof.attempt_patterns
    assert att["total_problems_attempted"] == 3
    # 1 of 3 passed on first attempt -> 33.3%
    assert att["first_attempt_pass_rate"] == 33.3
    # 2 problems failed initially: reverse-linked-list and valid-palindrome
    # reverse-linked-list was eventually solved, valid-palindrome was not -> 1 of 2 = 50.0% persistence
    assert att["problems_failed_initially"] == 2
    assert att["persistence_rate"] == 50.0

    # Debugging checks
    dbg = prof.debugging_patterns
    assert dbg["total_failures"] == 4
    assert dbg["error_distribution"]["compile_error"] == 3
    assert dbg["error_distribution"]["wrong_answer"] == 1
    assert dbg["dominant_error"] == "compile_error"


def test_session_and_complexity_behavior(test_dbs):
    """Test session completion, pacing, and complexity awareness analysis."""
    track_db = test_dbs["track_db"]
    prog_db = test_dbs["prog_db"]

    analyzer = CodingBehaviorAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )

    with analyzer.get_tracking_connection() as conn:
        # Create practice_sessions table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS practice_sessions (
                session_id TEXT PRIMARY KEY,
                plan_id TEXT,
                task_id TEXT,
                task_title TEXT,
                task_type TEXT,
                problem_id TEXT,
                language TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                paused_at TEXT,
                ended_at TEXT,
                elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                submissions_count INTEGER NOT NULL DEFAULT 0,
                passed_submissions_count INTEGER NOT NULL DEFAULT 0,
                failed_submissions_count INTEGER NOT NULL DEFAULT 0,
                final_submission_passed INTEGER NOT NULL DEFAULT 0,
                task_confirmed_completed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS practice_session_notes (
                session_id TEXT PRIMARY KEY,
                initial_approach TEXT NOT NULL DEFAULT '',
                mistakes_encountered TEXT NOT NULL DEFAULT '',
                hints_used TEXT NOT NULL DEFAULT '',
                final_approach TEXT NOT NULL DEFAULT '',
                time_complexity TEXT NOT NULL DEFAULT '',
                space_complexity TEXT NOT NULL DEFAULT '',
                key_learning TEXT NOT NULL DEFAULT '',
                follow_up_action TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS practice_session_events (
                event_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )

        # 3 sessions: 2 completed (1200s, 600s), 1 abandoned (300s)
        conn.execute(
            """
            INSERT INTO practice_sessions (session_id, language, status, created_at, elapsed_seconds)
            VALUES ('sess_1', 'python', 'completed', '2026-11-21T10:00:00Z', 1200)
            """
        )
        conn.execute(
            """
            INSERT INTO practice_sessions (session_id, language, status, created_at, elapsed_seconds)
            VALUES ('sess_2', 'python', 'completed', '2026-11-21T14:00:00Z', 600)
            """
        )
        conn.execute(
            """
            INSERT INTO practice_sessions (session_id, language, status, created_at, elapsed_seconds)
            VALUES ('sess_3', 'python', 'abandoned', '2026-11-21T18:00:00Z', 300)
            """
        )

        # Notes: sess_1 has complexity, sess_2 does not
        conn.execute(
            """
            INSERT INTO practice_session_notes (session_id, time_complexity, space_complexity)
            VALUES ('sess_1', 'O(n)', 'O(1)')
            """
        )
        conn.execute(
            """
            INSERT INTO practice_session_notes (session_id, time_complexity, space_complexity)
            VALUES ('sess_2', '', '')
            """
        )

        # Events: 2 pause events in sess_1
        conn.execute("INSERT INTO practice_session_events VALUES ('ev_1', 'sess_1', 'pause', '2026-11-21T10:10:00Z')")
        conn.execute("INSERT INTO practice_session_events VALUES ('ev_2', 'sess_1', 'pause', '2026-11-21T10:15:00Z')")
        conn.commit()

    report = analyzer.analyze(save=True)
    sess_met = report.profile.session_behavior
    assert sess_met["total_sessions"] == 3
    assert sess_met["completed_count"] == 2
    assert sess_met["abandoned_count"] == 1
    assert sess_met["completion_rate"] == 66.7
    assert sess_met["abandonment_rate"] == 33.3
    # Total elapsed: 2100s / 3 = 700s = 11.7 min
    assert sess_met["avg_session_duration_minutes"] == 11.7
    # 2 pauses across 3 sessions = 0.7
    assert sess_met["avg_pauses_per_session"] == 0.7

    # Complexity awareness: 1 note with complexity out of 2 notes = 50.0%
    psp = report.profile.problem_solving_progression
    assert psp["complexity_awareness_rate"] == 50.0


def test_revision_and_interview_behavior(test_dbs):
    """Test revision backlog and mock interview trend calculations."""
    track_db = test_dbs["track_db"]
    prog_db = test_dbs["prog_db"]

    analyzer = CodingBehaviorAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )

    with analyzer.get_tracking_connection() as conn:
        # revision_items
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS revision_items (
                problem_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                topics_json TEXT NOT NULL,
                next_review_at TEXT NOT NULL,
                interval_days INTEGER NOT NULL,
                repetition_count INTEGER NOT NULL,
                ease_factor REAL NOT NULL,
                status TEXT NOT NULL,
                last_outcome TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO revision_items (problem_id, title, difficulty, topics_json, next_review_at, interval_days, repetition_count, ease_factor, status)
            VALUES ('two-sum', 'Two Sum', 'Easy', '["array"]', '2026-11-20', 3, 2, 2.5, 'reviewed')
            """
        )
        conn.execute(
            """
            INSERT INTO revision_items (problem_id, title, difficulty, topics_json, next_review_at, interval_days, repetition_count, ease_factor, status)
            VALUES ('reverse-linked-list', 'Reverse Linked List', 'Easy', '["linked-list"]', '2026-11-15', 1, 1, 2.2, 'overdue')
            """
        )
        conn.execute(
            """
            INSERT INTO revision_items (problem_id, title, difficulty, topics_json, next_review_at, interval_days, repetition_count, ease_factor, status)
            VALUES ('lru-cache', 'LRU Cache', 'Medium', '["hash-table"]', '2026-11-10', 1, 1, 2.1, 'overdue')
            """
        )

        # mock_interviews
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mock_interviews (
                interview_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                track TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                language TEXT NOT NULL,
                status TEXT NOT NULL,
                total_score REAL,
                correctness_score REAL,
                completion_score REAL,
                structure_score REAL,
                complexity_score REAL,
                time_management_score REAL,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO mock_interviews (interview_id, title, track, duration_minutes, language, status, total_score, correctness_score, time_management_score, complexity_score, created_at)
            VALUES ('int_1', 'Practice Interview', 'intermediate', 45, 'python', 'completed', 85.0, 36.0, 9.0, 12.0, '2026-11-22T10:00:00Z')
            """
        )
        conn.commit()

    report = analyzer.analyze(save=True)

    # Revision metrics: 3 total items, 2 overdue -> 33.3% adherence
    rev_met = report.profile.revision_behavior
    assert rev_met["total_tracked_items"] == 3
    assert rev_met["overdue_count"] == 2
    assert rev_met["adherence_rate"] == 33.3

    # Interview metrics: 1 interview completed with 85.0 score
    int_met = report.profile.interview_behavior
    assert int_met["total_interviews"] == 1
    assert int_met["completed_count"] == 1
    assert int_met["avg_score"] == 85.0


def test_pattern_detection_and_recommendations(test_dbs):
    """Test deterministic pattern detection and structured previewable recommendations."""
    track_db = test_dbs["track_db"]
    prog_db = test_dbs["prog_db"]

    analyzer = CodingBehaviorAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )

    # Populate 4 problems: all passed on first try
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
        for i in range(1, 5):
            conn.execute(
                f"""
                INSERT INTO workspace_runs (run_id, problem_id, language, status, passed_count, total_tests, suggested_next_action, created_at)
                VALUES ('run_{i}', 'prob_{i}', 'python', 'passed', 5, 5, 'done', '2026-11-23T10:0{i}:00Z')
                """
            )
        conn.commit()

    report = analyzer.analyze(save=True)
    patterns = report.profile.patterns
    assert any("High First-Attempt Accuracy" in p.name for p in patterns)

    # Recommendations preview
    assert len(report.recommendations) > 0
    rec = report.recommendations[0]
    assert "priority" in rec
    assert "suggested_action" in rec
    assert "rationale" in rec


def test_persistence_and_queries(test_dbs):
    """Test storing and querying reports, profiles, and filtered insights."""
    track_db = test_dbs["track_db"]
    prog_db = test_dbs["prog_db"]

    analyzer = CodingBehaviorAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )

    rep1 = analyzer.analyze(save=True)
    assert rep1.report_id is not None

    # Fetch latest profile
    latest_prof = analyzer.get_latest_profile()
    assert latest_prof is not None
    assert latest_prof.profile_id == rep1.profile.profile_id

    # Fetch report by ID
    fetched_rep = analyzer.get_report(rep1.report_id)
    assert fetched_rep is not None
    assert fetched_rep.report_id == rep1.report_id
    assert fetched_rep.profile.profile_id == rep1.profile.profile_id

    # List reports
    rep_list = analyzer.list_reports(limit=5)
    assert len(rep_list) >= 1
    assert rep_list[0]["report_id"] == rep1.report_id

    # Query insights
    insights = analyzer.get_insights(limit=10)
    assert isinstance(insights, list)


def test_rest_api_endpoints(test_dbs):
    """Test Flask REST API routes for coding behavior intelligence."""
    app = create_app(
        db_path=test_dbs["prog_db"],
        tracking_db_path=test_dbs["track_db"],
    )
    client = app.test_client()

    # 1. GET /api/coding-behavior
    res = client.get("/api/coding-behavior")
    assert res.status_code == 200
    data = res.get_json()
    assert "profile_id" in data
    assert "confidence" in data
    assert "total_evidence_events" in data

    # 2. GET /api/coding-behavior/profile
    res = client.get("/api/coding-behavior/profile")
    assert res.status_code == 200
    prof = res.get_json()
    assert "attempt_patterns" in prof
    assert "debugging_patterns" in prof

    # 3. POST /api/coding-behavior/analyze
    res = client.post("/api/coding-behavior/analyze", json={})
    assert res.status_code == 201
    rep_data = res.get_json()
    assert "report_id" in rep_data
    report_id = rep_data["report_id"]

    # 4. GET /api/coding-behavior/report/<report_id>
    res = client.get(f"/api/coding-behavior/report/{report_id}")
    assert res.status_code == 200
    single_rep = res.get_json()
    assert single_rep["report_id"] == report_id

    # 5. GET /api/coding-behavior/history
    res = client.get("/api/coding-behavior/history")
    assert res.status_code == 200
    hist = res.get_json()
    assert len(hist) >= 1

    # 6. GET /api/coding-behavior/insights
    res = client.get("/api/coding-behavior/insights")
    assert res.status_code == 200
    ins_list = res.get_json()
    assert isinstance(ins_list, list)

    # Validation & Error checks
    # Invalid report_id regex
    res = client.get("/api/coding-behavior/report/invalid$id")
    assert res.status_code == 400

    # Non-existent report_id
    res = client.get("/api/coding-behavior/report/cbr_nonexistent")
    assert res.status_code == 404

    # Invalid category query param regex
    res = client.get("/api/coding-behavior/insights?category=bad$cat")
    assert res.status_code == 400


def test_progress_db_non_destructive(test_dbs):
    """Explicitly verify that progress.db is never written to during behavior analysis."""
    prog_db = test_dbs["prog_db"]
    track_db = test_dbs["track_db"]

    # Insert a dummy attempt in progress.db
    with sqlite3.connect(prog_db) as conn:
        conn.execute(
            """
            INSERT INTO attempts (problem_id, attempt_no, status, error, created_at)
            VALUES ('two-sum', 1, 'passed', '', '2026-11-25T10:00:00Z')
            """
        )
        conn.commit()

    # Record md5 / size of progress.db
    size_before = prog_db.stat().st_size
    mtime_before = prog_db.stat().st_mtime_ns

    analyzer = CodingBehaviorAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )
    report = analyzer.analyze(save=True)
    assert report is not None

    # Verify progress.db table content is identical
    with sqlite3.connect(prog_db) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM attempts")
        count = cur.fetchone()[0]
        assert count == 1
        # Verify no new tables were created in progress.db
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        assert "coding_behavior_profiles" not in tables
        assert "coding_behavior_reports" not in tables
        assert "coding_behavior_insights" not in tables


def test_insights_filtering_and_confidence_tiers(test_dbs):
    """Test filtering insights by category/severity and confidence tier progression."""
    prog_db = test_dbs["prog_db"]
    track_db = test_dbs["track_db"]

    analyzer = CodingBehaviorAnalyzer(
        tracking_db_path=track_db,
        progress_db_path=prog_db,
    )

    # With 0 events: insufficient_data
    report_empty = analyzer.analyze(save=True)
    assert report_empty.profile.confidence == "insufficient_data"

    # Filter insights by severity INFO
    info_insights = analyzer.get_insights(severity="info")
    assert len(info_insights) >= 1
    assert all(ins.severity == InsightSeverity.INFO for ins in info_insights)

    # Filter insights by category ATTEMPT_PATTERN
    att_insights = analyzer.get_insights(category="attempt_pattern")
    assert len(att_insights) >= 1
    assert all(ins.category == BehaviorCategory.ATTEMPT_PATTERN for ins in att_insights)

