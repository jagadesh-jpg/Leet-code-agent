"""Multi-Language Cross-Verification Benchmark Runner (Stage 17).

Proves that the SAME autonomous DSA architecture operates seamlessly across:
- C (gcc)
- C++ (g++)
- Java (javac + java)
- Python (python)

Executes representative problems across all four languages, measures compilation,
verifies execution, stress-tests intentional failures and autonomous self-correction,
and produces a structured multi-language verification matrix.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from agent.benchmarking.benchmark_registry import (
    BENCHMARK_REGISTRY,
    BenchmarkProblem,
    BenchmarkResult,
    to_problem_spec,
)
from agent.core.models import (
    AgentState,
    AlgorithmPlan,
    CandidateApproach,
    ExecutionStatus,
    ProblemSpec,
    SupportedLanguage,
    VerificationStatus,
)
from agent.core.orchestrator import SelfCorrectionOrchestrator
from agent.planning.pattern_classifier import PatternClassifier
from agent.planning.planner import AlgorithmPlanner
from agent.testing.engine import TestingEngine
from agent.verification.verifier import SolutionVerifier
from agent.execution.runner import ExecutionRunner


# Canonical multi-language implementations for representative benchmark problems
MULTI_LANG_CODE: Dict[str, Dict[SupportedLanguage, str]] = {
    # 1. TWO SUM (HASHING / ARRAY)
    "two-sum": {
        SupportedLanguage.C: """#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TABLE_CAP 4096

int* twoSum(int* nums, int numsSize, int target, int* returnSize) {
    *returnSize = 2;
    int* result = (int*)malloc(2 * sizeof(int));
    int keys[TABLE_CAP];
    int vals[TABLE_CAP];
    char occupied[TABLE_CAP];
    memset(occupied, 0, sizeof(occupied));

    for (int i = 0; i < numsSize; i++) {
        int comp = target - nums[i];
        unsigned int h_comp = ((unsigned int)comp * 2654435761U) % TABLE_CAP;
        if (occupied[h_comp] && keys[h_comp] == comp) {
            result[0] = vals[h_comp];
            result[1] = i;
            return result;
        }

        unsigned int h_num = ((unsigned int)nums[i] * 2654435761U) % TABLE_CAP;
        keys[h_num] = nums[i];
        vals[h_num] = i;
        occupied[h_num] = 1;
    }

    *returnSize = 0;
    return NULL;
}
""",
        SupportedLanguage.CPP: """#include <vector>
#include <unordered_map>
using namespace std;

class Solution {
public:
    vector<int> twoSum(vector<int>& nums, int target) {
        unordered_map<int, int> seen;
        for (int i = 0; i < (int)nums.size(); ++i) {
            int comp = target - nums[i];
            if (seen.find(comp) != seen.end()) {
                return {seen[comp], i};
            }
            seen[nums[i]] = i;
        }
        return {};
    }
};
""",
        SupportedLanguage.JAVA: """import java.util.HashMap;
import java.util.Map;

class Solution {
    public int[] twoSum(int[] nums, int target) {
        Map<Integer, Integer> seen = new HashMap<>();
        for (int i = 0; i < nums.length; i++) {
            int comp = target - nums[i];
            if (seen.containsKey(comp)) {
                return new int[]{seen.get(comp), i};
            }
            seen.put(nums[i], i);
        }
        return new int[0];
    }
}
""",
        SupportedLanguage.PYTHON: """class Solution:
    def twoSum(self, nums, target):
        seen = {}
        for i, val in enumerate(nums):
            comp = target - val
            if comp in seen:
                return [seen[comp], i]
            seen[val] = i
        return []
""",
    },

    # 2. VALID PALINDROME (TWO POINTERS / STRING)
    "valid-palindrome": {
        SupportedLanguage.C: """#include <stdbool.h>
#include <ctype.h>
#include <string.h>

bool isPalindrome(char* s) {
    int left = 0;
    int right = strlen(s) - 1;
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
""",
        SupportedLanguage.CPP: """#include <string>
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
        SupportedLanguage.JAVA: """class Solution {
    public boolean isPalindrome(String s) {
        int left = 0;
        int right = s.length() - 1;
        while (left < right) {
            char cl = s.charAt(left);
            char cr = s.charAt(right);
            if (!Character.isLetterOrDigit(cl)) {
                left++;
            } else if (!Character.isLetterOrDigit(cr)) {
                right--;
            } else {
                if (Character.toLowerCase(cl) != Character.toLowerCase(cr)) {
                    return false;
                }
                left++;
                right--;
            }
        }
        return true;
    }
}
""",
        SupportedLanguage.PYTHON: """class Solution:
    def isPalindrome(self, s: str) -> bool:
        left, right = 0, len(s) - 1
        while left < right:
            if not s[left].isalnum():
                left += 1
            elif not s[right].isalnum():
                right -= 1
            else:
                if s[left].lower() != s[right].lower():
                    return False
                left += 1
                right -= 1
        return True
""",
    },

    # 3. BINARY SEARCH (BINARY SEARCH)
    "binary-search": {
        SupportedLanguage.C: """int search(int* nums, int numsSize, int target) {
    int left = 0;
    int right = numsSize - 1;
    while (left <= right) {
        int mid = left + (right - left) / 2;
        if (nums[mid] == target) return mid;
        if (nums[mid] < target) left = mid + 1;
        else right = mid - 1;
    }
    return -1;
}
""",
        SupportedLanguage.CPP: """#include <vector>
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
        SupportedLanguage.JAVA: """class Solution {
    public int search(int[] nums, int target) {
        int left = 0;
        int right = nums.length - 1;
        while (left <= right) {
            int mid = left + (right - left) / 2;
            if (nums[mid] == target) return mid;
            if (nums[mid] < target) left = mid + 1;
            else right = mid - 1;
        }
        return -1;
    }
}
""",
        SupportedLanguage.PYTHON: """class Solution:
    def search(self, nums, target):
        left, right = 0, len(nums) - 1
        while left <= right:
            mid = left + (right - left) // 2
            if nums[mid] == target:
                return mid
            elif nums[mid] < target:
                left = mid + 1
            else:
                right = mid - 1
        return -1
""",
    },

    # 4. MAXIMUM SUBARRAY (ARRAY / KADANE'S / DP)
    "max-subarray": {
        SupportedLanguage.C: """int maxSubArray(int* nums, int numsSize) {
    int max_so_far = nums[0];
    int curr_max = nums[0];
    for (int i = 1; i < numsSize; i++) {
        if (nums[i] > curr_max + nums[i]) {
            curr_max = nums[i];
        } else {
            curr_max = curr_max + nums[i];
        }
        if (curr_max > max_so_far) {
            max_so_far = curr_max;
        }
    }
    return max_so_far;
}
""",
        SupportedLanguage.CPP: """#include <vector>
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
        SupportedLanguage.JAVA: """class Solution {
    public int maxSubArray(int[] nums) {
        int maxSoFar = nums[0];
        int currMax = nums[0];
        for (int i = 1; i < nums.length; i++) {
            currMax = Math.max(nums[i], currMax + nums[i]);
            maxSoFar = Math.max(maxSoFar, currMax);
        }
        return maxSoFar;
    }
}
""",
        SupportedLanguage.PYTHON: """class Solution:
    def maxSubArray(self, nums):
        max_so_far = nums[0]
        curr_max = nums[0]
        for x in nums[1:]:
            curr_max = max(x, curr_max + x)
            max_so_far = max(max_so_far, curr_max)
        return max_so_far
""",
    },

    # 5. CLIMBING STAIRS (DYNAMIC PROGRAMMING)
    "climbing-stairs": {
        SupportedLanguage.C: """int climbStairs(int n) {
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
""",
        SupportedLanguage.CPP: """class Solution {
public:
    int climbStairs(int n) {
        if (n <= 2) return n;
        int first = 1, second = 2;
        for (int i = 3; i <= n; ++i) {
            int third = first + second;
            first = second;
            second = third;
        }
        return second;
    }
};
""",
        SupportedLanguage.JAVA: """class Solution {
    public int climbStairs(int n) {
        if (n <= 2) return n;
        int first = 1, second = 2;
        for (int i = 3; i <= n; ++i) {
            int third = first + second;
            first = second;
            second = third;
        }
        return second;
    }
}
""",
        SupportedLanguage.PYTHON: """class Solution:
    def climbStairs(self, n: int) -> int:
        if n <= 2:
            return n
        first, second = 1, 2
        for _ in range(3, n + 1):
            first, second = second, first + second
        return second
""",
    },

    # 6. VALID PARENTHESES (STACK)
    "valid-parentheses": {
        SupportedLanguage.C: """#include <stdbool.h>
#include <string.h>

bool isValid(char* s) {
    int len = strlen(s);
    char stack[10005];
    int top = -1;
    for (int i = 0; i < len; ++i) {
        char c = s[i];
        if (c == '(' || c == '{' || c == '[') {
            stack[++top] = c;
        } else {
            if (top < 0) return false;
            char t = stack[top--];
            if (c == ')' && t != '(') return false;
            if (c == '}' && t != '{') return false;
            if (c == ']' && t != '[') return false;
        }
    }
    return top == -1;
}
""",
        SupportedLanguage.CPP: """#include <string>
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
        SupportedLanguage.JAVA: """import java.util.ArrayDeque;
import java.util.Deque;

class Solution {
    public boolean isValid(String s) {
        Deque<Character> stack = new ArrayDeque<>();
        for (char c : s.toCharArray()) {
            if (c == '(' || c == '{' || c == '[') {
                stack.push(c);
            } else {
                if (stack.isEmpty()) return false;
                char top = stack.pop();
                if (c == ')' && top != '(') return false;
                if (c == '}' && top != '{') return false;
                if (c == ']' && top != '[') return false;
            }
        }
        return stack.isEmpty();
    }
}
""",
        SupportedLanguage.PYTHON: """class Solution:
    def isValid(self, s: str) -> bool:
        stack = []
        mapping = {")": "(", "}": "{", "]": "["}
        for char in s:
            if char in mapping:
                top = stack.pop() if stack else '#'
                if mapping[char] != top:
                    return False
            else:
                stack.append(char)
        return not stack
""",
    },

    # 7. BEST TIME TO BUY AND SELL STOCK (GREEDY)
    "best-time-to-buy-and-sell-stock": {
        SupportedLanguage.C: """int maxProfit(int* prices, int pricesSize) {
    if (pricesSize == 0) return 0;
    int min_price = prices[0];
    int max_profit = 0;
    for (int i = 1; i < pricesSize; ++i) {
        if (prices[i] < min_price) {
            min_price = prices[i];
        } else if (prices[i] - min_price > max_profit) {
            max_profit = prices[i] - min_price;
        }
    }
    return max_profit;
}
""",
        SupportedLanguage.CPP: """#include <vector>
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
        SupportedLanguage.JAVA: """class Solution {
    public int maxProfit(int[] prices) {
        if (prices.length == 0) return 0;
        int minPrice = prices[0];
        int maxProfit = 0;
        for (int i = 1; i < prices.length; i++) {
            if (prices[i] < minPrice) {
                minPrice = prices[i];
            } else if (prices[i] - minPrice > maxProfit) {
                maxProfit = prices[i] - minPrice;
            }
        }
        return maxProfit;
    }
}
""",
        SupportedLanguage.PYTHON: """class Solution:
    def maxProfit(self, prices):
        if not prices:
            return 0
        min_p = prices[0]
        max_p = 0
        for p in prices[1:]:
            if p < min_p:
                min_p = p
            elif p - min_p > max_p:
                max_p = p - min_p
        return max_p
""",
    },

    # 8. VALID ANAGRAM (STRING / HASHING)
    "valid-anagram": {
        SupportedLanguage.C: """#include <stdbool.h>
#include <string.h>

bool isAnagram(char* s, char* t) {
    if (strlen(s) != strlen(t)) return false;
    int counts[26] = {0};
    int len = strlen(s);
    for (int i = 0; i < len; ++i) {
        counts[s[i] - 'a']++;
        counts[t[i] - 'a']--;
    }
    for (int i = 0; i < 26; ++i) {
        if (counts[i] != 0) return false;
    }
    return true;
}
""",
        SupportedLanguage.CPP: """#include <string>
#include <vector>
using namespace std;

class Solution {
public:
    bool isAnagram(string s, string t) {
        if (s.length() != t.length()) return false;
        vector<int> counts(26, 0);
        for (char c : s) counts[c - 'a']++;
        for (char c : t) {
            counts[c - 'a']--;
            if (counts[c - 'a'] < 0) return false;
        }
        return true;
    }
};
""",
        SupportedLanguage.JAVA: """class Solution {
    public boolean isAnagram(String s, String t) {
        if (s.length() != t.length()) return false;
        int[] counts = new int[26];
        for (int i = 0; i < s.length(); i++) {
            counts[s.charAt(i) - 'a']++;
            counts[t.charAt(i) - 'a']--;
        }
        for (int c : counts) {
            if (c != 0) return false;
        }
        return true;
    }
}
""",
        SupportedLanguage.PYTHON: """class Solution:
    def isAnagram(self, s: str, t: str) -> bool:
        if len(s) != len(t):
            return False
        counts = [0] * 26
        for c in s:
            counts[ord(c) - ord('a')] += 1
        for c in t:
            counts[ord(c) - ord('a')] -= 1
            if counts[ord(c) - ord('a')] < 0:
                return False
        return True
""",
    },

    # 9. REVERSE LINKED LIST (LINKED LIST)
    "reverse-linked-list": {
        SupportedLanguage.C: """void reverseList(int* head, int headSize) {
    int left = 0;
    int right = headSize - 1;
    while (left < right) {
        int temp = head[left];
        head[left] = head[right];
        head[right] = temp;
        left++;
        right--;
    }
}
""",
        SupportedLanguage.CPP: """#include <vector>
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
        SupportedLanguage.JAVA: """class Solution {
    public int[] reverseList(int[] head) {
        int left = 0;
        int right = head.length - 1;
        while (left < right) {
            int temp = head[left];
            head[left] = head[right];
            head[right] = temp;
            left++;
            right--;
        }
        return head;
    }
}
""",
        SupportedLanguage.PYTHON: """class Solution:
    def reverseList(self, head):
        left, right = 0, len(head) - 1
        while left < right:
            head[left], head[right] = head[right], head[left]
            left += 1
            right -= 1
        return head
""",
    },
}

# Intentional flawed candidates across all 4 languages to verify self-correction
INTENTIONAL_FLAWS: Dict[Tuple[str, SupportedLanguage], Tuple[str, str]] = {
    # C flaw: binary search boundary infinite loop / wrong bounds
    ("binary-search", SupportedLanguage.C): (
        """int search(int* nums, int numsSize, int target) {
    // Intentional Flaw: while (left < right) with left = mid causes boundary failure
    int left = 0;
    int right = numsSize - 1;
    while (left < right) {
        int mid = (left + right) / 2;
        if (nums[mid] < target) left = mid;
        else right = mid;
    }
    return (left < numsSize && nums[left] == target) ? left : -1;
}
""",
        "EDGE_CASE_FAILURE",
    ),

    # C++ flaw: compile error with missing semicolon
    ("valid-parentheses", SupportedLanguage.CPP): (
        """#include <string>
#include <stack>
using namespace std;

class Solution {
public:
    bool isValid(string s) {
        // Intentional Flaw: missing semicolon after stack declaration
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
        "COMPILE_ERROR",
    ),

    # Java flaw: wrong answer returning constant wrong array
    ("two-sum", SupportedLanguage.JAVA): (
        """class Solution {
    public int[] twoSum(int[] nums, int target) {
        // Intentional Flaw: dummy wrong answer
        return new int[]{0, 0};
    }
}
""",
        "WRONG_ANSWER",
    ),

    # Python flaw: returns incorrect static indices [0, 0]
    ("two-sum", SupportedLanguage.PYTHON): (
        """class Solution:
    def twoSum(self, nums, target):
        # Intentional Flaw: dummy static return fails on test suite
        return [0, 0]
""",
        "WRONG_ANSWER",
    ),
}


class MultiLanguageBenchmarkRunner:
    """Executes multi-language DSA benchmarks across C, C++, Java, and Python."""

    def __init__(
        self,
        testing_engine: Optional[TestingEngine] = None,
        orchestrator: Optional[SelfCorrectionOrchestrator] = None,
    ):
        self.testing_engine = testing_engine or TestingEngine()
        self.planner = AlgorithmPlanner()
        self.verifier = SolutionVerifier(testing_engine=self.testing_engine)
        self.orchestrator = orchestrator or SelfCorrectionOrchestrator(
            planner=self.planner,
            testing_engine=self.testing_engine,
            max_attempts=3,
        )

    def run_problem_language(
        self,
        problem: BenchmarkProblem,
        language: SupportedLanguage,
        use_flawed: bool = False,
    ) -> BenchmarkResult:
        """Run a single problem in a specific language through the complete autonomous pipeline."""
        start_time = time.time()
        spec = to_problem_spec(problem)

        # 1. Pattern Classification (Language-Independent)
        detected_patterns = PatternClassifier.classify(spec)
        primary_pattern = detected_patterns[0].name if detected_patterns else "UNKNOWN"
        candidate_patterns = [p.name for p in detected_patterns]
        pattern_confidence = 1.0 if detected_patterns else 0.0

        # 2. Algorithm Planning (Language-Independent)
        plan = self.planner.plan(spec)
        selected_algorithm = plan.selected_approach.name if plan.selected_approach else "UNKNOWN"
        planned_time = plan.selected_approach.time_complexity if plan.selected_approach else "UNKNOWN"
        planned_space = plan.selected_approach.space_complexity if plan.selected_approach else "UNKNOWN"

        # 3. Source Code Selection
        flaw_info = INTENTIONAL_FLAWS.get((problem.id, language))
        if use_flawed and flaw_info:
            initial_code, initial_failure_category = flaw_info
        else:
            initial_code = MULTI_LANG_CODE.get(problem.id, {}).get(language, "")
            initial_failure_category = None

        repair_attempts = 0

        # 4. Execution & Verification / Self-Correction
        if use_flawed and flaw_info:
            session = self.orchestrator.solve(
                problem=spec,
                language=language,
                override_initial_code=initial_code,
            )
            repair_attempts = len(session.attempt_history)
            fully_certified = session.is_verified
            final_status = "PASSED" if session.is_verified else "FAILED"
            final_verification_status = session.final_state.value

            if session.verification_report:
                total_tests = session.verification_report.total_tests_run
                tests_passed = session.verification_report.tests_passed
                tests_failed = session.verification_report.tests_failed
                inferred_time = session.verification_report.complexity_audit.inferred_time_complexity if session.verification_report.complexity_audit else planned_time
                inferred_space = session.verification_report.complexity_audit.inferred_space_complexity if session.verification_report.complexity_audit else planned_space
                warnings = session.verification_report.warnings
            else:
                total_tests = session.attempt_history[-1].tests_passed + session.attempt_history[-1].tests_failed if session.attempt_history else 0
                tests_passed = session.attempt_history[-1].tests_passed if session.attempt_history else 0
                tests_failed = session.attempt_history[-1].tests_failed if session.attempt_history else 0
                inferred_time = planned_time
                inferred_space = planned_space
                warnings = [session.error_summary] if session.error_summary else []

            compile_status = "SUCCESS" if (session.is_verified or total_tests > 0) else "FAILED"
        else:
            test_report = self.testing_engine.evaluate_solution(
                problem=spec,
                solution_code=initial_code,
                language=language,
                expand_suite=True,
                include_stress=False,
            )
            compile_status = "SUCCESS" if test_report.execution_status == ExecutionStatus.SUCCESS else "FAILED"
            total_tests = test_report.total_tests
            tests_passed = test_report.passed_count
            tests_failed = test_report.failed_count

            final_report = self.verifier.verify_solution(
                problem=spec,
                source_code=initial_code,
                language=language,
                plan=plan,
                test_report=test_report,
            )
            final_verification_status = final_report.final_verification_status.value
            fully_certified = final_report.is_fully_certified
            final_status = "PASSED" if (tests_failed == 0 and total_tests > 0 and fully_certified) else "FAILED"
            inferred_time = final_report.complexity_audit.inferred_time_complexity if final_report.complexity_audit else "UNKNOWN"
            inferred_space = final_report.complexity_audit.inferred_space_complexity if final_report.complexity_audit else "UNKNOWN"
            warnings = final_report.warnings

        elapsed_ms = (time.time() - start_time) * 1000.0

        return BenchmarkResult(
            problem_id=problem.id,
            title=problem.title,
            category=problem.category.value,
            detected_pattern=primary_pattern,
            pattern_confidence=pattern_confidence,
            candidate_patterns=candidate_patterns,
            selected_algorithm=selected_algorithm,
            language=language.value,
            compile_status=compile_status,
            total_tests=total_tests,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            repair_attempts=repair_attempts,
            initial_failure_category=initial_failure_category,
            final_status=final_status,
            final_verification_status=final_verification_status,
            fully_certified=fully_certified,
            planned_time=planned_time,
            inferred_time=inferred_time,
            planned_space=planned_space,
            inferred_space=inferred_space,
            warnings=warnings,
            execution_time_ms=elapsed_ms,
        )

    def run_multi_language_matrix(
        self,
        four_lang_problems: Optional[List[str]] = None,
        flawed_targets: Optional[List[Tuple[str, SupportedLanguage]]] = None,
    ) -> List[BenchmarkResult]:
        """Runs the benchmark matrix across all 4 languages."""
        # 1. Representative problems to execute across ALL FOUR languages
        four_langs = four_lang_problems or [
            "two-sum",
            "valid-palindrome",
            "binary-search",
            "max-subarray",
        ]

        flaw_set = set(flawed_targets or [
            ("binary-search", SupportedLanguage.C),
            ("valid-parentheses", SupportedLanguage.CPP),
            ("two-sum", SupportedLanguage.JAVA),
            ("two-sum", SupportedLanguage.PYTHON),
        ])

        results: List[BenchmarkResult] = []

        # Run 4-language core matrix
        for pid in four_langs:
            prob = BENCHMARK_REGISTRY[pid]
            for lang in [SupportedLanguage.C, SupportedLanguage.CPP, SupportedLanguage.JAVA, SupportedLanguage.PYTHON]:
                is_flawed = (pid, lang) in flaw_set
                res = self.run_problem_language(prob, lang, use_flawed=is_flawed)
                results.append(res)

        # Run remaining problems in the registry across other categories (>= 9 categories total)
        additional_problems = [
            ("climbing-stairs", SupportedLanguage.JAVA),
            ("valid-parentheses", SupportedLanguage.CPP),
            ("best-time-to-buy-and-sell-stock", SupportedLanguage.PYTHON),
            ("valid-anagram", SupportedLanguage.C),
            ("reverse-linked-list", SupportedLanguage.PYTHON),
        ]
        for pid, lang in additional_problems:
            if (pid, lang) in flaw_set:
                is_flawed = True
            else:
                is_flawed = False
            prob = BENCHMARK_REGISTRY[pid]
            res = self.run_problem_language(prob, lang, use_flawed=is_flawed)
            results.append(res)

        return results


if __name__ == "__main__":
    runner = MultiLanguageBenchmarkRunner()
    print("Executing Multi-Language Cross-Verification Benchmark across C, C++, Java, Python...")
    results = runner.run_multi_language_matrix()

    print("\n" + "=" * 135)
    print(f"{'Problem':<30} | {'Lang':<7} | {'Category':<15} | {'Tests':<8} | {'Repairs':<7} | {'Compile':<8} | {'Cert':<5} | {'Status'}")
    print("=" * 135)
    
    matrix: Dict[str, Dict[str, str]] = {}
    total_passed = 0
    total_tests_all = 0
    total_tests_passed_all = 0
    total_tests_failed_all = 0
    total_repairs = 0

    for r in results:
        total_tests_all += r.total_tests
        total_tests_passed_all += r.tests_passed
        total_tests_failed_all += r.tests_failed
        total_repairs += r.repair_attempts
        if r.final_status == "PASSED":
            total_passed += 1

        if r.problem_id not in matrix:
            matrix[r.problem_id] = {}
        matrix[r.problem_id][r.language] = "PASS" if r.final_status == "PASSED" else "FAIL"

        cert_str = "YES" if r.fully_certified else "NO"
        test_str = f"{r.tests_passed}/{r.total_tests}"
        print(f"{r.problem_id:<30} | {r.language:<7} | {r.category:<15} | {test_str:<8} | {r.repair_attempts:<7} | {r.compile_status:<8} | {cert_str:<5} | {r.final_status}")

    print("=" * 135)
    print("\nCROSS-LANGUAGE EXECUTION MATRIX:")
    print(f"{'Problem':<30} | {'C':<6} | {'C++':<6} | {'Java':<6} | {'Python':<6}")
    print("-" * 60)
    for pid, langs in matrix.items():
        c_status = langs.get("c", "-")
        cpp_status = langs.get("cpp", "-")
        java_status = langs.get("java", "-")
        py_status = langs.get("python", "-")
        print(f"{pid:<30} | {c_status:<6} | {cpp_status:<6} | {java_status:<6} | {py_status:<6}")

    print("-" * 60)
    print(f"Summary: {total_passed}/{len(results)} Language Runs Passed. Total Tests: {total_tests_all} ({total_tests_passed_all} passed, {total_tests_failed_all} failed). Total Repairs: {total_repairs}.")
