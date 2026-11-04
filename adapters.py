import abc
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional


from languages import LanguageSupport, _find_executable


def normalize_nested(obj: Any) -> Any:
    if isinstance(obj, list):
        normalized = [normalize_nested(item) for item in obj]
        try:
            return sorted(normalized)
        except TypeError:
            return sorted(normalized, key=lambda x: str(x))
    return obj


class BaseLanguageAdapter(abc.ABC):
    @abc.abstractmethod
    def language_name(self) -> str:
        pass

    @abc.abstractmethod
    def is_available(self) -> bool:
        pass

    @abc.abstractmethod
    def get_runtime_info(self) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    def run_solution(self, code: str, problem: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
        pass


class PythonLanguageAdapter(BaseLanguageAdapter):
    def language_name(self) -> str:
        return "python"

    def is_available(self) -> bool:
        return bool(_find_executable(["python", "python3"]))

    def get_runtime_info(self) -> Dict[str, Any]:
        return {
            "available": True,
            "runtime": sys.executable,
            "version": sys.version.split()[0],
        }

    def run_solution(self, code: str, problem: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
        from judge import run_solution as py_run_solution
        return py_run_solution(code, problem, timeout=timeout)


class CLanguageAdapter(BaseLanguageAdapter):
    def language_name(self) -> str:
        return "c"

    def is_available(self) -> bool:
        return bool(_find_executable(["gcc", "clang", "cl", "tcc"]))

    def get_runtime_info(self) -> Dict[str, Any]:
        comp = _find_executable(["gcc", "clang", "cl", "tcc"])
        return {
            "available": bool(comp),
            "compiler": comp,
            "type": "C"
        }

    def run_solution(self, code: str, problem: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
        total_tests = len(problem.get("tests", []))
        compiler = _find_executable(["gcc", "clang", "cl", "tcc"])
        if not compiler:
            return {
                "status": "runtime_unavailable",
                "passed_count": 0,
                "total": total_tests,
                "failure": None,
                "error": "C compiler (gcc, clang, cl, or tcc) is not installed or available on PATH.",
            }

        if not code or not code.strip():
            return {
                "status": "no_code",
                "passed_count": 0,
                "total": total_tests,
                "failure": None,
                "error": "No executable C code provided.",
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            src_file = os.path.join(tmpdir, "solution.c")
            exe_file = os.path.join(tmpdir, "solution.exe" if os.name == "nt" else "solution")

            # Check if code already contains main or needs problem harness
            if "main(" in code:
                full_c_code = code
            else:
                from harness import build_c_runner
                full_c_code = build_c_runner(code, problem)

            with open(src_file, "w", encoding="utf-8") as f:
                f.write(full_c_code)

            if not compiler.lower().endswith("cl.exe"):
                compile_cmd = [compiler, "solution.c", "-O2", "-o", exe_file]
            else:  # cl.exe (MSVC)
                compile_cmd = [compiler, "/Fe:" + exe_file, "solution.c"]

            comp_res = subprocess.run(
                compile_cmd,
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if comp_res.returncode != 0:
                return {
                    "status": "compile_error",
                    "passed_count": 0,
                    "total": total_tests,
                    "failure": None,
                    "error": (comp_res.stderr or comp_res.stdout or "Compilation failed")[:1500],
                }

            run_res = subprocess.run(
                [exe_file],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if run_res.returncode != 0:
                return {
                    "status": "runtime_error",
                    "passed_count": 0,
                    "total": total_tests,
                    "failure": None,
                    "error": (run_res.stderr or run_res.stdout or f"Process exited with {run_res.returncode}")[:1500],
                }

            return {
                "status": "passed",
                "passed_count": total_tests,
                "total": total_tests,
                "stdout": run_res.stdout,
                "stderr": run_res.stderr,
                "failure": None,
                "error": None,
            }


class CppLanguageAdapter(BaseLanguageAdapter):
    def language_name(self) -> str:
        return "cpp"

    def is_available(self) -> bool:
        return bool(_find_executable(["g++", "clang++", "cl"]))

    def get_runtime_info(self) -> Dict[str, Any]:
        comp = _find_executable(["g++", "clang++", "cl"])
        return {
            "available": bool(comp),
            "compiler": comp,
            "type": "C++"
        }

    def run_solution(self, code: str, problem: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
        total_tests = len(problem.get("tests", []))
        compiler = _find_executable(["g++", "clang++", "cl"])
        if not compiler:
            return {
                "status": "runtime_unavailable",
                "passed_count": 0,
                "total": total_tests,
                "failure": None,
                "error": "C++ compiler (g++, clang++, or cl) is not installed or available on PATH.",
            }

        if not code or not code.strip():
            return {
                "status": "no_code",
                "passed_count": 0,
                "total": total_tests,
                "failure": None,
                "error": "No executable C++ code provided.",
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            src_file = os.path.join(tmpdir, "solution.cpp")
            exe_file = os.path.join(tmpdir, "solution.exe" if os.name == "nt" else "solution")

            # Check if code already contains main or needs problem harness
            if "main(" in code:
                full_cpp_code = code
            else:
                from harness import build_cpp_runner
                full_cpp_code = build_cpp_runner(code, problem)

            with open(src_file, "w", encoding="utf-8") as f:
                f.write(full_cpp_code)

            if not compiler.lower().endswith("cl.exe"):
                compile_cmd = [compiler, "-std=c++17", "solution.cpp", "-O2", "-o", exe_file]
            else:  # cl.exe (MSVC)
                compile_cmd = [compiler, "/std:c++17", "/Fe:" + exe_file, "solution.cpp"]

            comp_res = subprocess.run(
                compile_cmd,
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if comp_res.returncode != 0:
                return {
                    "status": "compile_error",
                    "passed_count": 0,
                    "total": total_tests,
                    "failure": None,
                    "error": (comp_res.stderr or comp_res.stdout or "Compilation failed")[:1500],
                }

            run_res = subprocess.run(
                [exe_file],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if run_res.returncode != 0:
                return {
                    "status": "runtime_error",
                    "passed_count": 0,
                    "total": total_tests,
                    "failure": None,
                    "error": (run_res.stderr or run_res.stdout or f"Process exited with {run_res.returncode}")[:1500],
                }

            return {
                "status": "passed",
                "passed_count": total_tests,
                "total": total_tests,
                "stdout": run_res.stdout,
                "stderr": run_res.stderr,
                "failure": None,
                "error": None,
            }


class JavaLanguageAdapter(BaseLanguageAdapter):
    def language_name(self) -> str:
        return "java"

    def is_available(self) -> bool:
        return bool(_find_executable(["javac"]) and _find_executable(["java"]))

    def get_runtime_info(self) -> Dict[str, Any]:
        javac = _find_executable(["javac"])
        java = _find_executable(["java"])
        return {
            "available": bool(javac and java),
            "compiler": javac,
            "runtime": java,
        }

    def run_solution(self, code: str, problem: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
        total_tests = len(problem.get("tests", []))
        javac = _find_executable(["javac"])
        java = _find_executable(["java"])
        if not (javac and java):
            return {
                "status": "runtime_unavailable",
                "passed_count": 0,
                "total": total_tests,
                "failure": None,
                "error": "Java compiler (javac) or runtime (java) is not installed or available on PATH.",
            }

        if not code or not code.strip():
            return {
                "status": "no_code",
                "passed_count": 0,
                "total": total_tests,
                "failure": None,
                "error": "No executable code provided.",
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            src_file = os.path.join(tmpdir, "Solution.java")

            # Check if code already contains main or needs problem harness
            if "class TestRunner" in code or "main(" in code:
                full_java_code = code
                runner_class = "Solution" if "main(" in code else "TestRunner"
            else:
                from harness import build_java_runner
                full_java_code = build_java_runner(code, problem)
                runner_class = "TestRunner"

            with open(src_file, "w", encoding="utf-8") as f:
                f.write(full_java_code)

            # Compile
            javac_cmd = [javac, "Solution.java"]
            comp_res = subprocess.run(
                javac_cmd,
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if comp_res.returncode != 0:
                return {
                    "status": "compile_error",
                    "passed_count": 0,
                    "total": total_tests,
                    "failure": None,
                    "error": (comp_res.stderr or comp_res.stdout or "Compilation failed")[:1500],
                }

            # Execute test harness
            run_cmd = [java, "-cp", ".", runner_class]
            run_res = subprocess.run(
                run_cmd,
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if run_res.returncode != 0:
                return {
                    "status": "runtime_error",
                    "passed_count": 0,
                    "total": total_tests,
                    "failure": None,
                    "error": (run_res.stderr or run_res.stdout or f"Process exited with {run_res.returncode}")[:1500],
                }

            return {
                "status": "passed",
                "passed_count": total_tests,
                "total": total_tests,
                "stdout": run_res.stdout,
                "stderr": run_res.stderr,
                "failure": None,
                "error": None,
            }


class UnifiedJudge:
    """Unified multi-language test judge routing code to the appropriate language adapter."""

    _ADAPTERS: Dict[str, BaseLanguageAdapter] = {
        "python": PythonLanguageAdapter(),
        "c": CLanguageAdapter(),
        "cpp": CppLanguageAdapter(),
        "java": JavaLanguageAdapter(),
    }

    @classmethod
    def get_adapter(cls, language: Optional[str] = "python") -> BaseLanguageAdapter:
        from languages import LanguageSupport
        norm_lang = LanguageSupport.normalize_language(language)
        if norm_lang not in cls._ADAPTERS:
            norm_lang = "python"
        return cls._ADAPTERS[norm_lang]

    @classmethod
    def run_solution(
        cls,
        code: str,
        problem: Dict[str, Any],
        language: str = "python",
        timeout: int = 10,
    ) -> Dict[str, Any]:
        adapter = cls.get_adapter(language)
        return adapter.run_solution(code, problem, timeout=timeout)

