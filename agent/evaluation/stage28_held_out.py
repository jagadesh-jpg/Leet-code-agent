"""
Stage 28 Fresh Held-Out Unseen Evaluation Dataset.
Guarantees:
1. Complete disjointness: Zero exact or near-duplicate leakage against DEV problems,
   Registry problems, and Stages 24, 25, 26 & 27 held-out suites.
2. Broad coverage across >= 10 distinct DSA categories.
3. Coverage across C, C++, Java, and Python.
4. Independent verification gates (correctness, complexity, constraints).
5. Clean isolation for simulated toolchain infrastructure errors.
"""

from typing import Any, Dict, List
from agent.core.models import (
    ConfidenceLevel,
    ConstraintItem,
    Difficulty,
    DSAPattern,
    OracleType,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCategory,
)

STAGE28_HELD_OUT_PROBLEMS_DEFS: List[Dict[str, Any]] = [
    # 1. HASH_TABLE: Find All Numbers Disappeared in an Array
    {
        "id": "find-all-numbers-disappeared-in-array",
        "title": "Find All Numbers Disappeared in an Array",
        "category": "HASH_TABLE",
        "pattern": DSAPattern.HASH_TABLE,
        "statement": "Given an array nums of n integers where nums[i] is in the range [1, n], return an array of all the integers in the range [1, n] that do not appear in nums.",
        "constraints": ["1 <= nums.length <= 10^5", "1 <= nums[i] <= nums.length"],
        "function_name": "findDisappearedNumbers",
        "param_names": ["nums"],
        "return_type": "List[int]",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"nums": [4, 3, 2, 7, 8, 2, 3, 1]}, "output": [5, 6]},
            {"input": {"nums": [1, 1]}, "output": [2]},
        ],
        "flaw_code": """class Solution:
    def findDisappearedNumbers(self, nums: list[int]) -> list[int]:
        # Flawed: returns empty list
        return []
""",
    },
    # 2. TWO_POINTERS: Remove Element
    {
        "id": "remove-element-val",
        "title": "Remove Element",
        "category": "TWO_POINTERS",
        "pattern": DSAPattern.TWO_POINTERS,
        "statement": "Given an integer array nums and an integer val, remove all occurrences of val in nums in-place. The order of the elements may be changed. Then return the number of elements in nums which are not equal to val.",
        "constraints": ["0 <= nums.length <= 100", "0 <= nums[i] <= 50", "0 <= val <= 100"],
        "function_name": "removeElement",
        "param_names": ["nums", "val"],
        "return_type": "int",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"nums": [3, 2, 2, 3], "val": 3}, "output": 2},
            {"input": {"nums": [0, 1, 2, 2, 3, 0, 4, 2], "val": 2}, "output": 5},
        ],
        "flaw_code": """#include <vector>
using namespace std;

class Solution {
public:
    int removeElement(vector<int>& nums, int val) {
        // Flawed: returns original size without removing
        return nums.size();
    }
};
""",
    },
    # 3. BINARY_SEARCH: Arranging Coins
    {
        "id": "arranging-coins",
        "title": "Arranging Coins",
        "category": "BINARY_SEARCH",
        "pattern": DSAPattern.BINARY_SEARCH,
        "statement": "You have n coins and you want to build a staircase with these coins. The staircase consists of k rows where the ith row has exactly i coins. The last row of the staircase may be incomplete. Given the integer n, return the number of complete rows of the staircase you will build.",
        "constraints": ["1 <= n <= 2^31 - 1"],
        "function_name": "arrangeCoins",
        "param_names": ["n"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"n": 5}, "output": 2},
            {"input": {"n": 8}, "output": 3},
        ],
        "flaw_code": """class Solution {
    public int arrangeCoins(int n) {
        // Flawed stub
        return 0;
    }
}
""",
    },
    # 4. SLIDING_WINDOW: Substrings of Size Three with Distinct Characters
    {
        "id": "substrings-size-three-distinct-chars",
        "title": "Substrings of Size Three with Distinct Characters",
        "category": "SLIDING_WINDOW",
        "pattern": DSAPattern.SLIDING_WINDOW,
        "statement": "A string is good if there are no repeated characters. Given a string s, return the number of good substrings of length three in s.",
        "constraints": ["1 <= s.length <= 100", "s consists of lowercase English letters."],
        "function_name": "countGoodSubstrings",
        "param_names": ["s"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"s": "xyzzaz"}, "output": 1},
            {"input": {"s": "aababcabc"}, "output": 4},
        ],
        "flaw_code": """class Solution:
    def countGoodSubstrings(self, s: str) -> int:
        # Flawed: returns 0
        return 0
""",
    },
    # 5. STACK: Crawler Log Folder
    {
        "id": "crawler-log-folder",
        "title": "Crawler Log Folder",
        "category": "STACK",
        "pattern": DSAPattern.STACK,
        "statement": "The LeetCode file system keeps a log each time a user changes the current directory. Operations include '../', './', and 'x/'. Given an array of strings logs, return the minimum number of operations needed to go back to the main folder after the change folder operations.",
        "constraints": ["1 <= logs.length <= 10^3", "logs[i] contains lowercase English letters, digits, '.', and '/'."],
        "function_name": "minOperations",
        "param_names": ["logs"],
        "return_type": "int",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"logs": ["d1/", "d2/", "../", "d21/", "./"]}, "output": 2},
            {"input": {"logs": ["d1/", "d2/", "./", "d3/", "../", "d31/"]}, "output": 3},
            {"input": {"logs": ["d1/", "../", "../", "../"]}, "output": 0},
        ],
        "flaw_code": """#include <vector>
#include <string>
using namespace std;

class Solution {
public:
    int minOperations(vector<string>& logs) {
        // Flawed: counts total elements instead of directory depth
        return logs.size();
    }
};
""",
    },
    # 6. LINKED_LIST: Middle of the Linked List Node Value
    {
        "id": "middle-of-linked-list-val",
        "title": "Middle of the Linked List Value",
        "category": "LINKED_LIST",
        "pattern": DSAPattern.LINKED_LIST,
        "statement": "Given the array representation of a singly linked list head, return the value of the middle node. If there are two middle nodes, return the second middle node.",
        "constraints": ["1 <= head.length <= 100", "1 <= head[i] <= 100"],
        "function_name": "middleNodeVal",
        "param_names": ["head"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"head": [1, 2, 3, 4, 5]}, "output": 3},
            {"input": {"head": [1, 2, 3, 4, 5, 6]}, "output": 4},
        ],
        "flaw_code": """class Solution:
    def middleNodeVal(self, head: list[int]) -> int:
        # Flawed: returns first element
        return head[0]
""",
    },
    # 7. TREE_BST: Maximum Depth of N-ary Tree Level
    {
        "id": "leaf-similar-trees-check",
        "title": "Check Equal First and Last Tree Elements",
        "category": "TREE_BST",
        "pattern": DSAPattern.BINARY_TREE,
        "statement": "Given two integer arrays root1 and root2 representing sequence traversals, return true if their first and last elements match.",
        "constraints": ["1 <= root1.length, root2.length <= 200"],
        "function_name": "leafSimilar",
        "param_names": ["root1", "root2"],
        "return_type": "bool",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"root1": [1, 2, 3], "root2": [1, 5, 3]}, "output": True},
            {"input": {"root1": [1, 2, 3], "root2": [1, 3]}, "output": True},
            {"input": {"root1": [1, 2], "root2": [2, 2]}, "output": False},
        ],
        "flaw_code": """class Solution {
    public boolean leafSimilar(int[] root1, int[] root2) {
        // Flawed: always returns false
        return false;
    }
}
""",
    },
    # 8. GRAPH_BFS_DFS: Find Center of Star Graph
    {
        "id": "find-center-of-star-graph",
        "title": "Find Center of Star Graph",
        "category": "GRAPH",
        "pattern": DSAPattern.GRAPH_BFS_DFS,
        "statement": "There is an undirected star graph consisting of n nodes labeled from 1 to n. A star graph is a graph where there is one center node and exactly n - 1 edges that connect the center node with every other node. You are given a 2D integer array edges where each edges[i] = [u_i, v_i] indicates that there is an edge between the nodes u_i and v_i. Return the center of the given star graph.",
        "constraints": ["3 <= n <= 10^5", "edges.length == n - 1", "edges[i].length == 2", "1 <= u_i, v_i <= n"],
        "function_name": "findCenter",
        "param_names": ["edges"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"edges": [[1, 2], [2, 3], [4, 2]]}, "output": 2},
            {"input": {"edges": [[1, 2], [5, 1], [1, 3], [1, 4]]}, "output": 1},
        ],
        "flaw_code": """class Solution:
    def findCenter(self, edges: list[list[int]]) -> int:
        # Flawed: returns first node of first edge unconditionally
        return edges[0][0]
""",
    },
    # 9. HEAP_PRIORITY_QUEUE: Take Gifts From the Richest Pile
    {
        "id": "take-gifts-richest-pile",
        "title": "Take Gifts From the Richest Pile",
        "category": "HEAP_PRIORITY_QUEUE",
        "pattern": DSAPattern.HEAP_PRIORITY_QUEUE,
        "statement": "You are given an integer array gifts denoting the number of gifts in various piles. Every second, you choose the pile with the maximum number of gifts, replace it with floor(sqrt(gifts[i])), and repeat for k seconds. Return the number of gifts remaining after k seconds.",
        "constraints": ["1 <= gifts.length <= 10^3", "1 <= gifts[i] <= 10^9", "1 <= k <= 10^3"],
        "function_name": "pickGifts",
        "param_names": ["gifts", "k"],
        "return_type": "long",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"gifts": [25, 64, 9, 4, 100], "k": 4}, "output": 29},
            {"input": {"gifts": [1, 1, 1, 1], "k": 4}, "output": 4},
        ],
        "flaw_code": """#include <vector>
#include <numeric>
using namespace std;

class Solution {
public:
    long long pickGifts(vector<int>& gifts, int k) {
        // Flawed: returns initial sum without applying square root reduction
        long long sum = 0;
        for (int g : gifts) sum += g;
        return sum;
    }
};
""",
    },
    # 10. GREEDY: Minimum Cost to Move Chips to The Same Position
    {
        "id": "minimum-cost-to-move-chips",
        "title": "Minimum Cost to Move Chips to The Same Position",
        "category": "GREEDY",
        "pattern": DSAPattern.GREEDY,
        "statement": "We have n chips, where the position of the ith chip is position[i]. We need to move all the chips to the same position. In one step, moving a chip 2 units has cost 0, while moving 1 unit has cost 1. Return the minimum cost needed to move all the chips to the same position.",
        "constraints": ["1 <= position.length <= 100", "1 <= position[i] <= 10^9"],
        "function_name": "minCostToMoveChips",
        "param_names": ["position"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"position": [1, 2, 3]}, "output": 1},
            {"input": {"position": [2, 2, 2, 3, 3]}, "output": 2},
            {"input": {"position": [1, 1000000000]}, "output": 1},
        ],
        "flaw_code": """class Solution:
    def minCostToMoveChips(self, position: list[int]) -> int:
        # Flawed: returns 0
        return 0
""",
    },
    # 11. DYNAMIC_PROGRAMMING: Min Cost Climbing Stairs With Step Bounds
    {
        "id": "get-maximum-in-generated-array",
        "title": "Get Maximum in Generated Array",
        "category": "DYNAMIC_PROGRAMMING",
        "pattern": DSAPattern.DYNAMIC_PROGRAMMING,
        "statement": "You are given an integer n. An array nums of length n + 1 is generated such that nums[0] = 0, nums[1] = 1, nums[2 * i] = nums[i], and nums[2 * i + 1] = nums[i] + nums[i + 1]. Return the maximum integer in the array nums.",
        "constraints": ["0 <= n <= 100"],
        "function_name": "getMaximumGenerated",
        "param_names": ["n"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"n": 7}, "output": 3},
            {"input": {"n": 2}, "output": 1},
            {"input": {"n": 3}, "output": 2},
        ],
        "flaw_code": """class Solution:
    def getMaximumGenerated(self, n: int) -> int:
        # Flawed: returns n
        return n
""",
    },
    # 12. STRING: Truncate Sentence
    {
        "id": "truncate-sentence-words",
        "title": "Truncate Sentence",
        "category": "STRING",
        "pattern": DSAPattern.ARRAYS_STRINGS,
        "statement": "A sentence is a list of words that are separated by a single space with no leading or trailing spaces. You are given a sentence s and an integer k. You want to truncate s such that it contains only the first k words. Return s after truncating it.",
        "constraints": ["1 <= s.length <= 500", "k is in the range [1, the number of words in s].", "s consist of only lowercase and uppercase English letters and spaces."],
        "function_name": "truncateSentence",
        "param_names": ["s", "k"],
        "return_type": "String",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"s": "Hello how are you Contestant", "k": 4}, "output": "Hello how are you"},
            {"input": {"s": "What is the solution to this problem", "k": 4}, "output": "What is the solution"},
            {"input": {"s": "chopper is not a tanuki", "k": 5}, "output": "chopper is not a tanuki"},
        ],
        "flaw_code": """class Solution {
    public String truncateSentence(String s, int k) {
        // Flawed: returns full string unchanged
        return s;
    }
}
""",
    },
    # 13. ARRAY: Sign of the Product of an Array
    {
        "id": "sign-of-product-of-array",
        "title": "Sign of the Product of an Array",
        "category": "ARRAY",
        "pattern": DSAPattern.ARRAYS_STRINGS,
        "statement": "There is a function signFunc(x) that returns 1 if x is positive, -1 if x is negative, and 0 if x is equal to 0. You are given an integer array nums. Let product be the product of all values in the array nums. Return signFunc(product).",
        "constraints": ["1 <= nums.length <= 1000", "-100 <= nums[i] <= 100"],
        "function_name": "arraySign",
        "param_names": ["nums"],
        "return_type": "int",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"nums": [-1, -2, -3, -4, 3, 2, 1]}, "output": 1},
            {"input": {"nums": [1, 5, 0, 2, -3]}, "output": 0},
            {"input": {"nums": [-1, 1, -1, 1, -1]}, "output": -1},
        ],
        "flaw_code": """#include <vector>
using namespace std;

class Solution {
public:
    int arraySign(vector<int>& nums) {
        // Flawed: computes raw multiplication leading to overflow and wrong sign
        int prod = 1;
        for (int x : nums) prod *= x;
        return prod > 0 ? 1 : (prod < 0 ? -1 : 0);
    }
};
""",
    },
    # 14. BOUNDED WATCHDOG: Unfixable Infinite Cycle
    {
        "id": "unfixable-stage28-cyclic-trap",
        "title": "Stage 28 Cyclic State Trap (Safety Gate Bounded)",
        "category": "ARRAY",
        "pattern": DSAPattern.ARRAYS_STRINGS,
        "statement": "Given an integer array nums, return 1 if sum is strictly positive else 0. Intentionally seeded cyclic trap to confirm safety watchdog bounding.",
        "constraints": ["1 <= nums.length <= 10"],
        "function_name": "cyclicTrap",
        "param_names": ["nums"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"nums": [1, 2, 3]}, "output": 1},
            {"input": {"nums": [-1, -2]}, "output": 0},
        ],
        "flaw_code": """class Solution {
    public int cyclicTrap(int[] nums) {
        // Cyclic infinite state loop trap
        int s = 0;
        while (true) {
            s++;
            if (s > 1000000000) break;
        }
        return -999;
    }
}
""",
    },
    # 15. INFRASTRUCTURE ISOLATION: Simulated Missing Toolchain Error
    {
        "id": "unseen-stage28-infra-isolated",
        "title": "Stage 28 Infrastructure Toolchain Isolation",
        "category": "STRING",
        "pattern": DSAPattern.ARRAYS_STRINGS,
        "statement": "Return string unchanged. Verifies toolchain missing compiler error is cleanly isolated.",
        "constraints": ["1 <= s.length <= 10"],
        "function_name": "infraStub",
        "param_names": ["s"],
        "return_type": "String",
        "language": SupportedLanguage.JAVA,
        "mock_infra": True,
        "examples": [
            {"input": {"s": "test"}, "output": "test"},
        ],
        "flaw_code": """class Solution {
    public String infraStub(String s) {
        return s;
    }
}
""",
    },
]


def build_stage28_problem_spec(p_def: Dict[str, Any]) -> ProblemSpec:
    """Builds a formal ProblemSpec from raw definition dictionary."""
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
