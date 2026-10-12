"""Structured Test Risk Model for Stage 21 Intelligent & Adaptive Test Generation.

Analyzes problem specifications, constraints, algorithmic plans, candidate code structures,
and Stage 20 retrieved experience memory to synthesize actionable test risk signals.
Does NOT fabricate constraints or hallucinate code coverage.
"""

import ast
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agent.core.models import (
    ConfidenceLevel,
    ConstraintItem,
    DSAPattern,
    FailureCategory,
    ProblemSpec,
    SupportedLanguage,
)
from agent.memory.models import ExperienceRecommendation


class TestRiskSignal(BaseModel):
    """Specific targeted risk detected during analysis."""
    signal_id: str
    risk_category: str  # e.g., 'BOUNDARY', 'OFF_BY_ONE', 'EMPTY_OR_SINGLE', 'DUPLICATES', 'CYCLE_OR_GRAPH', 'RECURSION_LIMIT'
    description: str
    rationale: str
    severity: str = "HIGH"  # 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    target_variable: Optional[str] = None
    suggested_test_category: str = "boundary"  # 'boundary', 'adversarial', 'stress', 'edge_case', 'differential'
    is_memory_informed: bool = False
    source_experience_id: Optional[str] = None


class StructuralCodeRisk(BaseModel):
    """Signals derived from syntactic/structural inspection of candidate code."""
    has_nested_loops: bool = False
    has_recursion: bool = False
    has_pointer_or_index_arithmetic: bool = False
    has_boundary_comparisons: bool = False
    has_hash_lookups: bool = False
    has_stack_or_queue_ops: bool = False
    has_graph_adjacency_traversal: bool = False
    has_modulo_arithmetic: bool = False
    risk_notes: List[str] = Field(default_factory=list)


class TestRiskAnalysis(BaseModel):
    """Comprehensive test risk assessment for a problem and candidate solution."""
    problem_id: str
    identified_pattern: Optional[DSAPattern] = None
    language: SupportedLanguage
    signals: List[TestRiskSignal] = Field(default_factory=list)
    structural_risks: Optional[StructuralCodeRisk] = None
    memory_influences: List[str] = Field(default_factory=list)
    rejected_memories: List[str] = Field(default_factory=list)
    has_boundary_risk: bool = False
    has_adversarial_risk: bool = False
    has_stress_risk: bool = False
    has_off_by_one_risk: bool = False
    summary: str = ""


class StructuralCodeInspector:
    """Inspects candidate source code for risk patterns (syntax-based, language-tolerant)."""

    @classmethod
    def inspect(cls, code: str, language: SupportedLanguage) -> StructuralCodeRisk:
        risk = StructuralCodeRisk()
        if not code or not code.strip():
            return risk

        lines = [line.strip() for line in code.splitlines()]

        # 1. Python AST Inspection if Python
        if language == SupportedLanguage.PYTHON:
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.For, ast.While)):
                        for child in ast.walk(node):
                            if child is not node and isinstance(child, (ast.For, ast.While)):
                                risk.has_nested_loops = True
                    if isinstance(node, (ast.Compare,)):
                        risk.has_boundary_comparisons = True
                    if isinstance(node, (ast.Subscript,)):
                        risk.has_pointer_or_index_arithmetic = True
                    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                        risk.has_modulo_arithmetic = True
                    if isinstance(node, (ast.Dict, ast.Set)):
                        risk.has_hash_lookups = True
                    if isinstance(node, ast.Compare):
                        for op in node.ops:
                            if isinstance(op, (ast.In, ast.NotIn)):
                                risk.has_hash_lookups = True
                    if isinstance(node, ast.Call):
                        fn_name = ""
                        if isinstance(node.func, ast.Name):
                            fn_name = node.func.id.lower()
                        elif isinstance(node.func, ast.Attribute):
                            fn_name = node.func.attr.lower()
                        if fn_name in ("append", "pop", "popleft"):
                            risk.has_stack_or_queue_ops = True
                        if fn_name in ("dict", "set", "get"):
                            risk.has_hash_lookups = True
            except Exception:
                pass

        # 2. General / C / C++ / Java heuristic regex inspection
        code_lower = code.lower()

        # Nested loops heuristic
        loop_matches = len(re.findall(r"\b(for|while)\s*\(", code))
        if loop_matches >= 2 or risk.has_nested_loops:
            risk.has_nested_loops = True
            risk.risk_notes.append("Nested loops detected: potential O(N^2) or boundary crossing risk.")

        # Boundary comparisons (<, <=, >, >=, ==, !=, length - 1)
        if re.search(r"(<=|>=|<|>|==|!=)\s*(\w+|\d+)", code) or "- 1" in code or "+ 1" in code:
            risk.has_boundary_comparisons = True
            risk.has_pointer_or_index_arithmetic = True
            risk.risk_notes.append("Index arithmetic or boundary comparisons detected: off-by-one risk.")

        # Recursion
        if language != SupportedLanguage.PYTHON:
            # Check if function name calls itself
            func_defs = re.findall(r"\b(\w+)\s*\([^)]*\)\s*\{", code)
            for fname in func_defs:
                if fname not in ("if", "for", "while", "switch", "catch", "main"):
                    # Check if body calls fname
                    if len(re.findall(rf"\b{fname}\s*\(", code)) > 1:
                        risk.has_recursion = True
                        risk.risk_notes.append(f"Recursive function call {fname} detected: call stack risk.")
                        break

        # Map / Hash
        if any(term in code for term in ("unordered_map", "unordered_set", "HashMap", "HashSet", "dict", "set(", "TABLE_CAP", "{}", "seen")):
            risk.has_hash_lookups = True
            risk.risk_notes.append("Hash container or lookup table detected: duplicate key / collision risk.")

        # Stack / Queue
        if any(term in code for term in ("stack", "queue", "deque", "Deque", "Stack", "push", "pop", "peek")):
            risk.has_stack_or_queue_ops = True
            risk.risk_notes.append("Stack/Queue operations detected: empty structure pop / monotonic boundary risk.")

        # Graph adjacency
        if any(term in code for term in ("isConnected", "grid", "visited", "adj", "matrix", "neighbors")):
            risk.has_graph_adjacency_traversal = True
            risk.risk_notes.append("Adjacency matrix or grid traversal detected: disconnected/cycle risk.")

        return risk


class TestRiskClassifier:
    """Synthesizes risk signals from ProblemSpec, pattern, code, and Stage 20 memories."""

    @classmethod
    def analyze_risks(
        cls,
        problem: ProblemSpec,
        solution_code: Optional[str] = None,
        language: SupportedLanguage = SupportedLanguage.PYTHON,
        dsa_pattern: Optional[DSAPattern] = None,
        retrieved_memories: Optional[List[ExperienceRecommendation]] = None,
    ) -> TestRiskAnalysis:
        signals: List[TestRiskSignal] = []
        memory_influences: List[str] = []
        rejected_memories: List[str] = []

        # 1. Structural inspection of candidate code
        structural = StructuralCodeInspector.inspect(solution_code or "", language)

        # 2. Extract constraint limits
        min_n, max_n = cls._extract_size_bounds(problem.constraints)

        # 3. Analyze based on DSA Category / Pattern
        pattern = dsa_pattern or (problem.detected_patterns[0] if getattr(problem, "detected_patterns", None) else None)
        pid = problem.id.lower()

        # Binary Search Risks
        if (pattern == DSAPattern.BINARY_SEARCH) or ("binary-search" in pid) or ("search" in problem.function_name.lower()):
            signals.append(TestRiskSignal(
                signal_id="risk_bs_boundary",
                risk_category="OFF_BY_ONE",
                description="Binary search boundary condition: left/right interval update and target outside array bounds.",
                rationale="Binary-search boundary risk detected because algorithm uses left/right interval updates.",
                suggested_test_category="boundary",
            ))
            signals.append(TestRiskSignal(
                signal_id="risk_bs_single_element",
                risk_category="EMPTY_OR_SINGLE",
                description="Single element array: target found vs absent.",
                rationale="Array size 1 boundary condition is a common branch failure point in binary search.",
                suggested_test_category="boundary",
            ))
            signals.append(TestRiskSignal(
                signal_id="risk_bs_extremes",
                risk_category="BOUNDARY",
                description="Target smaller than minimum or greater than maximum element.",
                rationale="Validates that binary search does not run out-of-bounds when target is absent at extremes.",
                suggested_test_category="adversarial",
            ))

        # Two Pointers / Two Sum / Hashing Risks
        if (pattern in (DSAPattern.TWO_POINTERS, DSAPattern.HASH_TABLE, DSAPattern.ARRAYS_STRINGS)) or ("two-sum" in pid):
            signals.append(TestRiskSignal(
                signal_id="risk_two_sum_duplicates",
                risk_category="DUPLICATES",
                description="Duplicate elements forming target sum (e.g. [3, 3] target=6).",
                rationale="Hash map key overwrites or two-pointer skipping can miss duplicate element pairs.",
                suggested_test_category="adversarial",
            ))
            signals.append(TestRiskSignal(
                signal_id="risk_two_sum_negatives",
                risk_category="NEGATIVE_ZERO",
                description="All-negative array elements or zero targets.",
                rationale="Pointer direction or unsigned hash modulo can fail under negative values.",
                suggested_test_category="edge_case",
            ))
            signals.append(TestRiskSignal(
                signal_id="risk_min_length",
                risk_category="BOUNDARY",
                description=f"Minimum allowed length boundary (N={min_n or 2}).",
                rationale="Smallest valid input constraint must execute without out-of-bound errors.",
                suggested_test_category="boundary",
            ))

        # Stack / Parentheses
        if (pattern == DSAPattern.STACK) or ("valid-parentheses" in pid) or ("isvalid" in problem.function_name.lower()):
            signals.append(TestRiskSignal(
                signal_id="risk_stack_unmatched_single",
                risk_category="EMPTY_OR_SINGLE",
                description="Single unclosed opening bracket or single closing bracket.",
                rationale="Stack underflow on pop or leftover unclosed elements on termination.",
                suggested_test_category="boundary",
            ))
            signals.append(TestRiskSignal(
                signal_id="risk_stack_deeply_nested",
                risk_category="STRESS",
                description="Long sequence of deeply nested brackets.",
                rationale="Validates stack depth capacity and correct nesting order.",
                suggested_test_category="stress",
            ))

        # Sliding Window / Strings
        if (pattern == DSAPattern.SLIDING_WINDOW) or ("longest-substring" in pid):
            signals.append(TestRiskSignal(
                signal_id="risk_sliding_all_unique",
                risk_category="BOUNDARY",
                description="String with all distinct characters vs all identical characters.",
                rationale="Window expansion/contraction boundary when window size reaches 1 or N.",
                suggested_test_category="adversarial",
            ))

        # Dynamic Programming / Greedy
        if (pattern in (DSAPattern.DYNAMIC_PROGRAMMING, DSAPattern.GREEDY)) or ("climbing-stairs" in pid) or ("stock" in pid):
            signals.append(TestRiskSignal(
                signal_id="risk_dp_base_cases",
                risk_category="BOUNDARY",
                description="Smallest DP state base cases (N=1, N=2) and strictly decreasing sequences.",
                rationale="DP initialization errors or greedy assumptions frequently fail on minimal states or monotonic inputs.",
                suggested_test_category="boundary",
            ))

        # Graph / BFS / DFS / Tree
        if (pattern in (DSAPattern.GRAPH_BFS_DFS, DSAPattern.BINARY_TREE)) or ("provinces" in pid) or ("islands" in pid) or ("depth" in pid):
            signals.append(TestRiskSignal(
                signal_id="risk_graph_disconnected",
                risk_category="CYCLE_OR_GRAPH",
                description="Completely disconnected graph components (identity matrix) vs single connected component.",
                rationale="Component counting loops often fail when graph is fully disconnected or fully dense.",
                suggested_test_category="adversarial",
            ))

        # Backtracking / Subsets
        if (pattern == DSAPattern.BACKTRACKING_RECURSION) or ("subsets" in pid):
            signals.append(TestRiskSignal(
                signal_id="risk_backtracking_empty",
                risk_category="EMPTY_OR_SINGLE",
                description="Single element array and power set size 2^N validation.",
                rationale="Backtracking boundary conditions must generate exact mathematical power set 2^N.",
                suggested_test_category="boundary",
            ))

        # 4. Integrate Stage 20 Memory Signals
        if retrieved_memories:
            for mem in retrieved_memories:
                # Check relevance: pattern and problem compatibility
                if mem.relevance_score >= 0.5:
                    if mem.warning_notes:
                        for w in mem.warning_notes:
                            signals.append(TestRiskSignal(
                                signal_id=f"risk_mem_warning_{mem.experience_id[:8]}",
                                risk_category="MEMORY_INFORMED",
                                description=f"Memory-informed warning from verified problem {mem.problem_id}: {w}",
                                rationale=f"Stage 20 memory for pattern {mem.pattern.value if hasattr(mem.pattern, 'value') else mem.pattern} recorded failure/warning: {w}",
                                suggested_test_category="adversarial",
                                is_memory_informed=True,
                                source_experience_id=mem.experience_id,
                            ))
                            memory_influences.append(f"Retrieved relevant memory {mem.experience_id}: {w}")
                    elif mem.verified:
                        memory_influences.append(f"Retrieved verified baseline experience {mem.experience_id} for {mem.algorithm}")
                else:
                    rejected_memories.append(f"Rejected irrelevant memory {mem.experience_id} (relevance score {mem.relevance_score:.2f} < 0.5)")

        # 5. Summarize
        has_boundary = any(s.suggested_test_category == "boundary" for s in signals)
        has_adversarial = any(s.suggested_test_category == "adversarial" for s in signals)
        has_stress = any(s.suggested_test_category == "stress" for s in signals)
        has_off_by_one = any(s.risk_category == "OFF_BY_ONE" for s in signals)

        summary_parts = [f"Identified {len(signals)} risk signals"]
        if structural and structural.risk_notes:
            summary_parts.append(f"Structural signals: {len(structural.risk_notes)}")
        if memory_influences:
            summary_parts.append(f"Memory-informed signals: {len(memory_influences)}")

        return TestRiskAnalysis(
            problem_id=problem.id,
            identified_pattern=pattern,
            language=language,
            signals=signals,
            structural_risks=structural,
            memory_influences=memory_influences,
            rejected_memories=rejected_memories,
            has_boundary_risk=has_boundary,
            has_adversarial_risk=has_adversarial,
            has_stress_risk=has_stress,
            has_off_by_one_risk=has_off_by_one,
            summary="; ".join(summary_parts),
        )

    @classmethod
    def _extract_size_bounds(cls, constraints: List[str]) -> tuple[Optional[int], Optional[int]]:
        """Extracts (min_n, max_n) respecting explicit problem statements."""
        min_n = None
        max_n = None
        for c in constraints:
            stmt = c if isinstance(c, str) else getattr(c, "statement", "")
            # Look for 1 <= n <= 10^5 or 2 <= nums.length <= 1000
            m_range = re.search(r"(\d+)\s*<=\s*(?:[a-zA-Z._]+)\s*<=\s*(\d+(?:\^\d+)?)", stmt)
            if m_range:
                min_n = int(m_range.group(1))
                val_str = m_range.group(2)
                if "^" in val_str:
                    b, e = val_str.split("^", 1)
                    max_n = int(b) ** int(e)
                else:
                    max_n = int(val_str)
                break
        return min_n, max_n
