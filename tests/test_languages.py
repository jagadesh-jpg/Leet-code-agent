import pytest
from adapters import UnifiedJudge, PythonLanguageAdapter, CLanguageAdapter, CppLanguageAdapter, JavaLanguageAdapter
from languages import LanguageSupport


def test_language_normalization():
    assert LanguageSupport.normalize_language("python3") == "python"
    assert LanguageSupport.normalize_language("Python") == "python"
    assert LanguageSupport.normalize_language("c++") == "cpp"
    assert LanguageSupport.normalize_language("CPP") == "cpp"
    assert LanguageSupport.normalize_language("Java") == "java"
    assert LanguageSupport.normalize_language("C") == "c"


def test_python_adapter_runs_code():
    adapter = PythonLanguageAdapter()
    assert adapter.is_available() is True
    prob = {
        "id": "test-add",
        "function_name": "add",
        "tests": [{"input": [2, 3], "expected": 5}]
    }
    code = "def add(a, b): return a + b"
    res = adapter.run_solution(code, prob)
    assert res["status"] == "passed"
    assert res["passed_count"] == 1


def test_c_adapter_availability_and_handling():
    adapter = CLanguageAdapter()
    info = adapter.get_runtime_info()
    prob = {"id": "test-c", "tests": [{"input": [1], "expected": 1}]}
    if not adapter.is_available():
        res = adapter.run_solution("int main() { return 0; }", prob)
        assert res["status"] == "runtime_unavailable"
        assert "not installed" in res["error"]
    else:
        assert info["available"] is True


def test_cpp_adapter_availability_and_handling():
    adapter = CppLanguageAdapter()
    info = adapter.get_runtime_info()
    prob = {"id": "test-cpp", "tests": [{"input": [1], "expected": 1}]}
    if not adapter.is_available():
        res = adapter.run_solution("int main() { return 0; }", prob)
        assert res["status"] == "runtime_unavailable"
        assert "not installed" in res["error"]
    else:
        assert info["available"] is True


def test_java_adapter_compile_and_execution():
    adapter = JavaLanguageAdapter()
    if not adapter.is_available():
        pytest.skip("Java compiler/runtime (javac/java) is not installed on this system.")

    prob = {
        "id": "test-java-compile",
        "function_name": "twoSum",
        "tests": [{"input": [[2, 7], 9], "expected": [0, 1]}]
    }

    # Test compilation error handling
    bad_code = "class Solution { invalid syntax }"
    bad_res = adapter.run_solution(bad_code, prob)
    assert bad_res["status"] == "compile_error"
    assert bad_res["passed_count"] == 0

    # Test valid Java compilation
    valid_code = "class Solution { public int[] twoSum(int[] nums, int target) { return new int[]{0, 1}; } }"
    good_res = adapter.run_solution(valid_code, prob)
    assert good_res["status"] == "passed"

