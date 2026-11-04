import os
import shutil
from typing import Any, Dict, Optional


def _find_executable(names: list[str]) -> Optional[str]:
    # 1. Standard PATH lookup
    for name in names:
        p = shutil.which(name)
        if p and os.path.isfile(p):
            return p

    # 2. Well-known MSYS2 / MinGW / LLVM search locations on Windows
    fallback_dirs = [
        r"C:\msys64\ucrt64\bin",
        r"C:\msys64\mingw64\bin",
        r"C:\msys64\clang64\bin",
        r"C:\MinGW\bin",
        r"C:\Program Files\LLVM\bin",
    ]
    for d in fallback_dirs:
        for name in names:
            full = os.path.join(d, name if name.endswith(".exe") else f"{name}.exe")
            if os.path.isfile(full):
                # Ensure the directory is added to os.environ['PATH'] so dependencies (dlls) are found
                if d not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                return full
    return None


class LanguageSupport:
    """Detects available compilers and execution runtimes for supported programming languages."""

    SUPPORTED_LANGUAGES = ["python", "c", "cpp", "java"]

    @classmethod
    def normalize_language(cls, lang: Optional[str]) -> str:
        if not lang or not isinstance(lang, str):
            return "python"
        l = lang.strip().lower()
        if l in ["py", "python", "python3"]:
            return "python"
        if l in ["c"]:
            return "c"
        if l in ["cpp", "c++"]:
            return "cpp"
        if l in ["java"]:
            return "java"
        return l

    @classmethod
    def get_compiler_info(cls, lang: str) -> Dict[str, Any]:
        norm_lang = cls.normalize_language(lang)
        if norm_lang == "python":
            py_bin = _find_executable(["python", "python3"])
            return {"available": bool(py_bin), "binary": py_bin, "compiler": None}

        if norm_lang == "c":
            c_comp = _find_executable(["gcc", "clang", "cl", "tcc"])
            return {"available": bool(c_comp), "binary": None, "compiler": c_comp}

        if norm_lang == "cpp":
            cpp_comp = _find_executable(["g++", "clang++", "cl"])
            return {"available": bool(cpp_comp), "binary": None, "compiler": cpp_comp}

        if norm_lang == "java":
            javac = _find_executable(["javac"])
            java = _find_executable(["java"])
            is_avail = bool(javac and java)
            return {"available": is_avail, "binary": java, "compiler": javac}

        return {"available": False, "binary": None, "compiler": None}

    @classmethod
    def get_all_status(cls) -> Dict[str, Dict[str, Any]]:
        status = {}
        for l in cls.SUPPORTED_LANGUAGES:
            status[l] = cls.get_compiler_info(l)
        return status
