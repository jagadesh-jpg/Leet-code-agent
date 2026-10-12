"""
Stage 26: Independent Held-Out DSA Evaluation Suite & Benchmark Defs.
Strictly disjoint from:
- Stages 1-23 Benchmark Registry & Dev sets
- Stage 24 Held-Out problems (reclassified as diagnostic)
- Stage 25 Held-Out problems (reclassified as diagnostic)

Contains 15 authentic, independent DSA problems covering >= 10 DSA categories across C, C++, Java, and Python.
Includes:
- 13 Candidate-solvable problems
- 1 Deliberate bounded failure case (unfixable runaway trap)
- 1 Isolated host toolchain infrastructure failure case
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


STAGE26_HELD_OUT_PROBLEMS_DEFS: List[Dict[str, Any]] = [
    # 1. HASH TABLE / FREQUENCY: Word Pattern (Python)
    {
        "id": "word-pattern",
        "title": "Word Pattern",
        "category": "HASHING",
        "pattern": DSAPattern.HASH_TABLE,
        "statement": "Given a pattern and a string s, find if s follows the same pattern. Follow means a full match, such that there is a bijection between a letter in pattern and a non-empty word in s.",
        "constraints": ["1 <= pattern.length <= 300", "1 <= s.length <= 3000", "pattern contains only lower-case English letters.", "s contains only lowercase English letters and spaces ' '."],
        "function_name": "wordPattern",
        "param_names": ["pattern", "s"],
        "return_type": "bool",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"pattern": "abba", "s": "dog cat cat dog"}, "output": True},
            {"input": {"pattern": "abba", "s": "dog cat cat fish"}, "output": False},
            {"input": {"pattern": "aaaa", "s": "dog cat cat dog"}, "output": False},
        ],
        "flaw_code": """class Solution:
    def wordPattern(self, pattern, s):
        # Flawed: only checks word length count
        return len(pattern) == len(s.split())
""",
    },
    # 2. TWO POINTERS: Is Subsequence (C++)
    {
        "id": "is-subsequence",
        "title": "Is Subsequence",
        "category": "TWO_POINTERS",
        "pattern": DSAPattern.TWO_POINTERS,
        "statement": "Given two strings s and t, return true if s is a subsequence of t, or false otherwise. A subsequence of a string is a new string that is formed from the original string by deleting some (can be none) of the characters without disturbing the relative positions of the remaining characters.",
        "constraints": ["0 <= s.length <= 100", "0 <= t.length <= 10^4", "s and t consist only of lowercase English letters."],
        "function_name": "isSubsequence",
        "param_names": ["s", "t"],
        "return_type": "bool",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"s": "abc", "t": "ahbgdc"}, "output": True},
            {"input": {"s": "axc", "t": "ahbgdc"}, "output": False},
        ],
        "flaw_code": """#include <string>
using namespace std;

class Solution {
public:
    bool isSubsequence(string s, string t) {
        // Flawed: always returns true
        return true;
    }
};
""",
    },
    # 3. BINARY SEARCH: Guess Number Higher or Lower (Java)
    {
        "id": "guess-number-higher-lower",
        "title": "Guess Number Higher or Lower",
        "category": "BINARY_SEARCH",
        "pattern": DSAPattern.BINARY_SEARCH,
        "statement": "We are playing the Guess Game. The game will pick a number from 1 to n. Given an array representing candidate numbers [1..n] and target pick, locate the pick index.",
        "constraints": ["1 <= n <= 2^31 - 1", "1 <= pick <= n"],
        "function_name": "guessNumber",
        "param_names": ["nums", "target"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"nums": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "target": 6}, "output": 5},
            {"input": {"nums": [1], "target": 1}, "output": 0},
            {"input": {"nums": [1, 2], "target": 1}, "output": 0},
        ],
        "flaw_code": """class Solution {
    public int guessNumber(int[] nums, int target) {
        // Flawed: returns 0 always
        return 0;
    }
}
""",
    },
    # 4. SLIDING WINDOW: Maximum Number of Vowels in a Substring of Given Length (Python)
    {
        "id": "max-vowels-in-substring",
        "title": "Maximum Number of Vowels in a Substring of Given Length",
        "category": "SLIDING_WINDOW",
        "pattern": DSAPattern.SLIDING_WINDOW,
        "statement": "Given a string s and an integer k, return the maximum number of vowel letters in any substring of s with length k. Vowel letters in English are 'a', 'e', 'i', 'o', and 'u'.",
        "constraints": ["1 <= s.length <= 10^5", "s consists of lowercase English letters.", "1 <= k <= s.length"],
        "function_name": "maxVowels",
        "param_names": ["s", "k"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"s": "abciiidef", "k": 3}, "output": 3},
            {"input": {"s": "aeiou", "k": 2}, "output": 2},
            {"input": {"s": "leetcode", "k": 3}, "output": 2},
        ],
        "flaw_code": """class Solution:
    def maxVowels(self, s, k):
        # Flawed: counts total vowels without window constraint
        vowels = set('aeiou')
        return sum(1 for c in s if c in vowels)
""",
    },
    # 5. STACK: Baseball Game (C++)
    {
        "id": "baseball-game",
        "title": "Baseball Game",
        "category": "STACK",
        "pattern": DSAPattern.STACK,
        "statement": "You are keeping the scores for a baseball game with strange rules. Given a list of strings operations, where each operation is an integer, '+', 'D', or 'C', return the sum of all scores on the record after applying all the operations.",
        "constraints": ["1 <= operations.length <= 1000", "operations[i] is 'C', 'D', '+', or a string representing an integer in the range [-3 * 10^4, 3 * 10^4]."],
        "function_name": "calPoints",
        "param_names": ["operations"],
        "return_type": "int",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"operations": ["5", "2", "C", "D", "+"]}, "output": 30},
            {"input": {"operations": ["5", "-2", "4", "C", "D", "9", "+", "+"]}, "output": 27},
            {"input": {"operations": ["1", "C"]}, "output": 0},
        ],
        "flaw_code": """#include <vector>
#include <string>
using namespace std;

class Solution {
public:
    int calPoints(vector<string>& operations) {
        // Flawed: returns 0 always
        return 0;
    }
};
""",
    },
    # 6. LINKED LIST: Remove Linked List Elements (Python)
    {
        "id": "remove-linked-list-elements",
        "title": "Remove Linked List Elements",
        "category": "LINKED_LIST",
        "pattern": DSAPattern.LINKED_LIST,
        "statement": "Given the head of a linked list (represented as an integer array) and an integer val, remove all the nodes of the linked list that have Node.val == val, and return the new list.",
        "constraints": ["The number of nodes in the list is in the range [0, 10^4].", "1 <= Node.val <= 50", "0 <= val <= 50"],
        "function_name": "removeElements",
        "param_names": ["head", "val"],
        "return_type": "List[int]",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"head": [1, 2, 6, 3, 4, 5, 6], "val": 6}, "output": [1, 2, 3, 4, 5]},
            {"input": {"head": [], "val": 1}, "output": []},
            {"input": {"head": [7, 7, 7, 7], "val": 7}, "output": []},
        ],
        "flaw_code": """class Solution:
    def removeElements(self, head, val):
        # Flawed: returns original head without removing val
        return head
""",
    },
    # 7. TREE: Same Tree (Java)
    {
        "id": "same-tree",
        "title": "Same Tree",
        "category": "TREE_BST",
        "pattern": DSAPattern.BINARY_TREE,
        "statement": "Given the roots of two binary trees p and q (represented as integer level-order arrays), write a function to check if they are the same or not.",
        "constraints": ["The number of nodes in both trees is in the range [0, 100].", "-10^4 <= Node.val <= 10^4"],
        "function_name": "isSameTree",
        "param_names": ["p", "q"],
        "return_type": "bool",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"p": [1, 2, 3], "q": [1, 2, 3]}, "output": True},
            {"input": {"p": [1, 2], "q": [1, 0, 2]}, "output": False},
            {"input": {"p": [1, 2, 1], "q": [1, 1, 2]}, "output": False},
        ],
        "flaw_code": """class Solution {
    public boolean isSameTree(int[] p, int[] q) {
        // Flawed: only checks length equality
        return p.length == q.length;
    }
}
""",
    },
    # 8. BFS / DFS GRAPH: Flood Fill 4-Way (C)
    {
        "id": "flood-fill-matrix",
        "title": "Flood Fill Matrix Region",
        "category": "BFS_DFS",
        "pattern": DSAPattern.GRAPH_BFS_DFS,
        "statement": "An image is represented by an m x n integer grid image where image[i][j] represents the pixel value. You are given integers sr, sc, and color. Perform flood fill on the image starting from the pixel image[sr][sc].",
        "constraints": ["m == image.length", "n == image[i].length", "1 <= m, n <= 50", "0 <= image[i][j], color < 65536", "0 <= sr < m", "0 <= sc < n"],
        "function_name": "floodFillRegion",
        "param_names": ["image", "sr", "sc", "color"],
        "return_type": "List[List[int]]",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"image": [[1, 1, 1], [1, 1, 0], [1, 0, 1]], "sr": 1, "sc": 1, "color": 2}, "output": [[2, 2, 2], [2, 2, 0], [2, 0, 1]]},
            {"input": {"image": [[0, 0, 0], [0, 0, 0]], "sr": 0, "sc": 0, "color": 0}, "output": [[0, 0, 0], [0, 0, 0]]},
        ],
        "flaw_code": """class Solution:
    def floodFillRegion(self, image, sr, sc, color):
        # Flawed: only modifies starting cell
        image[sr][sc] = color
        return image
""",
    },
    # 9. HEAP / PRIORITY QUEUE: Relative Ranks (C++)
    {
        "id": "relative-ranks",
        "title": "Relative Ranks",
        "category": "HEAP_PRIORITY_QUEUE",
        "pattern": DSAPattern.HEAP_PRIORITY_QUEUE,
        "statement": "You are given an integer array score of size n, where score[i] is the score of the ith athlete. Return an array answer of size n where answer[i] is the rank of the ith athlete (top three receive medals: Gold Medal, Silver Medal, Bronze Medal).",
        "constraints": ["n == score.length", "1 <= n <= 10^4", "0 <= score[i] <= 10^6", "All the values in score are unique."],
        "function_name": "findRelativeRanks",
        "param_names": ["score"],
        "return_type": "List[str]",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"score": [5, 4, 3, 2, 1]}, "output": ["Gold Medal", "Silver Medal", "Bronze Medal", "4", "5"]},
            {"input": {"score": [10, 3, 8, 9, 4]}, "output": ["Gold Medal", "5", "Bronze Medal", "Silver Medal", "4"]},
        ],
        "flaw_code": """#include <vector>
#include <string>
using namespace std;

class Solution {
public:
    vector<string> findRelativeRanks(vector<int>& score) {
        // Flawed: returns empty vector
        return {};
    }
};
""",
    },
    # 10. GREEDY: Maximum Units on a Truck (Python)
    {
        "id": "maximum-units-on-a-truck",
        "title": "Maximum Units on a Truck",
        "category": "GREEDY",
        "pattern": DSAPattern.GREEDY,
        "statement": "You are assigned to put some amount of boxes onto one truck. You are given a 2D array boxTypes, where boxTypes[i] = [numberOfBoxes_i, numberOfUnitsPerBox_i]. You are also given truckSize, which is the maximum number of boxes that can be put on the truck. Return the maximum total number of units that can be put on the truck.",
        "constraints": ["1 <= boxTypes.length <= 1000", "1 <= numberOfBoxes_i, numberOfUnitsPerBox_i <= 1000", "1 <= truckSize <= 10^6"],
        "function_name": "maximumUnits",
        "param_names": ["boxTypes", "truckSize"],
        "return_type": "int",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"boxTypes": [[1, 3], [2, 2], [3, 1]], "truckSize": 4}, "output": 8},
            {"input": {"boxTypes": [[5, 10], [2, 5], [4, 7], [3, 9]], "truckSize": 10}, "output": 91},
        ],
        "flaw_code": """class Solution:
    def maximumUnits(self, boxTypes, truckSize):
        # Flawed: ignores units per box and takes first available boxes
        return sum(b[0] for b in boxTypes[:truckSize])
""",
    },
    # 11. DYNAMIC PROGRAMMING: Pascal's Triangle Row (Python)
    {
        "id": "pascals-triangle-row",
        "title": "Pascal's Triangle II",
        "category": "DYNAMIC_PROGRAMMING",
        "pattern": DSAPattern.DYNAMIC_PROGRAMMING,
        "statement": "Given an integer rowIndex, return the rowIndex-th (0-indexed) row of the Pascal's triangle.",
        "constraints": ["0 <= rowIndex <= 33"],
        "function_name": "getRow",
        "param_names": ["rowIndex"],
        "return_type": "List[int]",
        "language": SupportedLanguage.PYTHON,
        "examples": [
            {"input": {"rowIndex": 3}, "output": [1, 3, 3, 1]},
            {"input": {"rowIndex": 0}, "output": [1]},
            {"input": {"rowIndex": 1}, "output": [1, 1]},
        ],
        "flaw_code": """class Solution:
    def getRow(self, rowIndex):
        # Flawed: returns all ones
        return [1] * (rowIndex + 1)
""",
    },
    # 12. STRING / PARSING: Valid Palindrome II (Java)
    {
        "id": "valid-palindrome-ii",
        "title": "Valid Palindrome II",
        "category": "STRING",
        "pattern": DSAPattern.TWO_POINTERS,
        "statement": "Given a string s, return true if the s can be palindrome after deleting at most one character from it.",
        "constraints": ["1 <= s.length <= 10^5", "s consists of lowercase English letters."],
        "function_name": "validPalindrome",
        "param_names": ["s"],
        "return_type": "bool",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"s": "aba"}, "output": True},
            {"input": {"s": "abca"}, "output": True},
            {"input": {"s": "abc"}, "output": False},
        ],
        "flaw_code": """class Solution {
    public boolean validPalindrome(String s) {
        // Flawed: only checks exact palindrome without character deletion allowance
        int l = 0, r = s.length() - 1;
        while (l < r) {
            if (s.charAt(l) != s.charAt(r)) return false;
            l++;
            r--;
        }
        return true;
    }
}
""",
    },
    # 13. ARRAY / SORTING: Can Place Flowers (C++)
    {
        "id": "can-place-flowers",
        "title": "Can Place Flowers",
        "category": "ARRAY",
        "pattern": DSAPattern.GREEDY,
        "statement": "You have a long flowerbed in which some of the plots are planted, and some are not. However, flowers cannot be planted in adjacent plots. Given an integer array flowerbed containing 0's and 1's and an integer n, return true if n new flowers can be planted in the flowerbed without violating the no-adjacent-flowers rule and false otherwise.",
        "constraints": ["1 <= flowerbed.length <= 2 * 10^4", "flowerbed[i] is 0 or 1.", "There are no two adjacent flowers in flowerbed.", "0 <= n <= flowerbed.length"],
        "function_name": "canPlaceFlowers",
        "param_names": ["flowerbed", "n"],
        "return_type": "bool",
        "language": SupportedLanguage.CPP,
        "examples": [
            {"input": {"flowerbed": [1, 0, 0, 0, 1], "n": 1}, "output": True},
            {"input": {"flowerbed": [1, 0, 0, 0, 1], "n": 2}, "output": False},
        ],
        "flaw_code": """#include <vector>
using namespace std;

class Solution {
public:
    bool canPlaceFlowers(vector<int>& flowerbed, int n) {
        // Flawed: returns true if n == 0 only
        return n == 0;
    }
};
""",
    },
    # 14. BOUNDED UNFIXABLE CASE: Runaway Recurrence In State Machine (Java)
    {
        "id": "unfixable-stage26-runaway-trap",
        "title": "Unfixable Non-Terminating State Machine",
        "category": "GRAPH",
        "pattern": DSAPattern.GRAPH_BFS_DFS,
        "statement": "Test safety watchdogs on deliberate non-terminating runaway state machine recursion.",
        "constraints": ["1 <= n <= 100"],
        "function_name": "runawayMachine",
        "param_names": ["n"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"n": 5}, "output": 5},
        ],
        "flaw_code": """class Solution {
    public int runawayMachine(int n) {
        // Runaway infinite loop
        while (true) {}
    }
}
""",
        "is_unfixable": True,
    },
    # 15. ISOLATED INFRASTRUCTURE CASE: Host Toolchain Missing Runner (Java)
    {
        "id": "unseen-stage26-infra-isolated",
        "title": "Isolated Host Toolchain Exception Case",
        "category": "ARRAY",
        "pattern": DSAPattern.ARRAYS_STRINGS,
        "statement": "Synthetic problem engineered to trigger a host execution toolchain exception cleanly.",
        "constraints": ["1 <= n <= 100"],
        "function_name": "isolatedHostInfra",
        "param_names": ["n"],
        "return_type": "int",
        "language": SupportedLanguage.JAVA,
        "examples": [
            {"input": {"n": 10}, "output": 10},
        ],
        "mock_infra": True,
    },
]


def build_stage26_problem_spec(p_def: dict) -> ProblemSpec:
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
