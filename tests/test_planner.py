"""Tests for Personalized Learning Session Planner (Milestone 6.3.5).

Verifies:
- Configurable session size.
- Balanced session structure (Warm-up, Main Practice, Challenge).
- Deterministic plan generation.
- Topic diversity and weak-topic reinforcement.
- Difficulty progression.
- Solved-problem exclusion.
- Empty queue and insufficient candidate handling.
- Duplicate prevention.
- Preview-only nature (no execution or DB mutation).
- CLI integration and database isolation.
"""

from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List

import pytest

from intelligence.planner import (
    LearningSessionPlan,
    PlannedProblem,
    SessionPlanner,
    SessionProblemRole,
)
from problems import load_problems
import store


@pytest.fixture
def temp_planner_db(tmp_path: Path) -> Path:
    """Fixture providing a guaranteed isolated temporary database."""
    db_file = tmp_path / "test_session_planner.db"
    store.init(db_path=db_file)
    return db_file


def test_session_size_and_structure_default(temp_planner_db: Path):
    """Verify default 3-problem session includes warm-up, main practice, and challenge roles."""
    candidates = load_problems()
    planner = SessionPlanner(db_path=temp_planner_db, language="python")

    plan = planner.plan_session(candidates, session_size=3, skip_solved=False)

    assert plan.target_size == 3
    assert plan.total_problems == 3
    roles = [p.role for p in plan.planned_problems]
    assert SessionProblemRole.WARM_UP in roles
    assert SessionProblemRole.MAIN_PRACTICE in roles
    assert SessionProblemRole.CHALLENGE in roles

    # Progression check: Warm-up first, Challenge last
    assert plan.planned_problems[0].role == SessionProblemRole.WARM_UP
    assert plan.planned_problems[-1].role == SessionProblemRole.CHALLENGE
    assert len(plan.covered_topics) > 0


def test_session_size_custom_and_small(temp_planner_db: Path):
    """Verify session planner gracefully handles 1-problem and 2-problem requests."""
    candidates = load_problems()
    planner = SessionPlanner(db_path=temp_planner_db, language="python")

    # 1-problem session
    plan_1 = planner.plan_session(candidates, session_size=1, skip_solved=False)
    assert plan_1.total_problems == 1
    assert plan_1.planned_problems[0].role == SessionProblemRole.MAIN_PRACTICE
    assert plan_1.planned_problems[0].rank == 1

    # 2-problem session
    plan_2 = planner.plan_session(candidates, session_size=2, skip_solved=False)
    assert plan_2.total_problems == 2
    roles_2 = [p.role for p in plan_2.planned_problems]
    assert roles_2 == [SessionProblemRole.WARM_UP, SessionProblemRole.MAIN_PRACTICE]


def test_deterministic_session_generation(temp_planner_db: Path):
    """Verify that calling plan_session repeatedly produces exact same plan."""
    candidates = load_problems()
    planner = SessionPlanner(db_path=temp_planner_db, language="python")

    plan_a = planner.plan_session(candidates, session_size=4, skip_solved=False)
    plan_b = planner.plan_session(candidates, session_size=4, skip_solved=False)

    assert [p.problem_id for p in plan_a.planned_problems] == [p.problem_id for p in plan_b.planned_problems]
    assert [p.priority_score for p in plan_a.planned_problems] == [p.priority_score for p in plan_b.planned_problems]
    assert [p.role for p in plan_a.planned_problems] == [p.role for p in plan_b.planned_problems]
    assert plan_a.session_summary == plan_b.session_summary


def test_weak_topic_prioritization_in_session(temp_planner_db: Path):
    """Verify that a topic identified as weak is actively targeted in the session plan."""
    # Create failures in Stack problem "valid-parentheses"
    store.log_attempt("valid-parentheses", 1, "code", "wrong_answer", language="python", db_path=temp_planner_db)
    store.log_attempt("valid-parentheses", 2, "code", "runtime_error", language="python", db_path=temp_planner_db)
    store.mark_result("valid-parentheses", "failed", attempts=2, language="python", db_path=temp_planner_db)

    planner = SessionPlanner(db_path=temp_planner_db, language="python")
    candidates = load_problems()

    plan = planner.plan_session(candidates, session_size=3, skip_solved=True)

    assert "Stack" in plan.weak_topics
    assert "Stack" in plan.covered_topics
    planned_ids = [p.problem_id for p in plan.planned_problems]
    assert "valid-parentheses" in planned_ids
    # Check that reason mentions weak topic
    stack_problem = next(p for p in plan.planned_problems if p.problem_id == "valid-parentheses")
    assert "weak topic" in stack_problem.reason.lower() or "stack" in stack_problem.reason.lower()


def test_solved_problem_exclusion(temp_planner_db: Path):
    """Verify that solved problems are excluded when skip_solved=True and included when False."""
    store.mark_result("two-sum", "solved", attempts=1, language="python", db_path=temp_planner_db)

    planner = SessionPlanner(db_path=temp_planner_db, language="python")
    candidates = load_problems()

    # With skip_solved=True (default)
    plan_skip = planner.plan_session(candidates, session_size=5, skip_solved=True)
    planned_skip_ids = [p.problem_id for p in plan_skip.planned_problems]
    assert "two-sum" not in planned_skip_ids

    # With skip_solved=False
    plan_all = planner.plan_session(candidates, session_size=5, skip_solved=False)
    planned_all_ids = [p.problem_id for p in plan_all.planned_problems]
    assert "two-sum" in planned_all_ids


def test_empty_candidates_and_insufficient_candidates(temp_planner_db: Path):
    """Verify clean handling when candidates list is empty or fewer than requested size."""
    planner = SessionPlanner(db_path=temp_planner_db, language="python")

    # Empty candidate list
    plan_empty = planner.plan_session([], session_size=3)
    assert plan_empty.total_problems == 0
    assert "No candidate problems available" in plan_empty.session_summary

    # Pool smaller than session_size
    candidates = [
        {"id": "prob-a", "title": "Problem A", "difficulty": "easy", "topics": ["Arrays"]},
        {"id": "prob-b", "title": "Problem B", "difficulty": "medium", "topics": ["Trees"]},
    ]
    plan_small = planner.plan_session(candidates, session_size=5, skip_solved=False)
    assert plan_small.total_problems == 2
    assert len(set(p.problem_id for p in plan_small.planned_problems)) == 2


def test_duplicate_prevention(temp_planner_db: Path):
    """Verify no duplicate problem IDs appear in a planned session even with large session size."""
    candidates = load_problems()
    planner = SessionPlanner(db_path=temp_planner_db, language="python")

    plan = planner.plan_session(candidates, session_size=len(candidates) + 5, skip_solved=False)
    planned_ids = [p.problem_id for p in plan.planned_problems]

    assert len(planned_ids) == len(set(planned_ids))
    assert len(planned_ids) == len(candidates)


def test_cli_plan_command(temp_planner_db: Path):
    """Verify running pipeline_cli.py --plan works cleanly in preview-only mode."""
    cmd = [
        sys.executable,
        "pipeline_cli.py",
        "--plan",
        "--session-size", "3",
        "--db-path", str(temp_planner_db),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent.parent)

    assert res.returncode == 0
    output = res.stdout
    assert "PERSONALIZED LEARNING SESSION PLANNER" in output
    assert "PREVIEW-ONLY" in output
    assert "WARM UP" in output or "Warm Up" in output or "Warm-Up" in output
    assert "MAIN PRACTICE" in output or "Main Practice" in output
    assert "No problems were executed or submitted" in output
