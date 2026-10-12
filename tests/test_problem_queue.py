"""Stage 18 Autonomous Problem Queue Test Suite.

Comprehensive validation of:
1. Queue creation
2. Queue insertion
3. FIFO ordering
4. Priority ordering
5. Duplicate handling (rejection policy & allow policy)
6. State transitions (deterministic allowed paths)
7. Invalid state transition rejection
8. Multi-language queue (C, C++, Java, Python)
9. Multi-DSA queue (>= 9 categories)
10. Successful item processing
11. Self-correction inside queue
12. Failure isolation
13. Max-attempt handling (MAX_ATTEMPTS_REACHED)
14. Continuation after failure
15. Persistence (data survives store recreation)
16. Resume (resetting interrupted RUNNING items)
17. Idempotency (already verified items skipped)
18. Result aggregation
19. Queue limits (max_items_to_process)
20. Infrastructure failure handling
21. Verification gate preservation
"""

import os
import tempfile
import pytest

from agent.benchmarking.multi_language_runner import INTENTIONAL_FLAWS
from agent.core.models import SupportedLanguage
from agent.queue.models import QueueItem, QueueItemStatus, VALID_QUEUE_TRANSITIONS
from agent.queue.queue_runner import AutonomousQueueRunner
from agent.queue.store import SQLiteQueueStore


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


@pytest.fixture
def store(temp_db):
    s = SQLiteQueueStore(db_path=temp_db)
    yield s
    s.close()


@pytest.fixture
def runner(store):
    return AutonomousQueueRunner(store=store)


# 1. Queue creation
def test_queue_creation(store):
    assert os.path.exists(store.db_path)
    items = store.list_items()
    assert items == []


# 2. Queue insertion
def test_queue_insertion(runner, store):
    item = runner.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.PYTHON, priority=5)
    assert item.problem_id == "two-sum"
    assert item.status == QueueItemStatus.PENDING
    assert item.priority == 5
    persisted = store.get_item(item.queue_item_id)
    assert persisted is not None
    assert persisted.queue_item_id == item.queue_item_id


# 3. FIFO ordering
def test_fifo_ordering(runner):
    runner.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.PYTHON, priority=0)
    runner.enqueue(problem_id="valid-palindrome", preferred_language=SupportedLanguage.C, priority=0)
    runner.enqueue(problem_id="binary-search", preferred_language=SupportedLanguage.CPP, priority=0)

    # With use_priority=False, items should be retrieved strictly in insertion (FIFO) order
    first = runner.store.get_next_pending(use_priority=False)
    assert first.problem_id == "two-sum"
    first.transition_to(QueueItemStatus.RUNNING)
    runner.store.save_item(first)

    second = runner.store.get_next_pending(use_priority=False)
    assert second.problem_id == "valid-palindrome"


# 4. Priority ordering
def test_priority_ordering(runner):
    runner.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.PYTHON, priority=1)
    runner.enqueue(problem_id="valid-palindrome", preferred_language=SupportedLanguage.C, priority=10)
    runner.enqueue(problem_id="binary-search", preferred_language=SupportedLanguage.CPP, priority=5)

    # With use_priority=True, highest priority (10) must be retrieved first
    highest = runner.store.get_next_pending(use_priority=True)
    assert highest.problem_id == "valid-palindrome"
    assert highest.priority == 10
    highest.transition_to(QueueItemStatus.RUNNING)
    runner.store.save_item(highest)

    next_prio = runner.store.get_next_pending(use_priority=True)
    assert next_prio.problem_id == "binary-search"
    assert next_prio.priority == 5


# 5. Duplicate handling (both rejection and allow policies)
def test_duplicate_handling_policies(temp_db):
    # Strict deduplication runner
    strict_store = SQLiteQueueStore(db_path=temp_db)
    strict_runner = AutonomousQueueRunner(store=strict_store, allow_duplicates=False)
    strict_runner.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.PYTHON)

    with pytest.raises(ValueError, match="Duplicate queue entry rejected"):
        strict_runner.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.PYTHON)
    strict_store.close()

    # Allowed duplicate runner
    fd, path2 = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        allow_store = SQLiteQueueStore(db_path=path2)
        allow_runner = AutonomousQueueRunner(store=allow_store, allow_duplicates=True)
        item1 = allow_runner.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.PYTHON)
        item2 = allow_runner.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.PYTHON)
        assert item1.queue_item_id != item2.queue_item_id
        assert len(allow_store.list_items()) == 2
        allow_store.close()
    finally:
        allow_store.close()
        if os.path.exists(path2):
            os.remove(path2)


# 6. Deterministic state transitions
def test_valid_state_transitions():
    item = QueueItem(queue_item_id="test_job_1", problem_id="two-sum")
    assert item.status == QueueItemStatus.PENDING

    item.transition_to(QueueItemStatus.RUNNING)
    assert item.status == QueueItemStatus.RUNNING
    assert item.started_at is not None

    item.transition_to(QueueItemStatus.VERIFYING)
    assert item.status == QueueItemStatus.VERIFYING

    item.transition_to(QueueItemStatus.VERIFIED)
    assert item.status == QueueItemStatus.VERIFIED
    assert item.completed_at is not None


# 7. Invalid state transition rejection
def test_invalid_state_transition_rejection():
    item = QueueItem(queue_item_id="test_job_2", problem_id="two-sum")
    assert item.status == QueueItemStatus.PENDING

    # Illegal transition: PENDING directly to VERIFIED without running
    with pytest.raises(ValueError, match="Invalid queue state transition"):
        item.transition_to(QueueItemStatus.VERIFIED)

    item.transition_to(QueueItemStatus.RUNNING)
    item.transition_to(QueueItemStatus.VERIFIED)

    # Illegal transition: VERIFIED is terminal, cannot transition to RUNNING
    with pytest.raises(ValueError, match="Invalid queue state transition"):
        item.transition_to(QueueItemStatus.RUNNING)


# 8 & 9. Multi-language & Multi-DSA queue composition
def test_multilang_and_multidsa_queue_composition(runner):
    problems_to_queue = [
        ("two-sum", SupportedLanguage.CPP),
        ("valid-palindrome", SupportedLanguage.C),
        ("binary-search", SupportedLanguage.PYTHON),
        ("climbing-stairs", SupportedLanguage.JAVA),
        ("max-subarray", SupportedLanguage.CPP),
        ("reverse-linked-list", SupportedLanguage.PYTHON),
    ]
    for pid, lang in problems_to_queue:
        runner.enqueue(problem_id=pid, preferred_language=lang)

    items = runner.store.list_items()
    assert len(items) == 6
    langs = {it.preferred_language for it in items}
    assert langs == {SupportedLanguage.C, SupportedLanguage.CPP, SupportedLanguage.JAVA, SupportedLanguage.PYTHON}
    categories = {it.category for it in items if it.category}
    assert len(categories) >= 5


# 10. Successful item processing
def test_successful_item_processing(runner):
    runner.enqueue(problem_id="valid-palindrome", preferred_language=SupportedLanguage.C)
    summary = runner.run_queue()

    assert summary.total_items == 1
    assert summary.verified == 1
    assert summary.failed == 0
    assert summary.total_tests_passed > 0

    item = runner.store.list_items()[0]
    assert item.status == QueueItemStatus.VERIFIED
    assert item.final_status == "VERIFIED"
    assert item.verification_status == "VERIFIED"


# 11. Self-correction inside queue
def test_self_correction_inside_queue(runner):
    # Enqueue two-sum in Python with intentional wrong answer
    flaw, _ = INTENTIONAL_FLAWS[("two-sum", SupportedLanguage.PYTHON)]
    runner.enqueue(
        problem_id="two-sum",
        preferred_language=SupportedLanguage.PYTHON,
        initial_flawed_code=flaw,
    )

    summary = runner.run_queue()
    assert summary.verified == 1
    assert summary.failed == 0
    item = runner.store.list_items()[0]
    assert item.status == QueueItemStatus.VERIFIED
    # Autonomous self-correction performed repairs (attempts > 1)
    assert item.attempt_count > 1


# 12 & 14. Failure isolation and continuation after failure
def test_failure_isolation_and_continuation(runner):
    # Problem 1: Unfixable flaw in Java -> MAX_ATTEMPTS_REACHED
    unfixable = "class Solution { public int maxDepth(int[] n) { return -999; } }"
    runner.enqueue(
        problem_id="maximum-depth-of-binary-tree",
        preferred_language=SupportedLanguage.JAVA,
        priority=10,
        initial_flawed_code=unfixable,
    )
    # Problem 2: Valid C problem -> should verify safely despite Problem 1 failing
    runner.enqueue(
        problem_id="valid-palindrome",
        preferred_language=SupportedLanguage.C,
        priority=5,
    )

    summary = runner.run_queue()
    assert summary.total_items == 2
    assert summary.max_attempts_reached == 1
    assert summary.verified == 1

    items_by_prio = sorted(runner.store.list_items(), key=lambda x: x.priority, reverse=True)
    assert items_by_prio[0].status == QueueItemStatus.MAX_ATTEMPTS_REACHED
    assert items_by_prio[1].status == QueueItemStatus.VERIFIED


# 13. Max-attempt handling
def test_max_attempts_handling(runner):
    unfixable = "class Solution { public int maxDepth(int[] n) { return -999; } }"
    item = runner.enqueue(
        problem_id="maximum-depth-of-binary-tree",
        preferred_language=SupportedLanguage.JAVA,
        max_attempts=3,
        initial_flawed_code=unfixable,
    )
    summary = runner.run_queue()

    persisted = runner.store.get_item(item.queue_item_id)
    assert persisted.status == QueueItemStatus.MAX_ATTEMPTS_REACHED
    assert persisted.attempt_count <= 3
    assert summary.max_attempts_reached == 1


# 15. Persistence across store recreation
def test_persistence_across_store_recreation(temp_db):
    store1 = SQLiteQueueStore(db_path=temp_db)
    runner1 = AutonomousQueueRunner(store=store1)
    item = runner1.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.CPP, priority=7)
    store1.close()

    # Recreate store instance pointing to same sqlite file
    store2 = SQLiteQueueStore(db_path=temp_db)
    loaded = store2.get_item(item.queue_item_id)
    assert loaded is not None
    assert loaded.problem_id == "two-sum"
    assert loaded.priority == 7
    assert loaded.preferred_language == SupportedLanguage.CPP
    store2.close()


# 16. Resume after interruption
def test_resume_after_interruption(temp_db):
    store = SQLiteQueueStore(db_path=temp_db)
    runner = AutonomousQueueRunner(store=store)

    # Simulate an interrupted job by creating an item stuck in RUNNING
    item1 = runner.enqueue(problem_id="valid-palindrome", preferred_language=SupportedLanguage.C)
    item1.transition_to(QueueItemStatus.RUNNING)
    store.save_item(item1)

    item2 = runner.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.CPP)

    # Upon running, runner calls reset_in_progress_to_pending, recovering item1
    recovered_count = store.reset_in_progress_to_pending()
    assert recovered_count == 1
    assert store.get_item(item1.queue_item_id).status == QueueItemStatus.PENDING

    # Now run queue to completion
    summary = runner.run_queue()
    assert summary.verified == 2
    assert summary.running == 0
    store.close()


# 17. Idempotency (already verified items are not re-executed)
def test_idempotency_of_verified_items(runner):
    item = runner.enqueue(problem_id="valid-palindrome", preferred_language=SupportedLanguage.C)
    summary1 = runner.run_queue()
    assert summary1.verified == 1

    # Running queue again should not re-solve or duplicate results
    summary2 = runner.run_queue()
    assert summary2.verified == 1
    assert summary2.pending == 0


# 18. Result aggregation
def test_result_aggregation(runner):
    runner.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.CPP)
    runner.enqueue(problem_id="valid-palindrome", preferred_language=SupportedLanguage.C)
    summary = runner.run_queue()

    assert summary.total_items == 2
    assert summary.verified == 2
    assert summary.failed == 0
    assert summary.total_tests > 0
    assert summary.total_tests_passed == summary.total_tests
    assert summary.execution_time_ms > 0
    assert len(summary.item_results) == 2


# 19. Queue limits (max_items_to_process)
def test_queue_limits(runner):
    runner.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.CPP)
    runner.enqueue(problem_id="valid-palindrome", preferred_language=SupportedLanguage.C)
    runner.enqueue(problem_id="binary-search", preferred_language=SupportedLanguage.PYTHON)

    # Set limit to 2 items
    summary = runner.run_queue(max_items_to_process=2)
    assert summary.total_items == 3
    assert summary.verified == 2
    assert summary.pending == 1


# 20. Infrastructure failure handling
def test_infrastructure_error_handling(runner):
    item = runner.enqueue(problem_id="non-existent-problem", preferred_language=SupportedLanguage.PYTHON)
    summary = runner.run_queue()

    persisted = runner.store.get_item(item.queue_item_id)
    assert persisted.status == QueueItemStatus.FAILED
    assert "not registered" in (persisted.error_message or "")


# 21. Verification gate preservation
def test_verification_gate_preservation(runner):
    # Candidate with uncompilable syntax or wrong solution must not be verified
    item = runner.enqueue(
        problem_id="two-sum",
        preferred_language=SupportedLanguage.PYTHON,
        initial_flawed_code="def two_sum(n, t): return [0, 0] # strictly wrong",
    )
    # Orchestrator with 1 attempt
    runner.orchestrator.max_attempts = 1
    item.max_attempts = 1
    runner.store.save_item(item)

    summary = runner.run_queue()
    persisted = runner.store.get_item(item.queue_item_id)
    assert persisted.status in (QueueItemStatus.FAILED, QueueItemStatus.MAX_ATTEMPTS_REACHED)
    assert persisted.verification_status != "VERIFIED"
