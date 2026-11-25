import pytest
from pathlib import Path
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


def test_mock_llm_language_detection_and_signature_normalization():
    """Verify Task 1 & 2 requirements:
    1. Python language detection when prompt contains signatures for Python, C, C++, and Java.
    2. C language detection.
    3. C++ language detection.
    4. Java language detection.
    5. Signature normalization from a Python dictionary.
    6. Signature normalization from a serialized JSON dictionary.
    7. Backward compatibility with plain-string signatures.
    8. Missing or malformed signatures.
    """
    from prompts import normalize_signature, get_system_prompt_for_language

    # 5. Dict normalization
    dict_sig = {"python": "def solve():", "c": "void solve()", "cpp": "void solve()", "java": "public void solve()"}
    assert normalize_signature(dict_sig, "python") == "def solve():"
    assert normalize_signature(dict_sig, "c") == "void solve()"
    assert normalize_signature(dict_sig, "cpp") == "void solve()"
    assert normalize_signature(dict_sig, "java") == "public void solve()"

    # 6. Serialized JSON string normalization
    import json
    json_sig = json.dumps(dict_sig)
    assert normalize_signature(json_sig, "python") == "def solve():"
    assert normalize_signature(json_sig, "c") == "void solve()"
    assert normalize_signature(json_sig, "cpp") == "void solve()"
    assert normalize_signature(json_sig, "java") == "public void solve()"

    # 7. Backward compatibility with plain string
    plain_sig = "def sortColors(self, nums):"
    assert normalize_signature(plain_sig, "python") == "def sortColors(self, nums):"

    # 8. Missing or malformed signature
    assert "unavailable" in normalize_signature(None, "python").lower()
    assert "unavailable" in normalize_signature("", "python").lower()
    assert "unavailable" in normalize_signature("{invalid json", "python").lower()

    # 1. Python detection when prompt contains "cpp", "c", and "java" in signature
    mock = MockLLM()
    py_sys = get_system_prompt_for_language("python")
    user_prompt_with_multisig = (
        "Problem ID: sort-colors\n"
        "Function Signature:\n"
        '{"python": "def sortColors()", "cpp": "void sortColors()", "c": "void sortColors()", "java": "void sortColors()"}\n'
        "Please write the complete solution. Provide only the Python code block."
    )
    resp = mock.ask(py_sys, user_prompt_with_multisig)
    code = extract_code(resp)
    # Must produce Python code, NOT C++ code!
    assert "class Solution {" not in code
    assert "def sortColors" in code

    # 2. C detection
    c_sys = get_system_prompt_for_language("c")
    resp_c = mock.ask(c_sys, "Problem ID: sort-colors\nPlease write the complete solution.")
    assert "int sortColors" in extract_code(resp_c)

    # 3. C++ detection
    cpp_sys = get_system_prompt_for_language("cpp")
    resp_cpp = mock.ask(cpp_sys, "Problem ID: sort-colors\nPlease write the complete solution.")
    assert "class Solution" in extract_code(resp_cpp)

    # 4. Java detection
    java_sys = get_system_prompt_for_language("java")
    resp_java = mock.ask(java_sys, "Problem ID: sort-colors\nPlease write the complete solution.")
    assert "class Solution" in extract_code(resp_java)


def test_custom_problem_persistence_and_mock_cycle(tmp_path):
    """Verify Task 3, 4, 5 requirements:
    9. Custom reference solution persistence through import and retrieval.
    10. Fresh SQLite schema initialization.
    11. Additive migration of an existing database schema.
    12. Existing custom problem records preserved after migration.
    13. MockLLM's intentional failure followed by correction.
    14. Autonomous mock execution of sort-colors in Python using a temporary database.
    15. Regression test proving no C++ output is produced for a Python run solely because prompt contains 'cpp'.
    """
    import store
    import sqlite3
    from autonomous import run_autonomous_queue

    # 10. Fresh SQLite schema initialization
    fresh_db = tmp_path / "fresh.db"
    store.init(db_path=fresh_db)
    with store.get_connection(fresh_db) as conn:
        cols = [c[1] for c in conn.cursor().execute("PRAGMA table_info(custom_problems)").fetchall()]
        assert "reference_solution" in cols

    # 9. Custom problem persistence with reference_solution
    store.save_custom_problem(
        problem_id="test-custom-1",
        url="https://leetcode.com/problems/test-custom-1/",
        title="Test Custom 1",
        difficulty="Easy",
        description="Return number plus 1",
        function_name="plusOne",
        signature="def plusOne(self, x: int) -> int:",
        tests=[{"input": [1], "expected": 2}, {"input": [5], "expected": 6}],
        reference_solution="class Solution:\n    def plusOne(self, x: int) -> int:\n        return x + 1",
        db_path=fresh_db,
    )
    retrieved = store.get_custom_problem("test-custom-1", db_path=fresh_db)
    assert retrieved is not None
    assert retrieved["reference_solution"] == "class Solution:\n    def plusOne(self, x: int) -> int:\n        return x + 1"

    # 11 & 12. Additive migration of an older database schema without reference_solution column
    legacy_db = tmp_path / "legacy.db"
    conn_leg = sqlite3.connect(legacy_db)
    conn_leg.execute(
        """
        CREATE TABLE custom_problems (
            id TEXT PRIMARY KEY,
            url TEXT,
            title TEXT,
            difficulty TEXT,
            description TEXT,
            function_name TEXT,
            signature TEXT,
            tests_json TEXT,
            created_at TEXT
        )
        """
    )
    conn_leg.execute(
        """
        INSERT INTO custom_problems VALUES (
            'legacy-prob', 'url', 'Legacy Problem', 'Easy', 'desc', 'solve', 'sig', '[]', '2026-01-01'
        )
        """
    )
    conn_leg.commit()
    conn_leg.close()

    # store.init should perform additive migration safely
    store.init(db_path=legacy_db)
    with store.get_connection(legacy_db) as conn:
        cols = [c[1] for c in conn.cursor().execute("PRAGMA table_info(custom_problems)").fetchall()]
        assert "reference_solution" in cols

    # Check that existing record is preserved
    legacy_record = store.get_custom_problem("legacy-prob", db_path=legacy_db)
    assert legacy_record is not None
    assert legacy_record["title"] == "Legacy Problem"
    assert "reference_solution" not in legacy_record or legacy_record.get("reference_solution") is None

    # 13 & 14. Autonomous mock execution of sort-colors in Python using a temporary database
    # Import problems_batch_medium10.json into a temporary db
    import import_batch
    batch_file = Path(__file__).resolve().parent.parent / "problems_batch_medium10.json"
    import_res = import_batch.import_batch_from_file(batch_file, db_path=fresh_db)
    assert import_res["success"] is True
    assert "sort-colors" in import_res["imported"]

    prob_sc = store.get_custom_problem("sort-colors", db_path=fresh_db)
    assert prob_sc is not None
    assert prob_sc.get("reference_solution") is not None

    # Run MockLLM intentional failure followed by correction
    mock_llm = MockLLM(problems=[prob_sc])
    run_res = run_autonomous_queue(
        max_problems=1,
        max_attempts_per_problem=3,
        language="python",
        db_path=fresh_db,
        problem_ids=["sort-colors"],
        llm_client=mock_llm,
    )
    assert run_res["status"] == "completed"
    assert run_res["verified_count"] == 1
    assert run_res["failed_count"] == 0

    # 15. Verify that attempt 1 was a Python failure (NOT a C++ runtime_error syntax failure)
    with store.get_connection(fresh_db) as conn:
        attempts = conn.cursor().execute("SELECT attempt_no, status, code, error FROM attempts WHERE problem_id='sort-colors' ORDER BY attempt_no").fetchall()
        assert len(attempts) >= 2
        # Attempt 1: wrong_answer with python code, not runtime_error with C++
        assert attempts[0][1] == "wrong_answer"
        assert "class Solution {" not in attempts[0][2]
        # Attempt 2: passed with python reference solution
        assert attempts[1][1] == "passed"
        assert "class Solution:" in attempts[1][2]
