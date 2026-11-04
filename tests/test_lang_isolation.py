import pytest
from pathlib import Path

import autonomous
import store


@pytest.fixture
def test_db(tmp_path):
    db = tmp_path / "test_lang_isolation.db"
    store.init(db_path=db)
    return db


def test_language_specific_progress_isolation(test_db):
    """Verify that solving Binary Search in one language does not mark it solved in another."""
    prob_id = "binary-search"

    # Save a custom problem for binary search in the test database
    store.save_custom_problem(
        problem_id=prob_id,
        url="https://leetcode.com/problems/binary-search/",
        title="Binary Search",
        difficulty="easy",
        description="Search target in sorted array nums.",
        function_name="search",
        signature="def search(nums: list[int], target: int) -> int:",
        tests=[{"input": [[-1, 0, 3, 5, 9, 12], 9], "expected": 4}],
        db_path=test_db,
    )

    # Initially, problem is not solved in any language
    for lang in ["python", "java", "c", "cpp"]:
        assert store.is_solved(prob_id, language=lang, db_path=test_db) is False

    # 1. Solve in Python and mark it locally_verified
    store.mark_result(prob_id, "solved", attempts=1, language="python", db_path=test_db)
    assert store.is_solved(prob_id, language="python", db_path=test_db) is True

    # 2 & 3. Check pending queue for Java: Binary Search MUST remain eligible in Java
    queue_java = autonomous.get_pending_queue(language="java", db_path=test_db)
    assert any(p["id"] == prob_id for p in queue_java)

    # When querying Python queue again with skip_locally_verified=True, Python skips it
    queue_python = autonomous.get_pending_queue(language="python", db_path=test_db)
    assert not any(p["id"] == prob_id for p in queue_python)

    # 4. Mark it locally_verified in Java
    store.mark_result(prob_id, "solved", attempts=1, language="java", db_path=test_db)
    assert store.is_solved(prob_id, language="java", db_path=test_db) is True

    # 5 & 6. Check pending queue for C: Binary Search MUST remain eligible in C
    queue_c = autonomous.get_pending_queue(language="c", db_path=test_db)
    assert any(p["id"] == prob_id for p in queue_c)

    # 7. Repeat for C++
    store.mark_result(prob_id, "solved", attempts=1, language="c", db_path=test_db)
    assert store.is_solved(prob_id, language="c", db_path=test_db) is True

    queue_cpp = autonomous.get_pending_queue(language="cpp", db_path=test_db)
    assert any(p["id"] == prob_id for p in queue_cpp)

    store.mark_result(prob_id, "solved", attempts=1, language="cpp", db_path=test_db)
    assert store.is_solved(prob_id, language="cpp", db_path=test_db) is True

    # Now all four languages are locally verified individually
    for lang in ["python", "java", "c", "cpp"]:
        assert store.is_solved(prob_id, language=lang, db_path=test_db) is True

    # 8 & 9. Official LeetCode verdicts remain separate from local language verifications
    verdicts = store.get_official_verdicts(problem_id=prob_id, db_path=test_db)
    assert len(verdicts) == 0  # No official verdict created simply by local verifications

