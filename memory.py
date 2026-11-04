import re
from typing import Any, Dict, List, Optional
from pathlib import Path
import store


DEFAULT_LEARNING_PATTERNS = [
    {
        "category": "two_pointers",
        "title": "Two-Pointer Sorted Search (e.g. 3Sum, Two Sum II)",
        "pattern": "two_pointers",
        "summary": "When array is sorted, use left and right pointers. When incrementing/decrementing after matching, advance past duplicate values using while loops to prevent duplicate answers.",
        "code_snippet": "left, right = i + 1, n - 1\nwhile left < right:\n    tot = nums[i] + nums[left] + nums[right]\n    if tot == 0:\n        res.append([nums[i], nums[left], nums[right]])\n        left += 1\n        right -= 1\n        while left < right and nums[left] == nums[left - 1]: left += 1\n        while left < right and nums[right] == nums[right + 1]: right -= 1",
    },
    {
        "category": "sliding_window",
        "title": "Dynamic Sliding Window (e.g. Longest Substring Without Repeating Characters)",
        "pattern": "sliding_window",
        "summary": "Maintain a hash map of last seen indices or a frequency set. When a duplicate enters the window, contract the left boundary past the previous occurrence.",
        "code_snippet": "seen = {}\nleft = 0\nmax_len = 0\nfor right, ch in enumerate(s):\n    if ch in seen and seen[ch] >= left:\n        left = seen[ch] + 1\n    seen[ch] = right\n    max_len = max(max_len, right - left + 1)",
    },
    {
        "category": "hash_maps",
        "title": "Categorization by Canonical Key (e.g. Group Anagrams)",
        "pattern": "hash_maps",
        "summary": "Use sorted string or character count tuple as dictionary keys to aggregate matching items in O(N * K) or O(N * K log K).",
        "code_snippet": "from collections import defaultdict\ngroups = defaultdict(list)\nfor word in strs:\n    key = ''.join(sorted(word))\n    groups[key].append(word)\nreturn list(groups.values())",
    },
    {
        "category": "prefix_sum",
        "title": "Prefix and Suffix Accumulation (e.g. Product of Array Except Self)",
        "pattern": "prefix_sum",
        "summary": "Compute prefix products in a left-to-right pass, then multiply running suffix products in a right-to-left pass without division.",
        "code_snippet": "n = len(nums)\nres = [1] * n\nfor i in range(1, n):\n    res[i] = res[i - 1] * nums[i - 1]\ncurr = 1\nfor i in range(n - 1, -1, -1):\n    res[i] *= curr\n    curr *= nums[i]\nreturn res",
    },
    {
        "category": "dynamic_programming",
        "title": "Interval DP / Expansion Around Center (e.g. Longest Palindromic Substring)",
        "pattern": "dynamic_programming",
        "summary": "For palindromes, expand outwards from every single character (odd length) and between every pair of characters (even length).",
        "code_snippet": "def expand(l, r):\n    while l >= 0 and r < len(s) and s[l] == s[r]:\n        l -= 1\n        r += 1\n    return s[l + 1:r]",
    },
    {
        "category": "linked_list",
        "title": "In-Place Pointer Reversal (e.g. Reverse Linked List)",
        "pattern": "linked_list",
        "summary": "Maintain prev, curr, next pointers. Update curr.next = prev in a single loop traversal.",
        "code_snippet": "prev = None\ncurr = head\nwhile curr:\n    nxt = curr.next\n    curr.next = prev\n    prev = curr\n    curr = nxt\nreturn prev",
    },
]


def seed_default_learning(db_path: Optional[str | Path] = None) -> None:
    store.init(db_path=db_path)
    existing = store.get_learning_entries(limit=1, db_path=db_path)
    if not existing:
        for item in DEFAULT_LEARNING_PATTERNS:
            store.save_learning(
                category=item["category"],
                title=item["title"],
                pattern=item["pattern"],
                summary=item["summary"],
                code_snippet=item["code_snippet"],
                db_path=db_path,
            )


def retrieve_relevant_learning(
    problem: Dict[str, Any],
    limit: int = 3,
    db_path: Optional[str | Path] = None,
) -> List[Dict[str, Any]]:
    """Retrieve relevant algorithm patterns, common mistakes, and lessons from persistent memory."""
    seed_default_learning(db_path=db_path)
    entries = store.get_learning_entries(limit=100, db_path=db_path)

    text_to_match = f"{problem.get('id', '')} {problem.get('title', '')} {problem.get('description', '')}".lower()

    scored = []
    keywords_map = {
        "two_pointers": ["two pointers", "pointer", "triplet", "pair", "sum", "sorted"],
        "sliding_window": ["substring", "window", "consecutive", "repeating", "subarray"],
        "hash_maps": ["anagram", "frequency", "duplicate", "map", "count", "seen"],
        "prefix_sum": ["product", "prefix", "suffix", "except self", "cumulative"],
        "dynamic_programming": ["palindrome", "subsequence", "longest", "maximum sum", "dp"],
        "linked_list": ["listnode", "linked list", "reverse", "head", "next"],
    }

    for entry in entries:
        score = 0
        cat = entry["category"].lower()
        title = entry["title"].lower()
        summary = entry["summary"].lower()

        # Keyword match
        for kw in keywords_map.get(cat, [cat]):
            if kw in text_to_match:
                score += 2
        for word in title.split():
            if len(word) > 3 and word in text_to_match:
                score += 1
        if entry["pattern"].lower() in text_to_match:
            score += 3

        scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:limit]]


def format_learning_context(learning_items: List[Dict[str, Any]]) -> str:
    """Format retrieved learning memory for prompt context."""
    if not learning_items:
        return ""
    lines = ["Relevant Persistent Learning Memory & Patterns:"]
    for idx, item in enumerate(learning_items, 1):
        lines.append(f"{idx}. [{item['category']}] {item['title']}")
        lines.append(f"   Lesson: {item['summary']}")
        if item.get("code_snippet"):
            lines.append(f"   Pattern Snippet:\n   ```python\n   {item['code_snippet']}\n   ```")
    return "\n".join(lines)

