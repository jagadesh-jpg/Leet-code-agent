import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional


def _normalize_nested(obj: Any) -> Any:
    """Normalize nested lists for sorted_nested comparison by sorting inner lists and then outer list."""
    if isinstance(obj, list):
        normalized = [_normalize_nested(item) for item in obj]
        try:
            return sorted(normalized)
        except TypeError:
            return sorted(normalized, key=lambda x: str(x))
    return obj


RUNNER_TEMPLATE = r"""
import sys
import json

__MEMORY_LIMIT_CODE__

# LeetCode ListNode definition for Python
class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next

def list_to_linked_list(arr):
    if not isinstance(arr, list) or not arr:
        return None
    head = ListNode(arr[0])
    curr = head
    for v in arr[1:]:
        curr.next = ListNode(v)
        curr = curr.next
    return head

def linked_list_to_list(node):
    res = []
    visited = set()
    curr = node
    while curr is not None:
        if id(curr) in visited:
            break
        visited.add(id(curr))
        res.append(curr.val)
        curr = curr.next
    return res

# LeetCode TreeNode definition for Python
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right

def list_to_tree(arr):
    if not isinstance(arr, list) or not arr or arr[0] is None:
        return None
    root = TreeNode(arr[0])
    queue = [root]
    i = 1
    n = len(arr)
    while queue and i < n:
        curr = queue.pop(0)
        if curr is None:
            continue
        # Left child
        if i < n:
            val = arr[i]
            i += 1
            if val is not None:
                curr.left = TreeNode(val)
                queue.append(curr.left)
        # Right child
        if i < n:
            val = arr[i]
            i += 1
            if val is not None:
                curr.right = TreeNode(val)
                queue.append(curr.right)
    return root

def tree_to_list(root):
    if not root:
        return []
    res = []
    queue = [root]
    while queue:
        curr = queue.pop(0)
        if curr:
            res.append(curr.val)
            queue.append(curr.left)
            queue.append(curr.right)
        else:
            res.append(None)
    # Trim trailing Nones
    while res and res[-1] is None:
        res.pop()
    return res

# Candidate code
__CANDIDATE_CODE__

def normalize_nested(obj):
    if isinstance(obj, list):
        normalized = [normalize_nested(item) for item in obj]
        try:
            return sorted(normalized)
        except TypeError:
            return sorted(normalized, key=lambda x: str(x))
    return obj

def main():
    with open("problem_data.json", "r", encoding="utf-8") as f:
        problem = json.load(f)

    fn_name = problem["function_name"]
    fn = globals().get(fn_name)

    # Support LeetCode 'class Solution' if standalone function is not in globals
    if fn is None or not callable(fn):
        sol_cls = globals().get("Solution")
        if sol_cls is not None and isinstance(sol_cls, type):
            try:
                inst = sol_cls()
                method = getattr(inst, fn_name, None)
                if method is not None and callable(method):
                    fn = method
            except Exception:
                pass

    if fn is None or not callable(fn):
        res = {
            "status": "runtime_error",
            "passed_count": 0,
            "total": len(problem["tests"]),
            "failure": None,
            "error": f"Function '{fn_name}' was not found as a function or as a method on class Solution."
        }
        print("###RESULT_START###")
        print(json.dumps(res))
        print("###RESULT_END###")
        return

    tests = problem["tests"]
    compare_mode = problem.get("compare", "exact")
    sig_low = problem.get("signature", "").lower()
    pid_low = problem.get("id", "").lower()
    ptype_low = problem.get("type", "").lower()
    is_linked_list = ptype_low == "linked_list" or "reverselist" in fn_name.lower() or "reverse-linked-list" in pid_low or "listnode" in sig_low
    is_tree = ptype_low == "tree" or "treenode" in sig_low or "maxdepth" in fn_name.lower() or "tree" in pid_low
    passed_count = 0

    for idx, test in enumerate(tests):
        # Support both 'args' and 'input'
        if "args" in test:
            inp_args = test["args"]
        elif "input" in test:
            inp_args = test["input"]
        else:
            inp_args = []

        expected = test.get("expected")

        try:
            if is_linked_list:
                # If problem is linked list, convert input array(s) to ListNode
                if isinstance(inp_args, list) and len(inp_args) == 1 and isinstance(inp_args[0], list):
                    head = list_to_linked_list(inp_args[0])
                    actual_node = fn(head)
                elif isinstance(inp_args, list) and all(not isinstance(x, list) for x in inp_args):
                    head = list_to_linked_list(inp_args)
                    actual_node = fn(head)
                else:
                    head = list_to_linked_list(inp_args[0] if isinstance(inp_args, list) and inp_args else inp_args)
                    actual_node = fn(head)
                actual = linked_list_to_list(actual_node) if isinstance(actual_node, ListNode) or actual_node is None else actual_node
            elif is_tree:
                # If problem is tree, convert input array to TreeNode
                if isinstance(inp_args, list) and len(inp_args) == 1 and isinstance(inp_args[0], list):
                    root = list_to_tree(inp_args[0])
                    actual_res = fn(root)
                elif isinstance(inp_args, list) and (not inp_args or any(x is None or isinstance(x, (int, str)) for x in inp_args)):
                    root = list_to_tree(inp_args)
                    actual_res = fn(root)
                else:
                    root = list_to_tree(inp_args[0] if isinstance(inp_args, list) and inp_args else inp_args)
                    actual_res = fn(root)
                actual = tree_to_list(actual_res) if isinstance(actual_res, TreeNode) else actual_res
            else:
                if isinstance(inp_args, list):
                    actual = fn(*inp_args)
                else:
                    actual = fn(inp_args)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            res = {
                "status": "runtime_error",
                "passed_count": passed_count,
                "total": len(tests),
                "failure": {
                    "input": inp_args,
                    "expected": expected,
                    "actual": None
                },
                "error": tb
            }
            print("###RESULT_START###")
            print(json.dumps(res))
            print("###RESULT_END###")
            return

        is_match = False
        if compare_mode == "sorted_nested":
            is_match = (normalize_nested(actual) == normalize_nested(expected))
        else:
            is_match = (actual == expected)

        if is_match:
            passed_count += 1
        else:
            res = {
                "status": "wrong_answer",
                "passed_count": passed_count,
                "total": len(tests),
                "failure": {
                    "input": inp_args,
                    "expected": expected,
                    "actual": actual
                },
                "error": None
            }
            print("###RESULT_START###")
            print(json.dumps(res))
            print("###RESULT_END###")
            return

    res = {
        "status": "passed",
        "passed_count": passed_count,
        "total": len(tests),
        "failure": None,
        "error": None
    }
    print("###RESULT_START###")
    print(json.dumps(res))
    print("###RESULT_END###")

if __name__ == "__main__":
    main()
"""


from adapters import UnifiedJudge


def run_solution(code: str, problem: Dict[str, Any], timeout: int = 10, language: str = "python") -> Dict[str, Any]:
    if language and language.lower() not in ["python", "py", "python3"]:
        return UnifiedJudge.run_solution(code, problem, language=language, timeout=timeout)
    total_tests = len(problem.get("tests", []))
    if not code or not code.strip():
        return {
            "status": "no_code",
            "passed_count": 0,
            "total": total_tests,
            "failure": None,
            "error": "No executable code was provided.",
        }

    # On POSIX systems, apply 512 MB memory limit
    memory_limit_code = ""
    if os.name != "nt":
        memory_limit_code = """
try:
    import resource
    # 512 MB limit in bytes
    limit = 512 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
except Exception:
    pass
"""

    # Use safe string replacement instead of str.format() to prevent KeyError on braces in candidate code or runner logic
    runner_content = RUNNER_TEMPLATE.replace("__MEMORY_LIMIT_CODE__", memory_limit_code).replace(
        "__CANDIDATE_CODE__", code
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        runner_path = os.path.join(tmpdir, "runner.py")
        problem_data_path = os.path.join(tmpdir, "problem_data.json")

        with open(runner_path, "w", encoding="utf-8") as f:
            f.write(runner_content)

        with open(problem_data_path, "w", encoding="utf-8") as f:
            json.dump(problem, f)

        try:
            completed = subprocess.run(
                [sys.executable, "runner.py"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as e:
            stdout = e.stdout or ""
            stderr = e.stderr or ""
            err_msg = f"Execution timed out after {timeout} seconds."
            if stderr:
                err_msg += f"\nStderr:\n{stderr[-1000:]}"
            return {
                "status": "timeout",
                "passed_count": 0,
                "total": total_tests,
                "failure": None,
                "error": err_msg[-1500:],
            }
        except Exception as e:
            return {
                "status": "runtime_error",
                "passed_count": 0,
                "total": total_tests,
                "failure": None,
                "error": str(e)[-1500:],
            }

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""

        if "###RESULT_START###" in stdout and "###RESULT_END###" in stdout:
            try:
                start = stdout.index("###RESULT_START###") + len("###RESULT_START###")
                end = stdout.index("###RESULT_END###")
                result_json_str = stdout[start:end].strip()
                result = json.loads(result_json_str)
                if result.get("error") and len(result["error"]) > 1500:
                    result["error"] = result["error"][-1500:]
                return result
            except Exception as parse_err:
                combined_err = f"Failed to parse runner output: {parse_err}\nStdout:\n{stdout}\nStderr:\n{stderr}"
                return {
                    "status": "runtime_error",
                    "passed_count": 0,
                    "total": total_tests,
                    "failure": None,
                    "error": combined_err[-1500:],
                }

        # Non-zero return code or uncaught syntax/import error before json output
        err_text = stderr if stderr.strip() else stdout
        if not err_text.strip():
            err_text = f"Process exited with return code {completed.returncode}"
        return {
            "status": "runtime_error",
            "passed_count": 0,
            "total": total_tests,
            "failure": None,
            "error": err_text[-1500:],
        }
