import json
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional


def _is_linked_list_problem(problem: Dict[str, Any]) -> bool:
    fn = problem.get("function_name", "").lower()
    pid = problem.get("id", "").lower()
    ptype = problem.get("type", "").lower()
    sig = problem.get("signature", "").lower()
    return (
        ptype == "linked_list"
        or "listnode" in sig
        or "reverselist" in fn
        or "reverse-linked-list" in pid
        or "linked" in pid
    )


def _is_tree_problem(problem: Dict[str, Any]) -> bool:
    fn = problem.get("function_name", "").lower()
    pid = problem.get("id", "").lower()
    ptype = problem.get("type", "").lower()
    sig = problem.get("signature", "").lower()
    return (
        ptype == "tree"
        or "treenode" in sig
        or "maxdepth" in fn
        or "depth" in fn
        or "tree" in pid
    )


# ============================================================================
# C Test Runner Builders
# ============================================================================

def build_c_runner(user_code: str, problem: Dict[str, Any]) -> str:
    """Build a standalone C test runner that compiles and executes user code against problem tests."""
    tests = problem.get("tests", [])

    if _is_linked_list_problem(problem):
        # Linked list runner with struct ListNode, list builders, and memory cleanup
        test_cases_code = []
        for idx, t in enumerate(tests):
            inp = t.get("args", t.get("input", []))
            # Handle [1,2,3] or [[1,2,3]]
            if isinstance(inp, list) and len(inp) == 1 and isinstance(inp[0], list):
                nodes_arr = inp[0]
            elif isinstance(inp, list) and all(isinstance(x, int) for x in inp):
                nodes_arr = inp
            else:
                nodes_arr = inp[0] if isinstance(inp, list) and inp else []

            expected = t.get("expected", [])
            arr_str = ", ".join(map(str, nodes_arr))
            exp_str = ", ".join(map(str, expected))
            n_len = len(nodes_arr)
            exp_len = len(expected)

            test_cases_code.append(f"""
    {{
        int in_arr[] = {{{arr_str}}};
        int exp_arr[] = {{{exp_str}}};
        struct ListNode* head = create_list(in_arr, {n_len});
        struct ListNode* res = {problem.get('function_name', 'reverseList')}(head);

        bool ok = true;
        struct ListNode* curr = res;
        for (int i = 0; i < {exp_len}; i++) {{
            if (!curr || curr->val != exp_arr[i]) {{
                ok = false;
                break;
            }}
            curr = curr->next;
        }}
        if (curr != NULL) ok = false;

        if (ok) {{
            passed++;
        }} else {{
            printf("Test {idx+1} Failed\\n");
            failed++;
        }}
        free_list(res);
    }}
""")

        return f"""
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>

// Definition for singly-linked list.
struct ListNode {{
    int val;
    struct ListNode *next;
}};

static struct ListNode* create_list(int* arr, int n) {{
    if (n == 0) return NULL;
    struct ListNode* head = (struct ListNode*)malloc(sizeof(struct ListNode));
    head->val = arr[0];
    head->next = NULL;
    struct ListNode* curr = head;
    for (int i = 1; i < n; i++) {{
        curr->next = (struct ListNode*)malloc(sizeof(struct ListNode));
        curr = curr->next;
        curr->val = arr[i];
        curr->next = NULL;
    }}
    return head;
}}

static void free_list(struct ListNode* head) {{
    while (head) {{
        struct ListNode* tmp = head;
        head = head->next;
        free(tmp);
    }}
}}

// Candidate Solution Code
{user_code}

int main() {{
    int passed = 0;
    int failed = 0;
    int total = {len(tests)};
    {"".join(test_cases_code)}
    printf("RESULTS: passed=%d, failed=%d, total=%d\\n", passed, failed, total);
    return failed == 0 ? 0 : 1;
}}
"""

    if _is_tree_problem(problem):
        # C Tree runner with struct TreeNode and level-order array parser
        test_cases_code = []
        fn_name = problem.get("function_name", "maxDepth")
        for idx, t in enumerate(tests):
            inp = t.get("args", t.get("input", []))
            if isinstance(inp, list) and len(inp) == 1 and isinstance(inp[0], list):
                nodes_arr = inp[0]
            elif isinstance(inp, list):
                nodes_arr = inp
            else:
                nodes_arr = []

            expected = t.get("expected")

            # Convert null to sentinel -999999
            c_vals = []
            c_nulls = []
            for item in nodes_arr:
                if item is None:
                    c_vals.append("0")
                    c_nulls.append("1")
                else:
                    c_vals.append(str(item))
                    c_nulls.append("0")

            n_len = len(nodes_arr)
            vals_str = ", ".join(c_vals) if c_vals else "0"
            nulls_str = ", ".join(c_nulls) if c_nulls else "0"
            exp_val = expected if isinstance(expected, (int, float, bool)) else 0

            test_cases_code.append(f"""
    {{
        int vals[] = {{{vals_str}}};
        int is_null[] = {{{nulls_str}}};
        struct TreeNode* root = create_tree(vals, is_null, {n_len});
        int exp_val = {int(exp_val)};
        int actual = {fn_name}(root);
        if (actual == exp_val) {{
            passed++;
        }} else {{
            printf("Test {idx+1} Failed: expected %d, got %d\\n", exp_val, actual);
            failed++;
        }}
        free_tree(root);
    }}
""")

        return f"""
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>

// Definition for a binary tree node.
struct TreeNode {{
    int val;
    struct TreeNode *left;
    struct TreeNode *right;
}};

static struct TreeNode* create_tree(int* vals, int* is_null, int n) {{
    if (n == 0 || is_null[0]) return NULL;
    struct TreeNode* root = (struct TreeNode*)malloc(sizeof(struct TreeNode));
    root->val = vals[0];
    root->left = NULL;
    root->right = NULL;

    struct TreeNode** queue = (struct TreeNode**)malloc(sizeof(struct TreeNode*) * (n + 10));
    int head = 0, tail = 0;
    queue[tail++] = root;

    int i = 1;
    while (head < tail && i < n) {{
        struct TreeNode* curr = queue[head++];
        if (!curr) continue;

        // Left child
        if (i < n) {{
            if (!is_null[i]) {{
                curr->left = (struct TreeNode*)malloc(sizeof(struct TreeNode));
                curr->left->val = vals[i];
                curr->left->left = NULL;
                curr->left->right = NULL;
                queue[tail++] = curr->left;
            }}
            i++;
        }}

        // Right child
        if (i < n) {{
            if (!is_null[i]) {{
                curr->right = (struct TreeNode*)malloc(sizeof(struct TreeNode));
                curr->right->val = vals[i];
                curr->right->left = NULL;
                curr->right->right = NULL;
                queue[tail++] = curr->right;
            }}
            i++;
        }}
    }}
    free(queue);
    return root;
}}

static void free_tree(struct TreeNode* root) {{
    if (!root) return;
    free_tree(root->left);
    free_tree(root->right);
    free(root);
}}

// Candidate Solution Code
{user_code}

int main() {{
    int passed = 0;
    int failed = 0;
    int total = {len(tests)};
    {"".join(test_cases_code)}
    printf("RESULTS: passed=%d, failed=%d, total=%d\\n", passed, failed, total);
    return failed == 0 ? 0 : 1;
}}
"""

    # Default array / integer search runner
    test_cases_code = []
    for idx, t in enumerate(tests):
        inp = t.get("args", t.get("input", []))
        nums = inp[0] if len(inp) > 0 else []
        target = inp[1] if len(inp) > 1 else 0
        expected = t.get("expected", 0)

        nums_str = ", ".join(map(str, nums)) if isinstance(nums, list) else str(nums)
        n_len = len(nums) if isinstance(nums, list) else 1

        test_cases_code.append(f"""
    {{
        int nums[] = {{{nums_str}}};
        int target = {target};
        int expected = {expected};
        int actual = {problem.get('function_name', 'search')}(nums, {n_len}, target);
        if (actual == expected) {{
            passed++;
        }} else {{
            printf("Test {idx+1} Failed: expected %d, got %d\\n", expected, actual);
            failed++;
        }}
    }}
""")

    return f"""
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>

// Candidate Solution Code
{user_code}

int main() {{
    int passed = 0;
    int failed = 0;
    int total = {len(tests)};
    {"".join(test_cases_code)}
    printf("RESULTS: passed=%d, failed=%d, total=%d\\n", passed, failed, total);
    return failed == 0 ? 0 : 1;
}}
"""


# ============================================================================
# C++ Test Runner Builders
# ============================================================================

def build_cpp_runner(user_code: str, problem: Dict[str, Any]) -> str:
    """Build a standalone C++ test runner with LeetCode class Solution support."""
    tests = problem.get("tests", [])

    if _is_linked_list_problem(problem):
        test_cases_code = []
        for idx, t in enumerate(tests):
            inp = t.get("args", t.get("input", []))
            if isinstance(inp, list) and len(inp) == 1 and isinstance(inp[0], list):
                nodes_arr = inp[0]
            elif isinstance(inp, list) and all(isinstance(x, int) for x in inp):
                nodes_arr = inp
            else:
                nodes_arr = inp[0] if isinstance(inp, list) and inp else []

            expected = t.get("expected", [])
            arr_str = ", ".join(map(str, nodes_arr))
            exp_str = ", ".join(map(str, expected))

            test_cases_code.append(f"""
    {{
        std::vector<int> in_v = {{{arr_str}}};
        std::vector<int> exp_v = {{{exp_str}}};
        ListNode* head = create_list(in_v);
        ListNode* res = sol.{problem.get('function_name', 'reverseList')}(head);
        std::vector<int> act_v = list_to_vector(res);
        if (act_v == exp_v) {{
            passed++;
        }} else {{
            std::cout << "Test {idx+1} Failed\\n";
            failed++;
        }}
        free_list(res);
    }}
""")

        return f"""
#include <iostream>
#include <vector>
#include <string>
#include <algorithm>

// Definition for singly-linked list.
struct ListNode {{
    int val;
    ListNode *next;
    ListNode() : val(0), next(nullptr) {{}}
    ListNode(int x) : val(x), next(nullptr) {{}}
    ListNode(int x, ListNode *next) : val(x), next(next) {{}}
}};

static ListNode* create_list(const std::vector<int>& arr) {{
    if (arr.empty()) return nullptr;
    ListNode* head = new ListNode(arr[0]);
    ListNode* curr = head;
    for (size_t i = 1; i < arr.size(); ++i) {{
        curr->next = new ListNode(arr[i]);
        curr = curr->next;
    }}
    return head;
}}

static std::vector<int> list_to_vector(ListNode* head) {{
    std::vector<int> res;
    while (head) {{
        res.push_back(head->val);
        head = head->next;
    }}
    return res;
}}

static void free_list(ListNode* head) {{
    while (head) {{
        ListNode* tmp = head;
        head = head->next;
        delete tmp;
    }}
}}

// Candidate Solution Code
{user_code}

int main() {{
    Solution sol;
    int passed = 0;
    int failed = 0;
    int total = {len(tests)};
    {"".join(test_cases_code)}
    std::cout << "RESULTS: passed=" << passed << ", failed=" << failed << ", total=" << total << "\\n";
    return failed == 0 ? 0 : 1;
}}
"""

    if _is_tree_problem(problem):
        test_cases_code = []
        fn_name = problem.get("function_name", "maxDepth")
        for idx, t in enumerate(tests):
            inp = t.get("args", t.get("input", []))
            if isinstance(inp, list) and len(inp) == 1 and isinstance(inp[0], list):
                nodes_arr = inp[0]
            elif isinstance(inp, list):
                nodes_arr = inp
            else:
                nodes_arr = []

            expected = t.get("expected")

            cpp_nodes = []
            for item in nodes_arr:
                if item is None:
                    cpp_nodes.append("{0, true}")
                else:
                    cpp_nodes.append(f"{{{item}, false}}")

            nodes_init = ", ".join(cpp_nodes) if cpp_nodes else ""
            exp_val = expected if isinstance(expected, (int, float, bool)) else 0

            test_cases_code.append(f"""
    {{
        std::vector<std::pair<int, bool>> in_v = {{{nodes_init}}};
        TreeNode* root = create_tree(in_v);
        int exp_val = {int(exp_val)};
        int actual = sol.{fn_name}(root);
        if (actual == exp_val) {{
            passed++;
        }} else {{
            std::cout << "Test {idx+1} Failed: expected " << exp_val << ", got " << actual << "\\n";
            failed++;
        }}
        free_tree(root);
    }}
""")

        return f"""
#include <iostream>
#include <vector>
#include <string>
#include <algorithm>
#include <queue>
#include <utility>

// Definition for a binary tree node.
struct TreeNode {{
    int val;
    TreeNode *left;
    TreeNode *right;
    TreeNode() : val(0), left(nullptr), right(nullptr) {{}}
    TreeNode(int x) : val(x), left(nullptr), right(nullptr) {{}}
    TreeNode(int x, TreeNode *left, TreeNode *right) : val(x), left(left), right(right) {{}}
}};

static TreeNode* create_tree(const std::vector<std::pair<int, bool>>& arr) {{
    if (arr.empty() || arr[0].second) return nullptr;
    TreeNode* root = new TreeNode(arr[0].first);
    std::queue<TreeNode*> q;
    q.push(root);
    size_t i = 1;
    while (!q.empty() && i < arr.size()) {{
        TreeNode* curr = q.front();
        q.pop();
        if (!curr) continue;

        // Left child
        if (i < arr.size()) {{
            if (!arr[i].second) {{
                curr->left = new TreeNode(arr[i].first);
                q.push(curr->left);
            }}
            i++;
        }}

        // Right child
        if (i < arr.size()) {{
            if (!arr[i].second) {{
                curr->right = new TreeNode(arr[i].first);
                q.push(curr->right);
            }}
            i++;
        }}
    }}
    return root;
}}

static void free_tree(TreeNode* root) {{
    if (!root) return;
    free_tree(root->left);
    free_tree(root->right);
    delete root;
}}

// Candidate Solution Code
{user_code}

int main() {{
    Solution sol;
    int passed = 0;
    int failed = 0;
    int total = {len(tests)};
    {"".join(test_cases_code)}
    std::cout << "RESULTS: passed=" << passed << ", failed=" << failed << ", total=" << total << "\\n";
    return failed == 0 ? 0 : 1;
}}
"""

    # Default vector / scalar search runner
    test_cases_code = []
    for idx, t in enumerate(tests):
        inp = t.get("args", t.get("input", []))
        nums = inp[0] if len(inp) > 0 else []
        target = inp[1] if len(inp) > 1 else 0
        expected = t.get("expected", 0)

        nums_str = ", ".join(map(str, nums)) if isinstance(nums, list) else str(nums)

        test_cases_code.append(f"""
    {{
        std::vector<int> nums = {{{nums_str}}};
        int target = {target};
        int expected = {expected};
        int actual = sol.{problem.get('function_name', 'search')}(nums, target);
        if (actual == expected) {{
            passed++;
        }} else {{
            std::cout << "Test {idx+1} Failed: expected " << expected << ", got " << actual << "\\n";
            failed++;
        }}
    }}
""")

    return f"""
#include <iostream>
#include <vector>
#include <string>
#include <algorithm>

// Candidate Solution Code
{user_code}

int main() {{
    Solution sol;
    int passed = 0;
    int failed = 0;
    int total = {len(tests)};
    {"".join(test_cases_code)}
    std::cout << "RESULTS: passed=" << passed << ", failed=" << failed << ", total=" << total << "\\n";
    return failed == 0 ? 0 : 1;
}}
"""


# ============================================================================
# Java Test Runner Builders
# ============================================================================

def _format_java_val(val: Any) -> str:
    if isinstance(val, list):
        inner = ", ".join(_format_java_val(x) for x in val)
        return f"new int[]{{{inner}}}"
    return str(val)


def build_java_runner(user_code: str, problem: Dict[str, Any]) -> str:
    """Build a Java test harness for LeetCode class Solution."""
    tests = problem.get("tests", [])

    if _is_linked_list_problem(problem):
        test_cases_code = []
        for idx, t in enumerate(tests):
            inp = t.get("args", t.get("input", []))
            if isinstance(inp, list) and len(inp) == 1 and isinstance(inp[0], list):
                nodes_arr = inp[0]
            elif isinstance(inp, list) and all(isinstance(x, int) for x in inp):
                nodes_arr = inp
            else:
                nodes_arr = inp[0] if isinstance(inp, list) and inp else []

            expected = t.get("expected", [])
            arr_str = ", ".join(map(str, nodes_arr))
            exp_str = ", ".join(map(str, expected))

            test_cases_code.append(f"""
        {{
            int[] inArr = new int[]{{{arr_str}}};
            int[] expArr = new int[]{{{exp_str}}};
            ListNode head = createList(inArr);
            ListNode res = sol.{problem.get('function_name', 'reverseList')}(head);
            List<Integer> actList = listToVector(res);
            boolean ok = (actList.size() == expArr.length);
            if (ok) {{
                for (int i = 0; i < expArr.length; i++) {{
                    if (actList.get(i) != expArr[i]) {{
                        ok = false;
                        break;
                    }}
                }}
            }}
            if (ok) {{
                passed++;
            }} else {{
                System.out.println("Test {idx+1} Failed");
                failed++;
            }}
        }}
""")

        return f"""
import java.util.*;

// Definition for singly-linked list.
class ListNode {{
    int val;
    ListNode next;
    ListNode() {{}}
    ListNode(int val) {{ this.val = val; }}
    ListNode(int val, ListNode next) {{ this.val = val; this.next = next; }}
}}

{user_code}

class TestRunner {{
    static ListNode createList(int[] arr) {{
        if (arr == null || arr.length == 0) return null;
        ListNode head = new ListNode(arr[0]);
        ListNode curr = head;
        for (int i = 1; i < arr.length; i++) {{
            curr.next = new ListNode(arr[i]);
            curr = curr.next;
        }}
        return head;
    }}

    static List<Integer> listToVector(ListNode head) {{
        List<Integer> res = new ArrayList<>();
        while (head != null) {{
            res.add(head.val);
            head = head.next;
        }}
        return res;
    }}

    public static void main(String[] args) {{
        Solution sol = new Solution();
        int passed = 0;
        int failed = 0;
        int total = {len(tests)};
        {"".join(test_cases_code)}
        System.out.println("RESULTS: passed=" + passed + ", failed=" + failed + ", total=" + total);
        if (failed > 0) {{
            System.exit(1);
        }}
    }}
}}
"""

    if _is_tree_problem(problem):
        test_cases_code = []
        fn_name = problem.get("function_name", "maxDepth")
        for idx, t in enumerate(tests):
            inp = t.get("args", t.get("input", []))
            if isinstance(inp, list) and len(inp) == 1 and isinstance(inp[0], list):
                nodes_arr = inp[0]
            elif isinstance(inp, list):
                nodes_arr = inp
            else:
                nodes_arr = []

            expected = t.get("expected")

            java_nodes = []
            for item in nodes_arr:
                if item is None:
                    java_nodes.append("null")
                else:
                    java_nodes.append(str(item))

            nodes_init = ", ".join(java_nodes) if java_nodes else ""
            exp_val = expected if isinstance(expected, (int, float, bool)) else 0

            test_cases_code.append(f"""
        {{
            Integer[] arr = new Integer[]{{{nodes_init}}};
            TreeNode root = createTree(arr);
            int expected = {int(exp_val)};
            int actual = sol.{fn_name}(root);
            if (actual == expected) {{
                passed++;
            }} else {{
                System.out.println("Test {idx+1} Failed: expected " + expected + ", got " + actual);
                failed++;
            }}
        }}
""")

        return f"""
import java.util.*;

// Definition for a binary tree node.
class TreeNode {{
    int val;
    TreeNode left;
    TreeNode right;
    TreeNode() {{}}
    TreeNode(int val) {{ this.val = val; }}
    TreeNode(int val, TreeNode left, TreeNode right) {{
        this.val = val;
        this.left = left;
        this.right = right;
    }}
}}

{user_code}

class TestRunner {{
    static TreeNode createTree(Integer[] arr) {{
        if (arr == null || arr.length == 0 || arr[0] == null) return null;
        TreeNode root = new TreeNode(arr[0]);
        Queue<TreeNode> q = new LinkedList<>();
        q.offer(root);
        int i = 1;
        while (!q.isEmpty() && i < arr.length) {{
            TreeNode curr = q.poll();
            if (curr == null) continue;

            // Left
            if (i < arr.length) {{
                if (arr[i] != null) {{
                    curr.left = new TreeNode(arr[i]);
                    q.offer(curr.left);
                }}
                i++;
            }}

            // Right
            if (i < arr.length) {{
                if (arr[i] != null) {{
                    curr.right = new TreeNode(arr[i]);
                    q.offer(curr.right);
                }}
                i++;
            }}
        }}
        return root;
    }}

    public static void main(String[] args) {{
        Solution sol = new Solution();
        int passed = 0;
        int failed = 0;
        int total = {len(tests)};
        {"".join(test_cases_code)}
        System.out.println("RESULTS: passed=" + passed + ", failed=" + failed + ", total=" + total);
        if (failed > 0) {{
            System.exit(1);
        }}
    }}
}}
"""

    # Default array / scalar search runner
    test_cases_code = []
    for idx, t in enumerate(tests):
        inp = t.get("args", t.get("input", []))
        nums = inp[0] if len(inp) > 0 else []
        target = inp[1] if len(inp) > 1 else 0
        expected = t.get("expected", 0)

        nums_str = ", ".join(map(str, nums)) if isinstance(nums, list) else str(nums)
        exp_code = _format_java_val(expected)

        test_cases_code.append(f"""
        {{
            int[] nums = new int[]{{{nums_str}}};
            int target = {target};
            Object expected = {exp_code};
            Object actual = sol.{problem.get('function_name', 'search')}(nums, target);
            boolean match = Objects.deepEquals(actual, expected);
            if (actual instanceof int[] && expected instanceof int[]) {{
                match = Arrays.equals((int[])actual, (int[])expected);
            }}
            if (match) {{
                passed++;
            }} else {{
                System.out.println("Test {idx+1} Failed: expected " + expected + ", got " + actual);
                failed++;
            }}
        }}
""")

    return f"""
import java.util.*;

{user_code}

class TestRunner {{
    public static void main(String[] args) {{
        Solution sol = new Solution();
        int passed = 0;
        int failed = 0;
        int total = {len(tests)};
        {"".join(test_cases_code)}
        System.out.println("RESULTS: passed=" + passed + ", failed=" + failed + ", total=" + total);
        if (failed > 0) {{
            System.exit(1);
        }}
    }}
}}
"""
