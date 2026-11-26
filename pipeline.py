"""Autonomous Problem-Solving Pipeline for LeetCode Agent.

Provides a modular, provider-independent offline/online pipeline with distinct stages:
1. Problem selection from queue (custom or curated)
2. Requirements & metadata normalization
3. Solution generation via provider interface (real LLM or deterministic mock)
4. Local compilation & subprocess execution (UnifiedJudge)
5. Test-result evaluation
6. Failure classification (wrong_answer, compile_error, runtime_error, timeout)
7. Correction-cycle orchestration (retry prompt formatting & feedback loop)
8. Verification after correction (only marked verified if all tests pass locally)
9. Progress & attempt persistence (language-isolated SQLite)
10. Queue advancement and lifecycle reporting
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import time

import adapters
from judge import run_solution
import memory
from problems import load_problems
from prompts import (
    build_initial_prompt,
    build_retry_prompt,
    extract_code,
    get_system_prompt_for_language,
)
import store


class PipelineStage(str, Enum):
    IDLE = "idle"
    SELECTING = "selecting"
    LOADING = "loading"
    GENERATING = "generating"
    EXECUTING = "executing"
    EVALUATING = "evaluating"
    DIAGNOSING = "diagnosing"
    CORRECTING = "correcting"
    RECORDING = "recording"
    COMPLETED = "completed"
    FAILED = "failed"


class FailureCategory(str, Enum):
    NONE = "none"
    COMPILE_ERROR = "compile_error"
    RUNTIME_ERROR = "runtime_error"
    WRONG_ANSWER = "wrong_answer"
    TIMEOUT = "timeout"
    NO_CODE = "no_code"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    UNKNOWN = "unknown"


@dataclass
class StageResult:
    stage: PipelineStage
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ProblemExecutionResult:
    problem_id: str
    title: str
    language: str
    passed: bool
    attempts_used: int
    max_attempts: int
    final_verdict: str
    tests_passed: int
    total_tests: int
    final_code: str
    failure_category: FailureCategory
    error_details: Optional[str]
    elapsed_seconds: float
    history: List[Dict[str, Any]] = field(default_factory=list)


class MockSolutionGenerator:
    """Deterministic, provider-independent mock generator for offline pipeline testing.
    
    Supports scripted behavior per problem:
    - sequence of simulated responses (e.g. compile_error code -> wrong_answer code -> passing code)
    - deterministic attempt counts
    - failure simulation without live network calls
    """
    def __init__(self, scripts: Optional[Dict[str, List[str]]] = None):
        # scripts maps problem_id -> list of raw code or response strings per attempt
        self.scripts: Dict[str, List[str]] = scripts or {}
        self.call_history: List[Dict[str, Any]] = []
        self._attempt_counters: Dict[str, int] = {}

    def generate(self, problem: Dict[str, Any], attempt_no: int, language: str = "python", feedback: Optional[Dict[str, Any]] = None) -> str:
        prob_id = problem.get("id", "unknown")
        fn_name = problem.get("function_name", "solve")
        self.call_history.append({
            "problem_id": prob_id,
            "attempt_no": attempt_no,
            "language": language,
            "feedback": feedback,
        })
        
        # Check custom scripted response
        if prob_id in self.scripts and self.scripts[prob_id]:
            script_list = self.scripts[prob_id]
            idx = min(attempt_no - 1, len(script_list) - 1)
            raw = script_list[idx]
            if "```" in raw:
                return raw
            return f"```{language}\n{raw}\n```"

        # Default deterministic behavior:
        # Attempt 1: wrong answer stub
        # Attempt 2: reference solution if available, else empty stub
        if attempt_no == 1:
            if language in ["c"]:
                return f"```c\nint {fn_name}(void) {{ return -999999; }}\n```"
            elif language in ["cpp"]:
                return f"```cpp\nclass Solution {{\npublic:\n    int {fn_name}() {{ return -999999; }}\n}};\n```"
            elif language in ["java"]:
                return f"```java\nclass Solution {{\n    public int {fn_name}() {{ return -999999; }}\n}}\n```"
            return f"```python\ndef {fn_name}(*args, **kwargs):\n    return -999999\n```"
        else:
            ref = problem.get("reference_solution") or problem.get("reference_solutions", {}).get(language)
            if ref:
                return f"```{language}\n{ref.strip()}\n```"
            if language in ["c"]:
                return f"```c\nint {fn_name}(void) {{\n    return 0;\n}}\n```"
            elif language in ["cpp"]:
                return f"```cpp\nclass Solution {{\npublic:\n    int {fn_name}() {{\n        return 0;\n    }}\n}};\n```"
            elif language in ["java"]:
                return f"```java\nclass Solution {{\n    public int {fn_name}() {{\n        return 0;\n    }}\n}}\n```"
            return f"```python\ndef {fn_name}(*args, **kwargs):\n    return None\n```"


class AutonomousPipeline:
    """Modular, 10-stage autonomous problem-solving pipeline."""

    def __init__(
        self,
        generator: Any,
        db_path: Optional[str | Path] = None,
        language: str = "python",
        max_attempts: int = 3,
        timeout_seconds: int = 10,
        on_stage_change: Optional[Callable[[PipelineStage, Dict[str, Any]], None]] = None,
    ):
        self.generator = generator
        self.db_path = db_path
        self.language = (language or "python").strip().lower()
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.on_stage_change = on_stage_change
        self.current_stage = PipelineStage.IDLE

    def _set_stage(self, stage: PipelineStage, data: Optional[Dict[str, Any]] = None):
        self.current_stage = stage
        if self.on_stage_change:
            self.on_stage_change(stage, data or {})

    # Stage 1: Select problems from queue
    def select_queue(
        self,
        max_problems: int = 5,
        difficulty: Optional[str] = None,
        problem_ids: Optional[List[str]] = None,
        skip_solved: bool = True,
    ) -> List[Dict[str, Any]]:
        self._set_stage(PipelineStage.SELECTING, {"max_problems": max_problems, "difficulty": difficulty})
        store.init(db_path=self.db_path)
        custom_list = store.list_custom_problems(db_path=self.db_path)
        built_in = load_problems()

        if problem_ids:
            selected = []
            for pid in problem_ids:
                prob = store.get_custom_problem(pid, db_path=self.db_path)
                if not prob:
                    prob = next((b for b in built_in if b["id"] == pid), None)
                if prob:
                    if not (skip_solved and store.is_solved(pid, language=self.language, db_path=self.db_path)):
                        selected.append(prob)
            return selected[:max_problems]

        candidates = []
        seen = set()
        for cp in custom_list:
            pid = cp["id"]
            if pid not in seen:
                seen.add(pid)
                p = store.get_custom_problem(pid, db_path=self.db_path)
                if p:
                    candidates.append(p)
        for bp in built_in:
            pid = bp["id"]
            if pid not in seen:
                seen.add(pid)
                candidates.append(bp)

        if difficulty:
            d_norm = difficulty.strip().lower()
            candidates = [p for p in candidates if p.get("difficulty", "").lower() == d_norm]

        # Use ProblemSelector for deterministic prioritization
        from intelligence.selector import ProblemSelector
        selector = ProblemSelector(
            db_path=self.db_path,
            language=self.language,
            preferred_difficulty=difficulty,
        )
        prioritized = selector.prioritize_candidates(
            candidates,
            skip_solved=skip_solved,
            max_problems=max_problems,
        )
        return [p for p, _ in prioritized]

    # Stage 6: Classify failure
    @staticmethod
    def classify_failure(judge_status: str, error_text: Optional[str] = None) -> FailureCategory:
        s = (judge_status or "").lower()
        if s == "compile_error":
            return FailureCategory.COMPILE_ERROR
        if s == "runtime_error":
            return FailureCategory.RUNTIME_ERROR
        if s == "wrong_answer":
            return FailureCategory.WRONG_ANSWER
        if s == "timeout":
            return FailureCategory.TIMEOUT
        if s == "no_code":
            return FailureCategory.NO_CODE
        if s == "runtime_unavailable":
            return FailureCategory.RUNTIME_UNAVAILABLE
        if s == "passed":
            return FailureCategory.NONE
        return FailureCategory.UNKNOWN

    # Stages 2 - 9: Process single problem through generation-execution-diagnosis-repair loop
    def process_problem(self, problem: Dict[str, Any]) -> ProblemExecutionResult:
        start_time = time.time()
        prob_id = problem["id"]
        title = problem.get("title", prob_id)
        total_tests = len(problem.get("tests", []))

        # Ensure problem signature is never None for downstream runners/judges
        if problem.get("signature") is None:
            problem = dict(problem)
            problem["signature"] = ""

        store.init(db_path=self.db_path)
        learning_items = memory.retrieve_relevant_learning(problem, limit=3, db_path=self.db_path)
        learning_context = memory.format_learning_context(learning_items)

        history: List[Dict[str, Any]] = []
        last_code = ""
        last_judge_res: Dict[str, Any] = {}
        passed = False
        final_failure_category = FailureCategory.NONE

        for attempt_no in range(1, self.max_attempts + 1):
            # Stage 2 & 3: Requirement building & solution generation
            if attempt_no == 1:
                self._set_stage(PipelineStage.GENERATING, {"problem_id": prob_id, "attempt": attempt_no})
                base_prompt = build_initial_prompt(problem, self.language)
                user_prompt = f"{learning_context}\n\n{base_prompt}" if learning_context else base_prompt
                feedback_context = None
            else:
                self._set_stage(PipelineStage.CORRECTING, {"problem_id": prob_id, "attempt": attempt_no})
                user_prompt = build_retry_prompt(
                    problem=problem,
                    previous_code=last_code,
                    judge_status=last_judge_res.get("status", "error"),
                    failure_details=last_judge_res.get("failure"),
                    error_trace=last_judge_res.get("error"),
                )
                feedback_context = {
                    "judge_status": last_judge_res.get("status"),
                    "failure": last_judge_res.get("failure"),
                    "error": last_judge_res.get("error"),
                }

            # Generate candidate code via generator interface
            if hasattr(self.generator, "generate"):
                raw_response = self.generator.generate(
                    problem=problem,
                    attempt_no=attempt_no,
                    language=self.language,
                    feedback=feedback_context,
                )
            elif hasattr(self.generator, "ask"):
                sys_prompt = get_system_prompt_for_language(self.language)
                raw_response = self.generator.ask(sys_prompt, user_prompt)
            else:
                raise ValueError("Generator must implement generate() or ask() method.")

            code = extract_code(raw_response)
            last_code = code

            # Stage 4: Local Compilation & Subprocess Execution
            self._set_stage(PipelineStage.EXECUTING, {"problem_id": prob_id, "attempt": attempt_no})
            judge_res = run_solution(code, problem, language=self.language, timeout=self.timeout_seconds)
            last_judge_res = judge_res

            # Stage 5 & 6: Test evaluation & failure classification
            self._set_stage(PipelineStage.EVALUATING, {"problem_id": prob_id, "attempt": attempt_no})
            status = judge_res.get("status", "error")
            err_text = judge_res.get("error")
            fail_cat = self.classify_failure(status, err_text)
            final_failure_category = fail_cat

            # Stage 9: Record attempt in SQLite
            self._set_stage(PipelineStage.RECORDING, {"problem_id": prob_id, "attempt": attempt_no})
            store.log_attempt(
                problem_id=prob_id,
                attempt_no=attempt_no,
                code=code,
                status=status,
                error=err_text,
                db_path=self.db_path,
            )

            history.append({
                "attempt_no": attempt_no,
                "status": status,
                "failure_category": fail_cat.value,
                "passed_count": judge_res.get("passed_count", 0),
                "total_tests": judge_res.get("total", total_tests),
                "error": err_text,
                "code": code,
            })

            # Stage 8: Verification
            if status == "passed":
                passed = True
                store.mark_result(prob_id, "solved", attempt_no, language=self.language, db_path=self.db_path)
                break

        if not passed:
            store.mark_result(prob_id, "failed", self.max_attempts, language=self.language, db_path=self.db_path)
            self._set_stage(PipelineStage.FAILED, {"problem_id": prob_id})
        else:
            self._set_stage(PipelineStage.COMPLETED, {"problem_id": prob_id})

        elapsed = time.time() - start_time
        return ProblemExecutionResult(
            problem_id=prob_id,
            title=title,
            language=self.language,
            passed=passed,
            attempts_used=len(history),
            max_attempts=self.max_attempts,
            final_verdict="locally_verified" if passed else last_judge_res.get("status", "failed"),
            tests_passed=last_judge_res.get("passed_count", 0),
            total_tests=last_judge_res.get("total", total_tests),
            final_code=last_code,
            failure_category=final_failure_category,
            error_details=last_judge_res.get("error"),
            elapsed_seconds=elapsed,
            history=history,
        )

    # Stage 10: Queue advancement & batch execution
    def run_queue(
        self,
        max_problems: int = 5,
        difficulty: Optional[str] = None,
        problem_ids: Optional[List[str]] = None,
        skip_solved: bool = True,
    ) -> List[ProblemExecutionResult]:
        problems = self.select_queue(
            max_problems=max_problems,
            difficulty=difficulty,
            problem_ids=problem_ids,
            skip_solved=skip_solved,
        )
        results: List[ProblemExecutionResult] = []
        for problem in problems:
            res = self.process_problem(problem)
            results.append(res)
        return results
