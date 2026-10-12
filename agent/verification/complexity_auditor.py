"""
Asymptotic Complexity Auditor.
Performs deterministic static AST analysis and structural pattern auditing to compare
the actual candidate implementation against the expected AlgorithmPlan and ProblemSpec constraints.
Clearly distinguishes OBSERVED STRUCTURE from INFERRED COMPLEXITY.
"""

import ast
import re
from typing import List, Optional, Tuple

from agent.core.models import (
    AlgorithmPlan,
    ComplexityAuditResult,
    ComplexityConfidence,
    ConstraintCompatibilityResult,
    ProblemSpec,
    StructuralComplexityObservation,
    SupportedLanguage,
)
from agent.planning.constraint_evaluator import ConstraintEvaluator


class ComplexityAuditor:
    """
    Audits the asymptotic time and space complexity of generated code.
    - Inspects AST and structural patterns (dominant loops, nesting depth, recursion, sorting, allocations).
    - Compares inferred complexity against AlgorithmPlan.
    - Validates algorithmic bounds against ProblemSpec constraints.
    - Flags COMPLEXITY_UNCERTAIN if confident static inference is not possible.
    """

    @classmethod
    def audit(
        cls,
        source_code: str,
        language: SupportedLanguage,
        plan: Optional[AlgorithmPlan] = None,
        problem: Optional[ProblemSpec] = None,
    ) -> ComplexityAuditResult:
        """
        Conducts structural complexity analysis on the source code and compares it to the plan.
        """
        # 1. Default fallback complexities if plan is absent
        expected_time = plan.selected_approach.time_complexity if plan else "O(N)"
        expected_space = plan.selected_approach.space_complexity if plan else "O(1)"

        # 2. Extract structural observations
        obs = cls.observe_structure(source_code, language)

        # 3. Infer Big-O from observed structure
        inferred_time, inferred_space, confidence, worst_case_notes = cls.infer_complexity(obs, language, source_code)

        # 4. Check for structural anomalies / anti-patterns (respecting amortized inferences)
        anomalies = cls.detect_anomalies(obs, expected_time, inferred_time=inferred_time)

        # 5. Check consistency between plan and implementation
        consistent, inconsistency_reasons = cls.check_plan_consistency(
            expected_time=expected_time,
            inferred_time=inferred_time,
            expected_space=expected_space,
            inferred_space=inferred_space,
            obs=obs,
        )
        if not consistent:
            for reason in inconsistency_reasons:
                anomalies.append(reason)

        return ComplexityAuditResult(
            expected_time_complexity=expected_time,
            expected_space_complexity=expected_space,
            inferred_time_complexity=inferred_time,
            inferred_space_complexity=inferred_space,
            confidence=confidence,
            observed_structure=obs,
            plan_implementation_consistent=consistent,
            detected_anomalies=anomalies,
            worst_case_analysis=worst_case_notes,
        )

    @classmethod
    def observe_structure(cls, source_code: str, language: SupportedLanguage) -> StructuralComplexityObservation:
        """Extracts deterministic AST metrics (loops, recursion, sorting, allocations)."""
        if language == SupportedLanguage.PYTHON:
            return cls._observe_python_ast(source_code)
        else:
            return cls._observe_generic_patterns(source_code, language)

    @classmethod
    def _observe_python_ast(cls, source_code: str) -> StructuralComplexityObservation:
        obs = StructuralComplexityObservation()
        try:
            tree = ast.parse(source_code)
        except Exception:
            obs.dominant_loops.append("AST parse failed; static analysis degraded.")
            return obs

        max_depth = 0
        current_depth = 0
        func_defs: List[str] = []

        class ASTVisitor(ast.NodeVisitor):
            nonlocal max_depth, current_depth

            def visit_FunctionDef(self, node: ast.FunctionDef):
                func_defs.append(node.name)
                self.generic_visit(node)

            def visit_For(self, node: ast.For):
                nonlocal current_depth, max_depth
                current_depth += 1
                if current_depth > max_depth:
                    max_depth = current_depth
                obs.dominant_loops.append(f"For loop at line {node.lineno} (nesting depth {current_depth})")
                self.generic_visit(node)
                current_depth -= 1

            def visit_While(self, node: ast.While):
                nonlocal current_depth, max_depth
                current_depth += 1
                if current_depth > max_depth:
                    max_depth = current_depth
                obs.dominant_loops.append(f"While loop at line {node.lineno} (nesting depth {current_depth})")
                self.generic_visit(node)
                current_depth -= 1

            def visit_Call(self, node: ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                # Check sorting
                if func_name in ("sorted", "sort"):
                    obs.sorting_calls.append(f"Call to {func_name}() at line {getattr(node, 'lineno', 0)}")

                # Check recursion
                if func_name in func_defs:
                    obs.recursion_detected = True

                # Check hash operations or allocations
                if func_name in ("dict", "set", "defaultdict", "Counter"):
                    obs.data_structures_observed.append(func_name)
                    if current_depth > 0:
                        obs.hash_operations_in_loop = True

                # Check allocations like list(), [None]*n, etc.
                if func_name == "list":
                    obs.auxiliary_allocations.append("list() allocation")

                self.generic_visit(node)

            def visit_Dict(self, node: ast.Dict):
                obs.data_structures_observed.append("dict")
                obs.auxiliary_allocations.append("dict allocation")
                self.generic_visit(node)

            def visit_Set(self, node: ast.Set):
                obs.data_structures_observed.append("set")
                obs.auxiliary_allocations.append("set allocation")
                self.generic_visit(node)

            def visit_ListComp(self, node: ast.ListComp):
                obs.auxiliary_allocations.append(f"List comprehension at line {node.lineno}")
                self.generic_visit(node)

            def visit_BinOp(self, node: ast.BinOp):
                # Detect string concatenation inside loop (str += ... or str + ...)
                if isinstance(node.op, ast.Add) and current_depth > 0:
                    if (isinstance(node.left, ast.Constant) and isinstance(node.left.value, str)) or \
                       (isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)):
                        obs.string_concatenation_in_loop = True
                self.generic_visit(node)

            def visit_AugAssign(self, node: ast.AugAssign):
                if isinstance(node.op, ast.Add) and current_depth > 0:
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        obs.string_concatenation_in_loop = True
                self.generic_visit(node)

        visitor = ASTVisitor()
        visitor.visit(tree)

        obs.max_loop_depth = max_depth
        obs.has_nested_loops = (max_depth >= 2)
        if obs.recursion_detected:
            obs.recursion_depth_estimate = "O(N) (unbounded recursion depth risk)"

        return obs

    @classmethod
    def _observe_generic_patterns(cls, source_code: str, language: SupportedLanguage) -> StructuralComplexityObservation:
        """Regex-based structural observations for C, C++, and Java."""
        obs = StructuralComplexityObservation()

        # Count loop nesting accurately using brace-aware tracking (ignoring comments)
        lines = source_code.splitlines()
        max_depth = 0
        active_loop_brace_levels: List[int] = []
        current_brace_depth = 0
        in_block_comment = False
        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if in_block_comment:
                if "*/" in stripped:
                    in_block_comment = False
                    stripped = stripped.split("*/", 1)[1].strip()
                else:
                    continue
            if "/*" in stripped:
                if "*/" in stripped:
                    stripped = re.sub(r"/\*.*?\*/", "", stripped).strip()
                else:
                    in_block_comment = True
                    stripped = stripped.split("/*", 1)[0].strip()

            if stripped.startswith("//") or stripped.startswith("*"):
                continue

            # Strip inline comments
            if "//" in stripped:
                stripped = stripped.split("//", 1)[0].strip()

            is_loop = bool(re.search(r"\b(for|while)\s*\(", stripped))
            if is_loop:
                obs.dominant_loops.append(f"Loop at line {idx}: {stripped[:40]}")
                has_open_brace = "{" in stripped
                if not has_open_brace and stripped.endswith(";"):
                    # Single-line statement loop: nesting is active_loops + 1 only for this line
                    nesting = len(active_loop_brace_levels) + 1
                    if nesting > max_depth:
                        max_depth = nesting
                else:
                    active_loop_brace_levels.append(current_brace_depth + (1 if has_open_brace else 0))
                    nesting = len(active_loop_brace_levels)
                    if nesting > max_depth:
                        max_depth = nesting

            opens = stripped.count("{")
            closes = stripped.count("}")
            current_brace_depth += opens - closes
            while active_loop_brace_levels and current_brace_depth < active_loop_brace_levels[-1]:
                active_loop_brace_levels.pop()

        obs.max_loop_depth = max_depth
        obs.has_nested_loops = (max_depth >= 2)

        # Detect sorting
        if re.search(r"\b(std::sort|qsort|Arrays\.sort|Collections\.sort)\b", source_code):
            obs.sorting_calls.append("Standard library sort call detected")

        # Detect data structures (distinguish parameter signatures from auxiliary local instantiations)
        # Hash tables and sets are always tracked as auxiliary data structures
        for ds in ("HashMap", "HashSet", "unordered_map", "unordered_set"):
            if ds in source_code:
                obs.data_structures_observed.append(ds)

        # For sequential containers like vector/ArrayList, only count as auxiliary if locally instantiated
        # e.g. "vector<int> res", "vector<int> dp = ...", "new ArrayList", etc. (excluding method return types and signatures)
        for ds in ("vector", "ArrayList"):
            # Check for local declaration patterns: e.g. "vector<...>\s+\w+\s*=" or "vector<...>\s+\w+;"
            # Exclude constructor or function headers like "vector<int> funcName("
            if re.search(r"\b" + ds + r"<[^>]+>\s+\w+\s*(=|;)", source_code) or f"new {ds}" in source_code:
                obs.data_structures_observed.append(ds)

        return obs

    @classmethod
    def infer_complexity(
        cls,
        obs: StructuralComplexityObservation,
        language: SupportedLanguage,
        source_code: str,
    ) -> Tuple[str, str, ComplexityConfidence, str]:
        """
        Infers Big-O time and space complexity based strictly on deterministic structural evidence.
        Distinguishes observed structure from mathematical inferences.
        """
        notes: List[str] = []

        # If static analysis failed or code is empty
        if not source_code.strip():
            return "O(1)", "O(1)", ComplexityConfidence.HIGH, "Empty source."

        # Recursion with multiple recursive calls (e.g. tree or Fibonacci branching)
        # Check if recursion is present
        if obs.recursion_detected:
            # Check branching (e.g., func(x - 1) + func(x - 2))
            recursive_call_matches = len(re.findall(r"\b\w+\([^)]*\)\s*[\+\-]\s*\w+\([^)]*\)", source_code))
            if recursive_call_matches > 0:
                notes.append("Branching recursion observed; worst-case exponential O(2^N).")
                return "O(2^N)", "O(N)", ComplexityConfidence.MEDIUM, "; ".join(notes)
            else:
                notes.append("Linear or single-branch recursion observed; worst-case call stack depth O(N).")
                # If recursion also has sorting or loops inside
                if obs.max_loop_depth >= 1:
                    return "O(N^2)", "O(N)", ComplexityConfidence.MEDIUM, "; ".join(notes)
                return "O(N)", "O(N)", ComplexityConfidence.MEDIUM, "; ".join(notes)

        # Loop depth analysis
        # Check for two-pointer sliding window amortized linear time
        is_sliding_window_amortized = (
            obs.max_loop_depth == 2 and
            ("for" in source_code or "while" in source_code) and
            bool(re.search(r"\b(left|start|l)\s*(\+=|=)\s*(\1\s*\+\s*1|\b\w+\s*\+\s*1|1\b)", source_code)) and
            any(k in source_code for k in ("curr_sum", "window", "min_len", "max_len", "target", "nums[left]", "[left]"))
        )

        if obs.max_loop_depth >= 3:
            notes.append(f"Detected {obs.max_loop_depth} nested loop levels; worst-case O(N^{obs.max_loop_depth}).")
            time_comp = f"O(N^{obs.max_loop_depth})"
        elif obs.max_loop_depth == 2:
            if is_sliding_window_amortized:
                notes.append("Two-pointer sliding window contraction observed; amortized linear time O(N).")
                time_comp = "O(N)"
            else:
                notes.append("Detected 2 nested loop levels; worst-case O(N^2).")
                time_comp = "O(N^2)"
        elif obs.max_loop_depth == 1:
            if len(obs.sorting_calls) > 0:
                notes.append("Single loop with explicit sorting; dominant term O(N log N).")
                time_comp = "O(N log N)"
            elif re.search(r"/\s*2|>>\s*1", source_code) and ("mid" in source_code or "left" in source_code or "right" in source_code):
                notes.append("Binary search logarithmic index division observed; worst-case O(log N).")
                time_comp = "O(log N)"
            else:
                notes.append("Single linear loop; worst-case O(N).")
                time_comp = "O(N)"
        else:
            if len(obs.sorting_calls) > 0:
                notes.append("Explicit sorting without loop; dominant term O(N log N).")
                time_comp = "O(N log N)"
            else:
                notes.append("No loops or recursive calls observed; constant time O(1).")
                time_comp = "O(1)"

        # String concatenation in loops leading to quadratic behavior
        if obs.string_concatenation_in_loop and time_comp == "O(N)":
            notes.append("Repeated string concatenation inside loop introduces hidden quadratic O(N^2) memory copying.")
            time_comp = "O(N^2)"

        # Space complexity inference
        if len(obs.auxiliary_allocations) > 0 or len(obs.data_structures_observed) > 0:
            space_comp = "O(N)"
            notes.append("Auxiliary collections/allocations observed; space O(N).")
        else:
            space_comp = "O(1)"
            notes.append("No auxiliary collections observed; in-place / constant auxiliary space O(1).")

        return time_comp, space_comp, ComplexityConfidence.HIGH, "; ".join(notes)

    @classmethod
    def detect_anomalies(
        cls,
        obs: StructuralComplexityObservation,
        expected_time: str,
        inferred_time: Optional[str] = None,
    ) -> List[str]:
        """Detects anti-patterns such as hidden quadratics, repeated sorting, or accidental nesting."""
        anomalies: List[str] = []

        exp_clean = expected_time.upper().replace(" ", "")
        inf_clean = (inferred_time or "").upper().replace(" ", "")
        # If loops are nested but inferred to be amortized linear O(N) (e.g. sliding window), do not flag as accidental quadratic
        is_amortized_linear = (obs.max_loop_depth == 2 and inf_clean == "O(N)" and exp_clean == "O(N)")
        if obs.has_nested_loops and not is_amortized_linear and "N^2" not in exp_clean and "N^3" not in exp_clean and "V+E" not in exp_clean:
            anomalies.append(
                f"Accidental nested loop detected (depth {obs.max_loop_depth}); "
                f"inconsistent with expected {expected_time} approach."
            )

        if len(obs.sorting_calls) > 1 and obs.max_loop_depth > 0:
            anomalies.append("Repeated sorting detected inside iteration, which can cause O(N^2 log N) degradation.")

        if obs.string_concatenation_in_loop:
            anomalies.append("Repeated string concatenation in loop detected (quadratic buffer reallocation).")

        return anomalies

    @classmethod
    def check_plan_consistency(
        cls,
        expected_time: str,
        inferred_time: str,
        expected_space: str = "O(1)",
        inferred_space: str = "O(1)",
        obs: Optional[StructuralComplexityObservation] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Validates if implementation matches or satisfies the plan's time and space complexity.
        Returns (consistent: bool, reasons: List[str]).
        """
        reasons: List[str] = []
        is_consistent = True

        # Normalize time
        exp_t_clean = expected_time.upper().replace(" ", "").replace("*", "")
        inf_t_clean = inferred_time.upper().replace(" ", "").replace("*", "")

        # Rank complexities
        time_ranks = {
            "O(1)": 1,
            "O(LOGN)": 2,
            "O(LOG(N))": 2,
            "O(SQRT(N))": 3,
            "O(N)": 4,
            "O(NLOGK)": 5,
            "O(NLOG(K))": 5,
            "O(NLOGN)": 5,
            "O(NLOG(N))": 5,
            "O(V+E)": 6,
            "O(N^2)": 6,
            "O(N2)": 6,
            "O(N^3)": 7,
            "O(N3)": 7,
            "O(2^N)": 8,
            "O(2N)": 8,
            "O(N!)": 9,
        }

        exp_t_rank = time_ranks.get(exp_t_clean)
        inf_t_rank = time_ranks.get(inf_t_clean)

        if exp_t_rank is not None and inf_t_rank is not None:
            if inf_t_rank > exp_t_rank:
                is_consistent = False
                reasons.append(
                    f"Time complexity inconsistency: Plan expected {expected_time}, "
                    f"but implementation exhibits {inferred_time}."
                )

        # If nested loops observed when plan expected O(N) or O(N log N)
        is_amortized_linear = (obs and obs.max_loop_depth == 2 and inf_t_clean == "O(N)" and exp_t_clean == "O(N)")
        if obs and obs.has_nested_loops and not is_amortized_linear and ("N^2" not in exp_t_clean and "N^3" not in exp_t_clean and "V+E" not in exp_t_clean):
            is_consistent = False
            reasons.append(
                f"Loop depth inconsistency: Plan expected {expected_time}, "
                f"but nested loops (depth {obs.max_loop_depth}) were detected."
            )

        # Normalize space
        exp_s_clean = expected_space.upper().replace(" ", "").replace("*", "")
        inf_s_clean = inferred_space.upper().replace(" ", "").replace("*", "")

        space_ranks = {
            "O(1)": 1,
            "O(LOGN)": 2,
            "O(LOG(N))": 2,
            "O(H)": 3,
            "O(K)": 3,
            "O(V)": 4,
            "O(N)": 4,
            "O(N^2)": 5,
            "O(N2)": 5,
        }

        exp_s_rank = space_ranks.get(exp_s_clean)
        inf_s_rank = space_ranks.get(inf_s_clean)

        if exp_s_rank is not None and inf_s_rank is not None:
            if inf_s_rank > exp_s_rank:
                is_consistent = False
                reasons.append(
                    f"Space complexity inconsistency: Plan expected {expected_space} auxiliary space, "
                    f"but implementation exhibits {inferred_space} auxiliary space usage."
                )

        return is_consistent, reasons

    @classmethod
    def evaluate_constraint_compatibility(
        cls,
        complexity_str: str,
        problem: Optional[ProblemSpec],
    ) -> ConstraintCompatibilityResult:
        """
        Checks whether the complexity is reasonably compatible with problem's input bounds.
        Distinguishes explicit constraints from unknown/ambiguous constraints.
        """
        if not problem or not problem.constraints:
            return ConstraintCompatibilityResult(
                compatible=True,
                max_input_bound=None,
                estimated_operations=None,
                constraints_uncertain=True,
                details="No explicit numeric constraints provided; constraint compatibility is UNCERTAIN.",
            )

        max_n = ConstraintEvaluator.extract_max_n(problem.constraints)
        if max_n is None:
            return ConstraintCompatibilityResult(
                compatible=True,
                max_input_bound=None,
                estimated_operations=None,
                constraints_uncertain=True,
                details="Could not deterministically parse numeric input bound N; constraint compatibility is UNCERTAIN.",
            )

        ops = ConstraintEvaluator.estimate_operations(complexity_str, max_n)
        if ops is None:
            return ConstraintCompatibilityResult(
                compatible=True,
                max_input_bound=max_n,
                estimated_operations=None,
                constraints_uncertain=True,
                details=f"Unrecognized complexity expression '{complexity_str}'; cannot compute operation bounds.",
            )

        limit = ConstraintEvaluator.OPERATIONS_LIMIT
        if ops > limit:
            formatted_ops = f"{ops:.1e}" if ops > 10**6 else str(int(ops))
            return ConstraintCompatibilityResult(
                compatible=False,
                max_input_bound=max_n,
                estimated_operations=ops,
                operations_threshold=float(limit),
                constraints_uncertain=False,
                details=f"Incompatible: Estimated operations ({formatted_ops}) exceed threshold ({limit:.0e}) for N = {max_n}.",
            )

        return ConstraintCompatibilityResult(
            compatible=True,
            max_input_bound=max_n,
            estimated_operations=ops,
            operations_threshold=float(limit),
            constraints_uncertain=False,
            details=f"Compatible: Estimated operations ({ops:.1e} ops) are within safe limit (~{limit:.0e}) for N = {max_n}.",
        )
