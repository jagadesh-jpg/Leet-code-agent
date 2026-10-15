"""
Unit and regression tests for Task 3:
Python LeetCode harness with ListNode, TreeNode, typing imports, and serialization/deserialization.
"""

import pytest
from agent.execution.python_adapter import (
    ListNode,
    TreeNode,
    list_to_linkedlist,
    linkedlist_to_list,
    list_to_tree,
    tree_to_list,
    PythonAdapter,
)
from agent.core.models import (
    Difficulty,
    ProblemSpec,
    TestCase,
)


def test_listnode_conversion_roundtrip():
    values = [1, 2, 3, 4, 5]
    head = list_to_linkedlist(values)
    assert head is not None
    assert head.val == 1
    assert head.next.val == 2
    roundtrip = linkedlist_to_list(head)
    assert roundtrip == values


def test_listnode_empty():
    assert list_to_linkedlist([]) is None
    assert linkedlist_to_list(None) == []


def test_treenode_conversion_roundtrip():
    # [3, 9, 20, None, None, 15, 7]
    tree_vals = [3, 9, 20, None, None, 15, 7]
    root = list_to_tree(tree_vals)
    assert root is not None
    assert root.val == 3
    assert root.left.val == 9
    assert root.right.val == 20
    assert root.right.left.val == 15
    assert root.right.right.val == 7
    roundtrip = tree_to_list(root)
    assert roundtrip == tree_vals


def test_treenode_empty():
    assert list_to_tree([]) is None
    assert tree_to_list(None) == []


def test_python_harness_generates_standard_definitions():
    adapter = PythonAdapter()
    spec = ProblemSpec(
        id="invert-binary-tree",
        title="Invert Binary Tree",
        description="Invert a binary tree",
        raw_statement="Invert a binary tree",
        difficulty=Difficulty.EASY,
        function_name="invertTree",
        param_names=["root"],
        return_type="Optional[TreeNode]",
        test_cases=[
            TestCase(id="1", inputs={"root": [4, 2, 7]}, expected_output=[4, 7, 2])
        ],
    )
    code = """
class Solution:
    def invertTree(self, root: Optional[TreeNode]) -> Optional[TreeNode]:
        if not root:
            return None
        root.left, root.right = self.invertTree(root.right), self.invertTree(root.left)
        return root
"""
    harness = adapter.generate_harness(spec, code, spec.test_cases)
    assert "class ListNode:" in harness
    assert "class TreeNode:" in harness
    assert "from typing import" in harness
    assert "Optional" in harness
    assert "def list_to_tree" in harness
    assert "def list_to_linkedlist" in harness
