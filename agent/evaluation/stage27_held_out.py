"""
Stage 27: Independent Held-Out DSA Evaluation Suite & Benchmark Defs.
Strictly disjoint from:
- Stages 1-23 Benchmark Registry & Dev sets
- Stage 24 Held-Out problems (diagnostic)
- Stage 25 Held-Out problems (diagnostic)
- Stage 26 Held-Out problems (diagnostic)

Contains 15 authentic, independent DSA problems covering >= 10 DSA categories across C, C++, Java, and Python.
Includes:
- 13 Candidate-solvable problems
- 1 Deliberate bounded failure case (unfixable non-terminating trap)
- 1 Isolated host toolchain infrastructure failure case
"""

from typing import Any, Dict, List
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


STAGE27_HELD_OUT_PROBLEMS_DEFS: List[Dict[str, Any]] = [
    # 1. HASH TABLE / FREQUENCY: Jewels and Stones (Python)
    {
        "id": "jewels-and-stones",
        "title": "Jewels and Stones",
        "category": "HASHING",
        "pattern": DSAPattern.HASH_TABLE,
        "statement": "You are given strings jewels representing the types of stones that are jewels, and stones representing the stones you have. Each character in stones is a type of stone you have. You want to know how many of the stones you have are also jewels. Letters are case sensitive.",
        "constraints": ["1 <= jewels.length, stones.length <= 50", "jewels and stones consist of only English letters.", "All the characters of jewels are unique."],
        "function_name": "numJewelsInStones",
        "param_names": ["jewels", "stones"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"jewels": "aA", "stones": "aAAbbbb"}, "output": 3},
            {"input": {"jewels": "z", "stones": "ZZ"}, "output": 0},
        ],
        "flaw_code": """class Solution:
    def numJewelsInStones(self, jewels, stones):
        # Flawed: returns 0 always
        return 0
""",
    },
    # 2. TWO POINTERS: Reverse Vowels of a String (C++)
    {
        "id": "reverse-vowels-of-a-string",
        "title": "Reverse Vowels of a String",
        "category": "TWO_POINTERS",
        "pattern": DSAPattern.TWO_POINTERS,
        "statement": "Given a string s, reverse only all the vowels in the string and return it. The vowels are 'a', 'e', 'i', 'o', and 'u', and they can appear in both lower and upper cases, more than once.",
        "constraints": ["1 <= s.length <= 3 * 10^5", "s consist of printable ASCII characters."],
        "function_name": "reverseVowels",
        "param_names": ["s"],
        "return_type": "str",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"s": "IceCreAm"}, "output": "AceCreIm"},
            {"input": {"s": "leetcode"}, "output": "leotcede"},
        ],
        "flaw_code": """#include <string>
using namespace std;

class Solution {
public:
    string reverseVowels(string s) {
        // Flawed: returns string unchanged
        return s;
    }
};
""",
    },
    # 3. BINARY SEARCH: Valid Perfect Square (Java)
    {
        "id": "valid-perfect-square",
        "title": "Valid Perfect Square",
        "category": "BINARY_SEARCH",
        "pattern": DSAPattern.BINARY_SEARCH,
        "statement": "Given a positive integer num, return true if num is a perfect square or false otherwise. A perfect square is an integer that is the square of an integer.",
        "constraints": ["1 <= num <= 2^31 - 1"],
        "function_name": "isPerfectSquare",
        "param_names": ["num"],
        "return_type": "bool",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"num": 16}, "output": True},
            {"input": {"num": 14}, "output": False},
        ],
        "flaw_code": """class Solution {
    public boolean isPerfectSquare(int num) {
        // Flawed: returns true only if num <= 1
        return num <= 1;
    }
}
""",
    },
    # 4. SLIDING WINDOW: Maximum Length of Subarray With Positive Product (Python)
    {
        "id": "defuse-the-bomb",
        "title": "Defuse the Bomb (Circular Sliding Window)",
        "category": "SLIDING_WINDOW",
        "pattern": DSAPattern.SLIDING_WINDOW,
        "statement": "You have a bomb to defuse, and your informer gives you a circular array code of length n and a key k. If k > 0, replace each number with the sum of the next k numbers. If k < 0, replace with the sum of the previous k numbers. If k == 0, replace with 0.",
        "constraints": ["n == code.length", "1 <= n <= 100", "1 <= code[i] <= 100", "-(n - 1) <= k <= n - 1"],
        "function_name": "decrypt",
        "param_names": ["code", "k"],
        "return_type": "List[int]",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"code": [5, 7, 1, 4], "k": 3}, "output": [12, 10, 16, 13]},
            {"input": {"code": [1, 2, 3, 4], "k": 0}, "output": [0, 0, 0, 0]},
            {"input": {"code": [2, 4, 9, 3], "k": -2}, "output": [12, 5, 6, 13]},
        ],
        "flaw_code": """class Solution:
    def decrypt(self, code, k):
        # Flawed: returns all zeros always
        return [0] * len(code)
""",
    },
    # 5. STACK: Make The String Great (C++)
    {
        "id": "make-the-string-great",
        "title": "Make The String Great",
        "category": "STACK",
        "pattern": DSAPattern.STACK,
        "statement": "Given a string s of lower and upper case English letters. A good string does not have two adjacent characters s[i] and s[i + 1] where they are the same letter with different cases. Return the string after making it good.",
        "constraints": ["1 <= s.length <= 100", "s contains only lower and upper case English letters."],
        "function_name": "makeGood",
        "param_names": ["s"],
        "return_type": "str",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"s": "leEeetcode"}, "output": "leetcode"},
            {"input": {"s": "abBAcC"}, "output": ""},
            {"input": {"s": "s"}, "output": "s"},
        ],
        "flaw_code": """#include <string>
using namespace std;

class Solution {
public:
    string makeGood(string s) {
        // Flawed: returns original string unchanged
        return s;
    }
};
""",
    },
    # 6. LINKED LIST: Delete Node in a Linked List by Array Pos (Python)
    {
        "id": "remove-nth-node-from-end",
        "title": "Remove Nth Node From End of List",
        "category": "LINKED_LIST",
        "pattern": DSAPattern.LINKED_LIST,
        "statement": "Given the head of a linked list (represented as an integer array), remove the nth node from the end of the list and return its head array.",
        "constraints": ["The number of nodes in the list is sz.", "1 <= sz <= 30", "0 <= Node.val <= 100", "1 <= n <= sz"],
        "function_name": "removeNthFromEnd",
        "param_names": ["head", "n"],
        "return_type": "List[int]",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"head": [1, 2, 3, 4, 5], "n": 2}, "output": [1, 2, 3, 5]},
            {"input": {"head": [1], "n": 1}, "output": []},
            {"input": {"head": [1, 2], "n": 1}, "output": [1]},
        ],
        "flaw_code": """class Solution:
    def removeNthFromEnd(self, head, n):
        # Flawed: removes first element instead of nth from end
        return head[1:]
""",
    },
    # 7. TREE: Univalued Binary Tree (Java)
    {
        "id": "univalued-binary-tree",
        "title": "Univalued Binary Tree",
        "category": "TREE_BST",
        "pattern": DSAPattern.BINARY_TREE,
        "statement": "A binary tree is uni-valued if every node in the tree has the same value. Given the root of a binary tree (represented as level-order array), return true if the given tree is uni-valued, or false otherwise.",
        "constraints": ["The number of nodes in the tree is in the range [1, 100].", "0 <= Node.val < 100"],
        "function_name": "isUnivalTree",
        "param_names": ["root"],
        "return_type": "bool",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"root": [1, 1, 1, 1, 1, 0, 1]}, "output": True},
            {"input": {"root": [2, 2, 2, 5, 2]}, "output": False},
        ],
        "flaw_code": """class Solution {
    public boolean isUnivalTree(int[] root) {
        // Flawed: always returns true
        return true;
    }
}
""",
    },
    # 8. BFS / DFS GRAPH: Island Perimeter (Python)
    {
        "id": "island-perimeter",
        "title": "Island Perimeter",
        "category": "BFS_DFS",
        "pattern": DSAPattern.GRAPH_BFS_DFS,
        "statement": "You are given row x col grid representing a map where grid[i][j] = 1 represents land and grid[i][j] = 0 represents water. Grid cells are connected horizontally/vertically. Determine the perimeter of the island.",
        "constraints": ["row == grid.length", "col == grid[i].length", "1 <= row, col <= 100", "grid[i][j] is 0 or 1."],
        "function_name": "islandPerimeter",
        "param_names": ["grid"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"grid": [[0, 1, 0, 0], [1, 1, 1, 0], [0, 1, 0, 0], [1, 1, 0, 0]]}, "output": 16},
            {"input": {"grid": [[1]]}, "output": 4},
            {"input": {"grid": [[1, 0]]}, "output": 4},
        ],
        "flaw_code": """class Solution:
    def islandPerimeter(self, grid):
        # Flawed: returns 4 times land cell count ignoring shared boundaries
        return sum(cell == 1 for row in grid for cell in row) * 4
""",
    },
    # 9. HEAP / PRIORITY QUEUE: Minimum Cost to Connect Sticks (C++)
    {
        "id": "minimum-cost-connect-sticks",
        "title": "Minimum Cost to Connect Sticks",
        "category": "HEAP_PRIORITY_QUEUE",
        "pattern": DSAPattern.HEAP_PRIORITY_QUEUE,
        "statement": "You have some number of sticks with positive integer lengths. You can connect any two sticks of lengths x and y by paying a cost x + y. You must repeat this until there is only one stick remaining. Return the minimum cost to connect all sticks.",
        "constraints": ["1 <= sticks.length <= 10^4", "1 <= sticks[i] <= 10^4"],
        "function_name": "connectSticks",
        "param_names": ["sticks"],
        "return_type": "int",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"sticks": [2, 4, 3]}, "output": 14},
            {"input": {"sticks": [1, 8, 3, 5]}, "output": 30},
            {"input": {"sticks": [5]}, "output": 0},
        ],
        "flaw_code": """#include <vector>
using namespace std;

class Solution {
public:
    int connectSticks(vector<int>& sticks) {
        // Flawed: returns 0 always
        return 0;
    }
};
""",
    },
    # 10. GREEDY: Minimum Subsequence in Non-Increasing Order (Python)
    {
        "id": "min-subsequence-non-increasing",
        "title": "Minimum Subsequence in Non-Increasing Order",
        "category": "GREEDY",
        "pattern": DSAPattern.GREEDY,
        "statement": "Given the array nums, obtain a subsequence of the array whose sum of elements is strictly greater than the sum of the non-included elements in non-increasing order.",
        "constraints": ["1 <= nums.length <= 500", "1 <= nums[i] <= 100"],
        "function_name": "minSubsequence",
        "param_names": ["nums"],
        "return_type": "List[int]",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"nums": [4, 3, 10, 9, 8]}, "output": [10, 9]},
            {"input": {"nums": [4, 4, 7, 6, 7]}, "output": [7, 7, 6]},
        ],
        "flaw_code": """class Solution:
    def minSubsequence(self, nums):
        # Flawed: returns original array without greedy reduction
        return nums
""",
    },
    # 11. DYNAMIC PROGRAMMING: Divisor Game (Python)
    {
        "id": "divisor-game",
        "title": "Divisor Game",
        "category": "DYNAMIC_PROGRAMMING",
        "pattern": DSAPattern.DYNAMIC_PROGRAMMING,
        "statement": "Alice and Bob take turns playing a game, with Alice starting first. Initially, there is a number n on the chalkboard. On each turn, a player chooses x with 0 < x < n and n % x == 0, and replaces n with n - x. Return true if and only if Alice wins the game assuming both players play optimally.",
        "constraints": ["1 <= n <= 1000"],
        "function_name": "divisorGame",
        "param_names": ["n"],
        "return_type": "bool",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"n": 2}, "output": True},
            {"input": {"n": 3}, "output": False},
        ],
        "flaw_code": """class Solution:
    def divisorGame(self, n):
        # Flawed: returns true for all n
        return True
""",
    },
    # 12. STRING / PARSING: Check if the Sentence Is Pangram (Java)
    {
        "id": "check-sentence-pangram",
        "title": "Check if the Sentence Is Pangram",
        "category": "STRING",
        "pattern": DSAPattern.HASH_TABLE,
        "statement": "A pangram is a sentence where every letter of the English alphabet appears at least once. Given a string sentence containing only lowercase English letters, return true if sentence is a pangram, or false otherwise.",
        "constraints": ["1 <= sentence.length <= 1000", "sentence consists of lowercase English letters."],
        "function_name": "checkIfPangram",
        "param_names": ["sentence"],
        "return_type": "bool",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"sentence": "thequickbrownfoxjumpsoverthelazydog"}, "output": True},
            {"input": {"sentence": "leetcode"}, "output": False},
        ],
        "flaw_code": """class Solution {
    public boolean checkIfPangram(String sentence) {
        // Flawed: only checks length >= 26
        return sentence.length() >= 26;
    }
}
""",
    },
    # 13. ARRAY / TWO POINTERS: Duplicate Zeros (C++)
    {
        "id": "duplicate-zeros-array",
        "title": "Duplicate Zeros in Array",
        "category": "ARRAY",
        "pattern": DSAPattern.TWO_POINTERS,
        "statement": "Given a fixed-length integer array arr, duplicate each occurrence of zero, shifting the remaining elements to the right. Elements beyond the length of the original array are not written.",
        "constraints": ["1 <= arr.length <= 10^4", "0 <= arr[i] <= 9"],
        "function_name": "duplicateZeros",
        "param_names": ["arr"],
        "return_type": "List[int]",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"arr": [1, 0, 2, 3, 0, 4, 5, 0]}, "output": [1, 0, 0, 2, 3, 0, 0, 4]},
            {"input": {"arr": [1, 2, 3]}, "output": [1, 2, 3]},
        ],
        "flaw_code": """#include <vector>
using namespace std;

class Solution {
public:
    vector<int> duplicateZeros(vector<int>& arr) {
        // Flawed: returns original array without duplicating zeros
        return arr;
    }
};
""",
    },
    # 14. BOUNDED UNFIXABLE CASE: Runaway Self-Referential Cyclic Graph (Java)
    {
        "id": "unfixable-stage27-cyclic-trap",
        "title": "Unfixable Non-Terminating Self-Referential Graph",
        "category": "GRAPH",
        "pattern": DSAPattern.GRAPH_BFS_DFS,
        "statement": "Test safety watchdogs on deliberate non-terminating runaway cyclic recursion.",
        "constraints": ["1 <= n <= 100"],
        "function_name": "cyclicTrap",
        "param_names": ["n"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"n": 5}, "output": 5},
        ],
        "flaw_code": """class Solution {
    public int cyclicTrap(int n) {
        // Runaway infinite loop
        while (true) {}
    }
}
""",
        "is_unfixable": True,
    },
    # 15. ISOLATED INFRASTRUCTURE CASE: Host Compiler Quarantined Runner (Java)
    {
        "id": "unseen-stage27-infra-isolated",
        "title": "Quarantined Host Toolchain Fault Scenario",
        "category": "ARRAY",
        "pattern": DSAPattern.ARRAYS_STRINGS,
        "statement": "Simulated hardware environment sandbox fault isolation verifying unhandled executor crash handling.",
        "constraints": ["1 <= n <= 100"],
        "function_name": "quarantineFaultHarness",
        "param_names": ["n"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"n": 10}, "output": 10},
        ],
        "mock_infra": True,
    },
]


def build_stage27_problem_spec(p_def: dict) -> ProblemSpec:
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
