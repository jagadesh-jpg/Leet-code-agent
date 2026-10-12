"""
Deterministic DSA Pattern Classifier.
Analyzes problem descriptions, parameters, return types, and constraints to identify
candidate DSA patterns across the entire competitive programming spectrum.
"""

from typing import List, Set
from agent.core.models import DSAPattern, ProblemSpec


class PatternClassifier:
    """
    Classifies a ProblemSpec into one or more candidate DSAPattern categories
    based on syntactic markers, parameter types, algorithmic keywords, and mathematical invariants.
    """

    @classmethod
    def classify(cls, problem: ProblemSpec) -> List[DSAPattern]:
        """Returns sorted list of applicable DSA patterns for the given problem."""
        patterns: Set[DSAPattern] = set()

        text = f"{problem.id} {problem.title} {problem.function_name} {problem.description} {' '.join(problem.constraints)}".lower()
        param_names_lower = [p.lower() for p in problem.param_names]
        ret_type_lower = problem.return_type.lower()

        # 1. Linked List
        if "linked list" in text or "listnode" in text or "head" in param_names_lower or "list1" in param_names_lower:
            patterns.add(DSAPattern.LINKED_LIST)

        # 2. Binary Tree / BST
        import re
        if "binary tree" in text or "treenode" in text or "root" in param_names_lower or "symmetric" in text or re.search(r"\bbst\b|\btree\b", text):
            patterns.add(DSAPattern.BINARY_TREE)

        # 3. Graph Traversal / Shortest Path / MST
        if "graph" in text or re.search(r"\b(edges|vertices|provinces|islands|rooms)\b", text) or ("grid" in text or "matrix" in text) or (re.search(r"\badj\b|\badjacency\b", text) and "adjacent" not in text):
            if "linked list" not in text and "list1" not in param_names_lower and "treenode" not in text and "root" not in param_names_lower:
                if "shortest path" in text or "dijkstra" in text or "weight" in text:
                    patterns.add(DSAPattern.SHORTEST_PATH)
                elif "spanning tree" in text or "kruskal" in text or "prim" in text:
                    patterns.add(DSAPattern.MINIMUM_SPANNING_TREE)
                elif "topological" in text or "course schedule" in text or "dag" in text:
                    patterns.add(DSAPattern.TOPOLOGICAL_SORT)
                elif "connected components" in text or "disjoint" in text or "union" in text:
                    patterns.add(DSAPattern.UNION_FIND)
                else:
                    patterns.add(DSAPattern.GRAPH_BFS_DFS)

        # 4. Trie
        if "trie" in text or "prefix tree" in text or "autocomplete" in text:
            patterns.add(DSAPattern.TRIE)

        # 5. Heap / Priority Queue
        if "kth largest" in text or "kth smallest" in text or "median" in text or "priority queue" in text or "heap" in text or "stone weight" in text or "stream" in text:
            patterns.add(DSAPattern.HEAP_PRIORITY_QUEUE)

        # 6. Monotonic Stack / Stack
        if "valid parentheses" in text or "stack" in text or "next greater" in text or "daily temperatures" in text or "adjacent duplicates" in text or "backspace" in text:
            patterns.add(DSAPattern.STACK)

        # 7. Queue / Deque
        if "queue" in text or "sliding window maximum" in text:
            patterns.add(DSAPattern.QUEUE_DEQUE)

        # 8. Sliding Window
        if "substring" in text or "subarray" in text or "window" in text:
            if "longest" in text or "shortest" in text or "minimal length" in text or "at most k" in text or "exact k" in text or "average" in text:
                patterns.add(DSAPattern.SLIDING_WINDOW)

        # 9. Two Pointers
        if "two pointers" in text or "palindrome" in text or "target sum" in text or "container with most water" in text or "move zero" in text or "squares of a sorted" in text or "intersection" in text:
            patterns.add(DSAPattern.TWO_POINTERS)

        # 10. Binary Search
        if "binary search" in text or "rotated sorted" in text or "find peak" in text or "peak index" in text or "mountain array" in text or "search insert" in text or "search in" in text:
            patterns.add(DSAPattern.BINARY_SEARCH)
        elif ("sorted" in text and ("target" in param_names_lower or "search" in text or "insert" in text) and "square" not in text and "merge" not in text):
            patterns.add(DSAPattern.BINARY_SEARCH)

        # 11. Prefix Sum / Difference Array
        if "prefix sum" in text or "range sum" in text or "sum between" in text or "cumulative" in text:
            patterns.add(DSAPattern.PREFIX_SUM)

        # 12. Intervals / Sweep Line
        if "intervals" in text or "meeting rooms" in text or "overlapping" in text or "merge intervals" in text:
            patterns.add(DSAPattern.INTERVALS)

        # 13. Dynamic Programming
        if "maximum profit" in text or "minimum cost" in text or "number of ways" in text or "coin change" in text or "subsequence" in text or "knapsack" in text or "climbing stairs" in text or "house robber" in text or re.search(r"\b(rob|robber)\b", text):
            patterns.add(DSAPattern.DYNAMIC_PROGRAMMING)

        # 14. Greedy
        if "greedy" in text or "gas station" in text or "jump game" in text or "assign cookies" in text or "stock" in text or "buy and sell" in text or "lemonade" in text or "change" in text or "cookie" in text:
            patterns.add(DSAPattern.GREEDY)

        # 15. Backtracking & Recursion
        if "permutations" in text or "subsets" in text or "combinations" in text or "n-queens" in text or "word search" in text:
            patterns.add(DSAPattern.BACKTRACKING_RECURSION)

        # 16. Bit Manipulation
        if "bitwise" in text or "xor" in text or "single number" in text or "hamming" in text or "number of 1 bits" in text:
            patterns.add(DSAPattern.BIT_MANIPULATION)

        # 17. Hash Table (Lookup / Frequency)
        if ("frequency" in text or "two sum" in text or "two-sum" in text or "twosum" in text or "anagram" in text or ("duplicate" in text and "adjacent" not in text) or "count" in text or "hash" in text or "unique" in text or "ransom" in text or "magazine" in text or "intersect" in text):
            patterns.add(DSAPattern.HASH_TABLE)

        # 18. Default fallback: Arrays & Strings if inputs are lists or strings
        if not patterns:
            has_seq = any(
                p.type_str.startswith("List") or p.type_str == "str"
                for p in problem.params_schema
            ) or "nums" in param_names_lower or "s" in param_names_lower
            if has_seq:
                patterns.add(DSAPattern.ARRAYS_STRINGS)
            else:
                patterns.add(DSAPattern.UNKNOWN)

        return sorted(list(patterns), key=lambda x: x.value)
