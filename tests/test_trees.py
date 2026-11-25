import pytest
from adapters import UnifiedJudge

MAX_DEPTH_PROBLEM = {
    "id": "maximum-depth-of-binary-tree",
    "title": "Maximum Depth of Binary Tree",
    "difficulty": "Easy",
    "function_name": "maxDepth",
    "type": "tree",
    "signature": "def maxDepth(self, root: Optional[TreeNode]) -> int:",
    "tests": [
        {"input": [[3, 9, 20, None, None, 15, 7]], "expected": 3},
        {"input": [[1, None, 2]], "expected": 2},
        {"input": [[]], "expected": 0},
        {"input": [[0]], "expected": 1},
        {"input": [[1, 2, 3, 4, None, None, 5]], "expected": 3},
    ]
}


def test_python_tree_max_depth_success():
    py_code = """
class Solution:
    def maxDepth(self, root):
        if not root:
            return 0
        return 1 + max(self.maxDepth(root.left), self.maxDepth(root.right))
"""
    res = UnifiedJudge.run_solution(py_code, MAX_DEPTH_PROBLEM, language="python")
    assert res["status"] == "passed"
    assert res["passed_count"] == 5


def test_python_tree_max_depth_failure():
    bad_py = """
class Solution:
    def maxDepth(self, root):
        return -1
"""
    res = UnifiedJudge.run_solution(bad_py, MAX_DEPTH_PROBLEM, language="python")
    assert res["status"] == "wrong_answer"
    assert res["passed_count"] == 0


def test_c_tree_max_depth_success():
    c_code = """
int maxDepth(struct TreeNode* root) {
    if (!root) return 0;
    int l = maxDepth(root->left);
    int r = maxDepth(root->right);
    return 1 + (l > r ? l : r);
}
"""
    res = UnifiedJudge.run_solution(c_code, MAX_DEPTH_PROBLEM, language="c")
    assert res["status"] == "passed"
    assert res["passed_count"] == 5


def test_c_tree_max_depth_failure():
    bad_c = """
int maxDepth(struct TreeNode* root) {
    return 999;
}
"""
    res = UnifiedJudge.run_solution(bad_c, MAX_DEPTH_PROBLEM, language="c")
    assert res["status"] == "wrong_answer" or res["passed_count"] == 0


def test_cpp_tree_max_depth_success():
    cpp_code = """
#include <algorithm>

class Solution {
public:
    int maxDepth(TreeNode* root) {
        if (!root) return 0;
        return 1 + std::max(maxDepth(root->left), maxDepth(root->right));
    }
};
"""
    res = UnifiedJudge.run_solution(cpp_code, MAX_DEPTH_PROBLEM, language="cpp")
    assert res["status"] == "passed"
    assert res["passed_count"] == 5


def test_cpp_tree_max_depth_failure():
    bad_cpp = """
class Solution {
public:
    int maxDepth(TreeNode* root) {
        return 0;
    }
};
"""
    res = UnifiedJudge.run_solution(bad_cpp, MAX_DEPTH_PROBLEM, language="cpp")
    assert res["status"] == "wrong_answer" or res["passed_count"] < 5


def test_java_tree_max_depth_success():
    java_code = """
class Solution {
    public int maxDepth(TreeNode root) {
        if (root == null) return 0;
        return 1 + Math.max(maxDepth(root.left), maxDepth(root.right));
    }
}
"""
    res = UnifiedJudge.run_solution(java_code, MAX_DEPTH_PROBLEM, language="java")
    assert res["status"] == "passed"
    assert res["passed_count"] == 5


def test_java_tree_max_depth_failure():
    bad_java = """
class Solution {
    public int maxDepth(TreeNode root) {
        return -5;
    }
}
"""
    res = UnifiedJudge.run_solution(bad_java, MAX_DEPTH_PROBLEM, language="java")
    assert res["status"] == "wrong_answer" or res["passed_count"] == 0
