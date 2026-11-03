import pytest
from problems import get_problems, load_problems


def test_dataset_contains_nine_problems():
    problems = load_problems()
    assert len(problems) == 9, f"Expected 9 problems, found {len(problems)}"


def test_three_problems_per_difficulty():
    problems = load_problems()
    counts = {"easy": 0, "medium": 0, "hard": 0}
    for p in problems:
        counts[p["difficulty"]] += 1

    assert counts["easy"] == 3, f"Expected 3 easy problems, got {counts['easy']}"
    assert counts["medium"] == 3, f"Expected 3 medium problems, got {counts['medium']}"
    assert counts["hard"] == 3, f"Expected 3 hard problems, got {counts['hard']}"


def test_difficulty_ordering():
    problems = load_problems()
    difficulties = [p["difficulty"] for p in problems]
    expected_order = ["easy", "easy", "easy", "medium", "medium", "medium", "hard", "hard", "hard"]
    assert difficulties == expected_order, f"Order mismatch: {difficulties}"


def test_difficulty_filtering():
    easy_probs = get_problems("easy")
    assert len(easy_probs) == 3
    assert all(p["difficulty"] == "easy" for p in easy_probs)

    med_probs = get_problems("medium")
    assert len(med_probs) == 3
    assert all(p["difficulty"] == "medium" for p in med_probs)

    hard_probs = get_problems("hard")
    assert len(hard_probs) == 3
    assert all(p["difficulty"] == "hard" for p in hard_probs)


def test_invalid_difficulty_filter():
    with pytest.raises(ValueError):
        get_problems("extreme")
