"""Benchmark registry, models, and runner for Multi-Problem / Multi-DSA Benchmarking (Stage 16).

This module defines the canonical benchmark problems covering genuine DSA categories,
the structured benchmark result models, and conversion utilities to ProblemSpec.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import time

from agent.core.models import (
    ProblemSpec,
    ConstraintItem,
    TestCase,
    TestCategory,
    OracleType,
    ConfidenceLevel,
    Difficulty,
    SupportedLanguage,
    DSAPattern,
)


class DSACategory(str, Enum):
    ARRAY = "ARRAY"
    STRING = "STRING"
    HASHING = "HASHING"
    TWO_POINTERS = "TWO_POINTERS"
    SLIDING_WINDOW = "SLIDING_WINDOW"
    BINARY_SEARCH = "BINARY_SEARCH"
    STACK = "STACK"
    LINKED_LIST = "LINKED_LIST"
    TREE_BST = "TREE_BST"
    BFS_DFS = "BFS_DFS"
    HEAP_PRIORITY_QUEUE = "HEAP_PRIORITY_QUEUE"
    GREEDY = "GREEDY"
    BACKTRACKING = "BACKTRACKING"
    DYNAMIC_PROGRAMMING = "DYNAMIC_PROGRAMMING"
    GRAPH = "GRAPH"


@dataclass
class BenchmarkProblem:
    """Canonical problem definition for Stage 16 benchmarking."""
    id: str
    title: str
    category: DSACategory
    statement: str
    constraints: List[str]
    input_info: str
    output_info: str
    function_name: str
    param_names: List[str]
    return_type: str
    examples: List[Dict[str, Any]]
    expected_pattern: DSAPattern
    canonical_cpp_code: str
    intentional_flawed_code: Optional[str] = None
    flaw_category: Optional[str] = None
    reference_oracle: Optional[Callable] = None


@dataclass
class BenchmarkResult:
    """Structured benchmark outcome for an individual problem."""
    problem_id: str
    title: str
    category: str
    detected_pattern: str
    pattern_confidence: float
    candidate_patterns: List[str]
    selected_algorithm: str
    language: str
    compile_status: str
    total_tests: int
    tests_passed: int
    tests_failed: int
    repair_attempts: int
    initial_failure_category: Optional[str]
    final_status: str
    final_verification_status: str
    fully_certified: bool
    planned_time: str
    inferred_time: str
    planned_space: str
    inferred_space: str
    warnings: List[str] = field(default_factory=list)
    execution_time_ms: float = 0.0


# ---------------------------------------------------------------------------
# Canonical Problem Registry covering genuine DSA Categories
# ---------------------------------------------------------------------------

BENCHMARK_REGISTRY: Dict[str, BenchmarkProblem] = {
    # A. ARRAY
    "max-subarray": BenchmarkProblem(
        id="max-subarray",
        title="Maximum Subarray",
        category=DSACategory.ARRAY,
        statement="Given an integer array nums, find the subarray with the largest sum, and return its sum.",
        constraints=["1 <= nums.length <= 10^5", "-10^4 <= nums[i] <= 10^4"],
        input_info="nums: vector<int>",
        output_info="int",
        function_name="maxSubArray",
        param_names=["nums"],
        return_type="int",
        examples=[
            {"input": {"nums": [-2, 1, -3, 4, -1, 2, 1, -5, 4]}, "output": 6},
            {"input": {"nums": [1]}, "output": 1},
            {"input": {"nums": [5, 4, -1, 7, 8]}, "output": 23},
            {"input": {"nums": [-5, -2, -9, -1]}, "output": -1},
        ],
        expected_pattern=DSAPattern.ARRAYS_STRINGS,
        canonical_cpp_code="""#include <vector>
#include <algorithm>
using namespace std;

class Solution {
public:
    int maxSubArray(vector<int>& nums) {
        int max_so_far = nums[0];
        int curr_max = nums[0];
        for (size_t i = 1; i < nums.size(); ++i) {
            curr_max = max(nums[i], curr_max + nums[i]);
            max_so_far = max(max_so_far, curr_max);
        }
        return max_so_far;
    }
};
""",
        intentional_flawed_code="""#include <vector>
using namespace std;

class Solution {
public:
    int maxSubArray(vector<int>& nums) {
        // Bug: initial max is 0 instead of nums[0], fails for all negative numbers!
        int max_so_far = 0;
        int curr_max = 0;
        for (int x : nums) {
            curr_max += x;
            if (curr_max < 0) curr_max = 0;
            if (curr_max > max_so_far) max_so_far = curr_max;
        }
        return max_so_far;
    }
};
""",
        flaw_category="WRONG_ANSWER",
    ),

    # B. STRING
    "valid-anagram": BenchmarkProblem(
        id="valid-anagram",
        title="Valid Anagram",
        category=DSACategory.STRING,
        statement="Given two strings s and t, return true if t is an anagram of s, and false otherwise.",
        constraints=["1 <= s.length, t.length <= 5 * 10^4", "s and t consist of lowercase English letters."],
        input_info="s: string, t: string",
        output_info="bool",
        function_name="isAnagram",
        param_names=["s", "t"],
        return_type="bool",
        examples=[
            {"input": {"s": "anagram", "t": "nagaram"}, "output": True},
            {"input": {"s": "rat", "t": "car"}, "output": False},
        ],
        expected_pattern=DSAPattern.HASH_TABLE,
        canonical_cpp_code="""#include <string>
#include <vector>
using namespace std;

class Solution {
public:
    bool isAnagram(string s, string t) {
        if (s.length() != t.length()) return false;
        vector<int> counts(26, 0);
        for (char c : s) {
            counts[c - 'a']++;
        }
        for (char c : t) {
            counts[c - 'a']--;
            if (counts[c - 'a'] < 0) return false;
        }
        return true;
    }
};
""",
    ),

    # C. HASHING
    "two-sum": BenchmarkProblem(
        id="two-sum",
        title="Two Sum",
        category=DSACategory.HASHING,
        statement="Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target.",
        constraints=["2 <= nums.length <= 10^4", "-10^9 <= nums[i] <= 10^9", "-10^9 <= target <= 10^9"],
        input_info="nums: vector<int>, target: int",
        output_info="vector<int>",
        function_name="twoSum",
        param_names=["nums", "target"],
        return_type="vector<int>",
        examples=[
            {"input": {"nums": [2, 7, 11, 15], "target": 9}, "output": [0, 1]},
            {"input": {"nums": [3, 2, 4], "target": 6}, "output": [1, 2]},
            {"input": {"nums": [3, 3], "target": 6}, "output": [0, 1]},
        ],
        expected_pattern=DSAPattern.HASH_TABLE,
        canonical_cpp_code="""#include <vector>
#include <unordered_map>
using namespace std;

class Solution {
public:
    vector<int> twoSum(vector<int>& nums, int target) {
        unordered_map<int, int> seen;
        for (int i = 0; i < (int)nums.size(); ++i) {
            int comp = target - nums[i];
            auto it = seen.find(comp);
            if (it != seen.end()) {
                return {it->second, i};
            }
            seen[nums[i]] = i;
        }
        return {};
    }
};
""",
    ),

    # D. TWO POINTERS
    "valid-palindrome": BenchmarkProblem(
        id="valid-palindrome",
        title="Valid Palindrome",
        category=DSACategory.TWO_POINTERS,
        statement="A phrase is a palindrome if, after converting all uppercase letters into lowercase letters and removing all non-alphanumeric characters, it reads the same forward and backward. Given a string s, return true if it is a palindrome, or false otherwise.",
        constraints=["1 <= s.length <= 2 * 10^5", "s consists only of printable ASCII characters."],
        input_info="s: string",
        output_info="bool",
        function_name="isPalindrome",
        param_names=["s"],
        return_type="bool",
        examples=[
            {"input": {"s": "A man, a plan, a canal: Panama"}, "output": True},
            {"input": {"s": "race a car"}, "output": False},
            {"input": {"s": " "}, "output": True},
        ],
        expected_pattern=DSAPattern.TWO_POINTERS,
        canonical_cpp_code="""#include <string>
#include <cctype>
using namespace std;

class Solution {
public:
    bool isPalindrome(string s) {
        int left = 0;
        int right = (int)s.length() - 1;
        while (left < right) {
            if (!isalnum((unsigned char)s[left])) {
                left++;
            } else if (!isalnum((unsigned char)s[right])) {
                right--;
            } else {
                if (tolower((unsigned char)s[left]) != tolower((unsigned char)s[right])) {
                    return false;
                }
                left++;
                right--;
            }
        }
        return true;
    }
};
""",
        intentional_flawed_code="""#include <string>
#include <cctype>
using namespace std;

class Solution {
public:
    bool isPalindrome(string s) {
        // Bug: forgets to convert to lowercase!
        int left = 0, right = (int)s.length() - 1;
        while (left < right) {
            if (!isalnum((unsigned char)s[left])) {
                left++;
            } else if (!isalnum((unsigned char)s[right])) {
                right--;
            } else {
                if (s[left] != s[right]) return false;
                left++;
                right--;
            }
        }
        return true;
    }
};
""",
        flaw_category="WRONG_ANSWER",
    ),

    # F. BINARY SEARCH
    "binary-search": BenchmarkProblem(
        id="binary-search",
        title="Binary Search",
        category=DSACategory.BINARY_SEARCH,
        statement="Given an array of integers nums which is sorted in ascending order, and an integer target, write a function to search target in nums. If target exists, then return its index. Otherwise, return -1.",
        constraints=["1 <= nums.length <= 10^4", "-10^4 < nums[i], target < 10^4", "All the integers in nums are unique."],
        input_info="nums: vector<int>, target: int",
        output_info="int",
        function_name="search",
        param_names=["nums", "target"],
        return_type="int",
        examples=[
            {"input": {"nums": [-1, 0, 3, 5, 9, 12], "target": 9}, "output": 4},
            {"input": {"nums": [-1, 0, 3, 5, 9, 12], "target": 2}, "output": -1},
        ],
        expected_pattern=DSAPattern.BINARY_SEARCH,
        canonical_cpp_code="""#include <vector>
using namespace std;

class Solution {
public:
    int search(vector<int>& nums, int target) {
        int left = 0;
        int right = (int)nums.size() - 1;
        while (left <= right) {
            int mid = left + (right - left) / 2;
            if (nums[mid] == target) return mid;
            if (nums[mid] < target) left = mid + 1;
            else right = mid - 1;
        }
        return -1;
    }
};
""",
        intentional_flawed_code="""#include <vector>
using namespace std;

class Solution {
public:
    int search(vector<int>& nums, int target) {
        // Bug: infinite loop / off-by-one boundary failure with left < right and mid
        int left = 0;
        int right = (int)nums.size() - 1;
        while (left < right) {
            int mid = (left + right) / 2;
            if (nums[mid] < target) left = mid;
            else right = mid;
        }
        return (left < (int)nums.size() && nums[left] == target) ? left : -1;
    }
};
""",
        flaw_category="EDGE_CASE_FAILURE",
    ),

    # G. STACK
    "valid-parentheses": BenchmarkProblem(
        id="valid-parentheses",
        title="Valid Parentheses",
        category=DSACategory.STACK,
        statement="Given a string s containing just the characters '(', ')', '{', '}', '[' and ']', determine if the input string is valid. Open brackets must be closed by the same type of brackets and in the correct order.",
        constraints=["1 <= s.length <= 10^4", "s consists of parentheses only '()[]{}'."],
        input_info="s: string",
        output_info="bool",
        function_name="isValid",
        param_names=["s"],
        return_type="bool",
        examples=[
            {"input": {"s": "()"}, "output": True},
            {"input": {"s": "()[]{}"}, "output": True},
            {"input": {"s": "(]"}, "output": False},
        ],
        expected_pattern=DSAPattern.STACK,
        canonical_cpp_code="""#include <string>
#include <stack>
using namespace std;

class Solution {
public:
    bool isValid(string s) {
        stack<char> st;
        for (char c : s) {
            if (c == '(' || c == '{' || c == '[') {
                st.push(c);
            } else {
                if (st.empty()) return false;
                char top = st.top();
                st.pop();
                if (c == ')' && top != '(') return false;
                if (c == '}' && top != '{') return false;
                if (c == ']' && top != '[') return false;
            }
        }
        return st.empty();
    }
};
""",
        intentional_flawed_code="""#include <string>
#include <stack>
using namespace std;

class Solution {
public:
    bool isValid(string s) {
        // Bug: compile error with missing semicolon
        stack<char> st
        for (char c : s) {
            if (c == '(' || c == '{' || c == '[') {
                st.push(c);
            } else {
                if (st.empty()) return false;
                char top = st.top();
                st.pop();
                if (c == ')' && top != '(') return false;
                if (c == '}' && top != '{') return false;
                if (c == ']' && top != '[') return false;
            }
        }
        return st.empty();
    }
};
""",
        flaw_category="COMPILE_ERROR",
    ),

    # L. GREEDY
    "best-time-to-buy-and-sell-stock": BenchmarkProblem(
        id="best-time-to-buy-and-sell-stock",
        title="Best Time to Buy and Sell Stock",
        category=DSACategory.GREEDY,
        statement="You are given an array prices where prices[i] is the price of a given stock on the ith day. You want to maximize your profit by choosing a single day to buy one stock and choosing a different day in the future to sell that stock. Return the maximum profit you can achieve from this transaction. If you cannot achieve any profit, return 0.",
        constraints=["1 <= prices.length <= 10^5", "0 <= prices[i] <= 10^4"],
        input_info="prices: vector<int>",
        output_info="int",
        function_name="maxProfit",
        param_names=["prices"],
        return_type="int",
        examples=[
            {"input": {"prices": [7, 1, 5, 3, 6, 4]}, "output": 5},
            {"input": {"prices": [7, 6, 4, 3, 1]}, "output": 0},
        ],
        expected_pattern=DSAPattern.GREEDY,
        canonical_cpp_code="""#include <vector>
#include <algorithm>
using namespace std;

class Solution {
public:
    int maxProfit(vector<int>& prices) {
        if (prices.empty()) return 0;
        int min_price = prices[0];
        int max_profit = 0;
        for (size_t i = 1; i < prices.size(); ++i) {
            if (prices[i] < min_price) {
                min_price = prices[i];
            } else {
                max_profit = max(max_profit, prices[i] - min_price);
            }
        }
        return max_profit;
    }
};
""",
        intentional_flawed_code="""#include <vector>
#include <algorithm>
using namespace std;

class Solution {
public:
    int maxProfit(vector<int>& prices) {
        // Bug: ignores temporal ordering, finds global max - global min
        if (prices.empty()) return 0;
        int min_p = *min_element(prices.begin(), prices.end());
        int max_p = *max_element(prices.begin(), prices.end());
        return max(0, max_p - min_p);
    }
};
""",
        flaw_category="WRONG_ANSWER",
    ),

    # N. DYNAMIC PROGRAMMING
    "climbing-stairs": BenchmarkProblem(
        id="climbing-stairs",
        title="Climbing Stairs",
        category=DSACategory.DYNAMIC_PROGRAMMING,
        statement="You are climbing a staircase. It takes n steps to reach the top. Each time you can either climb 1 or 2 steps. In how many distinct ways can you climb to the top?",
        constraints=["1 <= n <= 45"],
        input_info="n: int",
        output_info="int",
        function_name="climbStairs",
        param_names=["n"],
        return_type="int",
        examples=[
            {"input": {"n": 2}, "output": 2},
            {"input": {"n": 3}, "output": 3},
        ],
        expected_pattern=DSAPattern.DYNAMIC_PROGRAMMING,
        canonical_cpp_code="""#include <vector>
using namespace std;

class Solution {
public:
    int climbStairs(int n) {
        if (n <= 2) return n;
        int first = 1;
        int second = 2;
        for (int i = 3; i <= n; ++i) {
            int third = first + second;
            first = second;
            second = third;
        }
        return second;
    }
};
""",
    ),

    # E. SLIDING WINDOW
    "longest-substring-without-repeating-characters": BenchmarkProblem(
        id="longest-substring-without-repeating-characters",
        title="Longest Substring Without Repeating Characters",
        category=DSACategory.SLIDING_WINDOW,
        statement="Given a string s, find the length of the longest substring without repeating characters in the window.",
        constraints=["0 <= s.length <= 5 * 10^4", "s consists of English letters, digits, symbols and spaces."],
        input_info="s: string",
        output_info="int",
        function_name="lengthOfLongestSubstring",
        param_names=["s"],
        return_type="int",
        examples=[
            {"input": {"s": "abcabcbb"}, "output": 3},
            {"input": {"s": "bbbbb"}, "output": 1},
            {"input": {"s": "pwwkew"}, "output": 3},
            {"input": {"s": ""}, "output": 0},
        ],
        expected_pattern=DSAPattern.SLIDING_WINDOW,
        canonical_cpp_code="""#include <string>
#include <vector>
#include <algorithm>
using namespace std;

class Solution {
public:
    int lengthOfLongestSubstring(string s) {
        vector<int> last_idx(256, -1);
        int max_len = 0;
        int left = 0;
        for (int right = 0; right < (int)s.length(); ++right) {
            unsigned char c = (unsigned char)s[right];
            if (last_idx[c] >= left) {
                left = last_idx[c] + 1;
            }
            last_idx[c] = right;
            max_len = max(max_len, right - left + 1);
        }
        return max_len;
    }
};
""",
        intentional_flawed_code="""#include <string>
#include <vector>
using namespace std;

class Solution {
public:
    int lengthOfLongestSubstring(string s) {
        // Bug: forgets to update left pointer when duplicate occurs, always returns total length
        return (int)s.length();
    }
};
""",
        flaw_category="WRONG_ANSWER",
    ),

    # H. LINKED LIST
    "reverse-linked-list": BenchmarkProblem(
        id="reverse-linked-list",
        title="Reverse Linked List",
        category=DSACategory.LINKED_LIST,
        statement="Given the head values of a singly linked list represented as an array head, return the reversed linked list values.",
        constraints=["0 <= head.length <= 5000", "-5000 <= head[i] <= 5000"],
        input_info="head: vector<int>",
        output_info="vector<int>",
        function_name="reverseList",
        param_names=["head"],
        return_type="vector<int>",
        examples=[
            {"input": {"head": [1, 2, 3, 4, 5]}, "output": [5, 4, 3, 2, 1]},
            {"input": {"head": [1, 2]}, "output": [2, 1]},
            {"input": {"head": []}, "output": []},
        ],
        expected_pattern=DSAPattern.LINKED_LIST,
        canonical_cpp_code="""#include <vector>
#include <algorithm>
using namespace std;

class Solution {
public:
    vector<int> reverseList(vector<int>& head) {
        int left = 0;
        int right = (int)head.size() - 1;
        while (left < right) {
            swap(head[left], head[right]);
            left++;
            right--;
        }
        return head;
    }
};
""",
        intentional_flawed_code="""#include <vector>
using namespace std;

class Solution {
public:
    vector<int> reverseList(vector<int>& head) {
        // Bug: returns original list unchanged without reversal
        return head;
    }
};
""",
        flaw_category="WRONG_ANSWER",
    ),

    # I. TREE / BST
    "maximum-depth-of-binary-tree": BenchmarkProblem(
        id="maximum-depth-of-binary-tree",
        title="Maximum Depth of Binary Tree",
        category=DSACategory.TREE_BST,
        statement="Given the root node count or level sizes of a binary tree, compute the maximum depth from root to leaf node.",
        constraints=["0 <= nodes.length <= 10^4", "-100 <= nodes[i] <= 100"],
        input_info="nodes: vector<int>",
        output_info="int",
        function_name="maxDepth",
        param_names=["nodes"],
        return_type="int",
        examples=[
            {"input": {"nodes": [3, 9, 20, 15, 7]}, "output": 3},
            {"input": {"nodes": [1, 2]}, "output": 2},
            {"input": {"nodes": []}, "output": 0},
        ],
        expected_pattern=DSAPattern.BINARY_TREE,
        canonical_cpp_code="""#include <vector>
using namespace std;

class Solution {
public:
    int maxDepth(vector<int>& nodes) {
        if (nodes.empty()) return 0;
        int depth = 0;
        int count = (int)nodes.size();
        while (count > 0) {
            depth++;
            count /= 2;
        }
        return depth;
    }
};
""",
        intentional_flawed_code="""#include <vector>
using namespace std;

class Solution {
public:
    int maxDepth(vector<int>& nodes) {
        // Bug: off-by-one depth counting
        return (int)nodes.size();
    }
};
""",
        flaw_category="WRONG_ANSWER",
    ),

    # J. BFS / DFS
    "number-of-islands": BenchmarkProblem(
        id="number-of-islands",
        title="Number of Islands",
        category=DSACategory.BFS_DFS,
        statement="Given an m x n 2D binary grid matrix which represents a map of '1's (land) and '0's (water), return the number of islands. An island is formed by connecting adjacent lands horizontally or vertically.",
        constraints=["m == grid.length", "n == grid[i].length", "1 <= m, n <= 300", "grid[i][j] is '0' or '1'."],
        input_info="grid: vector<vector<int>>",
        output_info="int",
        function_name="numIslands",
        param_names=["grid"],
        return_type="int",
        examples=[
            {
                "input": {
                    "grid": [
                        [1, 1, 1, 1, 0],
                        [1, 1, 0, 1, 0],
                        [1, 1, 0, 0, 0],
                        [0, 0, 0, 0, 0]
                    ]
                },
                "output": 1
            },
            {
                "input": {
                    "grid": [
                        [1, 1, 0, 0, 0],
                        [1, 1, 0, 0, 0],
                        [0, 0, 1, 0, 0],
                        [0, 0, 0, 1, 1]
                    ]
                },
                "output": 3
            },
        ],
        expected_pattern=DSAPattern.GRAPH_BFS_DFS,
        canonical_cpp_code="""#include <vector>
using namespace std;

class Solution {
private:
    void dfs(vector<vector<int>>& grid, int r, int c) {
        int m = (int)grid.size();
        int n = (int)grid[0].size();
        if (r < 0 || r >= m || c < 0 || c >= n || grid[r][c] != 1) return;
        grid[r][c] = 0;
        dfs(grid, r + 1, c);
        dfs(grid, r - 1, c);
        dfs(grid, r, c + 1);
        dfs(grid, r, c - 1);
    }
public:
    int numIslands(vector<vector<int>>& grid) {
        if (grid.empty()) return 0;
        int m = (int)grid.size();
        int n = (int)grid[0].size();
        int islands = 0;
        for (int i = 0; i < m; ++i) {
            for (int j = 0; j < n; ++j) {
                if (grid[i][j] == 1) {
                    islands++;
                    dfs(grid, i, j);
                }
            }
        }
        return islands;
    }
};
""",
        intentional_flawed_code="""#include <vector>
using namespace std;

class Solution {
public:
    int numIslands(vector<vector<int>>& grid) {
        // Bug: merely counts land cells without connected component DFS traversal
        int count = 0;
        for (const auto& row : grid) {
            for (int cell : row) {
                if (cell == 1) count++;
            }
        }
        return count;
    }
};
""",
        flaw_category="WRONG_ANSWER",
    ),

    # K. HEAP / PRIORITY QUEUE
    "kth-largest-element-in-an-array": BenchmarkProblem(
        id="kth-largest-element-in-an-array",
        title="Kth Largest Element in an Array",
        category=DSACategory.HEAP_PRIORITY_QUEUE,
        statement="Given an integer array nums and an integer k, return the kth largest element in the array using a priority queue.",
        constraints=["1 <= k <= nums.length <= 10^5", "-10^4 <= nums[i] <= 10^4"],
        input_info="nums: vector<int>, k: int",
        output_info="int",
        function_name="findKthLargest",
        param_names=["nums", "k"],
        return_type="int",
        examples=[
            {"input": {"nums": [3, 2, 1, 5, 6, 4], "k": 2}, "output": 5},
            {"input": {"nums": [3, 2, 3, 1, 2, 4, 5, 5, 6], "k": 4}, "output": 4},
        ],
        expected_pattern=DSAPattern.HEAP_PRIORITY_QUEUE,
        canonical_cpp_code="""#include <vector>
#include <queue>
using namespace std;

class Solution {
public:
    int findKthLargest(vector<int>& nums, int k) {
        priority_queue<int, vector<int>, greater<int>> min_heap;
        for (int x : nums) {
            min_heap.push(x);
            if ((int)min_heap.size() > k) {
                min_heap.pop();
            }
        }
        return min_heap.top();
    }
};
""",
        intentional_flawed_code="""#include <vector>
#include <algorithm>
using namespace std;

class Solution {
public:
    int findKthLargest(vector<int>& nums, int k) {
        // Bug: returns kth smallest instead of kth largest!
        sort(nums.begin(), nums.end());
        return nums[k - 1];
    }
};
""",
        flaw_category="WRONG_ANSWER",
    ),

    # M. BACKTRACKING
    "subsets": BenchmarkProblem(
        id="subsets",
        title="Subsets",
        category=DSACategory.BACKTRACKING,
        statement="Given an integer array nums of unique elements, return all possible subsets (the power set). The solution set must not contain duplicate subsets. Subsets may be returned in any order.",
        constraints=["1 <= nums.length <= 10", "-10 <= nums[i] <= 10", "All the numbers of nums are unique."],
        input_info="nums: vector<int>",
        output_info="vector<vector<int>>",
        function_name="subsets",
        param_names=["nums"],
        return_type="vector<vector<int>>",
        examples=[
            {"input": {"nums": [1, 2]}, "output": [[], [1], [2], [1, 2]]},
            {"input": {"nums": [0]}, "output": [[], [0]]},
        ],
        expected_pattern=DSAPattern.BACKTRACKING_RECURSION,
        canonical_cpp_code="""#include <vector>
using namespace std;

class Solution {
private:
    void backtrack(int start, vector<int>& nums, vector<int>& curr, vector<vector<int>>& res) {
        res.push_back(curr);
        for (int i = start; i < (int)nums.size(); ++i) {
            curr.push_back(nums[i]);
            backtrack(i + 1, nums, curr, res);
            curr.pop_back();
        }
    }
public:
    vector<vector<int>> subsets(vector<int>& nums) {
        vector<vector<int>> res;
        vector<int> curr;
        backtrack(0, nums, curr, res);
        return res;
    }
};
""",
        intentional_flawed_code="""#include <vector>
using namespace std;

class Solution {
public:
    vector<vector<int>> subsets(vector<int>& nums) {
        // Bug: returns only empty set without generating power set
        return {{}};
    }
};
""",
        flaw_category="WRONG_ANSWER",
    ),

    # O. GRAPH
    "number-of-provinces": BenchmarkProblem(
        id="number-of-provinces",
        title="Number of Provinces",
        category=DSACategory.GRAPH,
        statement="There are n cities. An n x n adjacency matrix isConnected where isConnected[i][j] = 1 if the ith city and the jth city are directly connected, and 0 otherwise. Return the total number of connected provinces.",
        constraints=["1 <= isConnected.length <= 200", "isConnected[i][j] is 1 or 0.", "isConnected[i][i] == 1", "isConnected[i][j] == isConnected[j][i]"],
        input_info="isConnected: vector<vector<int>>",
        output_info="int",
        function_name="findCircleNum",
        param_names=["isConnected"],
        return_type="int",
        examples=[
            {
                "input": {
                    "isConnected": [
                        [1, 1, 0],
                        [1, 1, 0],
                        [0, 0, 1]
                    ]
                },
                "output": 2
            },
            {
                "input": {
                    "isConnected": [
                        [1, 0, 0],
                        [0, 1, 0],
                        [0, 0, 1]
                    ]
                },
                "output": 3
            },
        ],
        expected_pattern=DSAPattern.GRAPH_BFS_DFS,
        canonical_cpp_code="""#include <vector>
using namespace std;

class Solution {
private:
    void dfs(int city, vector<vector<int>>& isConnected, vector<bool>& visited) {
        visited[city] = true;
        for (int neighbor = 0; neighbor < (int)isConnected.size(); ++neighbor) {
            if (isConnected[city][neighbor] == 1 && !visited[neighbor]) {
                dfs(neighbor, isConnected, visited);
            }
        }
    }
public:
    int findCircleNum(vector<vector<int>>& isConnected) {
        int n = (int)isConnected.size();
        vector<bool> visited(n, false);
        int provinces = 0;
        for (int i = 0; i < n; ++i) {
            if (!visited[i]) {
                provinces++;
                dfs(i, isConnected, visited);
            }
        }
        return provinces;
    }
};
""",
        intentional_flawed_code="""#include <vector>
using namespace std;

class Solution {
public:
    int findCircleNum(vector<vector<int>>& isConnected) {
        // Bug: returns total number of cities without graph traversal
        return (int)isConnected.size();
    }
};
""",
        flaw_category="WRONG_ANSWER",
    ),
}


def to_problem_spec(problem: BenchmarkProblem) -> ProblemSpec:
    """Convert canonical benchmark problem into standard ProblemSpec."""
    test_cases = [
        TestCase(
            id=f"{problem.id}_ex_{i+1}",
            inputs=ex["input"],
            expected_output=ex["output"],
            category=TestCategory.EXAMPLE,
            oracle_type=OracleType.PROBLEM_SPEC,
            rationale=f"Canonical example {i+1}",
            is_sample=True,
        )
        for i, ex in enumerate(problem.examples)
    ]

    structured_constraints = [
        ConstraintItem(statement=c, confidence=ConfidenceLevel.EXPLICIT)
        for c in problem.constraints
    ]

    return ProblemSpec(
        id=problem.id,
        title=problem.title,
        description=problem.statement,
        raw_statement=problem.statement,
        difficulty=Difficulty.EASY,
        function_name=problem.function_name,
        param_names=problem.param_names,
        return_type=problem.return_type,
        constraints=problem.constraints,
        structured_constraints=structured_constraints,
        test_cases=test_cases,
        is_ambiguous=False,
    )
