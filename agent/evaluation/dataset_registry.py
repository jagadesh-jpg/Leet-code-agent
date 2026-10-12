"""
Stage 24: Dataset Partition Registry & Held-Out Unseen Problem Suite.
Maintains strictly isolated:
- DEVELOPMENT Split (Problems used for baseline rule construction and Stage 1-23 tests)
- VALIDATION Split (Problems used for calibration / sanity checks)
- HELD-OUT TEST Split (Strictly unseen, genuine DSA problems covering >= 10 DSA categories across C, C++, Java, and Python)
"""

from typing import Dict, List, Optional, Tuple
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


# ---------------------------------------------------------------------------
# HELD-OUT TEST SET (15 Real, Unseen Problems Covering >= 10 DSA Categories)
# NOT present in BENCHMARK_REGISTRY or prior test suites.
# ---------------------------------------------------------------------------

HELD_OUT_PROBLEMS_DEFS = [
    # 1. ARRAY: Missing Number (Find missing number in [0..n])
    {
        "id": "missing-number",
        "title": "Missing Number",
        "category": "ARRAY",
        "pattern": DSAPattern.ARRAYS_STRINGS,
        "statement": "Given an array nums containing n distinct numbers in the range [0, n], return the only number in the range that is missing from the array.",
        "constraints": ["n == nums.length", "1 <= n <= 10^4", "0 <= nums[i] <= n", "All the numbers of nums are unique."],
        "function_name": "missingNumber",
        "param_names": ["nums"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"nums": [3, 0, 1]}, "output": 2},
            {"input": {"nums": [0, 1]}, "output": 2},
            {"input": {"nums": [9, 6, 4, 2, 3, 5, 7, 0, 1]}, "output": 8},
        ],
        "flaw_code": """class Solution:
    def missingNumber(self, nums):
        # Flawed: ignores 0 and returns wrong count
        return len(nums) - 1
""",
    },
    # 2. STRING: First Unique Character in a String
    {
        "id": "first-unique-character",
        "title": "First Unique Character in a String",
        "category": "STRING",
        "pattern": DSAPattern.HASH_TABLE,
        "statement": "Given a string s, find the first non-repeating character in it and return its index. If it does not exist, return -1.",
        "constraints": ["1 <= s.length <= 10^5", "s consists of only lowercase English letters."],
        "function_name": "firstUniqChar",
        "param_names": ["s"],
        "return_type": "int",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"s": "leetcode"}, "output": 0},
            {"input": {"s": "loveleetcode"}, "output": 2},
            {"input": {"s": "aabb"}, "output": -1},
        ],
        "flaw_code": """#include <string>
#include <vector>
using namespace std;

class Solution {
public:
    int firstUniqChar(string s) {
        // Flawed: missing semicolon or logic returning always 0
        return 0;
    }
};
""",
    },
    # 3. HASHING: Contains Duplicate
    {
        "id": "contains-duplicate",
        "title": "Contains Duplicate",
        "category": "HASHING",
        "pattern": DSAPattern.HASH_TABLE,
        "statement": "Given an integer array nums, return true if any value appears at least twice in the array, and return false if every element is distinct.",
        "constraints": ["1 <= nums.length <= 10^5", "-10^9 <= nums[i] <= 10^9"],
        "function_name": "containsDuplicate",
        "param_names": ["nums"],
        "return_type": "bool",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"nums": [1, 2, 3, 1]}, "output": True},
            {"input": {"nums": [1, 2, 3, 4]}, "output": False},
            {"input": {"nums": [1, 1, 1, 3, 3, 4, 3, 2, 4, 2]}, "output": True},
        ],
        "flaw_code": """class Solution:
    def containsDuplicate(self, nums):
        # Flawed: always returns False
        return False
""",
    },
    # 4. TWO POINTERS: Move Zeroes
    {
        "id": "move-zeroes",
        "title": "Move Zeroes",
        "category": "TWO_POINTERS",
        "pattern": DSAPattern.TWO_POINTERS,
        "statement": "Given an integer array nums, move all 0's to the end of it while maintaining the relative order of the non-zero elements. You must do this in-place.",
        "constraints": ["1 <= nums.length <= 10^4", "-2^31 <= nums[i] <= 2^31 - 1"],
        "function_name": "moveZeroes",
        "param_names": ["nums"],
        "return_type": "List[int]",
        "language": SupportedLanguage.C,
        "examples": [
            {"input": {"nums": [0, 1, 0, 3, 12]}, "output": [1, 3, 12, 0, 0]},
            {"input": {"nums": [0]}, "output": [0]},
        ],
        "flaw_code": """#include <stdio.h>
#include <stdlib.h>

int* moveZeroes(int* nums, int numsSize, int* returnSize) {
    *returnSize = numsSize;
    // Flawed: does nothing, returns original array unchanged
    return nums;
}
""",
    },
    # 5. BINARY SEARCH: Search Insert Position
    {
        "id": "search-insert-position",
        "title": "Search Insert Position",
        "category": "BINARY_SEARCH",
        "pattern": DSAPattern.BINARY_SEARCH,
        "statement": "Given a sorted array of distinct integers and a target value, return the index if the target is found. If not, return the index where it would be if it were inserted in order.",
        "constraints": ["1 <= nums.length <= 10^4", "-10^4 <= nums[i] <= 10^4", "nums contains distinct values sorted in ascending order.", "-10^4 <= target <= 10^4"],
        "function_name": "searchInsert",
        "param_names": ["nums", "target"],
        "return_type": "int",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"nums": [1, 3, 5, 6], "target": 5}, "output": 2},
            {"input": {"nums": [1, 3, 5, 6], "target": 2}, "output": 1},
            {"input": {"nums": [1, 3, 5, 6], "target": 7}, "output": 4},
        ],
        "flaw_code": """#include <vector>
using namespace std;

class Solution {
public:
    int searchInsert(vector<int>& nums, int target) {
        // Flawed: linear search returning -1 when missing instead of insert position
        for (int i = 0; i < (int)nums.size(); i++) {
            if (nums[i] == target) return i;
        }
        return -1;
    }
};
""",
    },
    # 6. SLIDING WINDOW: Maximum Average Subarray I
    {
        "id": "maximum-average-subarray-i",
        "title": "Maximum Average Subarray I",
        "category": "SLIDING_WINDOW",
        "pattern": DSAPattern.SLIDING_WINDOW,
        "statement": "You are given an integer array nums consisting of n elements, and an integer k. Find a contiguous subarray whose length is equal to k that has the maximum average value and return this maximum sum / k.",
        "constraints": ["n == nums.length", "1 <= k <= n <= 10^5", "-10^4 <= nums[i] <= 10^4"],
        "function_name": "findMaxAverage",
        "param_names": ["nums", "k"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"nums": [1, 12, -5, -6, 50, 3], "k": 4}, "output": 12},
            {"input": {"nums": [5], "k": 1}, "output": 5},
        ],
        "flaw_code": """class Solution:
    def findMaxAverage(self, nums, k):
        # Flawed: computes only sum of first k elements
        return sum(nums[:k]) // k
""",
    },
    # 7. STACK: Min Stack Retrieval or Backspace String Compare
    {
        "id": "backspace-string-compare",
        "title": "Backspace String Compare",
        "category": "STACK",
        "pattern": DSAPattern.STACK,
        "statement": "Given two strings s and t, return true if they are equal when both are typed into empty text editors. '#' means a backspace character.",
        "constraints": ["1 <= s.length, t.length <= 200", "s and t only contain lowercase letters and '#' characters."],
        "function_name": "backspaceCompare",
        "param_names": ["s", "t"],
        "return_type": "bool",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"s": "ab#c", "t": "ad#c"}, "output": True},
            {"input": {"s": "ab##", "t": "c#d#"}, "output": True},
            {"input": {"s": "a#c", "t": "b"}, "output": False},
        ],
        "flaw_code": """#include <string>
using namespace std;

class Solution {
public:
    bool backspaceCompare(string s, string t) {
        // Flawed: compares strings directly without processing backspaces
        return s == t;
    }
};
""",
    },
    # 8. LINKED LIST: Middle of the Linked List
    {
        "id": "middle-of-the-linked-list",
        "title": "Middle of the Linked List",
        "category": "LINKED_LIST",
        "pattern": DSAPattern.LINKED_LIST,
        "statement": "Given the array representation of a singly linked list head, return the middle node value or values from middle to end.",
        "constraints": ["1 <= head.length <= 100", "1 <= head[i] <= 100"],
        "function_name": "middleNode",
        "param_names": ["head"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"head": [1, 2, 3, 4, 5]}, "output": 3},
            {"input": {"head": [1, 2, 3, 4, 5, 6]}, "output": 4},
        ],
        "flaw_code": """class Solution {
    public int middleNode(int[] head) {
        // Flawed: always returns first element
        return head[0];
    }
}
""",
    },
    # 9. TREE/BST: Invert Binary Tree
    {
        "id": "invert-binary-tree",
        "title": "Invert Binary Tree",
        "category": "TREE_BST",
        "pattern": DSAPattern.BINARY_TREE,
        "statement": "Given the node values of a binary tree in level order, invert the tree (swap left and right children) and return inverted representation.",
        "constraints": ["0 <= nodes.length <= 100", "-100 <= nodes[i] <= 100"],
        "function_name": "invertTree",
        "param_names": ["nodes"],
        "return_type": "List[int]",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"nodes": [4, 2, 7, 1, 3, 6, 9]}, "output": [4, 7, 2, 9, 6, 3, 1]},
            {"input": {"nodes": [2, 1, 3]}, "output": [2, 3, 1]},
            {"input": {"nodes": []}, "output": []},
        ],
        "flaw_code": """class Solution:
    def invertTree(self, nodes):
        # Flawed: returns original nodes unchanged
        return nodes
""",
    },
    # 10. BFS/DFS: Flood Fill
    {
        "id": "flood-fill",
        "title": "Flood Fill",
        "category": "BFS_DFS",
        "pattern": DSAPattern.GRAPH_BFS_DFS,
        "statement": "An image is represented by an m x n integer grid image where image[i][j] represents the pixel value of the image. Perform flood fill starting from (sr, sc) with newColor.",
        "constraints": ["m == image.length", "n == image[i].length", "1 <= m, n <= 50", "0 <= image[i][j], color < 2^16"],
        "function_name": "floodFill",
        "param_names": ["image", "sr", "sc", "color"],
        "return_type": "List[List[int]]",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {
                "input": {"image": [[1, 1, 1], [1, 1, 0], [1, 0, 1]], "sr": 1, "sc": 1, "color": 2},
                "output": [[2, 2, 2], [2, 2, 0], [2, 0, 1]],
            }
        ],
        "flaw_code": """class Solution:
    def floodFill(self, image, sr, sc, color):
        # Flawed: changes only starting pixel without recursive expansion
        image[sr][sc] = color
        return image
""",
    },
    # 11. HEAP: Last Stone Weight
    {
        "id": "last-stone-weight",
        "title": "Last Stone Weight",
        "category": "HEAP_PRIORITY_QUEUE",
        "pattern": DSAPattern.HEAP_PRIORITY_QUEUE,
        "statement": "You are given an array of integers stones where stones[i] is the weight of the ith stone. Each turn, we choose the heaviest two stones x and y with x <= y and smash them. If x == y, both destroyed; if x != y, stone of weight y-x remains. Return the weight of the last remaining stone, or 0.",
        "constraints": ["1 <= stones.length <= 30", "1 <= stones[i] <= 1000"],
        "function_name": "lastStoneWeight",
        "param_names": ["stones"],
        "return_type": "int",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"stones": [2, 7, 4, 1, 8, 1]}, "output": 1},
            {"input": {"stones": [1]}, "output": 1},
        ],
        "flaw_code": """#include <vector>
using namespace std;

class Solution {
public:
    int lastStoneWeight(vector<int>& stones) {
        // Flawed: returns 0 always
        return 0;
    }
};
""",
    },
    # 12. GREEDY: Assign Cookies
    {
        "id": "assign-cookies",
        "title": "Assign Cookies",
        "category": "GREEDY",
        "pattern": DSAPattern.GREEDY,
        "statement": "Assume you are an awesome parent and want to give your children some cookies. Each child i has a greed factor g[i], and each cookie j has a size s[j]. If s[j] >= g[i], the child is content. Maximize the number of content children.",
        "constraints": ["1 <= g.length <= 3 * 10^4", "0 <= s.length <= 3 * 10^4", "1 <= g[i], s[j] <= 2^31 - 1"],
        "function_name": "findContentChildren",
        "param_names": ["g", "s"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"g": [1, 2, 3], "s": [1, 1]}, "output": 1},
            {"input": {"g": [1, 2], "s": [1, 2, 3]}, "output": 2},
        ],
        "flaw_code": """class Solution {
    public int findContentChildren(int[] g, int[] s) {
        // Flawed: returns cookie count directly without matching greed
        return s.length;
    }
}
""",
    },
    # 13. DYNAMIC PROGRAMMING: Min Cost Climbing Stairs
    {
        "id": "min-cost-climbing-stairs",
        "title": "Min Cost Climbing Stairs",
        "category": "DYNAMIC_PROGRAMMING",
        "pattern": DSAPattern.DYNAMIC_PROGRAMMING,
        "statement": "You are given an integer array cost where cost[i] is the cost of ith step on a staircase. Once you pay the cost, you can either climb one or two steps. Return the minimum cost to reach the top of the floor.",
        "constraints": ["2 <= cost.length <= 1000", "0 <= cost[i] <= 999"],
        "function_name": "minCostClimbingStairs",
        "param_names": ["cost"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"cost": [10, 15, 20]}, "output": 15},
            {"input": {"cost": [1, 100, 1, 1, 1, 100, 1, 1, 100, 1]}, "output": 6},
        ],
        "flaw_code": """class Solution:
    def minCostClimbingStairs(self, cost):
        # Flawed: returns cost[0] without DP transition
        return cost[0]
""",
    },
    # 14. BOUNDED UNFIXABLE CASE: Circular Infinite Loop in Java
    {
        "id": "circular-loop-unfixable",
        "title": "Circular Array Loop (Unfixable Loop)",
        "category": "GRAPH",
        "pattern": DSAPattern.GRAPH_BFS_DFS,
        "statement": "Detect circular infinite loops in array navigation index updates.",
        "constraints": ["1 <= nums.length <= 100"],
        "function_name": "circularLoop",
        "param_names": ["nums"],
        "return_type": "bool",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"nums": [2, -1, 1, 2, 2]}, "output": True},
        ],
        "flaw_code": """class Solution {
    public boolean circularLoop(int[] nums) {
        // Unfixable infinite while loop
        while (true) {
            // Runaway loop triggering watchdog
        }
    }
}
""",
        "is_unfixable": True,
    },
    # 15. ISOLATED INFRASTRUCTURE CASE: Missing Compiler Runtime
    {
        "id": "unseen-infra-isolated",
        "title": "Unseen Infrastructure Isolation Case",
        "category": "ARRAY",
        "pattern": DSAPattern.ARRAYS_STRINGS,
        "statement": "Evaluate toolchain missing environmental exception on unseen problem.",
        "constraints": ["1 <= n <= 100"],
        "function_name": "dummyFunc",
        "param_names": ["n"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"n": 5}, "output": 5},
        ],
        "mock_infra": True,
    },
]


class DatasetRegistry:
    """
    Central dataset partition registry managing:
    - Development Split
    - Validation Split
    - Held-Out Test Split
    """

    def __init__(self):
        self._dev_problems: Dict[str, ProblemSpec] = {}
        self._val_problems: Dict[str, ProblemSpec] = {}
        self._held_out_problems: Dict[str, ProblemSpec] = {}
        self._metadata: Dict[str, ProblemMetadata] = {}
        self._initialize_splits()

    def _initialize_splits(self):
        """Populates development and held-out test splits."""
        # 1. Held-out problems
        for p_def in HELD_OUT_PROBLEMS_DEFS:
            spec = self._build_problem_spec(p_def)
            self._held_out_problems[spec.id] = spec
            meta = ProblemMetadata(
                problem_id=spec.id,
                split=DatasetSplit.HELD_OUT_TEST,
                dataset_version="v24.0",
                source_type=ProblemSourceType.EXTERNAL_CANONICAL if not p_def.get("mock_infra") else ProblemSourceType.SYNTHETIC_BENCHMARK,
                source_attribution="Held-out unseen DSA benchmark suite (Stage 24)",
                exact_fingerprint=LeakageDetector.compute_exact_fingerprint(spec),
                token_fingerprint=LeakageDetector.compute_semantic_fingerprint(spec),
                is_held_out=True,
            )
            self._metadata[spec.id] = meta

    def _build_problem_spec(self, p_def: dict) -> ProblemSpec:
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

    def get_held_out_problems(self, stage: int = 24) -> List[Tuple[ProblemSpec, dict]]:
        """Returns list of (ProblemSpec, raw_dict) for held-out evaluation for the requested stage."""
        if stage == 28:
            from agent.evaluation.stage28_held_out import STAGE28_HELD_OUT_PROBLEMS_DEFS, build_stage28_problem_spec
            return [(build_stage28_problem_spec(d), d) for d in STAGE28_HELD_OUT_PROBLEMS_DEFS]
        if stage == 27:
            from agent.evaluation.stage27_held_out import STAGE27_HELD_OUT_PROBLEMS_DEFS, build_stage27_problem_spec
            return [(build_stage27_problem_spec(d), d) for d in STAGE27_HELD_OUT_PROBLEMS_DEFS]
        if stage == 26:
            from agent.evaluation.stage26_held_out import STAGE26_HELD_OUT_PROBLEMS_DEFS, build_stage26_problem_spec
            return [(build_stage26_problem_spec(d), d) for d in STAGE26_HELD_OUT_PROBLEMS_DEFS]
        if stage == 25:
            from agent.evaluation.stage25_held_out import STAGE25_HELD_OUT_PROBLEMS_DEFS, build_stage25_problem_spec
            return [(build_stage25_problem_spec(d), d) for d in STAGE25_HELD_OUT_PROBLEMS_DEFS]
        return [(self._held_out_problems[d["id"]], d) for d in HELD_OUT_PROBLEMS_DEFS]

    def get_diagnostic_dev_problems(self, stage: int = 24) -> List[Tuple[ProblemSpec, dict]]:
        """Returns the inspected cases reclassified to DEVELOPMENT/DIAGNOSTIC split.
        By default (stage=24), returns the 5 inspected Stage 24 cases for regression compatibility.
        If stage=26, returns the 15 inspected Stage 26 cases.
        If stage=27, returns the 15 inspected Stage 27 cases.
        """
        if stage == 27:
            from agent.evaluation.stage27_held_out import STAGE27_HELD_OUT_PROBLEMS_DEFS, build_stage27_problem_spec
            return [(build_stage27_problem_spec(d), d) for d in STAGE27_HELD_OUT_PROBLEMS_DEFS]
        if stage == 26:
            from agent.evaluation.stage26_held_out import STAGE26_HELD_OUT_PROBLEMS_DEFS, build_stage26_problem_spec
            return [(build_stage26_problem_spec(d), d) for d in STAGE26_HELD_OUT_PROBLEMS_DEFS]
        inspected_ids = {"move-zeroes", "search-insert-position", "assign-cookies", "min-cost-climbing-stairs", "circular-loop-unfixable"}
        return [(self._held_out_problems[d["id"]], d) for d in HELD_OUT_PROBLEMS_DEFS if d["id"] in inspected_ids]

    def get_stage26_diagnostic_problems(self) -> List[Tuple[ProblemSpec, dict]]:
        """Returns the 15 Stage 26 problems reclassified as diagnostic/development cases."""
        return self.get_diagnostic_dev_problems(stage=26)

    def get_stage27_diagnostic_problems(self) -> List[Tuple[ProblemSpec, dict]]:
        """Returns the 15 Stage 27 problems reclassified as diagnostic/development cases."""
        return self.get_diagnostic_dev_problems(stage=27)

    def get_problem_metadata(self, problem_id: str) -> Optional[ProblemMetadata]:
        return self._metadata.get(problem_id)

