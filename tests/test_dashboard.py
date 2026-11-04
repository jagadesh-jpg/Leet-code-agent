import pytest
from pathlib import Path

from dashboard import derive_problem_id, import_submissions_from_csv, get_dashboard_data
from mcp_server import import_csv_submissions, get_dashboard
import store


@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    """Ensure all dashboard tests operate against an isolated temporary SQLite database."""
    test_db = tmp_path / "test_dashboard.db"
    monkeypatch.setenv("LEETCODE_AGENT_DB_PATH", str(test_db))
    store.init(db_path=test_db)
    yield test_db


def test_derive_problem_id():
    assert derive_problem_id("https://leetcode.com/problems/two-sum/", "Two Sum") == "two-sum"
    assert derive_problem_id("https://leetcode.com/problems/3sum/description/", "3Sum") == "3sum"
    assert derive_problem_id("", "Reverse Linked List II") == "reverse-linked-list-ii"
    assert derive_problem_id("", "") == "unknown-problem"


def test_import_submissions_from_csv_text(isolate_db):
    sample_csv = """title,url,difficulty,verdict,submission_date,language,runtime_ms,memory_mb,notes
Two Sum,https://leetcode.com/problems/two-sum/,Easy,Accepted,2026-11-01 10:00:00,Python3,35,17.8,"Clean hash map"
3Sum,https://leetcode.com/problems/3sum/,Medium,Wrong Answer,2026-11-02 11:30:00,Python3,0,0,"Failed duplicates"
3Sum,https://leetcode.com/problems/3sum/,Medium,Accepted,2026-11-02 12:00:00,Python3,680,21.4,"Fixed two-pointer skip"
Longest Palindromic Substring,https://leetcode.com/problems/longest-palindromic-substring/,Medium,Time Limit Exceeded,2026-11-03 14:00:00,Python3,0,0,"O(n^3) TLE"
"""
    res = import_submissions_from_csv(sample_csv, db_path=isolate_db)
    assert res["status"] == "success"
    assert res["imported_count"] == 4
    assert res["skipped_count"] == 0

    # Retrieve dashboard
    dash = get_dashboard_data(username="jagadesh-02", db_path=isolate_db)
    summary = dash["summary"]
    assert summary["total_submissions_tracked"] == 4
    assert summary["unique_problems_solved"] == 2  # Two Sum and 3Sum
    assert summary["by_difficulty_solved"]["Easy"] == 1
    assert summary["by_difficulty_solved"]["Medium"] == 1
    assert summary["verdicts_breakdown"]["Accepted"] == 2
    assert summary["verdicts_breakdown"]["Wrong Answer"] == 1
    assert summary["verdicts_breakdown"]["Time Limit Exceeded"] == 1


def test_attempted_not_accepted_identification(isolate_db):
    sample_csv = """title,url,difficulty,verdict,submission_date,language,runtime_ms,memory_mb,notes
Valid Sudoku,https://leetcode.com/problems/valid-sudoku/,Medium,Wrong Answer,2026-11-01 09:00:00,Python3,0,0,"Box check error"
Valid Sudoku,https://leetcode.com/problems/valid-sudoku/,Medium,Runtime Error,2026-11-01 09:15:00,Python3,0,0,"Index out of bounds"
Invert Binary Tree,https://leetcode.com/problems/invert-binary-tree/,Easy,Accepted,2026-11-01 10:00:00,Python3,15,16.5,"Recursive swap"
"""
    import_submissions_from_csv(sample_csv, db_path=isolate_db)
    dash = get_dashboard_data(db_path=isolate_db)

    attempted_unsolved = dash["attempted_not_accepted"]
    assert len(attempted_unsolved) == 1
    assert attempted_unsolved[0]["problem_id"] == "valid-sudoku"
    assert attempted_unsolved[0]["attempts_count"] == 2

    # Check that it appears in recommendations
    recs = dash["recommendations"]
    rec_ids = [r["problem_id"] for r in recs]
    assert "valid-sudoku" in rec_ids
    assert "High (Unresolved Attempt)" in recs[0]["priority"]


def test_mcp_tools_dashboard(isolate_db, tmp_path):
    csv_file = tmp_path / "subs.csv"
    csv_file.write_text(
        "title,url,difficulty,verdict,submission_date,language,runtime_ms,memory_mb,notes\n"
        "Two Sum,https://leetcode.com/problems/two-sum/,Easy,Accepted,2026-11-01,Python3,30,16.0,Done\n"
    )

    # Tool 1: import_csv_submissions
    import_res = import_csv_submissions(str(csv_file))
    assert import_res["status"] == "success"
    assert import_res["imported_count"] == 1

    # Tool 2: get_dashboard
    dash_res = get_dashboard("jagadesh-02")
    assert dash_res["username"] == "jagadesh-02"
    assert dash_res["summary"]["total_submissions_tracked"] == 1
    assert dash_res["summary"]["unique_problems_solved"] == 1


def test_official_verdicts_in_dashboard_without_double_count(isolate_db):
    """Ensure official verdicts are tracked in dashboard and not double counted with CSV imports."""
    # 1. Record an official verdict
    store.record_official_verdict(
        problem_id="3sum",
        verdict="Accepted",
        runtime_ms=523.0,
        memory_mb=22.37,
        notes="Official accepted submission",
        db_path=isolate_db,
    )

    dash1 = get_dashboard_data(db_path=isolate_db)
    assert dash1["summary"]["total_submissions_tracked"] == 1
    assert dash1["summary"]["unique_problems_solved"] == 1
    assert dash1["summary"]["verdicts_breakdown"]["Accepted"] == 1
    assert len(dash1["recent_submissions"]) == 1
    assert dash1["recent_submissions"][0]["source"] == "official_verdict"
    assert dash1["recent_submissions"][0]["problem_id"] == "3sum"

    # 2. Import a CSV record for a different problem
    sample_csv = "title,url,difficulty,verdict,submission_date,language,runtime_ms,memory_mb,notes\nTwo Sum,https://leetcode.com/problems/two-sum/,Easy,Accepted,2026-11-01,Python3,30,16.0,Done\n"
    import_submissions_from_csv(sample_csv, db_path=isolate_db)

    dash2 = get_dashboard_data(db_path=isolate_db)
    assert dash2["summary"]["total_submissions_tracked"] == 2
    assert dash2["summary"]["unique_problems_solved"] == 2
    assert dash2["summary"]["verdicts_breakdown"]["Accepted"] == 2
    sources = {s["source"] for s in dash2["recent_submissions"]}
    assert "official_verdict" in sources
    assert "csv_import" in sources

    # 3. Import duplicate 3sum with exact same verdict and metrics -> should NOT double count
    dup_csv = "title,url,difficulty,verdict,submission_date,language,runtime_ms,memory_mb,notes\n3Sum,https://leetcode.com/problems/3sum/,Medium,Accepted,2026-11-04,Python3,523.0,22.37,Done\n"
    import_submissions_from_csv(dup_csv, db_path=isolate_db)

    dash3 = get_dashboard_data(db_path=isolate_db)
    assert dash3["summary"]["total_submissions_tracked"] == 2  # Still 2, deduped

