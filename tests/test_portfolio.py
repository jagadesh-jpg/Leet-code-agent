"""Unit and integration tests for Milestone 6.3.18: Personal Learning Portfolio & Progress Report Generator.

Validates:
- Evidence aggregation across all local subsystems:
    - Coding statistics and verified problem solves.
    - Difficulty and programming language distributions.
    - DSA Roadmap progress and topic mastery.
    - Practice consistency (sessions, daily missions, revisions, streaks).
    - Goal completion and unlocked milestone achievements.
    - Code quality review statistics (readability, structural, complexity awareness).
    - Chronological timeline events and executive summary.
- Profile and presentation personalization:
    - Learner name, portfolio title, objectives, skills to highlight.
    - Report style variants (developer_portfolio, dsa_progress, weekly_summary, monthly_report, goal_completion).
    - Date range presets (all_time, last_7_days, last_30_days, last_90_days, custom).
- Export formats and safe filesystem containment:
    - Markdown rendering (GitHub-Flavored Markdown tables and sections).
    - JSON serialization and deserialization.
    - Standalone HTML generation with embedded styling.
    - Path traversal prevention and filename sanitization.
    - Export history listing and retrieval.
- Dashboard API endpoints:
    - GET /api/portfolio
    - GET /api/portfolio/preview
    - POST /api/portfolio/config
    - POST /api/portfolio/generate
    - GET /api/portfolio/history
    - GET /api/portfolio/export/<export_id>
- Isolation and security:
    - Zero external network or API calls.
    - Progress.db is strictly read-only.
    - All tests use isolated temporary SQLite databases.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import pytest

from dashboard_server import create_app
from intelligence.portfolio import (
    CodingStatistics,
    ConsistencyMetrics,
    DsaMasterySummary,
    GoalAchievementSummary,
    LearningJourneyEvent,
    LearningPortfolioReport,
    PortfolioConfig,
    PortfolioManager,
    SolutionQualitySummary,
)


@pytest.fixture
def temp_environment(tmp_path):
    """Create isolated temporary progress.db, session_tracking.db, and exports directory."""
    prog_db = tmp_path / "test_progress.db"
    track_db = tmp_path / "test_session_tracking.db"
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    # Initialize progress.db schema
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
        conn.commit()

    # Seed some sample attempts
    now = datetime.now(timezone.utc)
    with sqlite3.connect(prog_db) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO attempts (problem_id, language, passed, total, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("two-sum", "python", 2, 2, (now - timedelta(days=2)).isoformat()),
        )
        cur.execute(
            "INSERT INTO attempts (problem_id, language, passed, total, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("valid-anagram", "python", 2, 2, (now - timedelta(days=1)).isoformat()),
        )
        cur.execute(
            "INSERT INTO attempts (problem_id, language, passed, total, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("3sum", "python", 1, 3, now.isoformat()),  # Failed attempt
        )
        conn.commit()

    return {
        "prog_db": prog_db,
        "track_db": track_db,
        "exports_dir": exports_dir,
    }


def test_portfolio_schema_initialization(temp_environment):
    """Verify portfolio tables are created in session_tracking.db without error."""
    mgr = PortfolioManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
        exports_dir=temp_environment["exports_dir"],
    )
    with sqlite3.connect(temp_environment["track_db"]) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "portfolio_configs" in tables
        assert "portfolio_exports" in tables


def test_config_save_and_retrieve(temp_environment):
    """Verify customized profile settings are persisted and reloaded correctly."""
    mgr = PortfolioManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
        exports_dir=temp_environment["exports_dir"],
    )

    # Default config initially
    default_cfg = mgr.get_saved_config()
    assert default_cfg.learner_name == "Learner"
    assert default_cfg.portfolio_title == "Developer Learning Portfolio"

    # Custom config
    custom_cfg = PortfolioConfig(
        learner_name="Alex Rivera",
        portfolio_title="Senior DSA Practice Portfolio",
        introduction="Focused algorithmic study with emphasis on Dynamic Programming and Graphs.",
        primary_language="python",
        learning_objectives=["Achieve 80% mastery across core roadmap", "Solve 50 hard problems"],
        skills_to_highlight=["Python", "Dynamic Programming", "Trees"],
        report_style="dsa_progress",
        date_range_preset="last_30_days",
    )
    mgr.save_config(custom_cfg)

    reloaded = mgr.get_saved_config()
    assert reloaded.learner_name == "Alex Rivera"
    assert reloaded.portfolio_title == "Senior DSA Practice Portfolio"
    assert "Dynamic Programming" in reloaded.introduction
    assert reloaded.report_style == "dsa_progress"
    assert reloaded.date_range_preset == "last_30_days"
    assert "Trees" in reloaded.skills_to_highlight


def test_evidence_aggregation_empty_db(tmp_path):
    """Verify aggregation handles completely empty databases gracefully without division by zero."""
    empty_prog = tmp_path / "empty_prog.db"
    empty_track = tmp_path / "empty_track.db"
    exports_dir = tmp_path / "exports"

    mgr = PortfolioManager(
        tracking_db_path=empty_track,
        progress_db_path=empty_prog,
        exports_dir=exports_dir,
    )
    report = mgr.aggregate_evidence()

    assert isinstance(report, LearningPortfolioReport)
    assert report.coding_stats.total_verified_solved == 0
    assert report.coding_stats.easy_count == 0
    assert report.coding_stats.total_attempts_logged == 0
    assert report.solution_quality.total_reviews_logged == 0
    assert report.solution_quality.average_readability_score == 0.0
    assert report.consistency.completed_sessions_count == 0
    assert "0 verified problems solved" in report.executive_summary


def test_evidence_aggregation_populated(temp_environment):
    """Verify aggregated metrics accurately reflect recorded evidence."""
    mgr = PortfolioManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
        exports_dir=temp_environment["exports_dir"],
    )

    report = mgr.aggregate_evidence()

    # Solves
    assert report.coding_stats.total_verified_solved == 2
    assert report.coding_stats.total_attempts_logged == 3
    assert report.coding_stats.failed_attempts_count == 1
    assert report.coding_stats.languages_used.get("python") == 2

    # Roadmap
    assert report.dsa_mastery.total_roadmap_topics > 0
    assert isinstance(report.dsa_mastery.overall_roadmap_progress_pct, float)

    # Timeline has events
    assert len(report.timeline) > 0
    assert any(e.event_type == "problem_solved" for e in report.timeline)

    # Executive summary
    assert "2 verified problems solved" in report.executive_summary


def test_date_range_filtering(temp_environment):
    """Verify date boundaries properly isolate events within time windows."""
    mgr = PortfolioManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
        exports_dir=temp_environment["exports_dir"],
    )

    # All-time includes both solves
    all_time_cfg = PortfolioConfig(date_range_preset="all_time")
    rep_all = mgr.aggregate_evidence(all_time_cfg)
    assert rep_all.coding_stats.total_verified_solved == 2

    # Custom range for tomorrow should yield 0 solves
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    next_week = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
    future_cfg = PortfolioConfig(
        date_range_preset="custom",
        start_date=tomorrow,
        end_date=next_week,
    )
    rep_future = mgr.aggregate_evidence(future_cfg)
    assert rep_future.coding_stats.total_verified_solved == 0


def test_report_formats_rendering(temp_environment):
    """Verify Markdown, JSON, and HTML renderers produce valid, non-empty outputs."""
    mgr = PortfolioManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
        exports_dir=temp_environment["exports_dir"],
    )
    report = mgr.aggregate_evidence()

    # Markdown
    md_output = mgr.render_markdown(report)
    assert f"# {report.config.portfolio_title}" in md_output
    assert "## 1. Executive Summary" in md_output
    assert "## 2. Verified Coding Statistics" in md_output
    assert "Total Solved Problems" in md_output

    # JSON
    json_output = mgr.render_json(report)
    parsed = json.loads(json_output)
    assert parsed["report_id"] == report.report_id
    assert parsed["coding_stats"]["total_verified_solved"] == 2
    assert "dsa_mastery" in parsed

    # HTML
    html_output = mgr.render_html(report)
    assert "<!DOCTYPE html>" in html_output
    assert "<title>" in html_output
    assert report.config.portfolio_title in html_output
    assert "Verified Problem Solving" in html_output


def test_safe_export_containment_and_history(temp_environment):
    """Verify export file is saved in designated directory, path traversal is blocked, and exports are tracked."""
    mgr = PortfolioManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
        exports_dir=temp_environment["exports_dir"],
    )
    report = mgr.aggregate_evidence()

    # Successful export
    export_res = mgr.export_portfolio(report, format_type="markdown", custom_filename="my_test_report")
    assert export_res["filename"] == "my_test_report.md"
    assert Path(export_res["filepath"]).is_file()
    assert Path(export_res["filepath"]).parent.resolve() == temp_environment["exports_dir"].resolve()

    # Check database export record
    exports_list = mgr.list_exports()
    assert len(exports_list) == 1
    assert exports_list[0]["export_id"] == export_res["export_id"]

    # Retrieve export file
    retrieved = mgr.get_export_file(export_res["export_id"])
    assert retrieved is not None
    assert retrieved[0] == "my_test_report.md"
    assert retrieved[2] == "markdown"

    # HTML export
    html_res = mgr.export_portfolio(report, format_type="html")
    assert html_res["filename"].endswith(".html")
    assert Path(html_res["filepath"]).is_file()

    # JSON export
    json_res = mgr.export_portfolio(report, format_type="json")
    assert json_res["filename"].endswith(".json")
    assert Path(json_res["filepath"]).is_file()

    # Path traversal attack attempt in custom_filename
    traversal_res = mgr.export_portfolio(report, format_type="markdown", custom_filename="../../../bad_path")
    # Sanitizer replaces slashes and periods, containing it within exports_dir
    assert Path(traversal_res["filepath"]).parent.resolve() == temp_environment["exports_dir"].resolve()
    assert ".." not in traversal_res["filename"]


def test_dashboard_portfolio_endpoints(temp_environment):
    """Verify all 6 Flask dashboard endpoints for portfolio management."""
    app = create_app(
        db_path=temp_environment["prog_db"],
        tracking_db_path=temp_environment["track_db"],
    )
    client = app.test_client()

    # 1. GET /api/portfolio
    res_root = client.get("/api/portfolio")
    assert res_root.status_code == 200
    root_data = res_root.get_json()
    assert root_data["status"] == "ready"
    assert "report" in root_data
    assert root_data["report"]["coding_stats"]["total_verified_solved"] == 2

    # 2. GET /api/portfolio/preview
    res_prev = client.get("/api/portfolio/preview?report_style=dsa_progress&date_preset=all_time")
    assert res_prev.status_code == 200
    prev_data = res_prev.get_json()
    assert prev_data["config"]["report_style"] == "dsa_progress"
    assert "report" in prev_data

    # 3. POST /api/portfolio/config
    res_cfg = client.post(
        "/api/portfolio/config",
        json={
            "learner_name": "Jordan Lee",
            "portfolio_title": "Full-Stack DSA Portfolio",
            "report_style": "weekly_summary",
        },
    )
    assert res_cfg.status_code == 200
    cfg_data = res_cfg.get_json()
    assert cfg_data["config"]["learner_name"] == "Jordan Lee"
    assert cfg_data["config"]["portfolio_title"] == "Full-Stack DSA Portfolio"

    # 4. POST /api/portfolio/generate
    res_gen = client.post(
        "/api/portfolio/generate",
        json={
            "format": "markdown",
            "report_style": "weekly_summary",
            "filename": "weekly_report_jordan",
        },
    )
    assert res_gen.status_code == 201
    gen_data = res_gen.get_json()
    assert "export_id" in gen_data
    assert gen_data["filename"] == "weekly_report_jordan.md"
    export_id = gen_data["export_id"]

    # 5. GET /api/portfolio/history
    res_hist = client.get("/api/portfolio/history")
    assert res_hist.status_code == 200
    hist_data = res_hist.get_json()
    assert len(hist_data) >= 1
    assert hist_data[0]["export_id"] == export_id

    # 6. GET /api/portfolio/export/<export_id>
    res_dl = client.get(f"/api/portfolio/export/{export_id}")
    assert res_dl.status_code == 200
    assert res_dl.content_type.startswith("text/markdown")
    assert b"# Full-Stack DSA Portfolio" in res_dl.data

    # Error handling on invalid or nonexistent export_id
    res_inv = client.get("/api/portfolio/export/invalid!id@here")
    assert res_inv.status_code == 400

    res_none = client.get("/api/portfolio/export/exp_0000000000")
    assert res_none.status_code == 404


def test_all_report_styles_and_presets(temp_environment):
    """Verify that all report styles and preset options render properly."""
    mgr = PortfolioManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
        exports_dir=temp_environment["exports_dir"],
    )

    styles = ["developer_portfolio", "dsa_progress", "weekly_summary", "monthly_report", "goal_completion"]
    presets = ["all_time", "last_7_days", "last_30_days", "last_90_days"]

    for st in styles:
        for pr in presets:
            cfg = PortfolioConfig(report_style=st, date_range_preset=pr)
            report = mgr.aggregate_evidence(cfg)
            assert report.config.report_style == st
            assert report.config.date_range_preset == pr
            md = mgr.render_markdown(report)
            assert len(md) > 100
            html = mgr.render_html(report)
            assert "<!DOCTYPE html>" in html


def test_unsupported_export_format_and_sanitization(temp_environment):
    """Verify ValueError is raised for invalid format and filename is safely cleaned."""
    mgr = PortfolioManager(
        tracking_db_path=temp_environment["track_db"],
        progress_db_path=temp_environment["prog_db"],
        exports_dir=temp_environment["exports_dir"],
    )
    report = mgr.aggregate_evidence()

    with pytest.raises(ValueError, match="Unsupported format"):
        mgr.export_portfolio(report, format_type="exe")

    # Clean filename test
    sanitized = mgr._sanitize_filename("my/unsafe\\file:name*?.txt")
    assert "/" not in sanitized
    assert "\\" not in sanitized
    assert ":" not in sanitized
    assert "*" not in sanitized
    assert "?" not in sanitized

