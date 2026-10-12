"""
Tests for Code Generation and Deterministic Static AST/Security Validation (Stage 5).
Verifies:
1. Valid Python solution generation and AST validation.
2. Valid C solution generation and static validation.
3. Valid C++ solution generation and static validation.
4. Valid Java solution generation and static validation.
5. Syntax-invalid generated code detection.
6. Python dangerous operation detection (import os/subprocess, eval, open).
7. C/C++ dangerous system/process/socket operation detection.
8. Java dangerous ProcessBuilder / Runtime / Socket operation detection.
9. Code that is syntactically valid but algorithmically incorrect (valid AST, but wrong logic).
10. Indirect AST-detectable prohibited operations (e.g. __import__, eval).
11. Valid solution using standard library data structures is NOT falsely rejected.
"""

from agent.core.models import (
    AlgorithmPlan,
    CandidateApproach,
    DSAPattern,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
)
from agent.generation.generator import CodeGenerator
from agent.generation.validator import CodeValidator


def sample_plan() -> AlgorithmPlan:
    return AlgorithmPlan(
        problem_id="two-sum",
        identified_patterns=[DSAPattern.HASH_TABLE],
        candidate_approaches=[
            CandidateApproach(
                name="Single-Pass Hash Map",
                data_structures=["Hash Map / Dict"],
                time_complexity="O(N)",
                space_complexity="O(N)",
                description="Hash map stores seen values to indices.",
                satisfies_constraints=True,
            )
        ],
        selected_approach=CandidateApproach(
            name="Single-Pass Hash Map",
            data_structures=["Hash Map / Dict"],
            time_complexity="O(N)",
            space_complexity="O(N)",
            description="Hash map stores seen values to indices.",
            satisfies_constraints=True,
        ),
        justification="Optimal O(N) time and space.",
        constraints_validated=True,
    )


def sample_problem() -> ProblemSpec:
    return ProblemSpec(
        id="two-sum",
        title="Two Sum",
        description="Return indices of two numbers that add up to target.",
        constraints=["2 <= nums.length <= 10^4"],
        function_name="twoSum",
        param_names=["nums", "target"],
        return_type="List[int]",
        test_cases=[TestCase(id="1", inputs={"nums": [2, 7, 11, 15], "target": 9}, expected_output=[0, 1])],
    )


# 1. Valid Python Solution
def test_1_valid_python_solution():
    gen = CodeGenerator()
    res = gen.generate(sample_problem(), sample_plan(), SupportedLanguage.PYTHON)
    assert res.target_language == SupportedLanguage.PYTHON
    assert res.validation_result.is_valid is True
    assert res.validation_result.has_syntax_error is False
    assert res.validation_result.has_security_violation is False
    assert res.validation_result.ast_tree_verified is True
    assert "class Solution" in res.source_code


# 2. Valid C Solution
def test_2_valid_c_solution():
    gen = CodeGenerator()
    res = gen.generate(sample_problem(), sample_plan(), SupportedLanguage.C)
    assert res.target_language == SupportedLanguage.C
    assert res.validation_result.is_valid is True
    assert res.validation_result.has_syntax_error is False
    assert res.validation_result.has_security_violation is False


# 3. Valid C++ Solution
def test_3_valid_cpp_solution():
    gen = CodeGenerator()
    res = gen.generate(sample_problem(), sample_plan(), SupportedLanguage.CPP)
    assert res.target_language == SupportedLanguage.CPP
    assert res.validation_result.is_valid is True
    assert res.validation_result.has_syntax_error is False
    assert res.validation_result.has_security_violation is False


# 4. Valid Java Solution
def test_4_valid_java_solution():
    gen = CodeGenerator()
    res = gen.generate(sample_problem(), sample_plan(), SupportedLanguage.JAVA)
    assert res.target_language == SupportedLanguage.JAVA
    assert res.validation_result.is_valid is True
    assert res.validation_result.has_syntax_error is False
    assert res.validation_result.has_security_violation is False


# 5. Syntax-Invalid Generated Code
def test_5_syntax_invalid_code():
    bad_py = "class Solution:\n    def twoSum(self, nums, target)\n        return []"
    val = CodeValidator.validate(bad_py, SupportedLanguage.PYTHON)
    assert val.is_valid is False
    assert val.has_syntax_error is True
    assert any("syntaxerror" in d.lower() for d in val.violation_details)

    bad_cpp = "class Solution { void foo() { return 0; "  # Missing closing brace
    val_cpp = CodeValidator.validate(bad_cpp, SupportedLanguage.CPP)
    assert val_cpp.is_valid is False
    assert val_cpp.has_syntax_error is True


# 6. Python Dangerous Operations (os, subprocess, eval, open)
def test_6_python_dangerous_operations():
    # Import os
    py_os = "import os\nclass Solution:\n    def solve(self):\n        os.system('whoami')"
    val1 = CodeValidator.validate(py_os, SupportedLanguage.PYTHON)
    assert val1.is_valid is False
    assert val1.has_security_violation is True
    assert any("forbidden import 'os'" in d.lower() for d in val1.violation_details)

    # eval call
    py_eval = "class Solution:\n    def solve(self, expr):\n        return eval(expr)"
    val2 = CodeValidator.validate(py_eval, SupportedLanguage.PYTHON)
    assert val2.is_valid is False
    assert val2.has_security_violation is True
    assert any("forbidden function call 'eval()'" in d.lower() for d in val2.violation_details)

    # file open
    py_open = "class Solution:\n    def solve(self):\n        with open('secrets.txt', 'r') as f: pass"
    val3 = CodeValidator.validate(py_open, SupportedLanguage.PYTHON)
    assert val3.is_valid is False
    assert val3.has_security_violation is True


# 7. C/C++ Dangerous Operations (system, socket, fork, windows.h)
def test_7_cpp_dangerous_operations():
    cpp_sys = """
    #include <cstdlib>
    class Solution {
    public:
        void hack() {
            system("calc.exe");
        }
    };
    """
    val = CodeValidator.validate(cpp_sys, SupportedLanguage.CPP)
    assert val.is_valid is False
    assert val.has_security_violation is True
    assert any("system" in d.lower() for d in val.violation_details)

    cpp_sock = """
    #include <sys/socket.h>
    class Solution {};
    """
    val_sock = CodeValidator.validate(cpp_sock, SupportedLanguage.CPP)
    assert val_sock.is_valid is False
    assert any("prohibited header" in d.lower() for d in val_sock.violation_details)


# 8. Java Dangerous Operations (ProcessBuilder, Runtime, Socket)
def test_8_java_dangerous_operations():
    java_proc = """
    class Solution {
        public void runCmd() throws Exception {
            new ProcessBuilder("notepad.exe").start();
        }
    }
    """
    val = CodeValidator.validate(java_proc, SupportedLanguage.JAVA)
    assert val.is_valid is False
    assert val.has_security_violation is True
    assert any("processbuilder" in d.lower() for d in val.violation_details)

    java_imp = """
    import java.io.FileOutputStream;
    class Solution {}
    """
    val_imp = CodeValidator.validate(java_imp, SupportedLanguage.JAVA)
    assert val_imp.is_valid is False
    assert any("prohibited java import" in d.lower() for d in val_imp.violation_details)


# 9. Code that is Syntactically Valid but Algorithmically Wrong
def test_9_syntactically_valid_but_algorithmically_wrong():
    """
    Verifies that AST validation confirms syntactic validity and security without
    confusing syntactic health with algorithmic correctness.
    """
    wrong_code = """
class Solution:
    def twoSum(self, nums, target):
        # Always returns empty list (algorithmically wrong for Two Sum)
        return []
"""
    val = CodeValidator.validate(wrong_code, SupportedLanguage.PYTHON)
    # The AST validator MUST pass it (it is safe and syntax-valid)
    assert val.is_valid is True
    assert val.has_syntax_error is False
    assert val.has_security_violation is False


# 10. Indirect AST-Detectable Mechanisms
def test_10_indirect_prohibited_mechanisms():
    py_indirect = """
class Solution:
    def solve(self):
        fn = getattr(__builtins__, "eval")
        return fn("1 + 1")
"""
    val = CodeValidator.validate(py_indirect, SupportedLanguage.PYTHON)
    assert val.is_valid is False
    assert val.has_security_violation is True


# 11. Valid Standard Library Solutions NOT Falsely Rejected
def test_11_standard_library_not_falsely_rejected():
    py_stdlib = """
import collections
import heapq
import math

class Solution:
    def solve(self, nums):
        dq = collections.deque(nums)
        heap = []
        heapq.heappush(heap, 42)
        val = math.isqrt(16)
        return [dq.popleft(), heap[0], val]
"""
    val = CodeValidator.validate(py_stdlib, SupportedLanguage.PYTHON)
    assert val.is_valid is True
    assert val.has_security_violation is False
    assert val.has_syntax_error is False
