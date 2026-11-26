"""Solution Quality Analyzer & Complexity Review Engine.

Milestone 6.3.17: Solution Quality Analyzer & Complexity Review.
Provides:
1. Static code quality analysis:
   - Line counts, nesting depth, loop structure, branch complexity, function structure.
   - Python AST analysis where practical; conservative lexical/block analysis for C, C++, and Java.
2. Heuristic complexity review:
   - Time complexity estimation (O(1), O(log N), O(N), O(N log N), O(N^2), O(2^N), etc.) with clear evidential basis.
   - Space complexity estimation (O(1), O(N), etc.) with collection and recursive stack evidence.
   - Learner self-assessment comparison (learner estimate vs heuristic analyzer estimate).
3. Problem-solving quality checklist:
   - Edge cases, empty input, duplicates, large inputs, redundant operations, data structures, readability, explanation.
4. Objective scoring indicators:
   - Readability (0-100), Structural quality (0-100), Complexity awareness (0-100), and Correctness (when test run available).
5. Evidence-based improvement suggestions (excessive nesting, linear searches, sorting redundancy, unclear naming).
6. Multi-attempt comparison:
   - Compares current draft against previous drafts/runs (line changes, structure, errors, test pass rate).
7. Nondestructive persistence in session_tracking.db (`solution_reviews`).

100% offline, deterministic, zero external API calls, read-only on progress.db.
Never exposes reference solutions, hidden test cases, or unrestricted local paths.
"""

import ast
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from languages import LanguageSupport
from problems import load_problems
import store


@dataclass
class CodeQualityMetrics:
    """Static structural measurements of a solution code snippet."""
    lines_of_code: int
    blank_lines: int
    comment_lines: int
    function_count: int
    max_nesting_depth: int
    loop_count: int
    branch_count: int
    variable_naming_score: float        # 0.0 to 100.0 based on identifier clarity
    readability_score: float            # 0.0 to 100.0
    structural_score: float             # 0.0 to 100.0
    observations: List[str] = field(default_factory=list)


@dataclass
class ComplexityReview:
    """Heuristic time and space complexity evaluation and learner comparison."""
    estimated_time_complexity: str      # e.g., "O(N)", "O(N^2)", "O(log N)"
    estimated_space_complexity: str     # e.g., "O(1)", "O(N)"
    time_complexity_rationale: str
    space_complexity_rationale: str
    learner_time_estimate: Optional[str] = None
    learner_space_estimate: Optional[str] = None
    time_comparison: Optional[str] = None
    space_comparison: Optional[str] = None
    complexity_awareness_score: float = 75.0


@dataclass
class ProblemSolvingChecklist:
    """Configurable checklist covering essential algorithmic edge cases and techniques."""
    handles_empty_input: bool = False
    handles_edge_cases: bool = False
    handles_duplicates: bool = False
    handles_large_inputs: bool = False
    avoids_redundant_operations: bool = False
    uses_appropriate_data_structures: bool = False
    is_readable: bool = False
    approach_explained: bool = False

    @property
    def completed_count(self) -> int:
        return sum([
            self.handles_empty_input,
            self.handles_edge_cases,
            self.handles_duplicates,
            self.handles_large_inputs,
            self.avoids_redundant_operations,
            self.uses_appropriate_data_structures,
            self.is_readable,
            self.approach_explained,
        ])

    @property
    def total_count(self) -> int:
        return 8


@dataclass
class AttemptComparison:
    """Comparative analysis against previous drafts or test runs."""
    previous_attempt_found: bool = False
    previous_language: Optional[str] = None
    loc_delta: int = 0
    nesting_delta: int = 0
    correctness_status_previous: Optional[str] = None
    correctness_status_current: Optional[str] = None
    summary_of_changes: str = "No prior attempt available for comparison."


@dataclass
class SolutionReviewReport:
    """Comprehensive diagnostic solution quality and complexity review."""
    review_id: str
    problem_id: str
    problem_title: str
    language: str
    review_timestamp: str
    quality_metrics: CodeQualityMetrics
    complexity_review: ComplexityReview
    checklist: ProblemSolvingChecklist
    improvement_suggestions: List[str]
    attempt_comparison: AttemptComparison
    reflection_prompts: List[str]
    linked_run_id: Optional[str] = None
    test_run_status: Optional[str] = None
    overall_summary: str = ""


def _get_utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Standard time & space complexity notation normalization
COMPLEXITY_PATTERNS = {
    "o(1)": "O(1)",
    "constant": "O(1)",
    "o(log n)": "O(log N)",
    "o(logn)": "O(log N)",
    "logarithmic": "O(log N)",
    "o(n)": "O(N)",
    "linear": "O(N)",
    "o(n log n)": "O(N log N)",
    "o(nlogn)": "O(N log N)",
    "o(n^2)": "O(N^2)",
    "o(n2)": "O(N^2)",
    "quadratic": "O(N^2)",
    "o(2^n)": "O(2^N)",
    "exponential": "O(2^N)",
}


def normalize_complexity_str(val: Optional[str]) -> Optional[str]:
    """Normalize freeform complexity strings like 'o(n)', 'O(N)', or 'linear'."""
    if not val or not val.strip():
        return None
    cleaned = val.strip().lower()
    return COMPLEXITY_PATTERNS.get(cleaned, val.strip())


class SolutionReviewEngine:
    """Deterministic, offline analyzer for code quality, structural metrics, and complexity review."""

    def __init__(
        self,
        tracking_db_path: Optional[str | Path] = None,
        progress_db_path: Optional[str | Path] = None,
    ):
        self.tracking_db_path = Path(tracking_db_path) if tracking_db_path is not None else DEFAULT_TRACKING_DB_PATH
        self.progress_db_path = progress_db_path
        self.init_schema()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.tracking_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """Create solution_reviews table in session_tracking.db safely."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS solution_reviews (
                    review_id TEXT PRIMARY KEY,
                    problem_id TEXT NOT NULL,
                    language TEXT NOT NULL,
                    review_timestamp TEXT NOT NULL,
                    quality_metrics_json TEXT NOT NULL,
                    complexity_review_json TEXT NOT NULL,
                    checklist_json TEXT NOT NULL,
                    improvement_suggestions_json TEXT NOT NULL,
                    attempt_comparison_json TEXT NOT NULL,
                    reflection_prompts_json TEXT NOT NULL,
                    linked_run_id TEXT,
                    test_run_status TEXT,
                    overall_summary TEXT NOT NULL
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_pid ON solution_reviews(problem_id)")
            conn.commit()

    # -------------------------------------------------------------------------
    # Static Code Quality Analysis
    # -------------------------------------------------------------------------

    def analyze_code_quality(self, code: str, language: str) -> CodeQualityMetrics:
        """Analyze structural quality, length, loops, nesting, and naming."""
        if not code or not code.strip():
            return CodeQualityMetrics(
                lines_of_code=0,
                blank_lines=0,
                comment_lines=0,
                function_count=0,
                max_nesting_depth=0,
                loop_count=0,
                branch_count=0,
                variable_naming_score=0.0,
                readability_score=0.0,
                structural_score=0.0,
                observations=["Code editor is empty."],
            )

        norm_lang = LanguageSupport.normalize_language(language)
        lines = code.split("\n")
        total_lines = len(lines)
        blank_lines = sum(1 for line in lines if not line.strip())

        # Comments count
        comment_lines = 0
        for line in lines:
            s = line.strip()
            if norm_lang == "python" and s.startswith("#"):
                comment_lines += 1
            elif norm_lang in ("c", "cpp", "java") and (s.startswith("//") or s.startswith("/*") or s.startswith("*")):
                comment_lines += 1

        loc = max(1, total_lines - blank_lines - comment_lines)

        if norm_lang == "python":
            return self._analyze_python_ast(code, loc, blank_lines, comment_lines)
        else:
            return self._analyze_c_family(code, norm_lang, loc, blank_lines, comment_lines)

    def _analyze_python_ast(self, code: str, loc: int, blank_lines: int, comment_lines: int) -> CodeQualityMetrics:
        """Analyze Python code using AST and lexical indentation analysis."""
        observations = []
        function_count = 0
        loop_count = 0
        branch_count = 0
        max_depth = 0
        identifiers = []

        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function_count += 1
                    identifiers.append(node.name)
                elif isinstance(node, (ast.For, ast.While)):
                    loop_count += 1
                elif isinstance(node, (ast.If, ast.IfExp)):
                    branch_count += 1
                elif isinstance(node, ast.Name):
                    identifiers.append(node.id)

            # Compute nesting depth by inspecting AST child nodes
            def get_nesting(node, current_depth=0):
                d = current_depth
                is_nesting_construct = isinstance(node, (ast.FunctionDef, ast.For, ast.While, ast.If, ast.With, ast.Try))
                next_d = current_depth + 1 if is_nesting_construct else current_depth
                max_d = next_d
                for child in ast.iter_child_nodes(node):
                    max_d = max(max_d, get_nesting(child, next_d))
                return max_d

            max_depth = max(0, get_nesting(tree) - 1)

        except SyntaxError as e:
            observations.append(f"Syntax issue detected during AST parsing (line {e.lineno}). Falling back to lexical scan.")
            # Fallback to indentation-based depth
            for line in code.split("\n"):
                stripped = line.lstrip()
                if stripped and not stripped.startswith("#"):
                    indent = len(line) - len(stripped)
                    depth = indent // 4
                    if depth > max_depth:
                        max_depth = depth
            loop_count = len(re.findall(r"\b(for|while)\b", code))
            branch_count = len(re.findall(r"\b(if|elif)\b", code))
            function_count = len(re.findall(r"\bdef\s+\w+", code))

        # Variable naming evaluation
        clean_ids = [i for i in identifiers if not i.startswith("__") and i not in ("self", "cls")]
        single_letter = sum(1 for i in clean_ids if len(i) == 1 and i not in ("i", "j", "k", "n", "m", "s", "t"))
        naming_score = 90.0
        if clean_ids:
            ratio = single_letter / len(clean_ids)
            naming_score = max(50.0, round(90.0 - (ratio * 40.0), 1))

        # Structural & Readability scores
        structural_score = 100.0
        if max_depth >= 4:
            structural_score -= 20.0
            observations.append(f"Deep nesting detected (depth {max_depth}). Consider refactoring or early returns.")
        elif max_depth >= 3:
            structural_score -= 10.0
            observations.append(f"Moderate nesting (depth {max_depth}).")

        if loc > 60:
            structural_score -= 15.0
            observations.append(f"Solution length ({loc} LOC) is long for a standard algorithm problem.")

        readability_score = round(min(100.0, max(40.0, (structural_score * 0.6) + (naming_score * 0.4))), 1)
        structural_score = round(min(100.0, max(40.0, structural_score)), 1)

        if not observations:
            observations.append("Clean function and control structure with well-bounded nesting.")

        return CodeQualityMetrics(
            lines_of_code=loc,
            blank_lines=blank_lines,
            comment_lines=comment_lines,
            function_count=function_count,
            max_nesting_depth=max_depth,
            loop_count=loop_count,
            branch_count=branch_count,
            variable_naming_score=naming_score,
            readability_score=readability_score,
            structural_score=structural_score,
            observations=observations,
        )

    def _analyze_c_family(self, code: str, lang: str, loc: int, blank_lines: int, comment_lines: int) -> CodeQualityMetrics:
        """Conservative lexical and block analysis for C, C++, and Java."""
        observations = []
        loop_count = len(re.findall(r"\b(for|while|do)\b", code))
        branch_count = len(re.findall(r"\b(if|else if|switch)\b", code))
        function_count = len(re.findall(r"\b(int|void|bool|char|double|long|auto|public|private|def)\s+\w+\s*\(", code))

        # Compute block nesting depth via curly braces
        max_depth = 0
        curr_depth = 0
        for char in code:
            if char == "{":
                curr_depth += 1
                if curr_depth > max_depth:
                    max_depth = curr_depth
            elif char == "}":
                curr_depth = max(0, curr_depth - 1)

        structural_score = 100.0
        if max_depth >= 4:
            structural_score -= 20.0
            observations.append(f"Deep block nesting detected (depth {max_depth}). Consider breaking into helper routines.")
        elif max_depth >= 3:
            structural_score -= 10.0
            observations.append(f"Moderate nesting (depth {max_depth}).")

        if loc > 80:
            structural_score -= 15.0
            observations.append(f"Code size ({loc} LOC) is extensive.")

        naming_score = 85.0
        readability_score = round(min(100.0, max(40.0, (structural_score * 0.7) + (naming_score * 0.3))), 1)
        structural_score = round(min(100.0, max(40.0, structural_score)), 1)

        if not observations:
            observations.append(f"Standard {lang.upper()} modular structure with clean control flow.")

        return CodeQualityMetrics(
            lines_of_code=loc,
            blank_lines=blank_lines,
            comment_lines=comment_lines,
            function_count=max(1, function_count),
            max_nesting_depth=max_depth,
            loop_count=loop_count,
            branch_count=branch_count,
            variable_naming_score=naming_score,
            readability_score=readability_score,
            structural_score=structural_score,
            observations=observations,
        )

    # -------------------------------------------------------------------------
    # Heuristic Complexity Review
    # -------------------------------------------------------------------------

    def review_complexity(
        self,
        code: str,
        language: str,
        learner_time: Optional[str] = None,
        learner_space: Optional[str] = None,
    ) -> ComplexityReview:
        """Heuristically estimate time and space complexity with documented evidence."""
        norm_lang = LanguageSupport.normalize_language(language)
        code_low = code.lower()

        # 1. Time Complexity Estimation
        # Check for nested loops
        has_nested_loops = False
        loop_matches = list(re.finditer(r"\b(for|while)\b", code_low))
        loop_count = len(loop_matches)

        if loop_count >= 2:
            # Check indentation or block nesting between loops
            for i in range(len(loop_matches) - 1):
                start1 = loop_matches[i].start()
                start2 = loop_matches[i+1].start()
                sub = code[start1:start2]
                if "{" in sub or "\n    " in sub:
                    has_nested_loops = True
                    break

        has_sorting = bool(re.search(r"(\.sort\(|sorted\(|std::sort|arrays\.sort|qsort)", code_low))
        has_binary_search = bool(re.search(r"\b(mid|left <= right|low <= high|binary_search|bisect)\b", code_low))
        has_recursion = bool(re.search(r"(\bself\.\w+\(.*\)|def\s+(\w+).*?\b\2\()", code_low))

        if has_nested_loops:
            est_time = "O(N^2)"
            time_reason = "Heuristic estimate based on nested loop structures detected in traversal."
        elif has_sorting:
            est_time = "O(N log N)"
            time_reason = "Heuristic estimate based on comparison-based sorting invocation."
        elif has_binary_search:
            est_time = "O(log N)"
            time_reason = "Heuristic estimate based on binary search midpoint halving logic."
        elif loop_count == 1:
            est_time = "O(N)"
            time_reason = "Heuristic estimate based on a single linear pass or loop over elements."
        else:
            est_time = "O(1)"
            time_reason = "Heuristic estimate based on constant-time direct indexing without loops."

        # 2. Space Complexity Estimation
        has_collections = bool(re.search(r"(\{\}|set\(|dict\(|list\(|\[\]|hashmap|hashset|vector<|arraylist)", code_low))
        if has_recursion:
            est_space = "O(N)"
            space_reason = "Heuristic estimate based on recursive call stack depth."
        elif has_collections and est_time in ("O(N)", "O(N^2)", "O(N log N)"):
            est_space = "O(N)"
            space_reason = "Heuristic estimate based on dynamic collection (hash table, list, set) storage."
        else:
            est_space = "O(1)"
            space_reason = "Heuristic estimate based on auxiliary variables and in-place operations."

        # 3. Learner Self-Assessment Comparison
        norm_learner_time = normalize_complexity_str(learner_time)
        norm_learner_space = normalize_complexity_str(learner_space)

        time_comp = None
        if norm_learner_time:
            if norm_learner_time.upper() == est_time.upper():
                time_comp = f"Matches heuristic analyzer assessment ({est_time}). Accurate complexity awareness!"
            else:
                time_comp = f"Your estimate ({norm_learner_time}) differs from analyzer estimate ({est_time}). {time_reason}"

        space_comp = None
        if norm_learner_space:
            if norm_learner_space.upper() == est_space.upper():
                space_comp = f"Matches heuristic analyzer assessment ({est_space}). Accurate auxiliary space awareness!"
            else:
                space_comp = f"Your estimate ({norm_learner_space}) differs from analyzer estimate ({est_space}). {space_reason}"

        awareness_score = 75.0
        if norm_learner_time and norm_learner_space:
            awareness_score = 95.0 if (time_comp and "Matches" in time_comp and space_comp and "Matches" in space_comp) else 85.0
        elif norm_learner_time or norm_learner_space:
            awareness_score = 80.0

        return ComplexityReview(
            estimated_time_complexity=est_time,
            estimated_space_complexity=est_space,
            time_complexity_rationale=time_reason,
            space_complexity_rationale=space_reason,
            learner_time_estimate=norm_learner_time,
            learner_space_estimate=norm_learner_space,
            time_comparison=time_comp,
            space_comparison=space_comp,
            complexity_awareness_score=awareness_score,
        )

    # -------------------------------------------------------------------------
    # Improvement Suggestions
    # -------------------------------------------------------------------------

    def generate_suggestions(
        self,
        metrics: CodeQualityMetrics,
        complexity: ComplexityReview,
        test_status: Optional[str] = None,
    ) -> List[str]:
        """Generate deterministic, evidence-based improvement recommendations."""
        suggestions = []

        if test_status and test_status != "passed":
            if test_status == "wrong_answer":
                suggestions.append("Check edge cases: Verify off-by-one bounds, zero values, or duplicate input elements.")
            elif test_status == "compile_error":
                suggestions.append("Address syntax or type mismatches identified in compilation diagnostics.")
            elif test_status == "timeout":
                suggestions.append("Potential TLE: Look for unreduced search spaces or infinite loop conditions.")

        if metrics.max_nesting_depth >= 4:
            suggestions.append("Refactor deep nesting using early returns or breaking nested logic into smaller functions.")

        if complexity.estimated_time_complexity == "O(N^2)" and "nested loop" in complexity.time_complexity_rationale.lower():
            suggestions.append("Explore whether a hash map or two-pointer approach can reduce O(N^2) loop nesting to O(N).")

        if metrics.variable_naming_score < 75.0:
            suggestions.append("Enhance identifier clarity by replacing non-standard single-character variables with descriptive names.")

        if not suggestions:
            suggestions.append("Code demonstrates solid efficiency and maintainability. Consider testing with large stress inputs.")

        return suggestions

    # -------------------------------------------------------------------------
    # Multi-Attempt Comparison
    # -------------------------------------------------------------------------

    def compare_with_previous(
        self,
        problem_id: str,
        current_metrics: CodeQualityMetrics,
        current_test_status: Optional[str],
    ) -> AttemptComparison:
        """Compare current solution against the most recent prior review for this problem."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM solution_reviews WHERE problem_id = ? ORDER BY review_timestamp DESC LIMIT 1",
                (problem_id,),
            )
            row = cursor.fetchone()

        if not row:
            return AttemptComparison(
                previous_attempt_found=False,
                summary_of_changes="First recorded solution review for this problem.",
            )

        try:
            prev_metrics = json.loads(row["quality_metrics_json"])
            prev_loc = prev_metrics.get("lines_of_code", current_metrics.lines_of_code)
            prev_depth = prev_metrics.get("max_nesting_depth", current_metrics.max_nesting_depth)
        except Exception:
            prev_loc = current_metrics.lines_of_code
            prev_depth = current_metrics.max_nesting_depth

        loc_delta = current_metrics.lines_of_code - prev_loc
        nesting_delta = current_metrics.max_nesting_depth - prev_depth
        prev_status = row["test_run_status"]

        summary_parts = []
        if loc_delta > 0:
            summary_parts.append(f"Code size increased by {loc_delta} lines.")
        elif loc_delta < 0:
            summary_parts.append(f"Code compacted by {abs(loc_delta)} lines.")
        else:
            summary_parts.append("Code length remained steady.")

        if nesting_delta < 0:
            summary_parts.append(f"Nesting reduced by {abs(nesting_delta)} level(s) (positive refactoring).")
        elif nesting_delta > 0:
            summary_parts.append(f"Nesting increased by {nesting_delta} level(s).")

        if prev_status and current_test_status:
            if prev_status != "passed" and current_test_status == "passed":
                summary_parts.append("Correctness progressed from failure to fully passed! 🏆")
            elif prev_status == current_test_status:
                summary_parts.append(f"Test status consistent ({current_test_status}).")

        return AttemptComparison(
            previous_attempt_found=True,
            previous_language=row["language"],
            loc_delta=loc_delta,
            nesting_delta=nesting_delta,
            correctness_status_previous=prev_status,
            correctness_status_current=current_test_status,
            summary_of_changes=" ".join(summary_parts),
        )

    # -------------------------------------------------------------------------
    # Comprehensive Review Workflow
    # -------------------------------------------------------------------------

    def review_solution(
        self,
        problem_id: str,
        code: str,
        language: str = "python",
        linked_run_id: Optional[str] = None,
        learner_time: Optional[str] = None,
        learner_space: Optional[str] = None,
        checklist_overrides: Optional[Dict[str, bool]] = None,
    ) -> SolutionReviewReport:
        """Perform comprehensive static analysis, complexity review, and reflection synthesis."""
        all_problems = load_problems()
        p = next((prob for prob in all_problems if prob.get("id") == problem_id), None)
        title = p.get("title", problem_id.replace("-", " ").title()) if p else problem_id

        norm_lang = LanguageSupport.normalize_language(language)
        metrics = self.analyze_code_quality(code, norm_lang)
        complexity = self.review_complexity(code, norm_lang, learner_time, learner_space)

        # Query test run outcome if linked
        test_status = None
        if linked_run_id:
            with self.get_connection() as conn:
                cur = conn.cursor()
                tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if "workspace_runs" in tables:
                    cur.execute("SELECT status FROM workspace_runs WHERE run_id = ?", (linked_run_id,))
                    row = cur.fetchone()
                    if row:
                        test_status = row["status"]

        # Checklist initialization
        checklist_kwargs = {}
        if checklist_overrides:
            for k, v in checklist_overrides.items():
                if hasattr(ProblemSolvingChecklist, k):
                    checklist_kwargs[k] = bool(v)
        else:
            # Auto-infer baseline checklist answers from code features
            checklist_kwargs = {
                "handles_empty_input": bool(re.search(r"\b(if not|len\(|== 0|null|nullptr|empty\(\))\b", code.lower())),
                "uses_appropriate_data_structures": bool(re.search(r"(\{\}|set|dict|hashmap|vector)", code.lower())),
                "is_readable": metrics.readability_score >= 70.0,
                "avoids_redundant_operations": metrics.max_nesting_depth <= 2,
            }
        checklist = ProblemSolvingChecklist(**checklist_kwargs)

        suggestions = self.generate_suggestions(metrics, complexity, test_status)
        attempt_comp = self.compare_with_previous(problem_id, metrics, test_status)

        # Reflection prompts
        reflection_prompts = [
            f"Can the {complexity.estimated_time_complexity} time complexity be improved using additional memory (time-space tradeoff)?",
            "What input edge case could potentially trigger unexpected output or exceptions?",
            "How would you explain the intuition behind this algorithm to an interviewer in under 60 seconds?",
        ]

        overall_summary = (
            f"Review for '{title}': {metrics.lines_of_code} LOC, max depth {metrics.max_nesting_depth}, "
            f"estimated time {complexity.estimated_time_complexity}, space {complexity.estimated_space_complexity}. "
            f"Readability score: {metrics.readability_score}/100."
        )

        review_id = f"rev_{uuid.uuid4().hex[:10]}"
        now_str = _get_utc_now_iso()

        report = SolutionReviewReport(
            review_id=review_id,
            problem_id=problem_id,
            problem_title=title,
            language=norm_lang,
            review_timestamp=now_str,
            quality_metrics=metrics,
            complexity_review=complexity,
            checklist=checklist,
            improvement_suggestions=suggestions,
            attempt_comparison=attempt_comp,
            reflection_prompts=reflection_prompts,
            linked_run_id=linked_run_id,
            test_run_status=test_status,
            overall_summary=overall_summary,
        )

        # Persist review
        self._save_review(report)
        return report

    def _save_review(self, report: SolutionReviewReport) -> None:
        """Persist review report to session_tracking.db."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO solution_reviews (
                    review_id, problem_id, language, review_timestamp, quality_metrics_json,
                    complexity_review_json, checklist_json, improvement_suggestions_json,
                    attempt_comparison_json, reflection_prompts_json, linked_run_id,
                    test_run_status, overall_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.review_id,
                    report.problem_id,
                    report.language,
                    report.review_timestamp,
                    json.dumps(asdict(report.quality_metrics)),
                    json.dumps(asdict(report.complexity_review)),
                    json.dumps(asdict(report.checklist)),
                    json.dumps(report.improvement_suggestions),
                    json.dumps(asdict(report.attempt_comparison)),
                    json.dumps(report.reflection_prompts),
                    report.linked_run_id,
                    report.test_run_status,
                    report.overall_summary,
                ),
            )
            conn.commit()

    def get_review(self, review_id: str) -> Optional[SolutionReviewReport]:
        """Fetch saved solution review by review_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM solution_reviews WHERE review_id = ?", (review_id,))
            row = cursor.fetchone()
            if not row:
                return None

        return SolutionReviewReport(
            review_id=row["review_id"],
            problem_id=row["problem_id"],
            problem_title=row["problem_id"].replace("-", " ").title(),
            language=row["language"],
            review_timestamp=row["review_timestamp"],
            quality_metrics=CodeQualityMetrics(**json.loads(row["quality_metrics_json"])),
            complexity_review=ComplexityReview(**json.loads(row["complexity_review_json"])),
            checklist=ProblemSolvingChecklist(**json.loads(row["checklist_json"])),
            improvement_suggestions=json.loads(row["improvement_suggestions_json"]),
            attempt_comparison=AttemptComparison(**json.loads(row["attempt_comparison_json"])),
            reflection_prompts=json.loads(row["reflection_prompts_json"]),
            linked_run_id=row["linked_run_id"],
            test_run_status=row["test_run_status"],
            overall_summary=row["overall_summary"],
        )

    def list_review_history(self, problem_id: Optional[str] = None, limit: int = 10) -> List[SolutionReviewReport]:
        """Fetch review history ordered by timestamp."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if problem_id:
                cursor.execute(
                    "SELECT review_id FROM solution_reviews WHERE problem_id = ? ORDER BY review_timestamp DESC LIMIT ?",
                    (problem_id.strip(), limit),
                )
            else:
                cursor.execute("SELECT review_id FROM solution_reviews ORDER BY review_timestamp DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            rev = self.get_review(r["review_id"])
            if rev:
                results.append(rev)
        return results
