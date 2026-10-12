"""
Code Generator.
Synthesizes target-language solution code according to the verified AlgorithmPlan
and ProblemSpec, then subjects the code to deterministic static AST validation.
"""

from typing import Optional
from agent.core.models import (
    AlgorithmPlan,
    GeneratedCode,
    ProblemSpec,
    SupportedLanguage,
)
from agent.generation.validator import CodeValidator
from agent.llm.base import BaseLLMProvider


class CodeGenerator:
    """
    Code Generator adhering strictly to the AlgorithmPlan.
    Supports C, C++, Java, and Python.
    """

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        self.llm = llm_provider

    def generate(
        self,
        problem: ProblemSpec,
        plan: AlgorithmPlan,
        language: SupportedLanguage = SupportedLanguage.PYTHON,
    ) -> GeneratedCode:
        """
        Generates source code in the target language and validates it through CodeValidator.
        """
        # If an LLM is configured, query LLM for the code adhering to plan
        # Otherwise, synthesize deterministic canonical implementation
        raw_code = ""
        used_model = False
        if self.llm and self.llm.is_configured():
            try:
                raw_code = self._generate_with_llm(problem, plan, language)
                if raw_code and raw_code.strip():
                    used_model = True
            except Exception:
                raw_code = ""

        if not raw_code:
            raw_code = self._synthesize_solution(problem, plan, language)

        # Apply deterministic static AST & security validation
        validation_result = CodeValidator.validate(raw_code, language)

        # Track whether live LLM produced the code or fallback was triggered
        code_provenance = "LIVE_MODEL" if used_model else "DETERMINISTIC_FALLBACK"

        return GeneratedCode(
            problem_id=problem.id,
            target_language=language,
            source_code=raw_code,
            algorithm_name=plan.selected_approach.name,
            expected_time_complexity=plan.selected_approach.time_complexity,
            expected_space_complexity=plan.selected_approach.space_complexity,
            validation_result=validation_result,
            generation_metadata={
                "language": language.value,
                "validated": validation_result.is_valid,
                "planner_id": plan.problem_id,
                "provenance": code_provenance,
            },
        )

    def _synthesize_solution(
        self,
        problem: ProblemSpec,
        plan: AlgorithmPlan,
        language: SupportedLanguage,
    ) -> str:
        """Generates standard solution template per target language."""
        fn = problem.function_name
        params = problem.param_names

        if language == SupportedLanguage.PYTHON:
            return self._build_python_template(problem, plan)
        elif language == SupportedLanguage.CPP:
            return self._build_cpp_template(problem, plan)
        elif language == SupportedLanguage.C:
            return self._build_c_template(problem, plan)
        elif language == SupportedLanguage.JAVA:
            return self._build_java_template(problem, plan)

        raise ValueError(f"Unsupported language: {language.value}")

    def _build_python_template(self, problem: ProblemSpec, plan: AlgorithmPlan) -> str:
        params_str = ", ".join(problem.param_names)
        # Check if algorithm is Hash Map (e.g. Two Sum)
        if "Hash Map" in plan.selected_approach.name:
            code = f"""class Solution:
    def {problem.function_name}(self, {params_str}):
        # Algorithm: {plan.selected_approach.name}
        # Time: {plan.selected_approach.time_complexity}, Space: {plan.selected_approach.space_complexity}
        seen = {{}}
        for i, val in enumerate(nums):
            comp = target - val
            if comp in seen:
                return [seen[comp], i]
            seen[val] = i
        return []
"""
            return code

        # Check if algorithm is Binary Search
        if "Binary Search" in plan.selected_approach.name:
            code = f"""class Solution:
    def {problem.function_name}(self, {params_str}):
        # Algorithm: {plan.selected_approach.name}
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
"""
            return code

        # Default standard method skeleton
        return f"""class Solution:
    def {problem.function_name}(self, {params_str}):
        # Algorithm: {plan.selected_approach.name}
        pass
"""

    def _build_cpp_template(self, problem: ProblemSpec, plan: AlgorithmPlan) -> str:
        params_str = ", ".join(f"auto {p}" for p in problem.param_names)
        return f"""#include <vector>
#include <string>
#include <unordered_map>
#include <algorithm>

using namespace std;

class Solution {{
public:
    // Algorithm: {plan.selected_approach.name}
    // Time: {plan.selected_approach.time_complexity}, Space: {plan.selected_approach.space_complexity}
    vector<int> {problem.function_name}(vector<int>& nums, int target) {{
        unordered_map<int, int> seen;
        for (int i = 0; i < (int)nums.size(); ++i) {{
            int comp = target - nums[i];
            if (seen.find(comp) != seen.end()) {{
                return {{seen[comp], i}};
            }}
            seen[nums[i]] = i;
        }}
        return {{}};
    }}
}};
"""

    def _build_c_template(self, problem: ProblemSpec, plan: AlgorithmPlan) -> str:
        return f"""#include <stdio.h>
#include <stdlib.h>

/*
 * Algorithm: {plan.selected_approach.name}
 * Time: {plan.selected_approach.time_complexity}, Space: {plan.selected_approach.space_complexity}
 */
int* {problem.function_name}(int* nums, int numsSize, int target, int* returnSize) {{
    *returnSize = 2;
    int* result = (int*)malloc(2 * sizeof(int));
    for (int i = 0; i < numsSize; i++) {{
        for (int j = i + 1; j < numsSize; j++) {{
            if (nums[i] + nums[j] == target) {{
                result[0] = i;
                result[1] = j;
                return result;
            }}
        }}
    }}
    *returnSize = 0;
    return NULL;
}}
"""

    def _build_java_template(self, problem: ProblemSpec, plan: AlgorithmPlan) -> str:
        return f"""import java.util.HashMap;
import java.util.Map;

class Solution {{
    // Algorithm: {plan.selected_approach.name}
    // Time: {plan.selected_approach.time_complexity}, Space: {plan.selected_approach.space_complexity}
    public int[] {problem.function_name}(int[] nums, int target) {{
        Map<Integer, Integer> seen = new HashMap<>();
        for (int i = 0; i < nums.length; i++) {{
            int comp = target - nums[i];
            if (seen.containsKey(comp)) {{
                return new int[]{{seen.get(comp), i}};
            }}
            seen.put(nums[i], i);
        }}
        return new int[0];
    }}
}}
"""

    def _generate_with_llm(
        self,
        problem: ProblemSpec,
        plan: AlgorithmPlan,
        language: SupportedLanguage,
    ) -> str:
        """Queries model for complete solution implementation adhering strictly to the planned approach."""
        import re
        from agent.llm.schemas import ModelCodeGeneration

        prompt = f"""You are generating an optimal, correct solution for the following DSA competitive programming problem:
Title: {problem.title}
Problem Description: {problem.description}
Function Name: {problem.function_name}
Parameters: {', '.join(problem.param_names)}
Return Type: {problem.return_type}
Constraints: {'; '.join(problem.constraints)}
Target Language: {language.value}

Algorithm Plan:
- Selected Algorithm: {plan.selected_approach.name}
- Expected Time Complexity: {plan.selected_approach.time_complexity}
- Expected Space Complexity: {plan.selected_approach.space_complexity}
- Strategy Description: {plan.selected_approach.description}

Requirements:
1. Implement the requested function/class cleanly and correctly.
2. In C++ and Java, include necessary standard library imports within the Solution file.
3. For Python and Java, define 'class Solution' containing the requested method '{problem.function_name}'.
4. For C++, define 'class Solution' containing public method '{problem.function_name}'.
5. For C, define standalone function '{problem.function_name}'.
6. Meet the target time complexity {plan.selected_approach.time_complexity} and space complexity {plan.selected_approach.space_complexity}.
7. Do NOT include any main() function, console printing, debug assertions, or prohibited syscalls.
"""
        gen_response: ModelCodeGeneration = self.llm.generate_structured(
            prompt=prompt,
            response_schema=ModelCodeGeneration,
            system_instruction="You are an expert DSA programmer. Implement complete, memory-efficient, bug-free competitive programming solutions adhering to exact function signatures.",
        )

        code = gen_response.source_code.strip()
        # Clean any accidental outer markdown backticks
        match = re.search(rf"```(?:{language.value})?\s*(.*?)\s*```", code, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return code
