import pytest
from pathlib import Path

import autonomous
from llm import MockLLM
import memory
from problems import load_problems
import store


@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    """Ensure tests run against a clean isolated SQLite database."""
    test_db = tmp_path / "test_autonomous.db"
    monkeypatch.setenv("LEETCODE_AGENT_DB_PATH", str(test_db))
    store.init(db_path=test_db)
    yield test_db


def test_learning_memory_retrieval(isolate_db):
    memory.seed_default_learning(db_path=isolate_db)
    entries = store.get_learning_entries(db_path=isolate_db)
    assert len(entries) >= 6

    # Test query for 3sum
    prob_3sum = {"id": "3sum", "title": "3Sum", "description": "find unique triplets"}
    relevant = memory.retrieve_relevant_learning(prob_3sum, limit=2, db_path=isolate_db)
    assert len(relevant) > 0
    categories = [r["category"] for r in relevant]
    assert "two_pointers" in categories


def test_autonomous_queue_sequential_solving(isolate_db):
    all_probs = load_problems()
    mock_llm = MockLLM(problems=all_probs)

    # Run queue for 2 problems
    res = autonomous.run_autonomous_queue(
        max_problems=2,
        max_attempts_per_problem=3,
        llm_client=mock_llm,
        db_path=isolate_db,
    )

    assert res["status"] == "completed"
    assert res["total_problems"] == 2
    assert res["completed_count"] == 2
    assert res["verified_count"] == 2
    assert res["failed_count"] == 0

    # Ensure status is properly updated
    status = autonomous.get_run_status(res["run_id"], db_path=isolate_db)
    assert status["status"] == "completed"
    assert len(status["queue"]) == 2
    for item in status["queue"]:
        assert item["status"] == "locally_verified"


def test_autonomous_queue_difficulty_filter(isolate_db):
    all_probs = load_problems()
    mock_llm = MockLLM(problems=all_probs)

    res = autonomous.run_autonomous_queue(
        max_problems=2,
        difficulty="hard",
        llm_client=mock_llm,
        db_path=isolate_db,
    )

    assert res["status"] == "completed"
    assert res["total_problems"] == 2
    assert res["verified_count"] == 2


def test_autonomous_retry_and_correction(isolate_db):
    all_probs = load_problems()
    # MockLLM natively fails attempt 1 with wrong answer and succeeds on attempt 2!
    mock_llm = MockLLM(problems=all_probs)

    res = autonomous.run_autonomous_queue(
        max_problems=1,
        max_attempts_per_problem=3,
        llm_client=mock_llm,
        db_path=isolate_db,
    )

    assert res["status"] == "completed"
    assert res["verified_count"] == 1
    # Check that attempt 1 failed and attempt 2 succeeded
    queue_items = store.get_autonomous_queue_items(res["run_id"], db_path=isolate_db)
    assert len(queue_items) == 1
    assert queue_items[0]["attempts_used"] == 2
    assert queue_items[0]["status"] == "locally_verified"


def test_pause_and_resume_controls(isolate_db):
    all_probs = load_problems()
    mock_llm = MockLLM(problems=all_probs)

    # Start run with background=False but check pause signal
    run_res = autonomous.start_autonomous_run(
        max_problems=3,
        llm_client=mock_llm,
        db_path=isolate_db,
        run_in_background=False,
    )
    assert run_res["status"] == "completed"

    # Test pausing and resuming recorded checkpoints
    pause_res = autonomous.pause_autonomous_run(run_res["run_id"], db_path=isolate_db)
    assert pause_res["status"] == "pause_requested"

    # Test stop control
    stop_res = autonomous.stop_autonomous_run(run_res["run_id"], db_path=isolate_db)
    assert stop_res["status"] == "stop_requested"


def test_interrupted_run_recovery(isolate_db):
    run_id = "test_interrupted_run"
    store.create_autonomous_run(
        run_id=run_id,
        total_problems=3,
        db_path=isolate_db,
    )
    store.save_autonomous_queue(run_id, ["two-sum", "valid-parentheses", "contains-duplicate"], db_path=isolate_db)

    # When thread is not alive, status reflects interrupted
    status = autonomous.get_run_status(run_id, db_path=isolate_db)
    assert status["status"] == "interrupted"

    # Resume run from checkpoint
    all_probs = load_problems()
    mock_llm = MockLLM(problems=all_probs)
    resume_res = autonomous.resume_autonomous_run(
        run_id=run_id,
        llm_client=mock_llm,
        db_path=isolate_db,
        run_in_background=False,
    )
    assert resume_res["status"] == "completed"
    assert resume_res["verified_count"] == 3
