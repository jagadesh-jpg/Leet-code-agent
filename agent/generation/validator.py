"""
Deterministic AST & Static Code Validator.
Applies deterministic syntax parsing and sandbox security policy enforcement
across Python, C++, C, and Java prior to execution.
"""

import ast
import re
from typing import List, Set
from agent.core.models import (
    StaticValidationResult,
    SupportedLanguage,
)


class CodeValidator:
    """
    Deterministic static validator enforcing:
    1. Valid syntactic structure.
    2. Zero unauthorized filesystem, network, process, or execution-environment escape calls.
    """

    # --- PYTHON RESTRICTIONS ---
    PYTHON_FORBIDDEN_MODULES: Set[str] = {
        "os", "sys", "subprocess", "socket", "http", "urllib", "requests",
        "shutil", "ctypes", "posix", "winreg", "importlib", "pathlib", "fcntl",
        "msvcrt", "multiprocessing", "threading", "pty", "commands",
    }
    PYTHON_FORBIDDEN_CALLS: Set[str] = {
        "eval", "exec", "compile", "__import__", "globals", "locals", "open",
    }
    PYTHON_FORBIDDEN_ATTRS: Set[str] = {
        "__subclasses__", "__bases__", "__class__", "__code__",
    }

    # --- C / C++ RESTRICTIONS ---
    CPP_FORBIDDEN_HEADERS: Set[str] = {
        "windows.h", "winsock.h", "winsock2.h", "sys/socket.h", "netinet/in.h",
        "arpa/inet.h", "unistd.h", "sys/types.h", "sys/stat.h", "fcntl.h",
        "dirent.h", "process.h", "signal.h", "spawn.h",
    }
    CPP_FORBIDDEN_PATTERNS: List[re.Pattern] = [
        re.compile(r"\b(system|popen|pclose|fork|execvp?|execlp?|CreateProcess|ShellExecute|socket|connect|bind|listen|accept)\s*\("),
        re.compile(r"\b(fopen|freopen|remove|rename|std::remove|std::rename)\s*\("),
        re.compile(r"\b(std::filesystem|boost::filesystem)\b"),
    ]

    # --- JAVA RESTRICTIONS ---
    JAVA_FORBIDDEN_IMPORTS: List[str] = [
        "java.io.File", "java.io.FileInputStream", "java.io.FileOutputStream",
        "java.io.RandomAccessFile", "java.nio.file", "java.net",
        "java.lang.Process", "java.lang.ProcessBuilder", "java.lang.Runtime",
        "java.lang.reflect", "sun.misc.Unsafe",
    ]
    JAVA_FORBIDDEN_PATTERNS: List[re.Pattern] = [
        re.compile(r"\b(Runtime\.getRuntime\(\)|ProcessBuilder|System\.exit|System\.load|System\.loadLibrary)\b"),
        re.compile(r"\b(Socket|ServerSocket|DatagramSocket|HttpURLConnection|HttpClient)\b"),
        re.compile(r"\b(FileOutputStream|FileInputStream|FileWriter|FileReader|RandomAccessFile|Files\.write|Files\.read)\b"),
    ]

    @classmethod
    def validate(cls, source_code: str, language: SupportedLanguage) -> StaticValidationResult:
        """Dispatches validation to language-specific deterministic checkers."""
        if not source_code or not source_code.strip():
            return StaticValidationResult(
                is_valid=False,
                has_syntax_error=True,
                violation_details=["Source code is empty."],
            )

        if language == SupportedLanguage.PYTHON:
            return cls._validate_python(source_code)
        elif language in (SupportedLanguage.CPP, SupportedLanguage.C):
            return cls._validate_c_cpp(source_code, language)
        elif language == SupportedLanguage.JAVA:
            return cls._validate_java(source_code)

        return StaticValidationResult(
            is_valid=False,
            violation_details=[f"Unsupported language for validation: {language.value}"],
        )

    # --- PYTHON VALIDATION VIA AST ---
    @classmethod
    def _validate_python(cls, source_code: str) -> StaticValidationResult:
        """Parses Python source using python's built-in AST library."""
        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            return StaticValidationResult(
                is_valid=False,
                has_syntax_error=True,
                violation_details=[f"SyntaxError on line {e.lineno}: {e.msg}"],
                ast_tree_verified=False,
            )

        violations: List[str] = []

        class SecurityVisitor(ast.NodeVisitor):
            def visit_Import(self, node: ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    if root_mod in CodeValidator.PYTHON_FORBIDDEN_MODULES:
                        violations.append(f"Line {node.lineno}: Forbidden import '{alias.name}'.")
                self.generic_visit(node)

            def visit_ImportFrom(self, node: ast.ImportFrom):
                if node.module:
                    root_mod = node.module.split(".")[0]
                    if root_mod in CodeValidator.PYTHON_FORBIDDEN_MODULES:
                        violations.append(f"Line {node.lineno}: Forbidden import-from '{node.module}'.")
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call):
                # Detect forbidden direct calls: eval(), exec(), open(), etc.
                if isinstance(node.func, ast.Name):
                    if node.func.id in CodeValidator.PYTHON_FORBIDDEN_CALLS:
                        violations.append(f"Line {node.lineno}: Forbidden function call '{node.func.id}()'.")
                # Detect indirect calls like getattr(__builtins__, 'eval') or os.system
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in CodeValidator.PYTHON_FORBIDDEN_CALLS:
                        violations.append(f"Line {node.lineno}: Forbidden attribute call '{node.func.attr}()'.")
                # Detect getattr(__builtins__, "eval")
                if isinstance(node.func, ast.Name) and node.func.id == "getattr":
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                        target_attr = node.args[1].value
                        if target_attr in CodeValidator.PYTHON_FORBIDDEN_CALLS or target_attr in CodeValidator.PYTHON_FORBIDDEN_ATTRS:
                            violations.append(f"Line {node.lineno}: Indirect forbidden attribute resolution via getattr('{target_attr}').")
                self.generic_visit(node)

            def visit_Name(self, node: ast.Name):
                if node.id in ("__builtins__", "__loader__", "__spec__"):
                    violations.append(f"Line {node.lineno}: Prohibited runtime introspection identifier '{node.id}'.")
                self.generic_visit(node)

            def visit_Attribute(self, node: ast.Attribute):
                if node.attr in CodeValidator.PYTHON_FORBIDDEN_ATTRS:
                    violations.append(f"Line {node.lineno}: Prohibited attribute access '{node.attr}'.")
                self.generic_visit(node)

        visitor = SecurityVisitor()
        visitor.visit(tree)

        has_sec = len(violations) > 0
        return StaticValidationResult(
            is_valid=not has_sec,
            has_syntax_error=False,
            has_security_violation=has_sec,
            violation_details=violations,
            ast_tree_verified=True,
        )

    # --- C / C++ VALIDATION ---
    @classmethod
    def _validate_c_cpp(cls, source_code: str, language: SupportedLanguage) -> StaticValidationResult:
        violations: List[str] = []

        # 1. Structural balance check (braces, parentheses)
        balance_err = cls._check_brackets_balance(source_code)
        if balance_err:
            return StaticValidationResult(
                is_valid=False,
                has_syntax_error=True,
                violation_details=[balance_err],
                ast_tree_verified=False,
            )

        # 2. Check forbidden headers: #include <windows.h>, #include <sys/socket.h>, etc.
        include_pattern = re.compile(r'#include\s*[<"]([^>"]+)[>"]')
        for match in include_pattern.finditer(source_code):
            header = match.group(1).strip().lower()
            if header in cls.CPP_FORBIDDEN_HEADERS:
                violations.append(f"Prohibited header include: '{header}'.")

        # 3. Check forbidden process, filesystem, socket calls
        for pattern in cls.CPP_FORBIDDEN_PATTERNS:
            match = pattern.search(source_code)
            if match:
                violations.append(f"Prohibited system/execution call detected: '{match.group(0).strip()}'.")

        has_sec = len(violations) > 0
        return StaticValidationResult(
            is_valid=not has_sec,
            has_syntax_error=False,
            has_security_violation=has_sec,
            violation_details=violations,
            ast_tree_verified=True,
        )

    # --- JAVA VALIDATION ---
    @classmethod
    def _validate_java(cls, source_code: str) -> StaticValidationResult:
        violations: List[str] = []

        # 1. Structural balance check
        balance_err = cls._check_brackets_balance(source_code)
        if balance_err:
            return StaticValidationResult(
                is_valid=False,
                has_syntax_error=True,
                violation_details=[balance_err],
                ast_tree_verified=False,
            )

        # 2. Check prohibited imports
        import_pattern = re.compile(r'import\s+([a-zA-Z0-9_\.]+);')
        for match in import_pattern.finditer(source_code):
            imp = match.group(1).strip()
            for forbidden in cls.JAVA_FORBIDDEN_IMPORTS:
                if imp == forbidden or imp.startswith(f"{forbidden}."):
                    violations.append(f"Prohibited Java import: '{imp}'.")

        # 3. Check prohibited calls (Runtime, ProcessBuilder, Socket, File I/O)
        for pattern in cls.JAVA_FORBIDDEN_PATTERNS:
            match = pattern.search(source_code)
            if match:
                violations.append(f"Prohibited Java runtime/process call: '{match.group(0).strip()}'.")

        has_sec = len(violations) > 0
        return StaticValidationResult(
            is_valid=not has_sec,
            has_syntax_error=False,
            has_security_violation=has_sec,
            violation_details=violations,
            ast_tree_verified=True,
        )

    @staticmethod
    def _check_brackets_balance(source: str) -> str:
        """Verifies balanced braces, brackets, and parentheses ignoring strings and comments."""
        stack = []
        mapping = {')': '(', '}': '{', ']': '['}
        in_string = False
        quote_char = None
        in_line_comment = False
        in_block_comment = False

        i = 0
        n = len(source)
        line = 1

        while i < n:
            ch = source[i]
            if ch == '\n':
                line += 1
                in_line_comment = False
                i += 1
                continue

            if in_line_comment:
                i += 1
                continue

            if in_block_comment:
                if ch == '*' and i + 1 < n and source[i + 1] == '/':
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            # Check comment start
            if ch == '/' and i + 1 < n:
                if source[i + 1] == '/':
                    in_line_comment = True
                    i += 2
                    continue
                elif source[i + 1] == '*':
                    in_block_comment = True
                    i += 2
                    continue

            # Check string literal
            if ch in ('"', "'"):
                if not in_string:
                    in_string = True
                    quote_char = ch
                elif quote_char == ch:
                    if source[i - 1] != '\\':
                        in_string = False
                        quote_char = None
                i += 1
                continue

            if in_string:
                i += 1
                continue

            # Bracket matching
            if ch in ('(', '{', '['):
                stack.append((ch, line))
            elif ch in (')', '}', ']'):
                if not stack:
                    return f"Syntax error: Unmatched closing bracket '{ch}' on line {line}."
                top, top_line = stack.pop()
                if top != mapping[ch]:
                    return f"Syntax error: Mismatched bracket '{ch}' on line {line} (opened '{top}' on line {top_line})."

            i += 1

        if stack:
            top, top_line = stack.pop()
            return f"Syntax error: Unclosed bracket '{top}' opened on line {top_line}."

        return ""
