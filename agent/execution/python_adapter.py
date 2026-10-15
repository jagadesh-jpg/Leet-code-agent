"""
Python Execution Adapter.
Generates deterministic test harnesses for Python solutions and prepares execution commands.
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from agent.core.models import (
    SupportedLanguage,
    ProblemSpec,
    TestCase,
    ExecutionResult,
)
from agent.execution.base import BaseLanguageAdapter


class ListNode:
    """Standard LeetCode singly-linked list node."""
    def __init__(self, val: int = 0, next: Optional["ListNode"] = None):
        self.val = val
        self.next = next

    def __repr__(self) -> str:
        vals = []
        curr = self
        visited = set()
        while curr and id(curr) not in visited:
            visited.add(id(curr))
            vals.append(str(curr.val))
            curr = curr.next
        return "[" + ",".join(vals) + "]"


class TreeNode:
    """Standard LeetCode binary tree node."""
    def __init__(self, val: int = 0, left: Optional["TreeNode"] = None, right: Optional["TreeNode"] = None):
        self.val = val
        self.left = left
        self.right = right

    def __repr__(self) -> str:
        return f"TreeNode({self.val})"


def list_to_linkedlist(arr: Optional[List[Any]]) -> Optional[ListNode]:
    if not arr:
        return None
    dummy = ListNode(0)
    curr = dummy
    for x in arr:
        curr.next = ListNode(x)
        curr = curr.next
    return dummy.next


def linkedlist_to_list(head: Optional[ListNode]) -> List[Any]:
    res = []
    curr = head
    visited = set()
    while curr and id(curr) not in visited:
        visited.add(id(curr))
        res.append(curr.val)
        curr = curr.next
    return res


def list_to_tree(arr: Optional[List[Any]]) -> Optional[TreeNode]:
    if not arr:
        return None
    root = TreeNode(arr[0])
    queue = [root]
    i = 1
    while queue and i < len(arr):
        node = queue.pop(0)
        if node is not None:
            if i < len(arr) and arr[i] is not None:
                node.left = TreeNode(arr[i])
                queue.append(node.left)
            i += 1
            if i < len(arr) and arr[i] is not None:
                node.right = TreeNode(arr[i])
                queue.append(node.right)
            i += 1
    return root


def tree_to_list(root: Optional[TreeNode]) -> List[Any]:
    if not root:
        return []
    res = []
    queue = [root]
    while queue:
        node = queue.pop(0)
        if node:
            res.append(node.val)
            queue.append(node.left)
            queue.append(node.right)
        else:
            res.append(None)
    while res and res[-1] is None:
        res.pop()
    return res


class PythonAdapter(BaseLanguageAdapter):
    """Python 3 execution adapter."""

    @property
    def language(self) -> SupportedLanguage:
        return SupportedLanguage.PYTHON

    @property
    def source_extension(self) -> str:
        return ".py"

    def is_toolchain_available(self) -> bool:
        return shutil.which(sys.executable) is not None

    def generate_harness(
        self,
        problem: ProblemSpec,
        solution_code: str,
        test_cases: List[TestCase],
    ) -> str:
        """
        Wraps solution code in an execution harness.
        Injects test cases, runs them safely, measures execution time,
        and prints serialized JSON to stdout with exact markers.
        """
        # Serialize test cases to embed in harness
        serialized_cases = []
        for tc in test_cases:
            serialized_cases.append({
                "id": tc.id,
                "inputs": tc.inputs,
                "expected": tc.expected_output,
            })

        cases_json_str = json.dumps(serialized_cases)
        harness_template = f'''# -*- coding: utf-8 -*-
"""Auto-generated deterministic test runner"""
import sys
import json
import time
import traceback
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Common LeetCode data structure definitions
class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next

    def __repr__(self):
        vals = []
        curr = self
        visited = set()
        while curr and id(curr) not in visited:
            visited.add(id(curr))
            vals.append(str(curr.val))
            curr = curr.next
        return "[" + ",".join(vals) + "]"

class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right

    def __repr__(self):
        return f"TreeNode({{self.val}})"

def list_to_linkedlist(arr):
    if not arr:
        return None
    dummy = ListNode(0)
    curr = dummy
    for x in arr:
        curr.next = ListNode(x)
        curr = curr.next
    return dummy.next

def linkedlist_to_list(head):
    res = []
    curr = head
    visited = set()
    while curr and id(curr) not in visited:
        visited.add(id(curr))
        res.append(curr.val)
        curr = curr.next
    return res

def list_to_tree(arr):
    if not arr:
        return None
    root = TreeNode(arr[0])
    queue = [root]
    i = 1
    while queue and i < len(arr):
        node = queue.pop(0)
        if node is not None:
            if i < len(arr) and arr[i] is not None:
                node.left = TreeNode(arr[i])
                queue.append(node.left)
            i += 1
            if i < len(arr) and arr[i] is not None:
                node.right = TreeNode(arr[i])
                queue.append(node.right)
            i += 1
    return root

def tree_to_list(root):
    if not root:
        return []
    res = []
    queue = [root]
    while queue:
        node = queue.pop(0)
        if node:
            res.append(node.val)
            queue.append(node.left)
            queue.append(node.right)
        else:
            res.append(None)
    while res and res[-1] is None:
        res.pop()
    return res

# --- User Solution Code Begin ---
{solution_code}
# --- User Solution Code End ---

TEST_CASES = json.loads({repr(cases_json_str)})
FUNCTION_NAME = {json.dumps(problem.function_name)}

def normalize(val):
    if isinstance(val, (set, frozenset)):
        return sorted(list(val))
    if isinstance(val, ListNode):
        return linkedlist_to_list(val)
    if isinstance(val, TreeNode):
        return tree_to_list(val)
    return val

def run_tests():
    # Instantiate Solution if class exists, else use global function
    target_fn = None
    if "Solution" in globals():
        sol_instance = globals()["Solution"]()
        if hasattr(sol_instance, FUNCTION_NAME):
            target_fn = getattr(sol_instance, FUNCTION_NAME)
    
    if target_fn is None and FUNCTION_NAME in globals():
        target_fn = globals()[FUNCTION_NAME]

    if target_fn is None:
        sys.stderr.write(f"Target function '{{FUNCTION_NAME}}' or 'Solution.{{FUNCTION_NAME}}' not found in solution.\\n")
        sys.exit(2)

    results = []
    all_passed = True

    for tc in TEST_CASES:
        tc_id = tc["id"]
        inputs = tc["inputs"]
        expected = tc["expected"]
        
        start_time = time.perf_counter()
        try:
            # Call function with kwargs or positional args
            if isinstance(inputs, dict):
                actual = target_fn(**inputs)
            elif isinstance(inputs, (list, tuple)):
                actual = target_fn(*inputs)
            else:
                actual = target_fn(inputs)
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            
            # Comparison: handle both strict equality and list comparison
            passed = (normalize(actual) == normalize(expected))
            if not passed:
                all_passed = False

            results.append({{
                "test_case_id": tc_id,
                "passed": passed,
                "input_data": inputs,
                "expected_output": expected,
                "actual_output": actual,
                "error_message": None,
                "execution_time_ms": elapsed_ms
            }})
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            all_passed = False
            results.append({{
                "test_case_id": tc_id,
                "passed": False,
                "input_data": inputs,
                "expected_output": expected,
                "actual_output": None,
                "error_message": f"{{type(e).__name__}}: {{str(e)}}\\n{{traceback.format_exc()}}",
                "execution_time_ms": elapsed_ms
            }})

    output_payload = {{
        "all_passed": all_passed,
        "results": results
    }}

    print("<<<EXECUTION_RESULTS_START>>>")
    print(json.dumps(output_payload))
    print("<<<EXECUTION_RESULTS_END>>>")

    if not all_passed:
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    run_tests()
'''
        return harness_template

    def compile(self, source_path: Path, output_dir: Path) -> Optional[ExecutionResult]:
        """Python is interpreted; no explicit compilation needed."""
        return None

    def get_run_command(self, source_or_binary_path: Path, output_dir: Path) -> List[str]:
        # -I: isolated mode (no user site packages, no current dir on sys.path injection vulnerabilities)
        return [sys.executable, "-I", str(source_or_binary_path)]
