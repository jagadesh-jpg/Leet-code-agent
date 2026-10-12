"""
Stage 25: Independent Held-Out DSA Evaluation Suite & Benchmark Defs.
Disjoint from:
- Stages 1-23 Benchmark Registry & Dev sets
- Stage 24 Held-Out problems (now reclassified as diagnostic / dev reference)
Contains 15 authentic, independent DSA problems covering >= 10 DSA categories across C, C++, Java, and Python.
"""

from typing import Any, Dict, List, Tuple
from agent.core.models import (
    ConstraintItem,
    ConfidenceLevel,
    Difficulty,
    DSAPattern,
    OracleType,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCategory,
)
from agent.evaluation.models import DatasetSplit, ProblemMetadata, ProblemSourceType
from agent.evaluation.leakage_detector import LeakageDetector


STAGE25_HELD_OUT_PROBLEMS_DEFS: List[Dict[str, Any]] = [
    # 1. ARRAY / TWO POINTERS: Squares of a Sorted Array (Python)
    {
        "id": "squares-of-a-sorted-array",
        "title": "Squares of a Sorted Array",
        "category": "TWO_POINTERS",
        "pattern": DSAPattern.TWO_POINTERS,
        "statement": "Given an integer array nums sorted in non-decreasing order, return an array of the squares of each number sorted in non-decreasing order.",
        "constraints": ["1 <= nums.length <= 10^4", "-10^4 <= nums[i] <= 10^4", "nums is sorted in non-decreasing order."],
        "function_name": "sortedSquares",
        "param_names": ["nums"],
        "return_type": "List[int]",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"nums": [-4, -1, 0, 3, 10]}, "output": [0, 1, 9, 16, 100]},
            {"input": {"nums": [-7, -3, 2, 3, 11]}, "output": [4, 9, 9, 49, 121]},
        ],
        "flaw_code": """class Solution:
    def sortedSquares(self, nums):
        # Flawed: squares elements but returns them in original order without sorting
        return [x * x for x in nums]
""",
    },
    # 2. HASHING / STRING: Ransom Note (C++)
    {
        "id": "ransom-note",
        "title": "Ransom Note",
        "category": "HASHING",
        "pattern": DSAPattern.HASH_TABLE,
        "statement": "Given two strings ransomNote and magazine, return true if ransomNote can be constructed by using the letters from magazine and false otherwise. Each letter in magazine can only be used once in ransomNote.",
        "constraints": ["1 <= ransomNote.length, magazine.length <= 10^5", "ransomNote and magazine consist of lowercase English letters."],
        "function_name": "canConstruct",
        "param_names": ["ransomNote", "magazine"],
        "return_type": "bool",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"ransomNote": "a", "magazine": "b"}, "output": False},
            {"input": {"ransomNote": "aa", "magazine": "ab"}, "output": False},
            {"input": {"ransomNote": "aa", "magazine": "aab"}, "output": True},
        ],
        "flaw_code": """#include <string>
using namespace std;

class Solution {
public:
    bool canConstruct(string ransomNote, string magazine) {
        // Flawed: only checks length instead of character counts
        return magazine.length() >= ransomNote.length();
    }
};
""",
    },
    # 3. BINARY SEARCH: Peak Index in a Mountain Array (Java)
    {
        "id": "peak-index-in-mountain-array",
        "title": "Peak Index in a Mountain Array",
        "category": "BINARY_SEARCH",
        "pattern": DSAPattern.BINARY_SEARCH,
        "statement": "An array arr is a mountain if it increases to a peak element and then decreases. Return the index of the peak element.",
        "constraints": ["3 <= arr.length <= 10^5", "0 <= arr[i] <= 10^6", "arr is guaranteed to be a mountain array."],
        "function_name": "peakIndexInMountainArray",
        "param_names": ["arr"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"arr": [0, 1, 0]}, "output": 1},
            {"input": {"arr": [0, 2, 1, 0]}, "output": 1},
            {"input": {"arr": [0, 10, 5, 2]}, "output": 1},
        ],
        "flaw_code": """class Solution {
    public int peakIndexInMountainArray(int[] arr) {
        // Flawed: returns 0 directly
        return 0;
    }
}
""",
    },
    # 4. SLIDING WINDOW: Minimum Size Subarray Sum (Python)
    {
        "id": "minimum-size-subarray-sum",
        "title": "Minimum Size Subarray Sum",
        "category": "SLIDING_WINDOW",
        "pattern": DSAPattern.SLIDING_WINDOW,
        "statement": "Given an array of positive integers nums and a positive integer target, return the minimal length of a subarray whose sum is greater than or equal to target. If there is no such subarray, return 0.",
        "constraints": ["1 <= target <= 10^9", "1 <= nums.length <= 10^5", "1 <= nums[i] <= 10^4"],
        "function_name": "minSubArrayLen",
        "param_names": ["target", "nums"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"target": 7, "nums": [2, 3, 1, 2, 4, 3]}, "output": 2},
            {"input": {"target": 4, "nums": [1, 4, 4]}, "output": 1},
            {"input": {"target": 11, "nums": [1, 1, 1, 1, 1, 1, 1, 1]}, "output": 0},
        ],
        "flaw_code": """class Solution:
    def minSubArrayLen(self, target, nums):
        # Flawed: returns 1 if total sum >= target else 0
        return 1 if sum(nums) >= target else 0
""",
    },
    # 5. STACK: Remove All Adjacent Duplicates In String (C++)
    {
        "id": "remove-all-adjacent-duplicates-in-string",
        "title": "Remove All Adjacent Duplicates In String",
        "category": "STACK",
        "pattern": DSAPattern.STACK,
        "statement": "You are given a string s consisting of lowercase English letters. A duplicate removal consists of choosing two adjacent and equal letters and removing them. Return the final string after all such duplicate removals have been made.",
        "constraints": ["1 <= s.length <= 10^5", "s consists of lowercase English letters."],
        "function_name": "removeDuplicates",
        "param_names": ["s"],
        "return_type": "str",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"s": "abbaca"}, "output": "ca"},
            {"input": {"s": "azxxzy"}, "output": "ay"},
        ],
        "flaw_code": """#include <string>
using namespace std;

class Solution {
public:
    string removeDuplicates(string s) {
        // Flawed: returns original string unchanged
        return s;
    }
};
""",
    },
    # 6. LINKED LIST: Merge Two Sorted Lists (Python)
    {
        "id": "merge-two-sorted-lists",
        "title": "Merge Two Sorted Lists",
        "category": "LINKED_LIST",
        "pattern": DSAPattern.LINKED_LIST,
        "statement": "You are given the heads of two sorted linked lists list1 and list2. Merge the two lists into one sorted list. (Represented as integer lists).",
        "constraints": ["The number of nodes in both lists is in the range [0, 50].", "-100 <= Node.val <= 100", "Both list1 and list2 are sorted in non-decreasing order."],
        "function_name": "mergeTwoLists",
        "param_names": ["list1", "list2"],
        "return_type": "List[int]",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"list1": [1, 2, 4], "list2": [1, 3, 4]}, "output": [1, 1, 2, 3, 4, 4]},
            {"input": {"list1": [], "list2": []}, "output": []},
            {"input": {"list1": [], "list2": [0]}, "output": [0]},
        ],
        "flaw_code": """class Solution:
    def mergeTwoLists(self, list1, list2):
        # Flawed: concatenates lists without sorting
        return list1 + list2
""",
    },
    # 7. TREE: Symmetric Tree (Java)
    {
        "id": "symmetric-tree",
        "title": "Symmetric Tree",
        "category": "TREE_BST",
        "pattern": DSAPattern.BINARY_TREE,
        "statement": "Given the root of a binary tree (represented as level-order array), check whether it is a mirror of itself (i.e., symmetric around its center).",
        "constraints": ["The number of nodes in the tree is in the range [1, 1000].", "-100 <= Node.val <= 100"],
        "function_name": "isSymmetric",
        "param_names": ["root"],
        "return_type": "bool",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"root": [1, 2, 2, 3, 4, 4, 3]}, "output": True},
            {"input": {"root": [1, 2, 2, 0, 3, 0, 3]}, "output": False},
        ],
        "flaw_code": """class Solution {
    public boolean isSymmetric(int[] root) {
        // Flawed: always returns true
        return true;
    }
}
""",
    },
    # 8. BFS / DFS GRAPH: Keys and Rooms (Python)
    {
        "id": "keys-and-rooms",
        "title": "Keys and Rooms",
        "category": "BFS_DFS",
        "pattern": DSAPattern.GRAPH_BFS_DFS,
        "statement": "There are n rooms labeled from 0 to n - 1. You start in room 0. Each room has a list of distinct keys to other rooms. Return true if you can visit all the rooms, or false otherwise.",
        "constraints": ["n == rooms.length", "2 <= n <= 1000", "0 <= rooms[i].length <= 1000"],
        "function_name": "canVisitAllRooms",
        "param_names": ["rooms"],
        "return_type": "bool",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"rooms": [[1], [2], [3], []]}, "output": True},
            {"input": {"rooms": [[1, 3], [3, 0, 1], [2], [0]]}, "output": False},
        ],
        "flaw_code": """class Solution:
    def canVisitAllRooms(self, rooms):
        # Flawed: only checks if room 0 has any keys
        return len(rooms[0]) > 0
""",
    },
    # 9. HEAP / PRIORITY QUEUE: Kth Largest Element in a Stream (C++)
    {
        "id": "kth-largest-element-stream",
        "title": "Kth Largest Element in an Array Stream",
        "category": "HEAP_PRIORITY_QUEUE",
        "pattern": DSAPattern.HEAP_PRIORITY_QUEUE,
        "statement": "Find the kth largest element in an unsorted array.",
        "constraints": ["1 <= k <= nums.length <= 10^5", "-10^4 <= nums[i] <= 10^4"],
        "function_name": "findKthLargestElement",
        "param_names": ["nums", "k"],
        "return_type": "int",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"nums": [3, 2, 1, 5, 6, 4], "k": 2}, "output": 5},
            {"input": {"nums": [3, 2, 3, 1, 2, 4, 5, 5, 6], "k": 4}, "output": 4},
        ],
        "flaw_code": """#include <vector>
using namespace std;

class Solution {
public:
    int findKthLargestElement(vector<int>& nums, int k) {
        // Flawed: returns first element
        return nums[0];
    }
};
""",
    },
    # 10. GREEDY: Lemonade Change (Python)
    {
        "id": "lemonade-change",
        "title": "Lemonade Change",
        "category": "GREEDY",
        "pattern": DSAPattern.GREEDY,
        "statement": "At a lemonade stand, each lemonade costs $5. Customers pay with a $5, $10, or $20 bill. Return true if you can provide every customer with correct change, or false otherwise.",
        "constraints": ["1 <= bills.length <= 10^5", "bills[i] is either 5, 10, or 20."],
        "function_name": "lemonadeChange",
        "param_names": ["bills"],
        "return_type": "bool",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"bills": [5, 5, 5, 10, 20]}, "output": True},
            {"input": {"bills": [5, 5, 10, 10, 20]}, "output": False},
        ],
        "flaw_code": """class Solution:
    def lemonadeChange(self, bills):
        # Flawed: returns true if first bill is 5
        return bills[0] == 5
""",
    },
    # 11. DYNAMIC PROGRAMMING: House Robber (Python)
    {
        "id": "house-robber",
        "title": "House Robber",
        "category": "DYNAMIC_PROGRAMMING",
        "pattern": DSAPattern.DYNAMIC_PROGRAMMING,
        "statement": "You are a professional robber planning to rob houses along a street. Each house has a certain amount of money stashed. Adjacent houses have security systems connected. Return the maximum amount of money you can rob tonight without alerting the police.",
        "constraints": ["1 <= nums.length <= 100", "0 <= nums[i] <= 400"],
        "function_name": "rob",
        "param_names": ["nums"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"nums": [1, 2, 3, 1]}, "output": 4},
            {"input": {"nums": [2, 7, 9, 3, 1]}, "output": 12},
        ],
        "flaw_code": """class Solution:
    def rob(self, nums):
        # Flawed: sums every alternate house without dynamic choice
        return sum(nums[::2])
""",
    },
    # 12. STRING / PARSING: Length of Last Word (Java)
    {
        "id": "length-of-last-word",
        "title": "Length of Last Word",
        "category": "STRING",
        "pattern": DSAPattern.ARRAYS_STRINGS,
        "statement": "Given a string s consisting of words and spaces, return the length of the last word in the string.",
        "constraints": ["1 <= s.length <= 10^4", "s consists of only English letters and spaces ' '."],
        "function_name": "lengthOfLastWord",
        "param_names": ["s"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"s": "Hello World"}, "output": 5},
            {"input": {"s": "   fly me   to   the moon  "}, "output": 4},
            {"input": {"s": "luffy is still joyboy"}, "output": 6},
        ],
        "flaw_code": """class Solution {
    public int lengthOfLastWord(String s) {
        // Flawed: returns length of first token
        return s.trim().split(" ")[0].length();
    }
}
""",
    },
    # 13. TWO POINTERS / ARRAY: Intersection of Two Arrays II (C++)
    {
        "id": "intersection-of-two-arrays-ii",
        "title": "Intersection of Two Arrays II",
        "category": "ARRAY",
        "pattern": DSAPattern.HASH_TABLE,
        "statement": "Given two integer arrays nums1 and nums2, return an array of their intersection. Each element in the result must appear as many times as it shows in both arrays.",
        "constraints": ["1 <= nums1.length, nums2.length <= 1000", "0 <= nums1[i], nums2[i] <= 1000"],
        "function_name": "intersect",
        "param_names": ["nums1", "nums2"],
        "return_type": "List[int]",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"nums1": [1, 2, 2, 1], "nums2": [2, 2]}, "output": [2, 2]},
            {"input": {"nums1": [4, 9, 5], "nums2": [9, 4, 9, 8, 4]}, "output": [4, 9]},
        ],
        "flaw_code": """#include <vector>
using namespace std;

class Solution {
public:
    vector<int> intersect(vector<int>& nums1, vector<int>& nums2) {
        // Flawed: returns empty vector
        return {};
    }
};
""",
    },
    # 14. BOUNDED UNFIXABLE CASE: Infinite Loop In Graph Traversal (Java)
    {
        "id": "unfixable-stage25-infinite-loop",
        "title": "Unfixable Graph Cyclic Trap",
        "category": "GRAPH",
        "pattern": DSAPattern.GRAPH_BFS_DFS,
        "statement": "Test safety watchdogs on runaway infinite recursion loops.",
        "constraints": ["1 <= n <= 100"],
        "function_name": "runawayTrap",
        "param_names": ["n"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"n": 5}, "output": 5},
        ],
        "flaw_code": """class Solution {
    public int runawayTrap(int n) {
        // Infinite runaway loop
        while (true) {}
    }
}
""",
        "is_unfixable": True,
    },
    # 15. ISOLATED INFRASTRUCTURE CASE: Host Toolchain Missing (Java)
    {
        "id": "unseen-stage25-infra-isolated",
        "title": "Stage 25 Toolchain Environment Isolation",
        "category": "ARRAY",
        "pattern": DSAPattern.ARRAYS_STRINGS,
        "statement": "Evaluate toolchain missing environmental exception on Stage 25 held-out problem.",
        "constraints": ["1 <= n <= 100"],
        "function_name": "dummyFunc25",
        "param_names": ["n"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"n": 10}, "output": 10},
        ],
        "mock_infra": True,
    },
]


def build_stage25_problem_spec(p_def: dict) -> ProblemSpec:
    test_cases = [
        TestCase(
            id=f"{p_def['id']}_ex_{i+1}",
            inputs=ex["input"],
            expected_output=ex["output"],
            category=TestCategory.EXAMPLE,
            oracle_type=OracleType.PROBLEM_SPEC,
            rationale=f"Canonical example {i+1}",
            is_sample=True,
        )
        for i, ex in enumerate(p_def.get("examples", []))
    ]

    structured_constraints = [
        ConstraintItem(statement=c, confidence=ConfidenceLevel.EXPLICIT)
        for c in p_def.get("constraints", [])
    ]

    return ProblemSpec(
        id=p_def["id"],
        title=p_def["title"],
        description=p_def["statement"],
        raw_statement=p_def["statement"],
        difficulty=Difficulty.EASY,
        function_name=p_def["function_name"],
        param_names=p_def["param_names"],
        return_type=p_def["return_type"],
        constraints=p_def.get("constraints", []),
        structured_constraints=structured_constraints,
        test_cases=test_cases,
        is_ambiguous=False,
    )
