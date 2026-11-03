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


def format_copy_ready_solution(code: str, function_name: str) -> str:
    """Ensure candidate code is properly formatted for LeetCode's class-based editor.
    If 'class Solution' is already present, return code as is.
    Otherwise, wrap the standalone function into class Solution."""
    if not code:
        return ""
    if re.search(r"\bclass\s+Solution\b", code):
        return code.strip()

    # Wrap standalone function
    lines = code.strip().splitlines()
    wrapped_lines = ["class Solution:"]
    for line in lines:
        if line.strip():
            # If line is function definition, add 'self' parameter if not present
            if re.match(r"\s*def\s+" + re.escape(function_name) + r"\s*\(", line):
                def_prefix = re.match(r"(\s*def\s+" + re.escape(function_name) + r"\s*\()", line).group(1)
                rest = line[len(def_prefix):]
                if not rest.startswith("self"):
                    if rest.startswith(")"):
                        line = def_prefix + "self" + rest
                    else:
                        line = def_prefix + "self, " + rest
            wrapped_lines.append("    " + line)
        else:
            wrapped_lines.append("")
    return "\n".join(wrapped_lines)


def build_complexity_prompt(problem: Dict[str, Any], code: str) -> str:
    return f"""Problem: {problem.get('title', problem.get('id', ''))}
Code:
```python
{code}
```

Please analyze the Big-O time and space complexity of this Python solution.
Reply in JSON format with exactly two keys:
{{
  "time_complexity": "O(...)",
  "space_complexity": "O(...)",
  "explanation": "concise explanation"
}}"""

