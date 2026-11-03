import os
import sys
from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP

from judge import run_solution
from problems import get_problems, load_problems
import store

# Initialize FastMCP server
mcp = FastMCP("leetcode-agent")

# Allow an optional environment variable to point to a custom/isolated database path (e.g. for testing)
DB_PATH: Optional[str] = os.environ.get("LEETCODE_AGENT_DB_PATH")


def _get_active_db_path() -> Optional[str]:
    return os.environ.get("LEETCODE_AGENT_DB_PATH", DB_PATH)


@mcp.tool()
def list_problems(difficulty: str = "") -> list[dict]:
    """List available LeetCode problems and whether each is solved."""
    db_path = _get_active_db_path()
    store.init(db_path=db_path)

    try:
        if difficulty and difficulty.strip():
            problem_list = get_problems(difficulty=difficulty.strip())
        else:
            problem_list = load_problems()
    except ValueError as e:
        sys.stderr.write(f"Error filtering problems by difficulty '{difficulty}': {e}\n")
        return []

    results = []
    for p in problem_list:
        prob_id = p["id"]
        solved = store.is_solved(prob_id, db_path=db_path)
        results.append({
            "id": prob_id,
            "title": p.get("title", ""),
            "difficulty": p.get("difficulty", ""),
            "solved": solved,
        })
    return results


@mcp.tool()
def get_problem(problem_id: str) -> dict:
    """Get the description, signature and two example tests for a problem."""
    all_problems = load_problems()
    target = None
    for p in all_problems:
        if p["id"] == problem_id:
            target = p
            break

    if not target:
        return {"error": "unknown problem"}

    # Extract first two example tests with args/input and expected output
    examples = []
    for test in target.get("tests", [])[:2]:
        inp = test.get("args", test.get("input"))
        examples.append({
            "input": inp,
            "expected": test.get("expected"),
        })

    return {
        "id": target["id"],
        "title": target.get("title", ""),
        "difficulty": target.get("difficulty", ""),
        "description": target.get("description", ""),
        "signature": target.get("signature", ""),
        "examples": examples,
    }


@mcp.tool()
def submit_solution(problem_id: str, code: str) -> dict:
    """Run submitted Python code against a problem's test cases and save the attempt."""
    db_path = _get_active_db_path()
    store.init(db_path=db_path)

    # 1. Validate problem_id
    all_problems = load_problems()
    problem = None
    for p in all_problems:
        if p["id"] == problem_id:
            problem = p
            break

    if not problem:
        return {"error": "unknown problem"}

    # 2. Reject code longer than 20,000 characters
    if len(code) > 20000:
        return {"error": "Code exceeds maximum allowed length of 20,000 characters."}

    # 3. Validate that code is non-empty
    if not code or not code.strip():
        return {"error": "Code cannot be empty."}

    # 4. Determine attempt number
    current_attempts = store.get_attempt_count(problem_id, db_path=db_path)
    attempt_no = current_attempts + 1

    # 5. Run through judge
    judge_result = run_solution(code, problem)
    status = judge_result.get("status")
    err_text = judge_result.get("error")

    # 6. Log attempt using store.py
    store.log_attempt(
        problem_id=problem_id,
        attempt_no=attempt_no,
        code=code,
        status=status,
        error=err_text,
        db_path=db_path,
    )

    # 7. If the solution passes, mark problem as solved
    if status == "passed":
        store.mark_result(problem_id, "solved", attempt_no, db_path=db_path)

    # Return judge result
    return {
        "status": status,
        "passed_count": judge_result.get("passed_count", 0),
        "total": judge_result.get("total", 0),
        "failure": judge_result.get("failure"),
        "error": err_text,
    }


@mcp.tool()
def get_progress() -> dict:
    """Return the current saved LeetCode solving progress."""
    db_path = _get_active_db_path()
    store.init(db_path=db_path)
    all_problems = load_problems()
    return store.summary(db_path=db_path, problems=all_problems)


if __name__ == "__main__":
    mcp.run()

