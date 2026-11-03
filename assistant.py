import json
import re
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from judge import run_solution
from llm import LLMClient, LLMError, MockLLM
from prompts import (
    SYSTEM_PROMPT,
    build_initial_prompt,
    build_retry_prompt,
    build_complexity_prompt,
    extract_code,
    format_copy_ready_solution,
)
import store


def validate_problem_url(url: str) -> bool:
    """Validate LeetCode URL without fetching or scraping."""
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url.strip())
    if parsed.scheme not in ["http", "https"]:
        return False
    if "leetcode.com" not in parsed.netloc and "leetcode.cn" not in parsed.netloc:
        return False
    return True


def solve_problem_flow(
    problem: Dict[str, Any],
    llm_client: Any,
    max_attempts: int = 5,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Autonomous solve-test-fix loop for an individual problem.
    Supports dependency injection for llm_client (e.g. LLMClient or MockLLM).
    Clearly distinguishes local test verification from official LeetCode submission.
    """
    prob_id = problem["id"]
    title = problem.get("title", prob_id)
    fn_name = problem.get("function_name", "solve")

    store.init(db_path=db_path)

    passed = False
    last_code = ""
    last_judge_res: Dict[str, Any] = {}
    attempts_used = 0

    for attempt_no in range(1, max_attempts + 1):
        attempts_used = attempt_no

        if attempt_no == 1:
            user_prompt = build_initial_prompt(problem)
        else:
            user_prompt = build_retry_prompt(
                problem=problem,
                previous_code=last_code,
                judge_status=last_judge_res.get("status", "error"),
                failure_details=last_judge_res.get("failure"),
                error_trace=last_judge_res.get("error"),
            )

        resp = llm_client.ask(SYSTEM_PROMPT, user_prompt)
        code = extract_code(resp)
        last_code = code

        # Run candidate code in isolated judge subprocess
        judge_res = run_solution(code, problem)
        last_judge_res = judge_res

        status = judge_res["status"]
        err_text = judge_res.get("error")

        # Record attempt in SQLite attempts table
        store.log_attempt(
            problem_id=prob_id,
            attempt_no=attempt_no,
            code=code,
            status=status,
            error=err_text,
            db_path=db_path,
        )

        if status == "passed":
            passed = True
            store.mark_result(prob_id, "solved", attempt_no, db_path=db_path)
            break

    if not passed:
        store.mark_result(prob_id, "failed", max_attempts, db_path=db_path)

    # Complexity estimate (AI-generated)
    time_complexity = "O(n) [AI estimate]"
    space_complexity = "O(1) [AI estimate]"
    if passed and last_code:
        try:
            comp_prompt = build_complexity_prompt(problem, last_code)
            comp_resp = llm_client.ask(SYSTEM_PROMPT, comp_prompt)
            match = re.search(r"\{[\s\S]*\}", comp_resp)
            if match:
                parsed = json.loads(match.group(0))
                time_complexity = parsed.get("time_complexity", time_complexity)
                space_complexity = parsed.get("space_complexity", space_complexity)
        except Exception:
            pass

    copy_ready = format_copy_ready_solution(last_code, fn_name)

    return {
        "problem_id": prob_id,
        "title": title,
        "passed": passed,
        "local_status": "locally_verified" if passed else last_judge_res.get("status", "failed"),
        "attempts": attempts_used,
        "tests_passed": last_judge_res.get("passed_count", 0),
        "total_tests": last_judge_res.get("total", len(problem.get("tests", []))),
        "raw_code": last_code,
        "copy_ready_code": copy_ready,
        "time_complexity": time_complexity,
        "space_complexity": space_complexity,
        "disclaimer": (
            "NOTICE: This solution has been LOCALLY VERIFIED against provided example tests only. "
            "It has NOT been submitted to LeetCode. Please review and manually submit on LeetCode."
        ),
    }
