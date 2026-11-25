import pytest
from pathlib import Path

from adapters import UnifiedJudge, PythonLanguageAdapter, CLanguageAdapter, CppLanguageAdapter, JavaLanguageAdapter
from harness import build_c_runner, build_cpp_runner, build_java_runner
import store

REVERSE_LIST_PROBLEM = {
    "id": "reverse-linked-list",
    "title": "Reverse Linked List",
    "difficulty": "easy",
    "function_name": "reverseList",
    "type": "linked_list",
    "signature": "def reverseList(self, head: Optional[ListNode]) -> Optional[ListNode]:",
    "tests": [
        {"input": [[1, 2, 3, 4, 5]], "expected": [5, 4, 3, 2, 1]},
        {"input": [[1, 2]], "expected": [2, 1]},
        {"input": [[]], "expected": []},
        {"input": [[1]], "expected": [1]},
        {"input": [[1, 1, 2]], "expected": [2, 1, 1]},
    ]
}


def test_python_reverse_linked_list_success():
    py_code = """
class Solution:
    def reverseList(self, head):
        prev = None
        curr = head
        while curr:
            nxt = curr.next
            curr.next = prev
            prev = curr
            curr = nxt
        return prev
"""
    res = UnifiedJudge.run_solution(py_code, REVERSE_LIST_PROBLEM, language="python")
    assert res["status"] == "passed"
    assert res["passed_count"] == 5


def test_python_reverse_linked_list_failure():
    # Incorrect solution returns unchanged head
    bad_py = """
class Solution:
    def reverseList(self, head):
        return head
"""
    res = UnifiedJudge.run_solution(bad_py, REVERSE_LIST_PROBLEM, language="python")
    assert res["status"] == "wrong_answer"
    assert res["passed_count"] < 5


def test_c_reverse_linked_list_success():
    c_code = """
struct ListNode* reverseList(struct ListNode* head) {
    struct ListNode* prev = NULL;
    struct ListNode* curr = head;
    while (curr) {
        struct ListNode* nxt = curr->next;
        curr->next = prev;
        prev = curr;
        curr = nxt;
    }
    return prev;
}
"""
    res = UnifiedJudge.run_solution(c_code, REVERSE_LIST_PROBLEM, language="c")
    assert res["status"] == "passed"
    assert res["passed_count"] == 5
    assert "RESULTS: passed=5, failed=0, total=5" in res.get("stdout", "")


def test_c_reverse_linked_list_failure():
    bad_c = """
struct ListNode* reverseList(struct ListNode* head) {
    return head;
}
"""
    res = UnifiedJudge.run_solution(bad_c, REVERSE_LIST_PROBLEM, language="c")
    assert res["status"] == "runtime_error" or res["passed_count"] < 5


def test_cpp_reverse_linked_list_success():
    cpp_code = """
class Solution {
public:
    ListNode* reverseList(ListNode* head) {
        ListNode* prev = nullptr;
        ListNode* curr = head;
        while (curr) {
            ListNode* nxt = curr->next;
            curr->next = prev;
            prev = curr;
            curr = nxt;
        }
        return prev;
    }
};
"""
    res = UnifiedJudge.run_solution(cpp_code, REVERSE_LIST_PROBLEM, language="cpp")
    assert res["status"] == "passed"
    assert res["passed_count"] == 5
    assert "RESULTS: passed=5, failed=0, total=5" in res.get("stdout", "")


def test_java_reverse_linked_list_success():
    java_code = """
class Solution {
    public ListNode reverseList(ListNode head) {
        ListNode prev = null;
        ListNode curr = head;
        while (curr != null) {
            ListNode nxt = curr.next;
            curr.next = prev;
            prev = curr;
            curr = nxt;
        }
        return prev;
    }
}
"""
    res = UnifiedJudge.run_solution(java_code, REVERSE_LIST_PROBLEM, language="java")
    assert res["status"] == "passed"
    assert res["passed_count"] == 5
    assert "RESULTS: passed=5, failed=0, total=5" in res.get("stdout", "")


def test_java_reverse_linked_list_failure():
    bad_java = """
class Solution {
    public ListNode reverseList(ListNode head) {
        return head;
    }
}
"""
    res = UnifiedJudge.run_solution(bad_java, REVERSE_LIST_PROBLEM, language="java")
    assert res["status"] == "runtime_error" or res["passed_count"] < 5
