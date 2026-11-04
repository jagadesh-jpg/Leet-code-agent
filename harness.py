import json
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional


def build_c_runner(user_code: str, problem: Dict[str, Any]) -> str:
    """Build a standalone C test runner that compiles and executes user code against problem tests.
    Expects standard C function signature, e.g. int search(int* nums, int numsSize, int target);
    """
    tests = problem.get("tests", [])
    test_cases_code = []

    for idx, t in enumerate(tests):
        inp = t.get("args", t.get("input", []))
        nums = inp[0] if len(inp) > 0 else []
        target = inp[1] if len(inp) > 1 else 0
        expected = t.get("expected", 0)

        nums_str = ", ".join(map(str, nums))
        n_len = len(nums)

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

    harness = f"""
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
    return harness


def build_cpp_runner(user_code: str, problem: Dict[str, Any]) -> str:
    """Build a standalone C++ test runner with LeetCode class Solution support."""
    tests = problem.get("tests", [])
    test_cases_code = []

    for idx, t in enumerate(tests):
        inp = t.get("args", t.get("input", []))
        nums = inp[0] if len(inp) > 0 else []
        target = inp[1] if len(inp) > 1 else 0
        expected = t.get("expected", 0)

        nums_str = ", ".join(map(str, nums))

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

    harness = f"""
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
    return harness


def _format_java_val(val: Any) -> str:
    if isinstance(val, list):
        inner = ", ".join(_format_java_val(x) for x in val)
        return f"new int[]{{{inner}}}"
    return str(val)


def build_java_runner(user_code: str, problem: Dict[str, Any]) -> str:
    """Build a Java test harness for LeetCode class Solution."""
    tests = problem.get("tests", [])
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

    harness = f"""
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
    return harness
