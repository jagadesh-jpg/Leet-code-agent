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

    # Verify that attempting to resume a completed run is safely rejected
    attempt_resume = autonomous.resume_autonomous_run(res["run_id"], db_path=isolate_db, run_in_background=False)
    assert "error" in attempt_resume
    assert "already marked 'completed'" in attempt_resume["error"]


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


def test_autonomous_exact_problem_ids_selection(isolate_db):
    """Verify that specifying problem_ids selects only those problems, respecting language filtering."""
    all_probs = load_problems()
    mock_llm = MockLLM(problems=all_probs)

    # 1. Custom problem addition using store.save_custom_problem
    store.save_custom_problem(
        problem_id="custom-prob-1",
        url="https://leetcode.com/problems/custom-prob-1/",
        title="Custom Problem 1",
        difficulty="Easy",
        description="Return 1",
        function_name="solve",
        signature="def solve(self) -> int:",
        tests=[{"input": [], "expected": 1}],
        db_path=isolate_db,
    )
    store.save_custom_problem(
        problem_id="custom-prob-2",
        url="https://leetcode.com/problems/custom-prob-2/",
        title="Custom Problem 2",
        difficulty="Easy",
        description="Return 2",
        function_name="solve",
        signature="def solve(self) -> int:",
        tests=[{"input": [], "expected": 2}],
        db_path=isolate_db,
    )

    # 2. Test get_pending_queue with exact problem_ids
    pending = autonomous.get_pending_queue(
        db_path=isolate_db,
        problem_ids=["custom-prob-2"],
        language="python",
    )
    assert len(pending) == 1
    assert pending[0]["id"] == "custom-prob-2"

    # 3. Test run_autonomous_queue selecting only custom-prob-2
    # Define a simple mock for custom-prob-2 matching assistant's llm_client.ask() interface
    class CustomMockLLM:
        def __init__(self):
            self.model_name = "mock"
        def ask(self, system_prompt: str, user_prompt: str) -> str:
            return "```python\nclass Solution:\n    def solve(self) -> int:\n        return 2\n```"

    run_res = autonomous.run_autonomous_queue(
        max_problems=5,
        problem_ids=["custom-prob-2"],
        language="python",
        llm_client=CustomMockLLM(),
        db_path=isolate_db,
    )
    assert run_res["status"] == "completed"
    assert run_res["total_problems"] == 1
    assert run_res["verified_count"] == 1
    queue = store.get_autonomous_queue_items(run_res["run_id"], db_path=isolate_db)
    assert len(queue) == 1
    assert queue[0]["problem_id"] == "custom-prob-2"
    assert store.is_solved("custom-prob-2", language="python", db_path=isolate_db)
    assert not store.is_solved("custom-prob-1", language="python", db_path=isolate_db)

    # 4. Once verified for Python, selecting it again with skip_locally_verified skips it
    pending_again = autonomous.get_pending_queue(
        db_path=isolate_db,
        problem_ids=["custom-prob-2"],
        language="python",
        skip_locally_verified=True,
    )
    assert len(pending_again) == 0

    # 5. But for Java, it remains eligible
    pending_java = autonomous.get_pending_queue(
        db_path=isolate_db,
        problem_ids=["custom-prob-2"],
        language="java",
        skip_locally_verified=True,
    )
    assert len(pending_java) == 1
    assert pending_java[0]["id"] == "custom-prob-2"


def test_start_autonomous_run_signature_and_param_forwarding(isolate_db, monkeypatch):
    """Verify start_autonomous_run accepts problem_ids and forwards it properly."""
    called_args = {}

    def mock_run_queue(**kwargs):
        called_args.update(kwargs)
        return {"status": "completed", "total_problems": len(kwargs.get("problem_ids") or [])}

    monkeypatch.setattr(autonomous, "run_autonomous_queue", mock_run_queue)

    # Without problem_ids (backward compatibility)
    res1 = autonomous.start_autonomous_run(
        max_problems=2,
        language="python",
        db_path=isolate_db,
        run_in_background=False,
    )
    assert res1["status"] == "completed"
    assert called_args.get("problem_ids") is None

    # With problem_ids
    res2 = autonomous.start_autonomous_run(
        max_problems=1,
        language="python",
        problem_ids=["reverse-linked-list"],
        db_path=isolate_db,
        run_in_background=False,
    )
    assert res2["status"] == "completed"
    assert called_args.get("problem_ids") == ["reverse-linked-list"]


def test_autonomous_queue_multi_language(isolate_db):
    """Verify autonomous queue solves across Python, C, C++, and Java using MockLLM."""
    # Seed reverse-linked-list into isolate_db
    store.save_custom_problem(
        problem_id="reverse-linked-list",
        url="https://leetcode.com/problems/reverse-linked-list/",
        title="Reverse Linked List",
        difficulty="Easy",
        description="Reverse singly linked list",
        function_name="reverseList",
        signature="def reverseList(self, head: Optional[ListNode]) -> Optional[ListNode]:",
        tests=[
            {"input": [[1, 2, 3, 4, 5]], "expected": [5, 4, 3, 2, 1]},
            {"input": [[1, 2]], "expected": [2, 1]},
        ],
        db_path=isolate_db,
    )
    all_probs = load_problems()
    # Test on reverse-linked-list which has native ListNode runners for C, C++, Java, and Python
    for lang in ["python", "c", "cpp", "java"]:
        mock_llm = MockLLM(problems=all_probs)
        res = autonomous.run_autonomous_queue(
            max_problems=1,
            problem_ids=["reverse-linked-list"],
            language=lang,
            max_attempts_per_problem=3,
            llm_client=mock_llm,
            db_path=isolate_db,
        )
        assert res["status"] == "completed", f"Failed for {lang}: {res}"
        assert res["verified_count"] == 1, f"Failed verification for {lang}: {res}"
        assert store.is_solved("reverse-linked-list", language=lang, db_path=isolate_db), f"Not marked solved for {lang}"
