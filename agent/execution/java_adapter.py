"""
Deterministic Java Execution Adapter.
Compiles Java solution using javac, synthesizes SolutionHarness.java,
executes via java with memory and security constraints, and parses structured output.
"""

import json
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


class JavaAdapter(BaseLanguageAdapter):
    """Java 8+ execution adapter using javac and java."""

    def __init__(self, javac_path: Optional[str] = None, java_path: Optional[str] = None):
        self._javac_path = javac_path or shutil.which("javac")
        self._java_path = java_path or shutil.which("java")

    @property
    def language(self) -> SupportedLanguage:
        return SupportedLanguage.JAVA

    @property
    def source_extension(self) -> str:
        return ".java"

    def is_toolchain_available(self) -> bool:
        return (self._javac_path is not None) and (self._java_path is not None)

    def generate_harness(
        self,
        problem: ProblemSpec,
        solution_code: str,
        test_cases: List[TestCase],
    ) -> str:
        """
        Synthesizes SolutionHarness.java wrapping the user's Solution class.
        Captures execution times, catches exceptions per test case, and serializes
        results in JSON between <<<EXECUTION_RESULTS_START>>> markers.
        """
        def java_lit(v):
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, int):
                return str(v)
            if isinstance(v, str):
                escaped = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                return f'"{escaped}"'
            if isinstance(v, (list, tuple)):
                if not v:
                    return "{}"
                if isinstance(v[0], (list, tuple)):
                    rows = ", ".join("{" + ", ".join(java_lit(x) for x in row) + "}" for row in v)
                    return f"{{{rows}}}"
                return "{" + ", ".join(java_lit(x) for x in v) + "}"
            return str(v)

        def java_type(v):
            if isinstance(v, bool):
                return "boolean"
            if isinstance(v, int):
                return "int"
            if isinstance(v, str):
                return "String"
            if isinstance(v, (list, tuple)):
                if not v:
                    return "int[]"
                if isinstance(v[0], (list, tuple)):
                    return "int[][]"
                return "int[]"
            return "Object"

        # Build individual test case execution blocks
        tests_code = []
        for tc in test_cases:
            tc_id = tc.id
            inputs = tc.inputs
            expected = tc.expected_output

            decl_lines = []
            call_args = []
            for p in problem.param_names:
                if p in inputs:
                    val = inputs[p]
                    j_type = java_type(val)
                    j_val = java_lit(val)
                    if isinstance(val, (list, tuple)):
                        decl_lines.append(f"                {j_type} {p} = new {j_type}{j_val};")
                    else:
                        decl_lines.append(f"                {j_type} {p} = {j_val};")
                    call_args.append(p)
                else:
                    call_args.append("null")

            arg_decls = "\n".join(decl_lines)
            fn_call = f"sol.{problem.function_name}({', '.join(call_args)})"
            exp_type = java_type(expected)
            exp_lit = java_lit(expected)

            if isinstance(expected, (list, tuple)):
                if expected and isinstance(expected[0], (list, tuple)):
                    exp_decl = f"                {exp_type} expected = new {exp_type}{exp_lit};"
                    comp = "java.util.Arrays.deepEquals(actual, expected)"
                    exp_fmt = 'java.util.Arrays.deepToString(expected).replace("\\"", "\\\\\\\"")'
                    act_fmt = 'java.util.Arrays.deepToString(actual).replace("\\"", "\\\\\\\"")'
                else:
                    exp_decl = f"                {exp_type} expected = new {exp_type}{exp_lit};"
                    comp = "java.util.Arrays.equals(actual, expected)"
                    exp_fmt = 'java.util.Arrays.toString(expected).replace("\\"", "\\\\\\\"")'
                    act_fmt = 'java.util.Arrays.toString(actual).replace("\\"", "\\\\\\\"")'
            elif isinstance(expected, str):
                exp_decl = f"                String expected = {exp_lit};"
                comp = "expected.equals(actual)"
                exp_fmt = '"\\"" + expected + "\\""'
                act_fmt = '(actual != null ? "\\"" + actual + "\\"" : "null")'
            else:
                exp_decl = f"                {exp_type} expected = {exp_lit};"
                comp = "(actual == expected)"
                exp_fmt = 'String.valueOf(expected)'
                act_fmt = 'String.valueOf(actual)'

            test_block = f"""
        {{
            long start = System.nanoTime();
            try {{
{arg_decls}
{exp_decl}
                {exp_type} actual = {fn_call};
                long elapsed = (System.nanoTime() - start) / 1000000;
                
                boolean passed = {comp};
                if (!passed) allPassed = false;
                
                sb.append("{{\\"test_case_id\\": \\"{tc_id}\\", \\"passed\\": " + passed + 
                          ", \\"input_data\\": {{}}, " +
                          "\\"expected_output\\": " + {exp_fmt} + ", " +
                          "\\"actual_output\\": " + {act_fmt} + ", " +
                          "\\"error_message\\": null, \\"execution_time_ms\\": " + elapsed + "}},");
            }} catch (Throwable t) {{
                allPassed = false;
                long elapsed = (System.nanoTime() - start) / 1000000;
                sb.append("{{\\"test_case_id\\": \\"{tc_id}\\", \\"passed\\": false, " +
                          "\\"input_data\\": {{}}, \\"expected_output\\": null, \\"actual_output\\": null, " +
                          "\\"error_message\\": \\"" + t.getClass().getSimpleName() + ": " + (t.getMessage() != null ? t.getMessage().replace("\\"", "\\\\\\"") : "") + "\\", " +
                          "\\"execution_time_ms\\": " + elapsed + "}},");
            }}
        }}
"""
            tests_code.append(test_block)

        all_tests_str = "\n".join(tests_code)

        harness_source = f"""// Auto-generated Java Test Harness
import java.util.*;

// --- User Solution Begin ---
{solution_code}
// --- User Solution End ---

class SolutionHarness {{
    public static void main(String[] args) {{
        Solution sol = new Solution();
        StringBuilder sb = new StringBuilder();
        boolean allPassed = true;

{all_tests_str}

        String resultsJson = sb.toString();
        if (resultsJson.endsWith(",")) {{
            resultsJson = resultsJson.substring(0, resultsJson.length() - 1);
        }}

        System.out.println("<<<EXECUTION_RESULTS_START>>>");
        System.out.println("{{\\"all_passed\\": " + allPassed + ", \\"results\\": [" + resultsJson + "]}}");
        System.out.println("<<<EXECUTION_RESULTS_END>>>");

        if (!allPassed) {{
            System.exit(1);
        }}
        System.exit(0);
    }}
}}
"""
        return harness_source

    def compile(self, source_path: Path, output_dir: Path) -> Optional[ExecutionResult]:
        if not self.is_toolchain_available():
            return ExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                error_detail="Java compiler (javac) not found in system PATH.",
            )

        start_time = time.perf_counter()
        try:
            # javac SolutionHarness.java
            proc = subprocess.run(
                [self._javac_path, str(source_path)],
                cwd=str(output_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10.0,
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
                    error_detail=f"Java compilation failed:\n{proc.stderr.strip()}",
                )
            return None
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT,
                failure_category=FailureCategory.TIME_LIMIT_EXCEEDED,
                error_detail="Java compilation timed out after 10 seconds.",
            )
        except Exception as e:
            return ExecutionResult(
                status=ExecutionStatus.INFRASTRUCTURE_ERROR,
                failure_category=FailureCategory.ENVIRONMENT_ERROR,
                error_detail=f"Failed to invoke javac: {str(e)}",
            )

    def get_run_command(self, source_or_binary_path: Path, output_dir: Path) -> List[str]:
        # -Xmx256m: Restrict heap memory to 256MB
        # -cp .: Classpath set to isolated temp dir
        return [self._java_path, "-Xmx256m", "-cp", str(output_dir), "SolutionHarness"]
