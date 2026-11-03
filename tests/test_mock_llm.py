import pytest
from llm import MockLLM
from problems import load_problems
from prompts import SYSTEM_PROMPT, build_initial_prompt, build_retry_prompt, extract_code
from judge import run_solution


def test_mock_llm_all_problems():
    problems = load_problems()
    assert len(problems) == 9

    mock = MockLLM(problems=problems)

    for problem in problems:
        fn_name = problem["function_name"]
        prob_id = problem["id"]

        # Attempt 1
        prompt1 = build_initial_prompt(problem)
        resp1 = mock.ask(SYSTEM_PROMPT, prompt1)
        code1 = extract_code(resp1)

        # First response defines the correct function name
        assert f"def {fn_name}" in code1, f"Problem {prob_id} attempt 1 did not define {fn_name}"

        # First response gives an incorrect answer (judge returns wrong_answer, not runtime_error)
        res1 = run_solution(code1, problem)
        assert res1["status"] == "wrong_answer", (
            f"Expected wrong_answer for {prob_id} on attempt 1, got {res1['status']} (error: {res1.get('error')})"
        )

        # Attempt 2
        prompt2 = build_retry_prompt(
            problem,
            code1,
            res1["status"],
            failure_details=res1.get("failure"),
            error_trace=res1.get("error"),
        )
        resp2 = mock.ask(SYSTEM_PROMPT, prompt2)
        code2 = extract_code(resp2)

        # Second response matches problem's reference solution and passes
        assert problem["reference_solution"].strip() in code2
        res2 = run_solution(code2, problem)
        assert res2["status"] == "passed", (
            f"Expected passed for {prob_id} on attempt 2, got {res2['status']} (error: {res2.get('error')})"
        )


def test_mock_llm_independent_counters():
    problems = load_problems()
    mock = MockLLM(problems=problems)

    p1 = problems[0]
    p2 = problems[1]

    # Prompt p1 attempt 1
    resp1_p1 = mock.ask(SYSTEM_PROMPT, build_initial_prompt(p1))
    assert f"def {p1['function_name']}" in extract_code(resp1_p1)
    assert p1["reference_solution"].strip() not in extract_code(resp1_p1)

    # Prompt p2 attempt 1 (should be on attempt 1 for p2, not attempt 2)
    resp1_p2 = mock.ask(SYSTEM_PROMPT, build_initial_prompt(p2))
    assert f"def {p2['function_name']}" in extract_code(resp1_p2)
    assert p2["reference_solution"].strip() not in extract_code(resp1_p2)

    # Prompt p1 attempt 2 (now should give reference solution for p1)
    resp2_p1 = mock.ask(SYSTEM_PROMPT, build_retry_prompt(p1, "", "wrong_answer"))
    assert p1["reference_solution"].strip() in extract_code(resp2_p1)
    # Must not contain p2 reference solution
    assert p2["reference_solution"].strip() not in extract_code(resp2_p1)

    # Prompt p2 attempt 2 (now should give reference solution for p2)
    resp2_p2 = mock.ask(SYSTEM_PROMPT, build_retry_prompt(p2, "", "wrong_answer"))
    assert p2["reference_solution"].strip() in extract_code(resp2_p2)
