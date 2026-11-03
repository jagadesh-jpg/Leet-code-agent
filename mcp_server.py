import os
import re
import sys
from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP

from assistant import solve_problem_flow, validate_problem_url
from judge import run_solution
from llm import LLMClient, LLMError, MockLLM
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
    """Return the current saved LeetCode solving progress including custom problems and official verdicts."""
    db_path = _get_active_db_path()
    store.init(db_path=db_path)
    all_problems = load_problems()
    summary = store.summary(db_path=db_path, problems=all_problems)

    # Add custom problems & official verdicts stats
    custom_list = store.list_custom_problems(db_path=db_path)
    verdicts = store.get_official_verdicts(db_path=db_path)

    verdict_counts: Dict[str, int] = {}
    for v in verdicts:
        v_name = v.get("verdict", "Unknown")
        verdict_counts[v_name] = verdict_counts.get(v_name, 0) + 1

    summary["custom_problems"] = {
        "total_imported": len(custom_list),
        "problems": [
            {
                "id": p["id"],
                "title": p["title"],
                "difficulty": p["difficulty"],
                "url": p["url"],
                "locally_solved": store.is_solved(p["id"], db_path=db_path),
            }
            for p in custom_list
        ],
    }
    summary["official_verdicts"] = {
        "total_recorded": len(verdicts),
        "breakdown": verdict_counts,
        "recent": verdicts[:5],
    }
    return summary


@mcp.tool()
def import_problem(
    url: str,
    title: str,
    difficulty: str,
    description: str,
    function_name: str,
    signature: str,
    example_tests: list[dict],
) -> dict:
    """Import a user-provided LeetCode problem manually without scraping or automated requests."""
    db_path = _get_active_db_path()
    store.init(db_path=db_path)

    # 1. Validate URL
    if not validate_problem_url(url):
        return {"error": "Invalid LeetCode problem URL. Must belong to leetcode.com or leetcode.cn."}

    # 2. Derive problem_id from URL slug or title
    slug = [seg for seg in url.strip().rstrip("/").split("/") if seg and seg != "description"]
    problem_id = slug[-1].lower() if slug else re.sub(r"[^a-zA-Z0-9_\-]+", "-", title.strip().lower())
    if not problem_id:
        problem_id = re.sub(r"[^a-zA-Z0-9_\-]+", "-", title.strip().lower())

    # 3. Validate metadata
    if not title or not description or not function_name or not signature:
        return {"error": "Missing required problem fields (title, description, function_name, or signature)."}

    diff_norm = difficulty.strip().lower()
    if diff_norm not in ["easy", "medium", "hard"]:
        diff_norm = "medium"

    # 4. Save custom problem
    store.save_custom_problem(
        problem_id=problem_id,
        url=url.strip(),
        title=title.strip(),
        difficulty=diff_norm,
        description=description.strip(),
        function_name=function_name.strip(),
        signature=signature.strip(),
        tests=example_tests,
        db_path=db_path,
    )

    return {
        "status": "imported",
        "problem_id": problem_id,
        "title": title.strip(),
        "difficulty": diff_norm,
        "example_tests_count": len(example_tests),
        "message": "Problem imported successfully. You can now solve it using solve_problem.",
    }


@mcp.tool()
def solve_problem(problem_id: str, max_attempts: int = 5) -> dict:
    """Generate, judge, and refine a Python solution for an imported or built-in problem."""
    db_path = _get_active_db_path()
    store.init(db_path=db_path)

    # Look in custom problems first, then built-in problems
    problem = store.get_custom_problem(problem_id, db_path=db_path)
    if not problem:
        for p in load_problems():
            if p["id"] == problem_id:
                problem = p
                break

    if not problem:
        return {"error": f"Problem '{problem_id}' not found in custom or built-in problems."}

    # Use LLMClient or fallback to MockLLM if not configured
    try:
        client = LLMClient()
    except Exception:
        all_probs = load_problems()
        if problem not in all_probs:
            all_probs = list(all_probs) + [problem]
        client = MockLLM(problems=all_probs)

    result = solve_problem_flow(problem, llm_client=client, max_attempts=max_attempts, db_path=db_path)
    return result


@mcp.tool()
def record_verdict(
    problem_id: str,
    verdict: str,
    runtime_ms: float = 0.0,
    memory_mb: float = 0.0,
    notes: str = "",
) -> dict:
    """Record official manual submission verdict on LeetCode (e.g. Accepted, Wrong Answer)."""
    db_path = _get_active_db_path()
    store.init(db_path=db_path)

    res = store.record_official_verdict(
        problem_id=problem_id,
        verdict=verdict,
        runtime_ms=runtime_ms,
        memory_mb=memory_mb,
        notes=notes,
        db_path=db_path,
    )
    return {
        "status": "recorded",
        "record": res,
        "note": "Official verdict saved in progress database.",
    }


if __name__ == "__main__":
    mcp.run()

