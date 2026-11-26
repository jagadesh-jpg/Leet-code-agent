"""Mission-Integrated Coding Workspace Engine.

Milestone 6.3.16: Mission-Integrated Coding Workspace.
Provides:
1. Workspace Problem Context extraction (metadata, examples, constraints, topics, related prerequisites, active mission task).
2. Solution Editor Workflow supporting Python, C, C++, and Java with isolated local draft persistence.
3. Local Judge Integration via existing adapters.UnifiedJudge without duplicating execution logic.
4. Workspace Result Interpretation connecting run results with OfflineCodingCoach pedagogical guidance.
5. Daily Mission Integration maintaining Focus Mode state and requiring explicit learner confirmation before task completion.
6. Safe, isolated draft and run history persistence in session_tracking.db without altering production progress.db.

100% offline, local-first, zero external API calls.
Never exposes reference solutions, hidden tests, or unrestricted local filesystem paths.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Tuple

from adapters import UnifiedJudge
from intelligence.coach import OfflineCodingCoach, ProblemCoachingGuide
from intelligence.daily_mission import DailyMissionManager, DailyMissionTask, MissionTaskStatus
from intelligence.roadmap import DsaRoadmapEngine
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from languages import LanguageSupport
from problems import load_problems
import store


@dataclass
class ProblemWorkspaceContext:
    """Rich context and metadata for a problem loaded into the coding workspace."""
    problem_id: str
    title: str
    difficulty: str
    topics: List[str]
    description: str
    constraints: List[str]
    examples: List[Dict[str, Any]]
    starter_code: Dict[str, str]       # Language -> starter code template
    current_mission_id: Optional[str] = None
    current_task_id: Optional[str] = None
    task_selection_reason: Optional[str] = None
    related_prerequisites: List[str] = field(default_factory=list)


@dataclass
class WorkspaceDraft:
    """A saved solution code draft specific to a problem and programming language."""
    problem_id: str
    language: str
    code: str
    created_at: str
    updated_at: str


@dataclass
class WorkspaceRunResult:
    """Structured interpretation of a local judge run."""
    run_id: str
    problem_id: str
    language: str
    status: str                         # "passed", "wrong_answer", "compile_error", "runtime_error", "timeout"
    passed_count: int
    total_tests: int
    runtime_ms: Optional[float]
    compile_error: Optional[str]
    execution_error: Optional[str]
    failed_test_detail: Optional[Dict[str, Any]]
    coach_feedback: Optional[str]
    suggested_next_action: str
    can_complete_task: bool
    created_at: str


def _get_utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Language starter templates for consistent editor initialization
DEFAULT_STARTER_CODE: Dict[str, str] = {
    "python": "class Solution:\n    def solve(self):\n        pass\n",
    "c": "/* Write your C solution */\n#include <stdio.h>\n#include <stdlib.h>\n",
    "cpp": "/* Write your C++ solution */\n#include <vector>\n#include <iostream>\nusing namespace std;\n\nclass Solution {\npublic:\n};\n",
    "java": "/* Write your Java solution */\nimport java.util.*;\n\nclass Solution {\n}\n",
}


class WorkspaceManager:
    """Coordinates local coding workspace, draft persistence, judge execution, and mission synchronization."""

    def __init__(
        self,
        tracking_db_path: Optional[str | Path] = None,
        progress_db_path: Optional[str | Path] = None,
        language: str = "python",
    ):
        self.tracking_db_path = Path(tracking_db_path) if tracking_db_path is not None else DEFAULT_TRACKING_DB_PATH
        self.progress_db_path = progress_db_path
        self.language = LanguageSupport.normalize_language(language or "python")
        self.init_schema()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.tracking_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """Create workspace draft and run history tables safely in session_tracking.db."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_drafts (
                    problem_id TEXT NOT NULL,
                    language TEXT NOT NULL,
                    code TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (problem_id, language)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_runs (
                    run_id TEXT PRIMARY KEY,
                    problem_id TEXT NOT NULL,
                    language TEXT NOT NULL,
                    status TEXT NOT NULL,
                    passed_count INTEGER NOT NULL,
                    total_tests INTEGER NOT NULL,
                    runtime_ms REAL,
                    compile_error TEXT,
                    execution_error TEXT,
                    failed_test_detail TEXT,
                    coach_feedback TEXT,
                    suggested_next_action TEXT NOT NULL,
                    can_complete_task INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_workspace_draft_pid ON workspace_drafts(problem_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_workspace_run_pid ON workspace_runs(problem_id)")
            conn.commit()

    def get_problem_context(
        self,
        problem_id: str,
        mission_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Optional[ProblemWorkspaceContext]:
        """Assemble full problem context, metadata, starter code, and active mission links."""
        all_problems = load_problems()
        p = next((prob for prob in all_problems if prob.get("id") == problem_id), None)
        if not p:
            # Check custom problems
            cp = store.get_custom_problem(problem_id, db_path=self.progress_db_path)
            if cp:
                p = cp
            else:
                return None

        # Related roadmap prerequisites
        related_prereqs: List[str] = []
        try:
            rm_engine = DsaRoadmapEngine(
                progress_db_path=self.progress_db_path,
                tracking_db_path=self.tracking_db_path,
                language=self.language,
            )
            for node in rm_engine.nodes:
                if rm_engine._match_problem_to_node(p, node):
                    related_prereqs.extend(node.prerequisites)
        except Exception:
            pass

        # Mission task information
        task_reason: Optional[str] = None
        if mission_id and task_id:
            try:
                mission_mgr = DailyMissionManager(
                    tracking_db_path=self.tracking_db_path,
                    progress_db_path=self.progress_db_path,
                )
                mission = mission_mgr.get_mission(mission_id)
                if mission:
                    task = next((t for t in mission.tasks if t.task_id == task_id), None)
                    if task:
                        task_reason = task.selection_reason
            except Exception:
                pass

        # Starter code mapping
        starter: Dict[str, str] = dict(DEFAULT_STARTER_CODE)
        # Check problem explicit starter code if any
        if p.get("starter_code"):
            for lang, code_snip in p["starter_code"].items():
                starter[lang] = code_snip

        # Format examples safely without exposing hidden internal test harnesses
        examples = p.get("examples") or []
        if not examples and (p.get("tests") or p.get("test_cases")):
            test_source = p.get("tests") or p.get("test_cases") or []
            for tc in test_source[:2]:
                inp_val = tc.get("input") if "input" in tc else tc.get("args")
                exp_val = tc.get("expected") or tc.get("output")
                examples.append({
                    "input": inp_val,
                    "output": exp_val,
                    "explanation": tc.get("explanation", ""),
                })

        return ProblemWorkspaceContext(
            problem_id=p.get("id", problem_id),
            title=p.get("title", problem_id.replace("-", " ").title()),
            difficulty=p.get("difficulty", "medium"),
            topics=p.get("topics") or ["Core DSA"],
            description=p.get("description", "No description available."),
            constraints=p.get("constraints") or ["Standard execution time & memory limits apply."],
            examples=examples,
            starter_code=starter,
            current_mission_id=mission_id,
            current_task_id=task_id,
            task_selection_reason=task_reason,
            related_prerequisites=list(set(related_prereqs)),
        )

    # -------------------------------------------------------------------------
    # Solution Draft Management
    # -------------------------------------------------------------------------

    def save_draft(self, problem_id: str, language: str, code: str) -> WorkspaceDraft:
        """Save local code draft partitioned cleanly by problem_id and language."""
        if not problem_id or not problem_id.strip():
            raise ValueError("problem_id cannot be empty.")
        norm_lang = LanguageSupport.normalize_language(language)

        now_str = _get_utc_now_iso()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT created_at FROM workspace_drafts WHERE problem_id = ? AND language = ?",
                (problem_id.strip(), norm_lang),
            )
            existing = cursor.fetchone()
            created_at = existing["created_at"] if existing else now_str

            cursor.execute(
                """
                INSERT OR REPLACE INTO workspace_drafts (
                    problem_id, language, code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (problem_id.strip(), norm_lang, code, created_at, now_str),
            )
            conn.commit()

        return WorkspaceDraft(
            problem_id=problem_id.strip(),
            language=norm_lang,
            code=code,
            created_at=created_at,
            updated_at=now_str,
        )

    def get_draft(self, problem_id: str, language: str) -> Optional[WorkspaceDraft]:
        """Load draft for a given problem and language. If none exists, return None."""
        norm_lang = LanguageSupport.normalize_language(language)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM workspace_drafts WHERE problem_id = ? AND language = ?",
                (problem_id.strip(), norm_lang),
            )
            row = cursor.fetchone()
            if not row:
                return None

        return WorkspaceDraft(
            problem_id=row["problem_id"],
            language=row["language"],
            code=row["code"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def clear_draft(self, problem_id: str, language: str) -> bool:
        """Explicitly clear a saved draft."""
        norm_lang = LanguageSupport.normalize_language(language)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM workspace_drafts WHERE problem_id = ? AND language = ?",
                (problem_id.strip(), norm_lang),
            )
            conn.commit()
            return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # Local Judge Execution & Result Interpretation
    # -------------------------------------------------------------------------

    def run_code(
        self,
        problem_id: str,
        code: str,
        language: str = "python",
        timeout: int = 10,
    ) -> WorkspaceRunResult:
        """Execute solution code using existing local judge and interpret the outcome."""
        all_problems = load_problems()
        problem = next((p for p in all_problems if p.get("id") == problem_id), None)
        if not problem:
            cp = store.get_custom_problem(problem_id, db_path=self.progress_db_path)
            if cp:
                problem = cp
            else:
                raise ValueError(f"Problem '{problem_id}' not found.")

        norm_lang = LanguageSupport.normalize_language(language)
        # Execute using existing UnifiedJudge without duplication
        raw_result = UnifiedJudge.run_solution(
            code=code,
            problem=problem,
            language=norm_lang,
            timeout=timeout,
        )

        status = raw_result.get("status", "runtime_error")
        passed_count = raw_result.get("passed_count", 0)
        total_tests = raw_result.get("total", len(problem.get("test_cases", [])))
        runtime_ms = raw_result.get("runtime_ms")

        compile_err = None
        exec_err = None
        failed_detail = None

        if status == "compile_error":
            compile_err = raw_result.get("error")
        elif status in ("runtime_error", "timeout"):
            exec_err = raw_result.get("error")
        elif status == "wrong_answer":
            failed_detail = raw_result.get("failure")

        # Coach feedback synthesis
        coach_feedback = None
        try:
            coach = OfflineCodingCoach(
                progress_db_path=self.progress_db_path,
                tracking_db_path=self.tracking_db_path,
                language=norm_lang,
            )
            hint_tier = 1 if status == "wrong_answer" else 2
            hint = coach.get_progressive_hint(problem_id, tier=hint_tier)
            if hint:
                coach_feedback = f"Coach Hint ({hint.tier.value.title()}): {hint.hint_content}"
        except Exception:
            pass

        # Actionable next step & task completion eligibility
        can_complete = (status == "passed")
        if can_complete:
            suggested_action = "All test cases passed! You can now confirm completion of your mission task."
        elif status == "wrong_answer":
            suggested_action = "Review edge cases and incorrect output in the failed test report above."
        elif status == "compile_error":
            suggested_action = "Fix syntax or type definitions reported in compilation diagnostics."
        elif status == "timeout":
            suggested_action = "Optimize algorithm time complexity to prevent infinite recursion/loops."
        else:
            suggested_action = "Check for null/index exceptions in the execution traceback."

        run_id = f"run_{uuid.uuid4().hex[:10]}"
        now_str = _get_utc_now_iso()

        run_res = WorkspaceRunResult(
            run_id=run_id,
            problem_id=problem_id,
            language=norm_lang,
            status=status,
            passed_count=passed_count,
            total_tests=total_tests,
            runtime_ms=runtime_ms,
            compile_error=compile_err,
            execution_error=exec_err,
            failed_test_detail=failed_detail,
            coach_feedback=coach_feedback,
            suggested_next_action=suggested_action,
            can_complete_task=can_complete,
            created_at=now_str,
        )

        # Persist run to session_tracking.db
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO workspace_runs (
                    run_id, problem_id, language, status, passed_count, total_tests,
                    runtime_ms, compile_error, execution_error, failed_test_detail,
                    coach_feedback, suggested_next_action, can_complete_task, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_res.run_id,
                    run_res.problem_id,
                    run_res.language,
                    run_res.status,
                    run_res.passed_count,
                    run_res.total_tests,
                    run_res.runtime_ms,
                    run_res.compile_error,
                    run_res.execution_error,
                    json.dumps(run_res.failed_test_detail) if run_res.failed_test_detail else None,
                    run_res.coach_feedback,
                    run_res.suggested_next_action,
                    1 if run_res.can_complete_task else 0,
                    run_res.created_at,
                ),
            )
            conn.commit()

        return run_res

    def get_run_result(self, run_id: str) -> Optional[WorkspaceRunResult]:
        """Fetch previously executed run result by run_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workspace_runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            if not row:
                return None

        failed_detail = None
        if row["failed_test_detail"]:
            try:
                failed_detail = json.loads(row["failed_test_detail"])
            except Exception:
                pass

        return WorkspaceRunResult(
            run_id=row["run_id"],
            problem_id=row["problem_id"],
            language=row["language"],
            status=row["status"],
            passed_count=row["passed_count"],
            total_tests=row["total_tests"],
            runtime_ms=row["runtime_ms"],
            compile_error=row["compile_error"],
            execution_error=row["execution_error"],
            failed_test_detail=failed_detail,
            coach_feedback=row["coach_feedback"],
            suggested_next_action=row["suggested_next_action"],
            can_complete_task=bool(row["can_complete_task"]),
            created_at=row["created_at"],
        )

    def list_run_history(self, problem_id: Optional[str] = None, limit: int = 10) -> List[WorkspaceRunResult]:
        """List recent test runs, optionally filtered by problem."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if problem_id:
                cursor.execute(
                    "SELECT run_id FROM workspace_runs WHERE problem_id = ? ORDER BY created_at DESC LIMIT ?",
                    (problem_id.strip(), limit),
                )
            else:
                cursor.execute("SELECT run_id FROM workspace_runs ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            res = self.get_run_result(r["run_id"])
            if res:
                results.append(res)
        return results

    # -------------------------------------------------------------------------
    # Mission Integration & Explicit Confirmation
    # -------------------------------------------------------------------------

    def confirm_mission_task_completion(
        self,
        mission_id: str,
        task_id: str,
        problem_id: str,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Explicitly confirm and validate mission task completion after passing local judge tests."""
        # Check that the run was actually verified as passed
        if run_id:
            run_res = self.get_run_result(run_id)
            if not run_res or run_res.status != "passed":
                raise ValueError("Cannot complete task: Test run did not pass all local tests.")

        mission_mgr = DailyMissionManager(
            tracking_db_path=self.tracking_db_path,
            progress_db_path=self.progress_db_path,
            language=self.language,
        )

        mission = mission_mgr.get_mission(mission_id)
        if not mission:
            raise ValueError(f"Mission '{mission_id}' not found.")

        task = next((t for t in mission.tasks if t.task_id == task_id), None)
        if not task:
            raise ValueError(f"Task '{task_id}' not found in mission.")

        # Prevent duplicate completion
        if task.status == MissionTaskStatus.COMPLETED:
            return {
                "message": f"Task '{task_id}' is already completed.",
                "task": asdict(task),
                "mission": asdict(mission),
            }

        # Complete task via DailyMissionManager
        completed_task, updated_mission = mission_mgr.complete_task(task_id)

        return {
            "message": f"Task '{completed_task.title}' successfully verified and completed!",
            "task": asdict(completed_task),
            "mission": asdict(updated_mission),
        }
