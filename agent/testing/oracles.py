"""
Deterministic Reference Algorithms & Oracles.
Provides simple, correctness-focused baseline solutions and property checkers
for computing expected outputs on generated test inputs.
"""

from typing import Any, Callable, Dict, Optional, Tuple
from agent.core.models import DSAPattern, ProblemSpec


class OracleFailure(Exception):
    """Raised when an oracle fails or cannot compute a valid expected answer."""
    pass


class ReferenceOracles:
    """
    Registry of canonical, trusted reference algorithms for differential testing.
    Uses simple, obviously-correct brute-force logic (e.g. O(N^2) search, sorting, simulation)
    to establish ground truth on generated inputs.
    """

    @classmethod
    def get_reference_solution(cls, problem: ProblemSpec) -> Optional[Callable[..., Any]]:
        """Finds or constructs a trusted reference function for the given problem."""
        pid = problem.id.lower()
        fn_name = problem.function_name.lower()

        # Two Sum
        if "two-sum" in pid or fn_name == "twosum":
            return cls._ref_two_sum

        # Valid Parentheses
        if "valid-parentheses" in pid or fn_name == "isvalid":
            return cls._ref_valid_parentheses

        # Maximum Subarray
        if "maximum-subarray" in pid or fn_name == "maxsubarray":
            return cls._ref_max_subarray

        # Binary Search / Search in Sorted Array (excluding searchInsert)
        if ("binary-search" in pid or "search" in fn_name) and "insert" not in fn_name:
            return cls._ref_linear_search

        # Valid Anagram
        if "valid-anagram" in pid or fn_name == "isanagram":
            return cls._ref_valid_anagram

        # Valid Palindrome
        if "valid-palindrome" in pid or fn_name == "ispalindrome":
            return cls._ref_valid_palindrome

        # Longest Substring Without Repeating Characters
        if "longest-substring" in pid or fn_name == "lengthoflongestsubstring":
            return cls._ref_longest_substring

        # Reverse Linked List (represented as list of integers)
        if "reverse-linked-list" in pid or fn_name == "reverselist":
            return cls._ref_reverse_list

        # Maximum Depth of Binary Tree
        if "maximum-depth" in pid or fn_name == "maxdepth":
            return cls._ref_max_depth

        # Number of Islands
        if "number-of-islands" in pid or fn_name == "numislands":
            return cls._ref_num_islands

        # Kth Largest Element
        if "kth-largest" in pid or fn_name == "findkthlargest":
            return cls._ref_find_kth_largest

        # Subsets
        if "subsets" in pid or fn_name == "subsets":
            return cls._ref_subsets

        # Number of Provinces
        if "number-of-provinces" in pid or fn_name == "findcirclenum":
            return cls._ref_find_circle_num

        # Climbing Stairs
        if "climbing-stairs" in pid or fn_name == "climbstairs":
            return cls._ref_climb_stairs

        # Best Time to Buy and Sell Stock
        if "best-time-to-buy-and-sell-stock" in pid or fn_name == "maxprofit":
            return cls._ref_max_profit

        # Default fallback: check if problem has a simple brute force derived from pattern
        return None

    @classmethod
    def evaluate_property(
        cls,
        problem: ProblemSpec,
        inputs: Dict[str, Any],
        actual_output: Any,
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluates problem-specific metamorphic properties or mathematical invariants.
        Returns: (passes_property, failure_reason)
        """
        # Property for Two Sum: output must be 2 distinct valid indices whose values sum to target
        if "two-sum" in problem.id.lower() or problem.function_name.lower() == "twosum":
            nums = inputs.get("nums", [])
            target = inputs.get("target")
            if not isinstance(actual_output, (list, tuple)) or len(actual_output) != 2:
                return False, f"Expected a list of 2 indices, got: {actual_output}"
            i, j = actual_output
            if not (isinstance(i, int) and isinstance(j, int)):
                return False, f"Indices must be integers, got: {actual_output}"
            if i == j:
                return False, f"Indices must be distinct, got {i} == {j}"
            if i < 0 or i >= len(nums) or j < 0 or j >= len(nums):
                return False, f"Indices ({i}, {j}) out of array bounds [0, {len(nums)-1}]"
            actual_sum = nums[i] + nums[j]
            if actual_sum != target:
                return False, f"nums[{i}] ({nums[i]}) + nums[{j}] ({nums[j]}) = {actual_sum} != target ({target})"
            return True, None

        # Property for Search: returned index must contain the target value, or -1 if target not in array
        # Exclude searchInsert which returns insertion index >= 0 rather than -1
        if ("binary-search" in problem.id.lower() or problem.function_name.lower() == "search") and "insert" not in problem.function_name.lower():
            nums = inputs.get("nums", [])
            target = inputs.get("target")
            if actual_output == -1:
                if target in nums:
                    return False, f"Target {target} is present in nums, but returned -1"
                return True, None
            if not isinstance(actual_output, int) or actual_output < 0 or actual_output >= len(nums):
                return False, f"Returned index {actual_output} is invalid for array of size {len(nums)}"
            if nums[actual_output] != target:
                return False, f"nums[{actual_output}] is {nums[actual_output]}, expected {target}"
            return True, None

        # Property for Subsets: power set has 2^N unique subsets containing only elements from nums
        if "subsets" in problem.id.lower() or problem.function_name.lower() == "subsets":
            nums = inputs.get("nums", [])
            if not isinstance(actual_output, (list, tuple)):
                return False, f"Expected list of subsets, got: {type(actual_output)}"
            if len(actual_output) != (1 << len(nums)):
                return False, f"Expected {1 << len(nums)} subsets, got {len(actual_output)}"
            # Convert each subset to sorted tuple and check set of subsets
            actual_set = set(tuple(sorted(sub)) for sub in actual_output)
            if len(actual_set) != (1 << len(nums)):
                return False, f"Subsets contain duplicates"
            # Verify each element is in nums
            nums_set = set(nums)
            for sub in actual_output:
                if not set(sub).issubset(nums_set):
                    return False, f"Subset {sub} contains elements not in nums {nums}"
            return True, None

        # Generic invariant: No specific invariant check defined
        return None, None

    # --- CANONICAL REFERENCE IMPLEMENTATIONS ---
    @staticmethod
    def _ref_two_sum(nums: list, target: int) -> list:
        """Brute-force O(N^2) reference for Two Sum."""
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                if nums[i] + nums[j] == target:
                    return [i, j]
        return []

    @staticmethod
    def _ref_valid_parentheses(s: str) -> bool:
        """Reference stack for Valid Parentheses."""
        stack = []
        mapping = {")": "(", "}": "{", "]": "["}
        for char in s:
            if char in mapping:
                top = stack.pop() if stack else "#"
                if mapping[char] != top:
                    return False
            else:
                stack.append(char)
        return not stack

    @staticmethod
    def _ref_max_subarray(nums: list) -> int:
        """Reference O(N) Kadane's for Maximum Subarray."""
        if not nums:
            return 0
        max_so_far = nums[0]
        current_max = nums[0]
        for x in nums[1:]:
            current_max = max(x, current_max + x)
            max_so_far = max(max_so_far, current_max)
        return max_so_far

    @staticmethod
    def _ref_linear_search(nums: list, target: int) -> int:
        """Reference linear scan for Binary Search."""
        for i, val in enumerate(nums):
            if val == target:
                return i
        return -1

    @staticmethod
    def _ref_valid_anagram(s: str, t: str) -> bool:
        """Independent reference for Valid Anagram: sorted character comparison."""
        return sorted(s) == sorted(t)

    @staticmethod
    def _ref_valid_palindrome(s: str) -> bool:
        """Independent reference for Valid Palindrome."""
        filtered = [c.lower() for c in s if c.isalnum()]
        return filtered == filtered[::-1]

    @staticmethod
    def _ref_longest_substring(s: str) -> int:
        """Independent brute force reference for Longest Substring Without Repeating Characters."""
        max_len = 0
        n = len(s)
        for i in range(n):
            seen = set()
            for j in range(i, n):
                if s[j] in seen:
                    break
                seen.add(s[j])
            max_len = max(max_len, len(seen))
        return max_len

    @staticmethod
    def _ref_reverse_list(head: list) -> list:
        """Independent reference for Reverse List."""
        return list(reversed(head))

    @staticmethod
    def _ref_max_depth(nodes: list) -> int:
        """Independent reference for Maximum Depth of complete/binary tree array representation."""
        if not nodes:
            return 0
        depth = 0
        count = len(nodes)
        while count > 0:
            depth += 1
            count //= 2
        return depth

    @staticmethod
    def _ref_num_islands(grid: list) -> int:
        """Independent reference for Number of Islands."""
        if not grid or not grid[0]:
            return 0
        m, n = len(grid), len(grid[0])
        visited = set()
        count = 0

        def dfs(r, c):
            visited.add((r, c))
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < m and 0 <= nc < n and (nr, nc) not in visited and grid[nr][nc] == 1:
                    dfs(nr, nc)

        for i in range(m):
            for j in range(n):
                if grid[i][j] == 1 and (i, j) not in visited:
                    count += 1
                    dfs(i, j)
        return count

    @staticmethod
    def _ref_find_kth_largest(nums: list, k: int) -> int:
        """Independent reference for Kth Largest Element."""
        return sorted(nums, reverse=True)[k - 1]

    @staticmethod
    def _ref_subsets(nums: list) -> list:
        """Independent reference for Subsets (Power Set)."""
        res = [[]]
        for num in nums:
            res += [curr + [num] for curr in res]
        return res

    @staticmethod
    def _ref_find_circle_num(isConnected: list) -> int:
        """Independent reference for Number of Provinces."""
        n = len(isConnected)
        visited = [False] * n
        provinces = 0

        def dfs(node):
            visited[node] = True
            for neighbor in range(n):
                if isConnected[node][neighbor] == 1 and not visited[neighbor]:
                    dfs(neighbor)

        for i in range(n):
            if not visited[i]:
                provinces += 1
                dfs(i)
        return provinces

    @staticmethod
    def _ref_climb_stairs(n: int) -> int:
        """Independent reference for Climbing Stairs."""
        if n <= 1:
            return 1
        a, b = 1, 1
        for _ in range(2, n + 1):
            a, b = b, a + b
        return b

    @staticmethod
    def _ref_max_profit(prices: list) -> int:
        """Independent reference for Best Time to Buy and Sell Stock."""
        if not prices:
            return 0
        min_price = prices[0]
        max_profit = 0
        for p in prices[1:]:
            max_profit = max(max_profit, p - min_price)
            min_price = min(min_price, p)
        return max_profit
