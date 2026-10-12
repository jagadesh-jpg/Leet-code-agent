"""Comprehensive Stage 19 Tests for Dynamic Problem Intake & Autonomous Solving.

Verifies:
1. Valid Markdown intake
2. Valid JSON intake
3. ProblemSpec intake
4. Malformed input handling
5. Incomplete problem handling
6. Unsupported language rejection
7. Explicit C intake
8. Explicit C++ intake
9. Explicit Java intake
10. Explicit Python intake
11. Normalization preservation
12. Queue item creation
13. Persistence across restarts
14. Duplicate detection
15. Deliberate duplicate rerun policy
16. Single-problem autonomous solve
17. Multi-problem intake
18. Invalid item isolation in batch
19. Self-correction through dynamic intake
20. MAX_ATTEMPTS_REACHED propagation
21. Infrastructure failure propagation
22. Verification evidence preservation
23. Result contract compliance
24. API integration (POST /api/v1/problems/intake)
25. Restart/resume behavior
26. Idempotency verification
"""

import json
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from agent.api.server import create_app
from agent.benchmarking.benchmark_registry import BENCHMARK_REGISTRY, to_problem_spec
from agent.benchmarking.multi_language_runner import INTENTIONAL_FLAWS, MULTI_LANG_CODE
from agent.core.models import (
    ConfidenceLevel,
    Difficulty,
    ExecutionStatus,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCategory,
    VerificationStatus,
)
from agent.intake.models import (
    DynamicSolveResult,
    IntakeValidationStatus,
    ProblemValidationReport,
)
from agent.intake.service import ProblemIntakeService
from agent.intake.validator import ProblemValidator
from agent.queue.models import QueueItem, QueueItemStatus
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
def intake_service(temp_db):
    store = SQLiteQueueStore(db_path=temp_db)
    runner = AutonomousQueueRunner(store=store, allow_duplicates=True)
    svc = ProblemIntakeService(queue_runner=runner, queue_store=store, db_path=temp_db)
    yield svc
    store.close()


# 1. Valid Markdown intake
def test_valid_markdown_intake(intake_service):
    markdown = """# Valid Palindrome (Easy)

A phrase is a palindrome if, after converting all uppercase letters into lowercase letters and removing all non-alphanumeric characters, it reads the same forward and backward.

### Constraints:
- 1 <= s.length <= 2 * 10^5
- s consists only of printable ASCII characters.

### Examples:
Example 1:
Input: s = "A man, a plan, a canal: Panama"
Output: true

Example 2:
Input: s = "race a car"
Output: false
"""
    item, report = intake_service.intake_problem(markdown, preferred_language="c")
    assert report.is_acceptable is True
    assert report.status in (IntakeValidationStatus.VALID, IntakeValidationStatus.INCOMPLETE_PROBLEM)
    assert item is not None
    assert item.preferred_language == SupportedLanguage.C
    assert "palindrome" in item.title.lower() or "palindrome" in item.problem_id.lower()


# 2. Valid JSON intake
def test_valid_json_intake(intake_service):
    payload = {
        "title": "Two Sum",
        "statement": "Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target.",
        "constraints": ["2 <= nums.length <= 10^4", "-10^9 <= nums[i] <= 10^9"],
        "examples": [
            {"inputs": {"nums": [2, 7, 11, 15], "target": 9}, "expected_output": [0, 1]},
            {"inputs": {"nums": [3, 2, 4], "target": 6}, "expected_output": [1, 2]},
        ],
        "preferred_language": "cpp",
    }
    item, report = intake_service.intake_problem(payload)
    assert report.is_acceptable is True
    assert item is not None
    assert item.preferred_language == SupportedLanguage.CPP
    assert item.title == "Two Sum"


# 3. ProblemSpec intake
def test_problemspec_intake(intake_service):
    bp = BENCHMARK_REGISTRY["binary-search"]
    spec = to_problem_spec(bp)
    item, report = intake_service.intake_problem(spec, preferred_language="python")
    assert report.is_acceptable is True
    assert item is not None
    assert item.problem_id == "binary-search"
    assert item.preferred_language == SupportedLanguage.PYTHON


# 4. Malformed input handling
def test_malformed_input(intake_service):
    malformed_json = '{"title": "Broken JSON", "statement": '
    item, report = intake_service.intake_problem(malformed_json)
    assert item is None
    assert report.status == IntakeValidationStatus.INVALID_PROBLEM
    assert any("malformed" in issue.lower() or "json" in issue.lower() for issue in report.issues)


# 5. Incomplete problem handling
def test_incomplete_problem(intake_service):
    incomplete_input = {
        "title": "",  # Missing title
        "statement": "Some vague description without examples or constraints.",
    }
    item, report = intake_service.intake_problem(incomplete_input)
    assert report.status == IntakeValidationStatus.INCOMPLETE_PROBLEM
    assert report.is_acceptable is True
    assert "examples" in report.missing_fields


# 6. Unsupported language rejection
def test_unsupported_language_rejection(intake_service):
    payload = {
        "title": "Unsupported Lang Test",
        "statement": "Compute something.",
        "preferred_language": "rust",
    }
    item, report = intake_service.intake_problem(payload)
    assert item is None
    assert report.status == IntakeValidationStatus.INVALID_PROBLEM
    assert report.language_valid is False
    assert any("unsupported language" in issue.lower() for issue in report.issues)


# 7-10. Explicit Language Intakes: C, C++, Java, Python
@pytest.mark.parametrize("lang_str, expected_enum", [
    ("c", SupportedLanguage.C),
    ("cpp", SupportedLanguage.CPP),
    ("java", SupportedLanguage.JAVA),
    ("python", SupportedLanguage.PYTHON),
])
def test_explicit_language_intake(intake_service, lang_str, expected_enum):
    bp = BENCHMARK_REGISTRY["two-sum"]
    spec = to_problem_spec(bp)
    item, report = intake_service.intake_problem(spec, preferred_language=lang_str)
    assert item is not None
    assert item.preferred_language == expected_enum
    assert report.selected_language == expected_enum


# 11. Normalization preservation
def test_normalization_preservation(intake_service):
    payload = {
        "title": "Climbing Stairs",
        "statement": "You are climbing a staircase. It takes n steps to reach the top. Each time you can climb 1 or 2 steps.",
        "constraints": ["1 <= n <= 45"],
        "examples": [
            {"inputs": {"n": 2}, "expected_output": 2},
            {"inputs": {"n": 3}, "expected_output": 3},
        ],
        "preferred_language": "python",
    }
    item, report = intake_service.intake_problem(payload)
    assert item is not None
    assert item.spec_json is not None
    restored_spec = ProblemSpec.model_validate_json(item.spec_json)
    assert restored_spec.title == "Climbing Stairs"
    assert len(restored_spec.constraints) == 1
    assert restored_spec.constraints[0] == "1 <= n <= 45"
    assert len(restored_spec.test_cases) == 2


# 12. Queue item creation
def test_queue_item_creation(intake_service):
    payload = {"title": "Sample Problem", "statement": "Sample problem body with details."}
    item, report = intake_service.intake_problem(payload, priority=42)
    assert item is not None
    assert item.priority == 42
    assert item.status == QueueItemStatus.PENDING
    persisted = intake_service.store.get_item(item.queue_item_id)
    assert persisted is not None
    assert persisted.queue_item_id == item.queue_item_id


# 13. Persistence across restarts
def test_persistence_across_restarts(temp_db):
    store1 = SQLiteQueueStore(db_path=temp_db)
    runner1 = AutonomousQueueRunner(store=store1)
    svc1 = ProblemIntakeService(queue_runner=runner1, queue_store=store1, db_path=temp_db)

    item1, _ = svc1.intake_problem({"title": "P1", "statement": "Statement 1"}, preferred_language="c")
    store1.close()

    # Restart: instantiate fresh service on same db
    store2 = SQLiteQueueStore(db_path=temp_db)
    svc2 = ProblemIntakeService(queue_store=store2, db_path=temp_db)
    loaded = svc2.store.get_item(item1.queue_item_id)
    assert loaded is not None
    assert loaded.title == "P1"
    assert loaded.preferred_language == SupportedLanguage.C
    store2.close()


# 14. Duplicate detection
def test_duplicate_detection(intake_service):
    # Set intake_service to reject duplicates
    intake_service.allow_rerun_duplicates = False
    intake_service.runner.allow_duplicates = False

    payload = {"title": "Dedup Test", "statement": "Deterministic identical content"}
    item1, report1 = intake_service.intake_problem(payload, preferred_language="python", allow_rerun=False)
    assert item1 is not None

    item2, report2 = intake_service.intake_problem(payload, preferred_language="python", allow_rerun=False)
    assert item2 is None
    assert report2.status == IntakeValidationStatus.INVALID_PROBLEM
    assert any("duplicate" in issue.lower() for issue in report2.issues)


# 15. Deliberate duplicate rerun policy
def test_deliberate_duplicate_rerun_policy(intake_service):
    payload = {"title": "Rerun Test", "statement": "Repeatable problem content"}
    item1, _ = intake_service.intake_problem(payload, preferred_language="python", allow_rerun=True)
    item2, _ = intake_service.intake_problem(payload, preferred_language="python", allow_rerun=True)

    assert item1 is not None
    assert item2 is not None
    # Receives distinct correlation IDs
    assert item1.queue_item_id != item2.queue_item_id
    assert item1.problem_hash == item2.problem_hash


# 16. Single-problem autonomous solve
def test_single_problem_autonomous_solve(intake_service):
    bp = BENCHMARK_REGISTRY["two-sum"]
    spec = to_problem_spec(bp)
    result = intake_service.solve_dynamically(spec, preferred_language="cpp")

    assert isinstance(result, DynamicSolveResult)
    assert result.status == "VERIFIED"
    assert result.is_verified is True
    assert result.attempt_count == 1
    assert result.verification.correctness is True
    assert result.verification.constraints is True
    assert result.verification.complexity is True


# 17. Multi-problem intake
def test_multi_problem_intake(intake_service):
    batch = [
        {"title": "Prob 1", "statement": "Problem 1 statement", "preferred_language": "c"},
        {"title": "Prob 2", "statement": "Problem 2 statement", "preferred_language": "cpp"},
        {"title": "Prob 3", "statement": "Problem 3 statement", "preferred_language": "python"},
    ]
    results = intake_service.intake_batch(batch)
    assert len(results) == 3
    for item, report in results:
        assert item is not None
        assert report.is_acceptable is True


# 18. Invalid item isolation in batch
def test_invalid_item_isolation(intake_service):
    batch = [
        {"title": "Valid Prob", "statement": "Problem 1 statement"},
        "   ",  # Blank invalid
        {"title": "Unsupported Lang", "statement": "Test", "preferred_language": "unsupported_lang"},
        {"title": "Valid Prob 2", "statement": "Problem 2 statement"},
    ]
    results = intake_service.intake_batch(batch)
    assert len(results) == 4
    # Item 0: Valid
    assert results[0][0] is not None
    # Item 1: Invalid blank
    assert results[1][0] is None
    assert results[1][1].status == IntakeValidationStatus.INVALID_PROBLEM
    # Item 2: Invalid unsupported lang
    assert results[2][0] is None
    # Item 3: Valid
    assert results[3][0] is not None


# 19. Self-correction through dynamic intake
def test_self_correction_through_dynamic_intake(intake_service):
    # Flawed binary-search in C
    flaw_code, _ = INTENTIONAL_FLAWS[("binary-search", SupportedLanguage.C)]
    bp = BENCHMARK_REGISTRY["binary-search"]
    spec = to_problem_spec(bp)

    result = intake_service.solve_dynamically(
        raw_input=spec,
        preferred_language=SupportedLanguage.C,
        initial_flawed_code=flaw_code,
    )
    assert result.status == "VERIFIED"
    assert result.is_verified is True
    assert result.attempt_count >= 2  # Proves self-correction loop was executed


# 20. MAX_ATTEMPTS_REACHED propagation
def test_max_attempts_reached_propagation(intake_service):
    # Unfixable Java flaw
    unfixable_flaw = """class Solution {
    public int maxDepth(int[] nodes) {
        return -999;
    }
}"""
    bp = BENCHMARK_REGISTRY["maximum-depth-of-binary-tree"]
    spec = to_problem_spec(bp)

    result = intake_service.solve_dynamically(
        raw_input=spec,
        preferred_language=SupportedLanguage.JAVA,
        max_attempts=2,
        initial_flawed_code=unfixable_flaw,
    )
    assert result.status == "MAX_ATTEMPTS_REACHED"
    assert result.is_verified is False
    assert 1 <= result.attempt_count <= 2


# 21. Infrastructure failure propagation
def test_infrastructure_failure_propagation(intake_service, monkeypatch):
    from agent.core.models import TestSuiteReport
    # Simulate an infrastructure failure in testing engine
    def mock_eval(*args, **kwargs):
        return TestSuiteReport(
            all_passed=False,
            total_tests=0,
            passed_count=0,
            failed_count=0,
            execution_status=ExecutionStatus.INFRASTRUCTURE_ERROR,
            notes=["Compiler execution timed out or container host failed."],
        )
    monkeypatch.setattr(intake_service.runner.testing_engine, "evaluate_solution", mock_eval)

    bp = BENCHMARK_REGISTRY["two-sum"]
    spec = to_problem_spec(bp)
    result = intake_service.solve_dynamically(spec, preferred_language=SupportedLanguage.CPP)

    assert result.status == "INFRASTRUCTURE_ERROR"
    assert result.is_verified is False


# 22. Verification evidence preservation
def test_verification_evidence_preservation(intake_service):
    bp = BENCHMARK_REGISTRY["valid-palindrome"]
    spec = to_problem_spec(bp)
    result = intake_service.solve_dynamically(spec, preferred_language="c")

    assert result.verification is not None
    assert result.verification.correctness is True
    assert result.verification.constraints is True
    assert result.verification.complexity is True
    assert result.verification.plan_consistency is True


# 23. Result contract compliance
def test_result_contract_compliance(intake_service):
    bp = BENCHMARK_REGISTRY["climbing-stairs"]
    spec = to_problem_spec(bp)
    result = intake_service.solve_dynamically(spec, preferred_language="python")

    contract = result.model_dump()
    required_keys = ["problem_id", "queue_item_id", "job_id", "status", "language", "attempt_count", "tests_total", "tests_passed", "verification"]
    for k in required_keys:
        assert k in contract


# 24. API integration (POST /api/v1/problems/intake)
def test_api_intake_endpoint():
    import asyncio
    import httpx
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async def _test():
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            response = await client.post(
                "/api/v1/problems/intake",
                json={
                    "title": "API Two Sum",
                    "statement": "Given an array of integers nums and an integer target...",
                    "preferred_language": "cpp",
                    "priority": 5,
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert "queue_item_id" in data
            assert data["status"] == "PENDING"
            assert data["language"] == "cpp"
    asyncio.run(_test())


# 25. Restart/resume behavior
def test_restart_resume_behavior(temp_db):
    store = SQLiteQueueStore(db_path=temp_db)
    runner = AutonomousQueueRunner(store=store)
    intake = ProblemIntakeService(queue_runner=runner, queue_store=store, db_path=temp_db)

    item, _ = intake.intake_problem({"title": "Resume Test", "statement": "Resume statement"})
    item.transition_to(QueueItemStatus.RUNNING)
    store.save_item(item)

    # Simulate restart: reset in-progress items
    reset_count = store.reset_in_progress_to_pending()
    assert reset_count == 1
    reloaded = store.get_item(item.queue_item_id)
    assert reloaded.status == QueueItemStatus.PENDING
    store.close()


# 26. Idempotency verification
def test_idempotency_verification(intake_service):
    payload = {"title": "Idempotent Problem", "statement": "Statement content for idempotency"}
    item1, _ = intake_service.intake_problem(payload, preferred_language="python", allow_rerun=True)
    item2, _ = intake_service.intake_problem(payload, preferred_language="python", allow_rerun=True)

    assert item1.problem_hash == item2.problem_hash
    assert item1.queue_item_id != item2.queue_item_id
    persisted_all = intake_service.store.list_items()
    hashes = [it.problem_hash for it in persisted_all if it.problem_hash]
    assert hashes.count(item1.problem_hash) == 2
