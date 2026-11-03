import json
from pathlib import Path
from typing import Any, Dict, List, Optional

VALID_DIFFICULTIES = ["easy", "medium", "hard"]
DIFFICULTY_ORDER = {"easy": 1, "medium": 2, "hard": 3}

REQUIRED_KEYS = [
    "id",
    "title",
    "difficulty",
    "description",
    "function_name",
    "signature",
    "tests",
    "compare",
    "reference_solution",
]


def load_problems(json_path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    if json_path is None:
        json_path = Path(__file__).resolve().parent / "problems.json"
    else:
        json_path = Path(json_path)

    if not json_path.exists():
        raise FileNotFoundError(f"Problems file not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        problems = json.load(f)

    if not isinstance(problems, list):
        raise ValueError("problems.json must contain a JSON array of problem objects.")

    for idx, p in enumerate(problems):
        if not isinstance(p, dict):
            raise ValueError(f"Problem at index {idx} must be a JSON object.")
        for key in REQUIRED_KEYS:
            if key not in p:
                raise ValueError(f"Problem {p.get('id', idx)} is missing required key '{key}'.")
        diff = p["difficulty"].lower()
        if diff not in VALID_DIFFICULTIES:
            raise ValueError(f"Problem {p['id']} has invalid difficulty '{p['difficulty']}'.")
        p["difficulty"] = diff
        if not isinstance(p["tests"], list) or len(p["tests"]) < 6:
            raise ValueError(f"Problem {p['id']} must have at least 6 test cases.")
        if p["compare"] not in ["exact", "sorted_nested"]:
            raise ValueError(f"Problem {p['id']} has unsupported compare rule '{p['compare']}'.")

    # Sort problems in order: easy, medium, hard
    problems.sort(key=lambda x: DIFFICULTY_ORDER.get(x["difficulty"], 99))
    return problems


def get_problems(difficulty: Optional[str] = None, json_path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    all_problems = load_problems(json_path)
    if difficulty:
        diff_clean = difficulty.strip().lower()
        if diff_clean not in VALID_DIFFICULTIES:
            raise ValueError(f"Invalid difficulty filter: '{difficulty}'. Must be easy, medium, or hard.")
        return [p for p in all_problems if p["difficulty"] == diff_clean]
    return all_problems
