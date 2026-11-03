import json
import re
from typing import Any, Dict, Optional

SYSTEM_PROMPT = "You are an expert Python programmer. Reply with exactly one Python code block containing the complete solution and nothing else. Use only the Python standard library."


def build_initial_prompt(problem: Dict[str, Any]) -> str:
    examples = problem.get("tests", [])[:2]
    example_strs = []
    for i, ex in enumerate(examples, 1):
        inp_val = ex.get("input", ex.get("args"))
        example_strs.append(
            f"Example {i}:\n  Input: {json.dumps(inp_val)}\n  Expected: {json.dumps(ex.get('expected'))}"
        )
    examples_formatted = "\n\n".join(example_strs)

    return f"""Problem ID: {problem.get('id')}
Problem Title: {problem.get('title')}
Difficulty: {problem.get('difficulty')}

Description:
{problem.get('description')}

Function Signature:
{problem.get('signature')}

Example Tests:
{examples_formatted}

Please write the complete solution. Provide only the Python code block."""


def build_retry_prompt(
    problem: Dict[str, Any],
    previous_code: str,
    judge_status: str,
    failure_details: Optional[Any] = None,
    error_trace: Optional[str] = None,
) -> str:
    details_part = ""
    if failure_details:
        inp_val = failure_details.get("input", failure_details.get("args"))
        details_part += (
            f"Failing Test Case:\n"
            f"Input: {json.dumps(inp_val)}\n"
            f"Expected: {json.dumps(failure_details.get('expected'))}\n"
            f"Actual: {json.dumps(failure_details.get('actual'))}\n"
        )
    if error_trace:
        details_part += f"Error / Traceback:\n{error_trace}\n"

    return f"""Problem ID: {problem.get('id')}
Problem Title: {problem.get('title')}
Problem Description:
{problem.get('description')}

Function Signature:
{problem.get('signature')}

Previous Attempt:
```python
{previous_code}
```

Judge Status: {judge_status}
{details_part}
Please fix the error and provide the complete corrected solution in one Python code block."""


def extract_code(response_text: str) -> str:
    if not response_text:
        return ""

    # 1. Extract first ```python ... ``` code block
    py_pattern = r"```python\s*([\s\S]*?)```"
    py_match = re.search(py_pattern, response_text, re.IGNORECASE)
    if py_match:
        return py_match.group(1).strip()

    # 2. Extract first generic ``` ... ``` code block
    gen_pattern = r"```([\s\S]*?)```"
    gen_match = re.search(gen_pattern, response_text)
    if gen_match:
        return gen_match.group(1).strip()

    # 3. Otherwise return empty string
    return ""
