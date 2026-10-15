"""
Problem Normalizer and Analyzer.
Parses raw problem statements (LeetCode style text or semi-structured data)
into validated, canonical ProblemSpec objects without hallucinating facts.
"""

import ast
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from agent.core.models import (
    ConfidenceLevel,
    ConstraintItem,
    Difficulty,
    EdgeCaseItem,
    OracleType,
    ProblemSpec,
    TestCase,
    TestCategory,
    TypedField,
)


class ProblemNormalizer:
    """
    Deterministic parser and schema normalizer for DSA problem statements.
    Preserves raw content verbatim, extracts explicit structures, derives logically
    inferred edge cases, and labels any unresolved information as unknown or ambiguous.
    """

    def parse(self, raw_input: str, problem_id: Optional[str] = None) -> ProblemSpec:
        """
        Parses raw text or JSON problem statement into a strongly validated ProblemSpec.
        """
        if not raw_input or not raw_input.strip():
            raise ValueError("Problem statement cannot be empty.")

        clean_text = raw_input.strip()

        # Check if input is a structured JSON dump
        if clean_text.startswith("{") and clean_text.endswith("}"):
            try:
                data = json.loads(clean_text)
                if isinstance(data, dict):
                    return self._from_dict(data, clean_text, problem_id)
            except json.JSONDecodeError:
                pass  # Fall through to raw text parsing

        return self._from_text(clean_text, problem_id)

    def _from_dict(self, data: Dict[str, Any], raw_text: str, override_id: Optional[str]) -> ProblemSpec:
        """Constructs ProblemSpec from a dictionary with strict validation."""
        pid = override_id or data.get("id") or self._slugify(data.get("title", "unnamed-problem"))
        title = data.get("title") or pid.replace("-", " ").title()
        description = data.get("description", "").strip()
        raw_statement = raw_text

        difficulty = self._parse_difficulty(data.get("difficulty"))
        function_name = data.get("function_name", "").strip()
        param_names = data.get("param_names", [])
        return_type = data.get("return_type", "Any").strip()

        constraints = data.get("constraints", [])
        structured_constraints = [
            ConstraintItem(statement=c, confidence=ConfidenceLevel.EXPLICIT)
            for c in constraints
        ]

        test_cases: List[TestCase] = []
        raw_tests = data.get("test_cases", []) or data.get("examples", [])
        for i, tc in enumerate(raw_tests):
            if isinstance(tc, dict):
                inp = tc.get("inputs") if "inputs" in tc else tc.get("input", {})
                outp = tc.get("expected_output") if "expected_output" in tc else tc.get("output")
                test_cases.append(TestCase(
                    id=tc.get("id", f"tc_{i+1}"),
                    inputs=inp,
                    expected_output=outp,
                    description=tc.get("description"),
                    is_sample=tc.get("is_sample", True),
                    is_edge_case=tc.get("is_edge_case", False),
                ))

        edge_cases = self._derive_edge_cases(structured_constraints, description)
        ambiguities = []

        # If function_name or param_names missing, check known benchmarks or infer from test cases
        if not function_name:
            from agent.benchmarking.benchmark_registry import BENCHMARK_REGISTRY
            if pid in BENCHMARK_REGISTRY:
                function_name = BENCHMARK_REGISTRY[pid].function_name
            else:
                function_name = self._camel_case(title) or "solve"

        if not param_names:
            from agent.benchmarking.benchmark_registry import BENCHMARK_REGISTRY
            if pid in BENCHMARK_REGISTRY:
                param_names = list(BENCHMARK_REGISTRY[pid].param_names)
            elif test_cases and test_cases[0].inputs:
                param_names = list(test_cases[0].inputs.keys())
            else:
                param_names = ["arg1"]

        if return_type == "Any":
            from agent.benchmarking.benchmark_registry import BENCHMARK_REGISTRY
            if pid in BENCHMARK_REGISTRY:
                return_type = BENCHMARK_REGISTRY[pid].return_type

        if not test_cases:
            ambiguities.append("No test cases or examples could be identified.")

        params_schema = [
            TypedField(name=p, type_str="Any", confidence=ConfidenceLevel.UNKNOWN)
            for p in param_names
        ]

        return ProblemSpec(
            id=pid,
            title=title,
            description=description or raw_statement,
            raw_statement=raw_statement,
            difficulty=difficulty,
            function_name=function_name or "solve",
            param_names=param_names,
            params_schema=params_schema,
            return_type=return_type,
            constraints=constraints,
            structured_constraints=structured_constraints,
            edge_cases=edge_cases,
            test_cases=test_cases,
            is_ambiguous=len(ambiguities) > 0,
            ambiguity_notes=ambiguities,
        )

    def _from_text(self, text: str, override_id: Optional[str]) -> ProblemSpec:
        """Parses standard markdown/plain text LeetCode problem descriptions."""
        # Normalize escaped literal newlines if present (e.g. from CLI text arguments)
        normalized_text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
        lines = [line.rstrip() for line in normalized_text.splitlines()]

        # 1. Title & Difficulty
        title, difficulty = self._extract_title_and_difficulty(lines)
        pid = override_id or self._slugify(title)

        # 2. Extract sections
        description_lines, example_blocks, constraint_lines = self._partition_sections(lines)

        description = "\n".join(description_lines).strip()

        # 3. Parse Constraints
        constraints, structured_constraints = self._parse_constraints(constraint_lines)

        # 4. Parse Examples / Test Cases
        test_cases, inferred_fn, inferred_params, inferred_return, unresolved_notes = self._parse_examples(example_blocks)

        # 5. Extract Code Signature if present
        fn_from_sig, params_from_sig, ret_from_sig = self._extract_signature_from_text(text)

        final_fn = fn_from_sig or inferred_fn
        final_params = params_from_sig or inferred_params
        final_return = ret_from_sig or inferred_return or "Any"

        ambiguities = list(unresolved_notes)
        if not final_fn:
            final_fn = self._camel_case(title) or "solve"

        if not final_params:
            if test_cases and test_cases[0].inputs:
                final_params = list(test_cases[0].inputs.keys())
            else:
                final_params = ["arg1"]
                ambiguities.append("Parameter names could not be determined with certainty.")

        if not test_cases:
            ambiguities.append("No explicit examples or test cases found in problem statement.")

        params_schema = [
            TypedField(
                name=p,
                type_str=self._infer_type_from_examples(p, test_cases),
                confidence=ConfidenceLevel.INFERRED if test_cases else ConfidenceLevel.UNKNOWN,
            )
            for p in final_params
        ]

        edge_cases = self._derive_edge_cases(structured_constraints, description)

        return ProblemSpec(
            id=pid,
            title=title,
            description=description,
            raw_statement=text,
            difficulty=difficulty,
            function_name=final_fn,
            param_names=final_params,
            params_schema=params_schema,
            return_type=final_return,
            constraints=constraints,
            structured_constraints=structured_constraints,
            edge_cases=edge_cases,
            test_cases=test_cases,
            is_ambiguous=len(ambiguities) > 0,
            ambiguity_notes=ambiguities,
        )

    def _extract_title_and_difficulty(self, lines: List[str]) -> Tuple[str, Difficulty]:
        """Extracts title line and optional difficulty badge."""
        title = "Untitled Problem"
        difficulty = Difficulty.UNKNOWN

        for line in lines[:5]:
            stripped = line.strip()
            if not stripped:
                continue
            # Remove leading markdown heading #
            candidate = re.sub(r"^#+\s*", "", stripped).strip()

            # If the candidate line is long and contains a sentence ending period without heading,
            # take only the first title-like phrase
            if not stripped.startswith("#") and "." in candidate:
                first_part = candidate.split(".", 1)[0].strip()
                if len(first_part) <= 60 and len(first_part.split()) <= 6:
                    candidate = first_part

            # Check for difficulty tags e.g. "Two Sum [Easy]" or "Two Sum (Easy)"
            diff_match = re.search(r"[\(\[\s](Easy|Medium|Hard)[\)\]\s]?$", candidate, re.IGNORECASE)
            if diff_match:
                diff_str = diff_match.group(1).capitalize()
                difficulty = self._parse_difficulty(diff_str)
                candidate = candidate[:diff_match.start()].strip()

            if candidate:
                title = candidate
                break

        return title, difficulty

    def _partition_sections(self, lines: List[str]) -> Tuple[List[str], List[List[str]], List[str]]:
        """Partitions raw lines into description, example blocks, and constraint lines."""
        desc: List[str] = []
        examples: List[List[str]] = []
        constraints: List[str] = []

        current_section = "desc"
        current_example: List[str] = []

        for line in lines:
            stripped = line.strip()
            lower = stripped.lower()

            if re.match(r"^#*\s*\*{0,2}example\s*\d*:?\*{0,2}", lower):
                if current_example:
                    examples.append(current_example)
                    current_example = []
                current_section = "example"
                current_example.append(line)
                continue

            if re.match(r"^#*\s*constraints?:", lower):
                if current_example:
                    examples.append(current_example)
                    current_example = []
                current_section = "constraints"
                continue

            if current_section == "desc":
                desc.append(line)
            elif current_section == "example":
                current_example.append(line)
            elif current_section == "constraints":
                if stripped.startswith("- ") or stripped.startswith("* "):
                    constraints.append(stripped[2:].strip())
                elif stripped:
                    constraints.append(stripped)

        if current_example:
            examples.append(current_example)

        return desc, examples, constraints

    def _parse_constraints(self, raw_lines: List[str]) -> Tuple[List[str], List[ConstraintItem]]:
        """Extracts structured items from raw constraint strings."""
        items: List[ConstraintItem] = []
        cleaned: List[str] = []

        for line in raw_lines:
            stmt = line.strip()
            if not stmt:
                continue
            cleaned.append(stmt)
            # Try to identify numeric range e.g., "1 <= nums.length <= 10^4" or "0 <= k <= 1000"
            range_match = re.search(r"(-?\d+(?:\^\d+)?)\s*(?:<=|<)\s*([a-zA-Z_\.]+)\s*(?:<=|<)\s*(-?\d+(?:\^\d+)?)", stmt)
            if range_match:
                min_v, var_name, max_v = range_match.groups()
                items.append(ConstraintItem(
                    statement=stmt,
                    confidence=ConfidenceLevel.EXPLICIT,
                    variable=var_name,
                    min_val=min_v,
                    max_val=max_v,
                ))
            else:
                items.append(ConstraintItem(
                    statement=stmt,
                    confidence=ConfidenceLevel.EXPLICIT,
                ))

        return cleaned, items

    def _parse_examples(
        self, example_blocks: List[List[str]]
    ) -> Tuple[List[TestCase], Optional[str], Optional[List[str]], Optional[str], List[str]]:
        """Parses Example blocks extracting Input, Output, and Explanation. Tracks malformed examples."""
        test_cases: List[TestCase] = []
        inferred_fn = None
        inferred_params = None
        unresolved_notes: List[str] = []

        for idx, block in enumerate(example_blocks):
            block_text = "\n".join(block)
            tc_id = f"example_{idx+1}"

            # Match "Input: ... Output: ..." allowing optional markdown bolding (e.g. **Input:** or Input:)
            input_match = re.search(r"\*{0,2}Input:\*{0,2}\s*(.*?)(?=\n\s*\*{0,2}Output:\*{0,2}|\n\s*\*{0,2}Expected:\*{0,2}|\Z)", block_text, re.DOTALL | re.IGNORECASE)
            output_match = re.search(r"\*{0,2}Output:\*{0,2}\s*(.*?)(?=\n\s*\*{0,2}Explanation:\*{0,2}|\Z)", block_text, re.DOTALL | re.IGNORECASE)
            explanation_match = re.search(r"\*{0,2}Explanation:\*{0,2}\s*(.*)", block_text, re.DOTALL | re.IGNORECASE)

            if not input_match or not output_match:
                unresolved_notes.append(f"Example {idx+1} could not be parsed safely (missing Input or Output marker).")
                continue

            raw_input_str = input_match.group(1).strip()
            raw_output_str = output_match.group(1).strip()
            explanation = explanation_match.group(1).strip() if explanation_match else None

            # Parse inputs into dictionary
            inputs_dict, detected_fn = self._parse_inputs_string(raw_input_str)
            if not inputs_dict:
                unresolved_notes.append(f"Example {idx+1} inputs could not be parsed safely into structured arguments.")
                continue

            if detected_fn and not inferred_fn:
                inferred_fn = detected_fn

            if inputs_dict and not inferred_params:
                inferred_params = list(inputs_dict.keys())

            # Parse expected output value
            expected_val = self._safe_eval_literal(raw_output_str)

            test_cases.append(TestCase(
                id=tc_id,
                inputs=inputs_dict,
                expected_output=expected_val,
                category=TestCategory.EXAMPLE,
                oracle_type=OracleType.PROBLEM_SPEC,
                rationale=explanation,
                description=explanation,
                is_sample=True,
            ))

        return test_cases, inferred_fn, inferred_params, None, unresolved_notes

    def _parse_inputs_string(self, input_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Parses strings like:
        "nums = [2,7,11,15], target = 9"
        or function call syntax:
        "twoSum([2,7,11,15], 9)"
        """
        inputs: Dict[str, Any] = {}
        detected_fn = None

        # Check function call syntax e.g. solve(x, y)
        call_match = re.match(r"^([a-zA-Z_]\w*)\s*\((.*)\)$", input_str.strip(), re.DOTALL)
        if call_match:
            detected_fn = call_match.group(1)
            raw_args = call_match.group(2)
            parsed_args = self._split_arguments(raw_args)
            for i, arg in enumerate(parsed_args):
                inputs[f"arg_{i+1}"] = self._safe_eval_literal(arg)
            return inputs, detected_fn

        # Standard LeetCode key = value pattern: "nums = [2,7,11,15], target = 9"
        # Split by comma where comma is followed by `ident = `
        parts = re.split(r",\s*(?=[a-zA-Z_]\w*\s*=)", input_str.strip())
        for part in parts:
            if "=" in part:
                k, v = part.split("=", 1)
                k_clean = k.strip()
                v_clean = v.strip()
                inputs[k_clean] = self._safe_eval_literal(v_clean)

        return inputs, detected_fn

    def _split_arguments(self, args_str: str) -> List[str]:
        """Splits argument list by comma while respecting brackets and parentheses."""
        parts = []
        current = []
        depth = 0
        in_quote = False
        quote_char = None

        for char in args_str:
            if char in ('"', "'"):
                if not in_quote:
                    in_quote = True
                    quote_char = char
                elif quote_char == char:
                    in_quote = False
                    quote_char = None
            if not in_quote:
                if char in ("[", "(", "{"):
                    depth += 1
                elif char in ("]", ")", "}"):
                    depth -= 1
                elif char == "," and depth == 0:
                    parts.append("".join(current).strip())
                    current = []
                    continue
            current.append(char)

        if current:
            parts.append("".join(current).strip())
        return parts

    def _safe_eval_literal(self, val_str: str) -> Any:
        """Safely parses JSON or python literal without code execution."""
        clean = val_str.strip()
        # Normal boolean mappings
        if clean.lower() == "true":
            return True
        if clean.lower() == "false":
            return False
        if clean.lower() == "null" or clean.lower() == "none":
            return None

        # Try ast.literal_eval
        try:
            return ast.literal_eval(clean)
        except (ValueError, SyntaxError):
            pass

        # Try json.loads
        try:
            return json.loads(clean)
        except Exception:
            pass

        # Return as raw string if neither succeeded
        return clean

    def _extract_signature_from_text(self, text: str) -> Tuple[Optional[str], Optional[List[str]], Optional[str]]:
        """Scans for class Solution / method signature in text across supported languages."""
        # 1. Python signature: def twoSum(self, nums: List[int], target: int) -> List[int]:
        py_match = re.search(
            r"def\s+([a-zA-Z_]\w*)\s*\(\s*(?:self\s*,\s*)?(.*?)\)\s*(?:->\s*([^:]+))?:",
            text
        )
        if py_match:
            fn_name = py_match.group(1)
            raw_params = py_match.group(2)
            ret_type = py_match.group(3).strip() if py_match.group(3) else "Any"

            param_names = []
            for p in raw_params.split(","):
                p_clean = p.split(":")[0].strip()
                if p_clean and p_clean != "self":
                    param_names.append(p_clean)

            return fn_name, param_names, ret_type

        # 2. C++ / Java signature: vector<int> twoSum(vector<int>& nums, int target)
        cpp_match = re.search(
            r"(?:public:\s*)?(?:static\s+)?([a-zA-Z_][\w<>,:*\s&]*?)\s+([a-zA-Z_]\w*)\s*\(([^)]*)\)\s*(?:const)?\s*\{?",
            text
        )
        if cpp_match:
            ret_candidate = cpp_match.group(1).strip()
            fn_candidate = cpp_match.group(2).strip()
            args_candidate = cpp_match.group(3).strip()

            # Ignore non-function constructs
            if fn_candidate not in ("if", "for", "while", "switch", "catch", "class", "struct", "Solution"):
                param_names = []
                if args_candidate:
                    for arg in args_candidate.split(","):
                        arg_clean = arg.strip()
                        # Extract the parameter name as the last word token: e.g. "vector<int>& nums" -> "nums"
                        arg_name_match = re.search(r"([a-zA-Z_]\w*)$", arg_clean)
                        if arg_name_match:
                            param_names.append(arg_name_match.group(1))

                return fn_candidate, param_names, ret_candidate

        return None, None, None

    def _infer_type_from_examples(self, param_name: str, test_cases: List[TestCase]) -> str:
        """Derives a type string from example input values."""
        for tc in test_cases:
            if param_name in tc.inputs:
                val = tc.inputs[param_name]
                if isinstance(val, bool):
                    return "bool"
                if isinstance(val, int):
                    return "int"
                if isinstance(val, float):
                    return "float"
                if isinstance(val, str):
                    return "str"
                if isinstance(val, list):
                    if len(val) > 0 and isinstance(val[0], int):
                        return "List[int]"
                    if len(val) > 0 and isinstance(val[0], str):
                        return "List[str]"
                    return "List[Any]"
                if isinstance(val, dict):
                    return "Dict[str, Any]"
        return "Any"

    def _derive_edge_cases(self, constraints: List[ConstraintItem], description: str) -> List[EdgeCaseItem]:
        """Derives standard boundary cases strictly derived from constraints and description."""
        edge_cases = []
        for c in constraints:
            if c.min_val is not None and c.variable:
                # Minimum bound edge case
                edge_cases.append(EdgeCaseItem(
                    description=f"Minimum boundary condition for {c.variable} ({c.variable} = {c.min_val})",
                    confidence=ConfidenceLevel.INFERRED,
                ))
            if c.max_val is not None and c.variable:
                # Maximum bound edge case
                edge_cases.append(EdgeCaseItem(
                    description=f"Maximum boundary condition for {c.variable} ({c.variable} = {c.max_val})",
                    confidence=ConfidenceLevel.INFERRED,
                ))

        # Check for explicit empty string or 0 in constraints
        lower_desc = description.lower()
        if "empty" in lower_desc or "length == 0" in lower_desc:
            edge_cases.append(EdgeCaseItem(
                description="Handling of empty collection or string",
                confidence=ConfidenceLevel.INFERRED,
            ))
        if "negative" in lower_desc:
            edge_cases.append(EdgeCaseItem(
                description="Handling of negative values",
                confidence=ConfidenceLevel.INFERRED,
            ))

        return edge_cases

    def _parse_difficulty(self, diff_val: Optional[str]) -> Difficulty:
        if not diff_val:
            return Difficulty.UNKNOWN
        val = diff_val.strip().capitalize()
        if val in (Difficulty.EASY.value, Difficulty.MEDIUM.value, Difficulty.HARD.value):
            return Difficulty(val)
        return Difficulty.UNKNOWN

    def _slugify(self, title: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9\s-]", "", title).strip().lower()
        return re.sub(r"[\s-]+", "-", slug) or "problem"

    def _camel_case(self, title: str) -> str:
        words = re.findall(r"[a-zA-Z0-9]+", title)
        if not words:
            return "solve"
        first = words[0].lower()
        rest = "".join(w.capitalize() for w in words[1:])
        return first + rest
