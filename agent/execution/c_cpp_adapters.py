"""
Deterministic C and C++ Execution Adapters.
Compiles C (via gcc/clang/cl) and C++ (via g++/clang++/cl) into native binaries,
synthesizes deterministic test runners that output JSON markers, and captures exit codes/times.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional
from agent.core.models import (
    SupportedLanguage,
    ProblemSpec,
    TestCase,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
)
from agent.execution.base import BaseLanguageAdapter


class CppAdapter(BaseLanguageAdapter):
    """C++ execution adapter supporting GCC (g++), Clang (clang++), or MSVC (cl)."""

    def __init__(self, compiler_path: Optional[str] = None):
        if os.environ.get("DISABLE_CPP_TOOLCHAIN", "").lower() in ("1", "true", "yes"):
            self._compiler = None
        else:
            self._compiler = (
                compiler_path
                or os.environ.get("CPP_COMPILER_PATH")
                or shutil.which("g++")
                or shutil.which("clang++")
                or shutil.which("cl")
                or shutil.which(r"C:\msys64\ucrt64\bin\g++.exe")
                or shutil.which(r"C:\msys64\mingw64\bin\g++.exe")
            )

    @property
    def language(self) -> SupportedLanguage:
        return SupportedLanguage.CPP

    @property
    def source_extension(self) -> str:
        return ".cpp"

    def is_toolchain_available(self) -> bool:
        return self._compiler is not None

    def generate_harness(
        self,
        problem: ProblemSpec,
        solution_code: str,
        test_cases: List[TestCase],
    ) -> str:
        """
        Synthesizes C++ harness with standard STL includes and JSON results printer.
        """
        def cpp_val(v):
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, int):
                return str(v)
            if isinstance(v, str):
                escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                return f'string("{escaped}")'
            if isinstance(v, (list, tuple)):
                if not v:
                    return "{}"
                inner = ", ".join(cpp_val(x) for x in v)
                return f"{{{inner}}}"
            return str(v)

        def cpp_type(v):
            if isinstance(v, bool):
                return "bool"
            if isinstance(v, int):
                return "int"
            if isinstance(v, str):
                return "string"
            if isinstance(v, (list, tuple)):
                if not v:
                    return "vector<int>"
                inner_type = cpp_type(v[0])
                return f"vector<{inner_type}>"
            return "auto"

        def cpp_print_json(var_name, v):
            if isinstance(v, bool):
                return f'results_stream << ({var_name} ? "true" : "false");'
            if isinstance(v, (int, float)):
                return f'results_stream << {var_name};'
            if isinstance(v, str):
                return f'results_stream << "\\"" << {var_name} << "\\"";'
            if isinstance(v, (list, tuple)):
                if not v or not isinstance(v[0], (list, tuple)):
                    return f'''results_stream << "[";
        for (size_t _k = 0; _k < {var_name}.size(); ++_k) {{
            if (_k > 0) results_stream << ",";
            results_stream << {var_name}[_k];
        }}
        results_stream << "]";'''
                else:
                    return f'''results_stream << "[";
        for (size_t _i = 0; _i < {var_name}.size(); ++_i) {{
            if (_i > 0) results_stream << ",";
            results_stream << "[";
            for (size_t _j = 0; _j < {var_name}[_i].size(); ++_j) {{
                if (_j > 0) results_stream << ",";
                results_stream << {var_name}[_i][_j];
            }}
            results_stream << "]";
        }}
        results_stream << "]";'''
            return f'results_stream << "null";'

        tests_code = []
        for tc in test_cases:
            tc_id = tc.id
            inputs = tc.inputs
            expected = tc.expected_output

            # Construct arg declarations and call
            decl_lines = []
            call_args = []
            for p in problem.param_names:
                if p in inputs:
                    val = inputs[p]
                    v_type = cpp_type(val)
                    v_lit = cpp_val(val)
                    decl_lines.append(f"        {v_type} {p} = {v_lit};")
                    call_args.append(p)
                else:
                    call_args.append("{}")

            arg_decls = "\n".join(decl_lines)
            fn_call_str = f"sol.{problem.function_name}({', '.join(call_args)})"
            exp_type = cpp_type(expected)
            exp_lit = cpp_val(expected)

            print_exp = cpp_print_json("expected", expected)
            print_act = cpp_print_json("actual", expected)
            print_act = print_act.replace("expected", "actual")

            test_block = f"""
    {{
{arg_decls}
        {exp_type} expected = {exp_lit};
        {exp_type} actual = {fn_call_str};

        bool passed = (actual == expected);
        if (!passed) all_passed = false;

        if (!first_result) results_stream << ",";
        first_result = false;
        results_stream << "{{\\"test_case_id\\": \\"{tc_id}\\", \\"passed\\": " << (passed ? "true" : "false")
             << ", \\"input_data\\": {{}}, "
             << "\\"expected_output\\": ";
        {print_exp}
        results_stream << ", \\"actual_output\\": ";
        {print_act}
        results_stream << ", \\"error_message\\": null, \\"execution_time_ms\\": 0}}";
    }}
"""
            tests_code.append(test_block)

        all_tests = "\n".join(tests_code)

        harness_template = """#include <iostream>
#include <vector>
#include <string>
#include <sstream>
#include <algorithm>

using namespace std;

// --- User Solution Begin ---
{solution_code}
// --- User Solution End ---

int main() {
    Solution sol;
    bool all_passed = true;
    bool first_result = true;
    stringstream results_stream;

    // Run tests
{all_tests}

    cout << "<<<EXECUTION_RESULTS_START>>>" << endl;
    cout << "{\\"all_passed\\": " << (all_passed ? "true" : "false")
         << ", \\"results\\": [" << results_stream.str() << "]}" << endl;
    cout << "<<<EXECUTION_RESULTS_END>>>" << endl;

    return all_passed ? 0 : 1;
}
"""
        return harness_template.replace("{solution_code}", solution_code).replace("{all_tests}", all_tests)


    def compile(self, source_path: Path, output_dir: Path) -> Optional[ExecutionResult]:
        if not self.is_toolchain_available():
            return ExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                error_detail="C++ compiler (g++, clang++, or cl) not found in system PATH.",
            )

        binary_path = output_dir / ("harness.exe" if os.name == "nt" else "harness")
        start_time = time.perf_counter()

        cmd = [self._compiler, "-std=c++17", "-static", "-O2", str(source_path), "-o", str(binary_path)]
        env = os.environ.copy()
        if self._compiler:
            compiler_dir = str(Path(self._compiler).parent)
            env["PATH"] = compiler_dir + os.pathsep + env.get("PATH", "")
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(output_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10.0,
                env=env,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            if proc.returncode != 0:
                return ExecutionResult(
                    status=ExecutionStatus.COMPILE_ERROR,
                    failure_category=FailureCategory.COMPILE_ERROR,
                    exit_code=proc.returncode,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    compile_output=proc.stderr.strip() or proc.stdout.strip(),
                    execution_time_ms=elapsed_ms,
                    error_detail=f"C++ compilation failed:\n{proc.stderr.strip()}",
                )
            return None
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT,
                failure_category=FailureCategory.TIME_LIMIT_EXCEEDED,
                error_detail="C++ compilation timed out after 10 seconds.",
            )
        except Exception as e:
            return ExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                error_detail=f"Failed to invoke C++ compiler: {str(e)}",
            )

    def get_run_command(self, source_or_binary_path: Path, output_dir: Path) -> List[str]:
        binary_path = output_dir / ("harness.exe" if os.name == "nt" else "harness")
        return [str(binary_path)]


class CAdapter(BaseLanguageAdapter):
    """C execution adapter supporting GCC, Clang, or MSVC."""

    def __init__(self, compiler_path: Optional[str] = None):
        if os.environ.get("DISABLE_C_TOOLCHAIN", "").lower() in ("1", "true", "yes"):
            self._compiler = None
        else:
            self._compiler = (
                compiler_path
                or os.environ.get("C_COMPILER_PATH")
                or shutil.which("gcc")
                or shutil.which("clang")
                or shutil.which("cl")
                or shutil.which(r"C:\msys64\ucrt64\bin\gcc.exe")
                or shutil.which(r"C:\msys64\mingw64\bin\gcc.exe")
            )


    @property
    def language(self) -> SupportedLanguage:
        return SupportedLanguage.C

    @property
    def source_extension(self) -> str:
        return ".c"

    def is_toolchain_available(self) -> bool:
        return self._compiler is not None

    def generate_harness(
        self,
        problem: ProblemSpec,
        solution_code: str,
        test_cases: List[TestCase],
    ) -> str:
        """
        Synthesizes standard C11 harness with standard headers and JSON results printer.
        """
        def c_val(v):
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, int):
                return str(v)
            if isinstance(v, str):
                escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                return f'"{escaped}"'
            if isinstance(v, (list, tuple)):
                if not v:
                    return "{0}"
                inner = ", ".join(c_val(x) for x in v)
                return f"{{{inner}}}"
            return str(v)

        tests_code = []
        for tc_idx, tc in enumerate(test_cases):
            tc_id = tc.id
            inputs = tc.inputs
            expected = tc.expected_output

            # Check return type
            is_arr_ret = isinstance(expected, (list, tuple))
            is_str_ret = isinstance(expected, str)
            is_bool_ret = isinstance(expected, bool)

            # Generate inputs
            decl_lines = []
            call_args = []
            for p in problem.param_names:
                if p in inputs:
                    val = inputs[p]
                    if isinstance(val, (list, tuple)):
                        arr_len = len(val)
                        decl_lines.append(f"        int {p}_arr[] = {c_val(val)};")
                        decl_lines.append(f"        int {p}_size = {arr_len};")
                        call_args.append(f"{p}_arr")
                        # If problem function signature accepts size parameter right after array or as explicit param
                        # We check if param_names contains size or if function takes array
                    elif isinstance(val, str):
                        decl_lines.append(f'        char* {p} = "{val}";')
                        call_args.append(p)
                    elif isinstance(val, bool):
                        decl_lines.append(f"        bool {p} = {c_val(val)};")
                        call_args.append(p)
                    else:
                        decl_lines.append(f"        int {p} = {c_val(val)};")
                        call_args.append(p)

            # If the C function takes array size parameter(s) and/or returnSize
            # Check function signature style:
            # 1) twoSum(int* nums, int numsSize, int target, int* returnSize)
            # 2) maxSubArray(int* nums, int numsSize)
            # 3) search(int* nums, int numsSize, int target)
            # 4) climbStairs(int n)
            # 5) isPalindrome(char* s)
            # 6) isValid(char* s)
            # 7) isAnagram(char* s, char* t)
            # 8) maxProfit(int* prices, int pricesSize)
            # 9) lengthOfLongestSubstring(char* s)
            fn_call_str = ""
            comp_block = ""
            print_block = ""

            if problem.function_name == "twoSum":
                decl_lines.append("        int returnSize = 0;")
                call_str = f"twoSum(nums_arr, nums_size, target, &returnSize)"
                exp_len = len(expected)
                comp_block = f"""
        int* actual = {call_str};
        bool passed = (actual != NULL && returnSize == {exp_len});
        if (passed) {{
            int exp_arr[] = {c_val(expected)};
            for (int _i = 0; _i < {exp_len}; ++_i) {{
                if (actual[_i] != exp_arr[_i]) {{ passed = false; break; }}
            }}
        }}
        if (!passed) all_passed = false;
"""
                print_block = f"""
        printf("{{\\"test_case_id\\": \\"{tc_id}\\", \\"passed\\": %s, \\"input_data\\": {{}}, ", passed ? "true" : "false");
        printf("\\"expected_output\\": [%s], ", "{", ".join(map(str, expected))}");
        if (actual != NULL && returnSize > 0) {{
            printf("\\"actual_output\\": [");
            for (int _k = 0; _k < returnSize; ++_k) {{
                if (_k > 0) printf(",");
                printf("%d", actual[_k]);
            }}
            printf("], ");
        }} else {{
            printf("\\"actual_output\\": null, ");
        }}
        printf("\\"error_message\\": null, \\"execution_time_ms\\": 0}}");
        if (actual != NULL) free(actual);
"""
            elif problem.function_name in ("maxSubArray", "maxProfit"):
                arr_p = problem.param_names[0]
                call_str = f"{problem.function_name}({arr_p}_arr, {arr_p}_size)"
                comp_block = f"""
        int expected = {c_val(expected)};
        int actual = {call_str};
        bool passed = (actual == expected);
        if (!passed) all_passed = false;
"""
                print_block = f"""
        printf("{{\\"test_case_id\\": \\"{tc_id}\\", \\"passed\\": %s, \\"input_data\\": {{}}, ", passed ? "true" : "false");
        printf("\\"expected_output\\": %d, \\"actual_output\\": %d, \\"error_message\\": null, \\"execution_time_ms\\": 0}}", expected, actual);
"""
            elif problem.function_name == "search":
                # binary search: search(int* nums, int numsSize, int target)
                call_str = f"search(nums_arr, nums_size, target)"
                comp_block = f"""
        int expected = {c_val(expected)};
        int actual = {call_str};
        bool passed = (actual == expected);
        if (!passed) all_passed = false;
"""
                print_block = f"""
        printf("{{\\"test_case_id\\": \\"{tc_id}\\", \\"passed\\": %s, \\"input_data\\": {{}}, ", passed ? "true" : "false");
        printf("\\"expected_output\\": %d, \\"actual_output\\": %d, \\"error_message\\": null, \\"execution_time_ms\\": 0}}", expected, actual);
"""
            elif problem.function_name in ("isPalindrome", "isValid", "isAnagram"):
                args = ", ".join(problem.param_names)
                call_str = f"{problem.function_name}({args})"
                comp_block = f"""
        bool expected = {c_val(expected)};
        bool actual = {call_str};
        bool passed = (actual == expected);
        if (!passed) all_passed = false;
"""
                print_block = f"""
        printf("{{\\"test_case_id\\": \\"{tc_id}\\", \\"passed\\": %s, \\"input_data\\": {{}}, ", passed ? "true" : "false");
        printf("\\"expected_output\\": %s, \\"actual_output\\": %s, \\"error_message\\": null, \\"execution_time_ms\\": 0}}", expected ? "true" : "false", actual ? "true" : "false");
"""
            elif problem.function_name in ("climbStairs", "lengthOfLongestSubstring", "maxDepth"):
                if problem.function_name == "climbStairs":
                    call_str = f"climbStairs(n)"
                elif problem.function_name == "lengthOfLongestSubstring":
                    call_str = f"lengthOfLongestSubstring(s)"
                else:
                    arr_p = problem.param_names[0]
                    call_str = f"maxDepth({arr_p}_arr, {arr_p}_size)"
                comp_block = f"""
        int expected = {c_val(expected)};
        int actual = {call_str};
        bool passed = (actual == expected);
        if (!passed) all_passed = false;
"""
                print_block = f"""
        printf("{{\\"test_case_id\\": \\"{tc_id}\\", \\"passed\\": %s, \\"input_data\\": {{}}, ", passed ? "true" : "false");
        printf("\\"expected_output\\": %d, \\"actual_output\\": %d, \\"error_message\\": null, \\"execution_time_ms\\": 0}}", expected, actual);
"""
            elif problem.function_name == "moveZeroes":
                arr_p = problem.param_names[0]
                decl_lines.append("        int returnSize = 0;")
                call_str = f"moveZeroes({arr_p}_arr, {arr_p}_size, &returnSize)"
                exp_len = len(expected)
                comp_block = f"""
        int* actual = {call_str};
        bool passed = (actual != NULL);
        if (passed) {{
            int exp_arr[] = {c_val(expected)};
            for (int _i = 0; _i < {exp_len}; ++_i) {{
                if (actual[_i] != exp_arr[_i]) {{ passed = false; break; }}
            }}
        }}
        if (!passed) all_passed = false;
"""
                print_block = f"""
        printf("{{\\"test_case_id\\": \\"{tc_id}\\", \\"passed\\": %s, \\"input_data\\": {{}}, ", passed ? "true" : "false");
        printf("\\"expected_output\\": [%s], ", "{", ".join(map(str, expected))}");
        if (actual != NULL) {{
            printf("\\"actual_output\\": [");
            for (int _k = 0; _k < {arr_p}_size; ++_k) {{
                if (_k > 0) printf(",");
                printf("%d", actual[_k]);
            }}
            printf("], ");
        }} else {{
            printf("\\"actual_output\\": null, ");
        }}
        printf("\\"error_message\\": null, \\"execution_time_ms\\": 0}}");
"""
            elif problem.function_name == "reverseList":
                arr_p = problem.param_names[0]
                call_str = f"reverseList({arr_p}_arr, {arr_p}_size)"
                exp_len = len(expected)
                comp_block = f"""
        {call_str};
        bool passed = true;
        int exp_arr[] = {c_val(expected)};
        for (int _i = 0; _i < {arr_p}_size; ++_i) {{
            if ({arr_p}_arr[_i] != exp_arr[_i]) {{ passed = false; break; }}
        }}
        if (!passed) all_passed = false;
"""
                print_block = f"""
        printf("{{\\"test_case_id\\": \\"{tc_id}\\", \\"passed\\": %s, \\"input_data\\": {{}}, ", passed ? "true" : "false");
        printf("\\"expected_output\\": [%s], \\"actual_output\\": [", "{", ".join(map(str, expected))}");
        for (int _k = 0; _k < {arr_p}_size; ++_k) {{
            if (_k > 0) printf(",");
            printf("%d", {arr_p}_arr[_k]);
        }}
        printf("], \\"error_message\\": null, \\"execution_time_ms\\": 0}}");
"""
            else:
                # Generic fallback invocation
                args_str = ", ".join(call_args)
                call_str = f"{problem.function_name}({args_str})"
                comp_block = f"""
        int expected = {c_val(expected) if isinstance(expected, int) else 0};
        int actual = {call_str};
        bool passed = (actual == expected);
        if (!passed) all_passed = false;
"""
                print_block = f"""
        printf("{{\\"test_case_id\\": \\"{tc_id}\\", \\"passed\\": %s, \\"input_data\\": {{}}, \\"expected_output\\": %d, \\"actual_output\\": %d, \\"error_message\\": null, \\"execution_time_ms\\": 0}}", passed ? "true" : "false", expected, actual);
"""

            arg_decls = "\n".join(decl_lines)
            test_block = f"""
    {{
{arg_decls}
{comp_block}
        if (!first_result) printf(",");
        first_result = false;
{print_block}
    }}
"""
            tests_code.append(test_block)

        all_tests = "\n".join(tests_code)

        harness_source = f"""#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <ctype.h>

// --- User Solution Begin ---
{solution_code}
// --- User Solution End ---

int main() {{
    bool all_passed = true;
    bool first_result = true;

    printf("<<<EXECUTION_RESULTS_START>>>\\n");
    printf("{{\\"all_passed\\": ");

    // Run tests
    printf("%s", "["); // placeholder - we will print all_passed at the end or print stream
    // Actually we need to capture or buffer the tests or print them cleanly.
    // In C, print results array:
{all_tests}
    printf("]}}\\n");
    printf("<<<EXECUTION_RESULTS_END>>>\\n");

    return all_passed ? 0 : 1;
}}
"""
        # Fix json formatting:
        # Instead of printing in the middle of all_passed, let's structure main() cleanly:
        harness_source = f"""#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <ctype.h>

// --- User Solution Begin ---
{solution_code}
// --- User Solution End ---

int main() {{
    bool all_passed = true;
    bool first_result = true;

    printf("<<<EXECUTION_RESULTS_START>>>\\n");
    printf("{{\\"results\\": [");

{all_tests}

    printf("], \\"all_passed\\": %s}}\\n", all_passed ? "true" : "false");
    printf("<<<EXECUTION_RESULTS_END>>>\\n");

    return all_passed ? 0 : 1;
}}
"""
        return harness_source

    def compile(self, source_path: Path, output_dir: Path) -> Optional[ExecutionResult]:
        if not self.is_toolchain_available():
            return ExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                error_detail="C compiler (gcc, clang, or cl) not found in system PATH.",
            )

        binary_path = output_dir / ("harness.exe" if os.name == "nt" else "harness")
        cmd = [self._compiler, "-std=c11", "-static", "-O2", str(source_path), "-o", str(binary_path)]
        env = os.environ.copy()
        if self._compiler:
            compiler_dir = str(Path(self._compiler).parent)
            env["PATH"] = compiler_dir + os.pathsep + env.get("PATH", "")
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(output_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10.0,
                env=env,
            )
            if proc.returncode != 0:
                return ExecutionResult(
                    status=ExecutionStatus.COMPILE_ERROR,
                    failure_category=FailureCategory.COMPILE_ERROR,
                    exit_code=proc.returncode,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    compile_output=proc.stderr.strip() or proc.stdout.strip(),
                    error_detail=f"C compilation failed:\n{proc.stderr.strip()}",
                )
            return None
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT,
                failure_category=FailureCategory.TIME_LIMIT_EXCEEDED,
                error_detail="C compilation timed out after 10 seconds.",
            )
        except Exception as e:
            return ExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                error_detail=f"Failed to invoke C compiler: {str(e)}",
            )

    def get_run_command(self, source_or_binary_path: Path, output_dir: Path) -> List[str]:
        binary_path = output_dir / ("harness.exe" if os.name == "nt" else "harness")
        return [str(binary_path)]
