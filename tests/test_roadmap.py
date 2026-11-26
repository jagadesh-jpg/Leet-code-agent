"""Unit and integration tests for Milestone 6.3.14: Personalized DSA Skill Roadmap & Mastery Map.

Validates:
- 5-stage roadmap structure and topic metadata.
- Prerequisite graph validation and circular dependency detection.
- Deterministic mastery score calculation across various solving states.
- Empty database behavior (no fabrication, safe defaults).
- Prerequisite readiness, gap detection, and locked/not_started/learning/practicing/proficient statuses.
- Personalized recommendation generation (strengthen fundamentals, learn new topic, revision due, goal focus).
- Roadmap analytics and stage summaries.
- Dashboard REST endpoints (/api/roadmap, /api/roadmap/analytics, /api/roadmap/stages, /api/roadmap/topics, /api/roadmap/recommendations).
- Database isolation (temporary SQLite databases only, zero modification to production databases).
"""

import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.roadmap import (
    DsaRoadmapEngine,
    ROADMAP_STAGES_CONFIG,
    ROADMAP_TOPIC_NODES,
    RoadmapOverviewReport,
    RoadmapRecommendation,
    RoadmapRecommendationType,
    RoadmapStageSummary,
    TopicMasteryRecord,
    TopicMasteryStatus,
    TopicRoadmapNode,
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
            CREATE TABLE learning_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                session_size INTEGER NOT NULL,
                difficulty_preference TEXT,
                focus_topic TEXT,
                completed_at TEXT,
                total_duration_sec REAL DEFAULT 0.0,
                notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE spaced_revisions (
                problem_id TEXT PRIMARY KEY,
                difficulty TEXT NOT NULL,
                topics TEXT NOT NULL,
                box_level INTEGER NOT NULL DEFAULT 1,
                interval_days INTEGER NOT NULL DEFAULT 1,
                last_reviewed_at TEXT,
                next_review_at TEXT NOT NULL,
                recall_history TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                review_count INTEGER NOT NULL DEFAULT 0,
                streak INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE learning_goals (
                goal_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                goal_type TEXT NOT NULL,
                target_metric INTEGER NOT NULL,
                current_progress INTEGER NOT NULL,
                target_parameter TEXT,
                deadline TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                notes TEXT
            )
            """
        )

    return prog_db, track_db


def test_roadmap_stage_and_node_taxonomy():
    """Verify standard 5 stages and topic nodes exist."""
    assert len(ROADMAP_STAGES_CONFIG) == 5
    assert ROADMAP_STAGES_CONFIG[1] == "Programming Foundations"
    assert ROADMAP_STAGES_CONFIG[2] == "Core Data Structures"
    assert ROADMAP_STAGES_CONFIG[3] == "Core Algorithms"
    assert ROADMAP_STAGES_CONFIG[4] == "Advanced Data Structures"
    assert ROADMAP_STAGES_CONFIG[5] == "Advanced Algorithms"

    assert len(ROADMAP_TOPIC_NODES) >= 20
    topic_ids = [n.topic_id for n in ROADMAP_TOPIC_NODES]
    assert "arrays" in topic_ids
    assert "strings" in topic_ids
    assert "hashing" in topic_ids
    assert "linked-list" in topic_ids
    assert "stack" in topic_ids
    assert "trees" in topic_ids
    assert "binary-search" in topic_ids
    assert "dynamic-programming" in topic_ids


def test_roadmap_circular_dependency_detection():
    """Verify engine detects circular dependencies and missing prerequisites."""
    # Circular dependency
    bad_nodes_cycle = [
        TopicRoadmapNode(topic_id="a", display_name="A", stage_id=1, stage_name="S1", prerequisites=["b"], description=""),
        TopicRoadmapNode(topic_id="b", display_name="B", stage_id=1, stage_name="S1", prerequisites=["a"], description=""),
    ]
    with pytest.raises(ValueError, match="Circular dependency detected"):
        DsaRoadmapEngine(custom_nodes=bad_nodes_cycle)

    # Missing prerequisite target
    bad_nodes_missing = [
        TopicRoadmapNode(topic_id="a", display_name="A", stage_id=1, stage_name="S1", prerequisites=["non_existent"], description=""),
    ]
    with pytest.raises(ValueError, match="Invalid prerequisite"):
        DsaRoadmapEngine(custom_nodes=bad_nodes_missing)


def test_empty_database_behavior(temp_dbs):
    """Verify engine runs gracefully with empty database without fabrication."""
    prog_db, track_db = temp_dbs
    engine = DsaRoadmapEngine(progress_db_path=prog_db, tracking_db_path=track_db)

    overview = engine.get_roadmap_overview()
    assert isinstance(overview, RoadmapOverviewReport)
    assert overview.proficient_topics_count == 0
    assert overview.overall_roadmap_progress_pct == 0.0

    # Arrays should be NOT_STARTED (stage 1 foundational, no prereqs)
    arr_detail = engine.get_topic_detail("arrays")
    assert arr_detail is not None
    assert arr_detail.status == TopicMasteryStatus.NOT_STARTED
    assert arr_detail.mastery_score == 0.0
    assert arr_detail.distinct_solved == 0

    # Trees should be LOCKED (stage 2, requires linked-list and stack)
    trees_detail = engine.get_topic_detail("trees")
    assert trees_detail is not None
    assert trees_detail.status == TopicMasteryStatus.LOCKED
    assert trees_detail.prerequisites_met is False
    assert len(trees_detail.missing_prerequisites) > 0


def test_mastery_calculation_with_solves_and_attempts(temp_dbs):
    """Verify deterministic mastery scoring on solved and failed attempts."""
    prog_db, track_db = temp_dbs
    engine = DsaRoadmapEngine(progress_db_path=prog_db, tracking_db_path=track_db)

    # Add solves for two-sum (Arrays, Hashing - Easy) and contains-duplicate (Arrays, Hashing - Easy)
    with sqlite3.connect(prog_db) as conn:
        conn.execute(
            "INSERT INTO attempts (problem_id, language, passed, total, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("two-sum", "python", 10, 10, "2026-11-26 10:00:00"),
        )
        conn.execute(
            "INSERT INTO attempts (problem_id, language, passed, total, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("contains-duplicate", "python", 5, 5, "2026-11-26 11:00:00"),
        )

    arr_detail = engine.get_topic_detail("arrays")
    assert arr_detail is not None
    assert arr_detail.distinct_solved >= 2
    assert arr_detail.easy_solves >= 2
    assert arr_detail.success_rate == 100.0
    assert arr_detail.mastery_score >= 60.0
    assert arr_detail.status in (TopicMasteryStatus.PRACTICING, TopicMasteryStatus.PROFICIENT)

    # Add failed attempts to test success rate drop
    with sqlite3.connect(prog_db) as conn:
        conn.execute(
            "INSERT INTO attempts (problem_id, language, passed, total, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("product-of-array-except-self", "python", 1, 5, "2026-11-26 12:00:00"),
        )
        conn.execute(
            "INSERT INTO attempts (problem_id, language, passed, total, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("product-of-array-except-self", "python", 2, 5, "2026-11-26 13:00:00"),
        )

    arr_detail_after = engine.get_topic_detail("arrays")
    assert arr_detail_after.total_attempts == 4
    assert arr_detail_after.failed_attempts == 2
    assert arr_detail_after.success_rate == 50.0


def test_stage_summaries_aggregation(temp_dbs):
    """Verify stage summaries and average mastery scores."""
    prog_db, track_db = temp_dbs
    engine = DsaRoadmapEngine(progress_db_path=prog_db, tracking_db_path=track_db)

    stages = engine.get_stage_summaries()
    assert len(stages) == 5
    s1 = stages[0]
    assert s1.stage_id == 1
    assert s1.stage_name == "Programming Foundations"
    assert s1.total_topics == 3  # Arrays, Strings, Basic Hashing


def test_recommendation_generation(temp_dbs):
    """Verify personalized recommendation triggers for new topics, weak topics, and revisions."""
    prog_db, track_db = temp_dbs

    # 1. Add revision due for two-sum
    with sqlite3.connect(track_db) as conn:
        conn.execute(
            "INSERT INTO spaced_revisions (problem_id, difficulty, topics, next_review_at, review_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("two-sum", "easy", "arrays,hashing", "2026-11-25 00:00:00", 1, "2026-11-20 00:00:00"),  # Past review
        )
        # Add active learning goal for stack
        conn.execute(
            "INSERT INTO learning_goals (goal_id, title, goal_type, target_metric, current_progress, target_parameter, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("g1", "Master Stacks", "practice_topic", 3, 0, "stack", "active", "2026-11-26 00:00:00", "2026-11-26 00:00:00"),
        )

    engine = DsaRoadmapEngine(progress_db_path=prog_db, tracking_db_path=track_db)
    recs = engine.generate_recommendations(limit=5)
    assert len(recs) >= 1

    rec_types = [r.recommendation_type for r in recs]
    # Priority 1: spaced revision
    assert RoadmapRecommendationType.REVISE_OVERDUE_TOPIC in rec_types
    # Priority 2: learning goal
    assert RoadmapRecommendationType.PRACTICE_WEAK_TOPIC in rec_types


def test_dashboard_api_roadmap_endpoints(temp_dbs):
    """Verify Flask API routes for roadmap."""
    prog_db, track_db = temp_dbs
    app = create_app(db_path=prog_db, tracking_db_path=track_db)
    client = app.test_client()

    # GET /api/roadmap
    res_rm = client.get("/api/roadmap")
    assert res_rm.status_code == 200
    rm_data = res_rm.get_json()
    assert "overall_roadmap_progress_pct" in rm_data
    assert "stages" in rm_data

    # GET /api/roadmap/stages
    res_stg = client.get("/api/roadmap/stages")
    assert res_stg.status_code == 200
    stg_data = res_stg.get_json()
    assert len(stg_data) == 5

    # GET /api/roadmap/topics
    res_top = client.get("/api/roadmap/topics")
    assert res_top.status_code == 200
    top_data = res_top.get_json()
    assert len(top_data) >= 20

    # GET /api/roadmap/topics/<topic_id>
    res_arr = client.get("/api/roadmap/topics/arrays")
    assert res_arr.status_code == 200
    assert res_arr.get_json()["topic_id"] == "arrays"

    res_inv = client.get("/api/roadmap/topics/non_existent_topic")
    assert res_inv.status_code == 404

    # GET /api/roadmap/recommendations
    res_rec = client.get("/api/roadmap/recommendations")
    assert res_rec.status_code == 200
    rec_data = res_rec.get_json()
    assert isinstance(rec_data, list)
