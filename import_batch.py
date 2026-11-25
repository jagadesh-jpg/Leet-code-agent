#!/usr/bin/env python3
"""Batch problem importer for LeetCode Agent.
Reads a JSON file of problems, validates them, tests reference solutions
with the local judge, and imports valid ones into the SQLite database.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import judge
import store


REQUIRED_FIELDS = [
    "id",
    "title",
    "difficulty",
    "description",
    "function_name",
    "reference_solution",
    "tests",
]

VALID_DIFFICULTIES = {"easy", "medium", "hard"}


def validate_problem_data(
    item: Any, existing_ids: set, seen_batch_ids: set
) -> Tuple[bool, str]:
    """Validate data shape, required fields, difficulty, duplicate IDs, and test count."""
    if not isinstance(item, dict):
        return False, "Item must be a JSON object"

    for field in REQUIRED_FIELDS:
        if field not in item or item[field] is None:
            return False, f"Missing required field: '{field}'"
        if isinstance(item[field], str) and not item[field].strip():
            return False, f"Field '{field}' cannot be empty"

    prob_id = str(item["id"]).strip().lower()
    if not prob_id:
        return False, "Field 'id' cannot be blank"

    if prob_id in seen_batch_ids:
        return False, f"Duplicate problem ID in this file: '{prob_id}'"

    if prob_id in existing_ids:
        return False, f"Problem ID already exists in database: '{prob_id}'"

    diff = str(item["difficulty"]).strip().lower()
    if diff not in VALID_DIFFICULTIES:
        return False, f"Invalid difficulty: '{item['difficulty']}'. Must be Easy, Medium, or Hard"

    tests = item.get("tests")
    if not isinstance(tests, list):
        return False, "Field 'tests' must be a list"

    if len(tests) < 5:
        return False, f"Must provide at least 5 test cases (found {len(tests)})"

    for idx, test_case in enumerate(tests):
        if not isinstance(test_case, dict):
            return False, f"Test #{idx+1} must be an object with 'input' and 'expected'"
        if "input" not in test_case:
            return False, f"Test #{idx+1} missing 'input' field"
        if "expected" not in test_case:
            return False, f"Test #{idx+1} missing 'expected' field"

    return True, ""


def verify_reference_solution(item: Dict[str, Any]) -> Tuple[bool, str]:
    """Run reference solution through judge against tests to confirm correctness."""
    ref_code = item["reference_solution"]
    res = judge.run_solution(ref_code, item, language="python")

    if res.get("status") != "passed":
        err_msg = res.get("error") or res.get("failure") or "Did not pass all tests"
        passed_count = res.get("passed_count", 0)
        total = res.get("total", len(item["tests"]))
        return False, f"Reference solution failed local judge ({passed_count}/{total} passed): {err_msg}"

    return True, ""


def import_batch_from_file(
    file_path: str | Path, db_path: Optional[str | Path] = None
) -> Dict[str, Any]:
    """Validate, test, and import a batch of problems from a JSON file."""
    path = Path(file_path)
    if not path.exists():
        return {
            "success": False,
            "error": f"File not found: {path}",
            "imported": [],
            "rejected": [{"id": "N/A", "reason": f"File not found: {path}"}],
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to parse JSON file: {e}",
            "imported": [],
            "rejected": [{"id": "N/A", "reason": f"Invalid JSON syntax: {e}"}],
        }

    if not isinstance(data, list):
        return {
            "success": False,
            "error": "Root JSON element must be an array of problem objects",
            "imported": [],
            "rejected": [{"id": "N/A", "reason": "Root JSON must be a list"}],
        }

    store.init(db_path=db_path)
    existing_custom = {p["id"] for p in store.list_custom_problems(db_path=db_path)}

    imported_list = []
    rejected_list = []
    seen_batch_ids = set()

    for item in data:
        raw_id = item.get("id") if isinstance(item, dict) else None
        item_id = str(raw_id).strip().lower() if raw_id else "unknown"

        # 1. Structural and field validation
        valid_data, data_err = validate_problem_data(item, existing_custom, seen_batch_ids)
        if not valid_data:
            rejected_list.append({"id": item_id, "reason": data_err})
            continue

        seen_batch_ids.add(item_id)

        # 2. Reference solution judge test
        valid_sol, sol_err = verify_reference_solution(item)
        if not valid_sol:
            rejected_list.append({"id": item_id, "reason": sol_err})
            continue

        # 3. Import problem via standard store code path
        norm_diff = str(item["difficulty"]).strip().capitalize()
        norm_url = item.get("url") or f"https://leetcode.com/problems/{item_id}/"
        norm_title = str(item["title"]).strip()
        norm_desc = str(item["description"]).strip()
        norm_fn = str(item["function_name"]).strip()

        # Signatures can be string or dict
        sigs = item.get("signatures")
        if isinstance(sigs, dict):
            sig_str = json.dumps(sigs)
        elif isinstance(item.get("signature"), str):
            sig_str = item["signature"]
        else:
            sig_str = f"def {norm_fn}(self, *args):"

        store.save_custom_problem(
            problem_id=item_id,
            url=norm_url,
            title=norm_title,
            difficulty=norm_diff,
            description=norm_desc,
            function_name=norm_fn,
            signature=sig_str,
            tests=item["tests"],
            reference_solution=item.get("reference_solution"),
            db_path=db_path,
        )

        existing_custom.add(item_id)
        imported_list.append(item_id)

    return {
        "success": True,
        "total_read": len(data),
        "imported_count": len(imported_list),
        "rejected_count": len(rejected_list),
        "imported": imported_list,
        "rejected": rejected_list,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Bulk import LeetCode problems from a JSON file into LeetCode Agent."
    )
    parser.add_argument("file", help="Path to JSON file containing problems list.")
    parser.add_argument("--db", default=None, help="Optional SQLite database path.")
    args = parser.parse_args()

    res = import_batch_from_file(args.file, db_path=args.db)

    print("\n" + "=" * 50)
    print("BATCH PROBLEM IMPORT SUMMARY")
    print("=" * 50)
    print(f"Total read: {res.get('total_read', 0)}")
    print(f"Imported:   {res.get('imported_count', 0)}")
    print(f"Rejected:   {res.get('rejected_count', 0)}")

    if res.get("imported"):
        print("\nImported Problems:")
        for pid in res["imported"]:
            print(f"  [+] {pid}")

    if res.get("rejected"):
        print("\nRejected Problems:")
        for rej in res["rejected"]:
            print(f"  [-] {rej['id']}: {rej['reason']}")
    print("=" * 50 + "\n")

    if res.get("imported_count", 0) == 0 and res.get("rejected_count", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
