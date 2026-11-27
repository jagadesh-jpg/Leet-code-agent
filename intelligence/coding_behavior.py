"""Personal Coding Behavior Intelligence Subsystem.

Milestone 6.3.23: Personal Coding Behavior Intelligence.
Provides:
1. Multi-dimensional behavioral analysis:
   - Attempt patterns: First-attempt pass rate, attempts-per-problem ratio, attempt persistence.
   - Debugging patterns: Error distribution (wrong answer, compile error, runtime error, timeout),
     bug resolution cycle, compile vs runtime ratio.
   - Problem-solving progression: Topic fluency, difficulty progression (easy, medium, hard),
     and complexity notation awareness.
   - Session behavior: Practice session completion vs abandonment, duration, pacing, and pauses.
   - Revision behavior: Spaced repetition queue adherence, overdue count, and ease factor evolution.
   - Interview behavior: Mock interview performance trends, time management, and score consistency.
2. Objective, sample-adequate profiling:
   - Explicit sample adequacy validation (threshold N < 3 => insufficient_data).
   - Strict adherence to factual, audit-backed observations; strictly zero psychological profiling,
     IQ claims, or hiring suitability scores.
   - Explicit limitations and deterministic confidence tiers.
3. Actionable, non-trivial insights and recommendations:
   - Rule-based pattern detection with severity categorization (info, positive, neutral, attention, recommendation).
   - Previewable practice recommendations that never silently alter schedules or preparation plans.
4. Non-destructive persistence:
   - Dedicated tables in session_tracking.db (coding_behavior_profiles, coding_behavior_reports, coding_behavior_insights).
   - Leaves production progress.db strictly read-only.

100% offline, local-first, zero external API or LLM calls.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from problems import load_problems
import store


class BehaviorCategory(str, Enum):
    """Behavioral evidence dimensions analyzed."""
    ATTEMPT_PATTERN = "attempt_pattern"
    DEBUGGING = "debugging"
    PROBLEM_SOLVING = "problem_solving"
    SESSION_BEHAVIOR = "session_behavior"
    REVISION_BEHAVIOR = "revision_behavior"
    INTERVIEW_BEHAVIOR = "interview_behavior"


class InsightSeverity(str, Enum):
    """Categorization of insight impact and actionability."""
    INFO = "info"
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    ATTENTION = "attention"
    RECOMMENDATION = "recommendation"


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_utc_now_iso() -> str:
    return _get_utc_now().isoformat()


@dataclass
class BehaviorEvidence:
    """Atomic evidence record backing a detected pattern or insight."""
    source: str                           # "workspace_runs", "attempts", "practice_sessions", etc.
    metric_name: str
    sample_count: int
    observed_value: Any
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodingBehaviorPattern:
    """Identified recurring pattern in coding, debugging, or session execution."""
    pattern_id: str
    category: BehaviorCategory
    name: str
    description: str
    frequency: float                      # Percentage or ratio (0.0 - 100.0)
    sample_count: int
    evidence_summary: str


@dataclass
class CodingBehaviorInsight:
    """Actionable behavioral insight with explicit severity and practice recommendation."""
    insight_id: str
    category: BehaviorCategory
    severity: InsightSeverity
    title: str
    description: str
    evidence: str
    sample_count: int
    recommended_action: str


@dataclass
class CodingBehaviorProfile:
    """Synthesized deterministic personal coding behavior profile."""
    profile_id: str
    created_at: str
    total_evidence_events: int
    sample_adequate: bool
    confidence: str                       # "high", "medium", "low", "insufficient_data"
    attempt_patterns: Dict[str, Any]
    debugging_patterns: Dict[str, Any]
    problem_solving_progression: Dict[str, Any]
    session_behavior: Dict[str, Any]
    revision_behavior: Dict[str, Any]
    interview_behavior: Dict[str, Any]
    patterns: List[CodingBehaviorPattern] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)


@dataclass
class BehaviorAnalysisReport:
    """Comprehensive analytical report containing profile, insights, and recommendations."""
    report_id: str
    created_at: str
    profile: CodingBehaviorProfile
    summary: str
    insights: List[CodingBehaviorInsight] = field(default_factory=list)
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)


class CodingBehaviorAnalyzer:
    """Analyzes learner attempt history, debugging outcomes, and sessions to build behavior intelligence."""

    MIN_SAMPLE_THRESHOLD = 3
    HIGH_CONFIDENCE_THRESHOLD = 25
    MEDIUM_CONFIDENCE_THRESHOLD = 10

    def __init__(
        self,
        tracking_db_path: Optional[str | Path] = None,
        progress_db_path: Optional[str | Path] = None,
    ):
        self.tracking_db_path = Path(tracking_db_path) if tracking_db_path is not None else DEFAULT_TRACKING_DB_PATH
        self.progress_db_path = Path(progress_db_path) if progress_db_path is not None else store.DEFAULT_DB_PATH
        self.init_schema()

    def get_tracking_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.tracking_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_progress_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.progress_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """Create coding behavior persistence tables non-destructively in session_tracking.db."""
        with self.get_tracking_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS coding_behavior_profiles (
                    profile_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    total_evidence_events INTEGER NOT NULL DEFAULT 0,
                    sample_adequate INTEGER NOT NULL DEFAULT 0,
                    confidence TEXT NOT NULL,
                    profile_json TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS coding_behavior_reports (
                    report_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    dimensions_json TEXT NOT NULL,
                    insights_json TEXT NOT NULL,
                    recommendations_json TEXT NOT NULL,
                    limitations_json TEXT NOT NULL,
                    FOREIGN KEY (profile_id) REFERENCES coding_behavior_profiles(profile_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS coding_behavior_insights (
                    insight_id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    sample_count INTEGER NOT NULL,
                    recommended_action TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (report_id) REFERENCES coding_behavior_reports(report_id)
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cb_reports_created ON coding_behavior_reports(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cb_insights_cat ON coding_behavior_insights(category)")
            conn.commit()

    def extract_evidence(self) -> Dict[str, Any]:
        """Collect raw observational data from progress.db (read-only) and session_tracking.db."""
        evidence: Dict[str, Any] = {
            "attempts": [],
            "workspace_runs": [],
            "practice_sessions": [],
            "practice_notes": [],
            "practice_events": [],
            "revision_items": [],
            "revision_history": [],
            "mock_interviews": [],
        }

        # 1. Read attempts from progress.db (read-only)
        if self.progress_db_path.exists():
            try:
                with self.get_progress_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attempts'")
                    if cur.fetchone():
                        cur.execute("SELECT id, problem_id, attempt_no, status, error, created_at FROM attempts ORDER BY id ASC")
                        evidence["attempts"] = [dict(r) for r in cur.fetchall()]
            except Exception:
                pass

        # 2. Read session_tracking.db tables
        if self.tracking_db_path.exists():
            try:
                with self.get_tracking_connection() as conn:
                    cur = conn.cursor()

                    # workspace_runs
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='workspace_runs'")
                    if cur.fetchone():
                        cur.execute(
                            """
                            SELECT run_id, problem_id, language, status, passed_count, total_tests,
                                   runtime_ms, compile_error, execution_error, created_at
                            FROM workspace_runs ORDER BY created_at ASC
                            """
                        )
                        evidence["workspace_runs"] = [dict(r) for r in cur.fetchall()]

                    # practice_sessions
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='practice_sessions'")
                    if cur.fetchone():
                        cur.execute(
                            """
                            SELECT session_id, plan_id, task_id, problem_id, language, status,
                                   created_at, started_at, paused_at, ended_at, elapsed_seconds,
                                   submissions_count, passed_submissions_count, failed_submissions_count,
                                   final_submission_passed, task_confirmed_completed
                            FROM practice_sessions ORDER BY created_at ASC
                            """
                        )
                        evidence["practice_sessions"] = [dict(r) for r in cur.fetchall()]

                    # practice_session_notes
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='practice_session_notes'")
                    if cur.fetchone():
                        cur.execute(
                            """
                            SELECT session_id, initial_approach, mistakes_encountered, hints_used,
                                   final_approach, time_complexity, space_complexity, key_learning, follow_up_action
                            FROM practice_session_notes
                            """
                        )
                        evidence["practice_notes"] = [dict(r) for r in cur.fetchall()]

                    # practice_session_events
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='practice_session_events'")
                    if cur.fetchone():
                        cur.execute(
                            """
                            SELECT event_id, session_id, event_type, timestamp
                            FROM practice_session_events ORDER BY timestamp ASC
                            """
                        )
                        evidence["practice_events"] = [dict(r) for r in cur.fetchall()]

                    # revision_items
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='revision_items'")
                    if cur.fetchone():
                        cur.execute(
                            """
                            SELECT problem_id, title, difficulty, topics_json, next_review_at,
                                   interval_days, repetition_count, ease_factor, status, last_outcome
                            FROM revision_items
                            """
                        )
                        evidence["revision_items"] = [dict(r) for r in cur.fetchall()]

                    # revision_history
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='revision_history'")
                    if cur.fetchone():
                        cur.execute("SELECT id, problem_id, outcome, reviewed_at, interval_days, ease_factor FROM revision_history")
                        evidence["revision_history"] = [dict(r) for r in cur.fetchall()]

                    # mock_interviews
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mock_interviews'")
                    if cur.fetchone():
                        cur.execute(
                            """
                            SELECT interview_id, title, track, duration_minutes, language, status,
                                   total_score, correctness_score, completion_score, structure_score,
                                   complexity_score, time_management_score, created_at, completed_at
                            FROM mock_interviews
                            """
                        )
                        evidence["mock_interviews"] = [dict(r) for r in cur.fetchall()]
            except Exception:
                pass

        return evidence

    def analyze_attempt_patterns(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze first-attempt pass rates, attempts-per-problem, and persistence."""
        attempts = evidence.get("attempts", [])
        workspace_runs = evidence.get("workspace_runs", [])

        # Group attempts by problem_id in order
        problem_history: Dict[str, List[Dict[str, Any]]] = {}

        for a in attempts:
            pid = a.get("problem_id")
            if pid:
                problem_history.setdefault(pid, []).append({
                    "status": a.get("status", "unknown"),
                    "time": a.get("created_at", ""),
                })

        for r in workspace_runs:
            pid = r.get("problem_id")
            if pid:
                problem_history.setdefault(pid, []).append({
                    "status": r.get("status", "unknown"),
                    "time": r.get("created_at", ""),
                })

        total_problems = len(problem_history)
        total_runs = sum(len(runs) for runs in problem_history.values())

        if total_problems == 0:
            return {
                "total_problems_attempted": 0,
                "total_attempts": 0,
                "first_attempt_pass_rate": 0.0,
                "avg_attempts_per_problem": 0.0,
                "persistence_rate": 0.0,
                "problems_eventually_solved": 0,
                "problems_failed_initially": 0,
            }

        first_attempt_passed = 0
        problems_failed_initially = 0
        problems_persisted_and_solved = 0
        problems_eventually_solved = 0

        for pid, runs in problem_history.items():
            first_run = runs[0]
            first_status = str(first_run.get("status", "")).lower()
            is_first_pass = (first_status in ("passed", "success", "accepted"))

            if is_first_pass:
                first_attempt_passed += 1

            has_ever_passed = any(
                str(run.get("status", "")).lower() in ("passed", "success", "accepted")
                for run in runs
            )

            if has_ever_passed:
                problems_eventually_solved += 1

            if not is_first_pass:
                problems_failed_initially += 1
                if has_ever_passed:
                    problems_persisted_and_solved += 1

        first_pass_rate = round((first_attempt_passed / total_problems) * 100.0, 1)
        avg_attempts = round(total_runs / total_problems, 2)
        persistence_rate = (
            round((problems_persisted_and_solved / problems_failed_initially) * 100.0, 1)
            if problems_failed_initially > 0 else 100.0
        )

        return {
            "total_problems_attempted": total_problems,
            "total_attempts": total_runs,
            "first_attempt_pass_rate": first_pass_rate,
            "avg_attempts_per_problem": avg_attempts,
            "persistence_rate": persistence_rate,
            "problems_eventually_solved": problems_eventually_solved,
            "problems_failed_initially": problems_failed_initially,
        }

    def analyze_debugging_patterns(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze failure frequencies, error distribution, and debugging resolution."""
        workspace_runs = evidence.get("workspace_runs", [])
        attempts = evidence.get("attempts", [])

        distribution: Dict[str, int] = {
            "wrong_answer": 0,
            "compile_error": 0,
            "runtime_error": 0,
            "timeout": 0,
            "other": 0,
        }
        total_failures = 0

        # Classify workspace runs
        for r in workspace_runs:
            status = str(r.get("status", "")).lower()
            if status in ("passed", "success", "accepted"):
                continue

            total_failures += 1
            if status in ("wrong_answer", "fail", "failed"):
                distribution["wrong_answer"] += 1
            elif status in ("compile_error", "compilation_error"):
                distribution["compile_error"] += 1
            elif status in ("runtime_error", "exception"):
                distribution["runtime_error"] += 1
            elif status in ("timeout", "time_limit_exceeded"):
                distribution["timeout"] += 1
            else:
                distribution["other"] += 1

        # Classify progress.db attempts if not already passed
        for a in attempts:
            status = str(a.get("status", "")).lower()
            if status in ("passed", "success", "accepted"):
                continue

            err = str(a.get("error", "")).lower()
            total_failures += 1
            if "syntax" in err or "compile" in err or "nameerror" in err or "indentation" in err:
                distribution["compile_error"] += 1
            elif "timeout" in err or "time limit" in err:
                distribution["timeout"] += 1
            elif "assertion" in err or "wrong" in status or "expected" in err:
                distribution["wrong_answer"] += 1
            elif err:
                distribution["runtime_error"] += 1
            else:
                distribution["other"] += 1

        dominant_error = None
        max_count = 0
        for err_type, count in distribution.items():
            if count > max_count:
                max_count = count
                dominant_error = err_type

        # Ratio of compile to runtime errors
        total_sys_errors = distribution["compile_error"] + distribution["runtime_error"]
        compile_ratio = (
            round((distribution["compile_error"] / total_sys_errors) * 100.0, 1)
            if total_sys_errors > 0 else 0.0
        )

        return {
            "total_failures": total_failures,
            "error_distribution": distribution,
            "dominant_error": dominant_error,
            "compile_vs_runtime_ratio": compile_ratio,
        }

    def analyze_problem_solving(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze difficulty progression, topic fluency, and complexity awareness."""
        all_problems = {p.get("id"): p for p in load_problems()}
        attempts = evidence.get("attempts", [])
        workspace_runs = evidence.get("workspace_runs", [])
        practice_notes = evidence.get("practice_notes", [])
        mock_interviews = evidence.get("mock_interviews", [])

        # Difficulty distribution
        attempted_pids: Set[str] = set()
        for a in attempts:
            if a.get("problem_id"):
                attempted_pids.add(a["problem_id"])
        for r in workspace_runs:
            if r.get("problem_id"):
                attempted_pids.add(r["problem_id"])

        diff_dist: Dict[str, int] = {"Easy": 0, "Medium": 0, "Hard": 0, "Custom": 0}
        for pid in attempted_pids:
            prob = all_problems.get(pid)
            if prob:
                diff = prob.get("difficulty", "Medium").capitalize()
                diff_dist[diff] = diff_dist.get(diff, 0) + 1
            else:
                diff_dist["Custom"] += 1

        # Topic fluency
        topic_attempts: Dict[str, int] = {}
        topic_passes: Dict[str, int] = {}

        for r in workspace_runs:
            pid = r.get("problem_id")
            prob = all_problems.get(pid) if pid else None
            topics = prob.get("topics", []) if prob else []
            is_pass = str(r.get("status", "")).lower() in ("passed", "success", "accepted")

            for t in topics:
                t_lower = t.lower()
                topic_attempts[t_lower] = topic_attempts.get(t_lower, 0) + 1
                if is_pass:
                    topic_passes[t_lower] = topic_passes.get(t_lower, 0) + 1

        topic_fluency: Dict[str, float] = {}
        for t, total in topic_attempts.items():
            passes = topic_passes.get(t, 0)
            topic_fluency[t] = round((passes / total) * 100.0, 1)

        # Complexity awareness rate
        notes_with_complexity = 0
        for n in practice_notes:
            tc = (n.get("time_complexity") or "").strip()
            sc = (n.get("space_complexity") or "").strip()
            if tc or sc:
                notes_with_complexity += 1

        interview_complexity_events = sum(
            1 for m in mock_interviews if (m.get("complexity_score") or 0.0) > 0.0
        )

        total_complexity_opportunities = len(practice_notes) + len(mock_interviews)
        complexity_rate = (
            round(((notes_with_complexity + interview_complexity_events) / total_complexity_opportunities) * 100.0, 1)
            if total_complexity_opportunities > 0 else 0.0
        )

        return {
            "difficulty_distribution": diff_dist,
            "topic_fluency": topic_fluency,
            "complexity_awareness_rate": complexity_rate,
            "notes_with_complexity": notes_with_complexity,
            "total_complexity_opportunities": total_complexity_opportunities,
        }

    def analyze_session_behavior(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze practice session completion, duration, abandonment, and pacing."""
        sessions = evidence.get("practice_sessions", [])
        events = evidence.get("practice_events", [])

        total_sessions = len(sessions)
        if total_sessions == 0:
            return {
                "total_sessions": 0,
                "completed_count": 0,
                "abandoned_count": 0,
                "active_or_paused_count": 0,
                "completion_rate": 0.0,
                "abandonment_rate": 0.0,
                "avg_session_duration_minutes": 0.0,
                "avg_pauses_per_session": 0.0,
            }

        completed = sum(1 for s in sessions if s.get("status") == "completed")
        abandoned = sum(1 for s in sessions if s.get("status") == "abandoned")
        active_or_paused = sum(1 for s in sessions if s.get("status") in ("active", "paused"))

        total_elapsed_seconds = sum(s.get("elapsed_seconds", 0) for s in sessions)
        avg_duration_min = round((total_elapsed_seconds / total_sessions) / 60.0, 1)

        pause_events = sum(1 for e in events if e.get("event_type") == "pause")
        avg_pauses = round(pause_events / total_sessions, 1)

        completion_rate = round((completed / total_sessions) * 100.0, 1)
        abandonment_rate = round((abandoned / total_sessions) * 100.0, 1)

        return {
            "total_sessions": total_sessions,
            "completed_count": completed,
            "abandoned_count": abandoned,
            "active_or_paused_count": active_or_paused,
            "completion_rate": completion_rate,
            "abandonment_rate": abandonment_rate,
            "avg_session_duration_minutes": avg_duration_min,
            "avg_pauses_per_session": avg_pauses,
        }

    def analyze_revision_behavior(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze spaced repetition queue adherence and review discipline."""
        items = evidence.get("revision_items", [])
        history = evidence.get("revision_history", [])

        total_items = len(items)
        if total_items == 0:
            return {
                "total_tracked_items": 0,
                "overdue_count": 0,
                "due_count": 0,
                "reviewed_count": 0,
                "adherence_rate": 100.0,
                "avg_ease_factor": 2.5,
                "total_reviews_logged": len(history),
            }

        overdue = sum(1 for it in items if it.get("status") == "overdue")
        due = sum(1 for it in items if it.get("status") == "due")
        reviewed = sum(1 for it in items if it.get("status") == "reviewed")

        ease_factors = [it.get("ease_factor", 2.5) for it in items if it.get("ease_factor") is not None]
        avg_ease = round(sum(ease_factors) / len(ease_factors), 2) if ease_factors else 2.5

        # Adherence: items reviewed or not overdue
        adherence_rate = round(((total_items - overdue) / total_items) * 100.0, 1)

        return {
            "total_tracked_items": total_items,
            "overdue_count": overdue,
            "due_count": due,
            "reviewed_count": reviewed,
            "adherence_rate": adherence_rate,
            "avg_ease_factor": avg_ease,
            "total_reviews_logged": len(history),
        }

    def analyze_interview_behavior(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze mock interview completion, time management, and scores."""
        interviews = evidence.get("mock_interviews", [])
        total_interviews = len(interviews)

        if total_interviews == 0:
            return {
                "total_interviews": 0,
                "completed_count": 0,
                "avg_score": 0.0,
                "avg_time_management_score": 0.0,
                "avg_correctness_score": 0.0,
                "score_consistency": "insufficient_data",
            }

        completed = [i for i in interviews if i.get("status") == "completed"]
        completed_count = len(completed)

        if completed_count == 0:
            return {
                "total_interviews": total_interviews,
                "completed_count": 0,
                "avg_score": 0.0,
                "avg_time_management_score": 0.0,
                "avg_correctness_score": 0.0,
                "score_consistency": "insufficient_data",
            }

        scores = [c.get("total_score", 0.0) or 0.0 for c in completed]
        tm_scores = [c.get("time_management_score", 0.0) or 0.0 for c in completed]
        corr_scores = [c.get("correctness_score", 0.0) or 0.0 for c in completed]

        avg_score = round(sum(scores) / completed_count, 1)
        avg_tm = round(sum(tm_scores) / completed_count, 1)
        avg_corr = round(sum(corr_scores) / completed_count, 1)

        # Consistency: spread between min and max
        score_range = max(scores) - min(scores) if scores else 0.0
        consistency = "high" if score_range <= 15.0 else ("moderate" if score_range <= 30.0 else "variable")

        return {
            "total_interviews": total_interviews,
            "completed_count": completed_count,
            "avg_score": avg_score,
            "avg_time_management_score": avg_tm,
            "avg_correctness_score": avg_corr,
            "score_consistency": consistency,
        }

    def detect_patterns(
        self,
        attempt_metrics: Dict[str, Any],
        debugging_metrics: Dict[str, Any],
        session_metrics: Dict[str, Any],
        revision_metrics: Dict[str, Any],
    ) -> List[CodingBehaviorPattern]:
        """Detect recurring behavioral patterns deterministically from metrics."""
        patterns: List[CodingBehaviorPattern] = []

        # 1. High First-Attempt Accuracy
        if attempt_metrics["total_problems_attempted"] >= self.MIN_SAMPLE_THRESHOLD:
            rate = attempt_metrics["first_attempt_pass_rate"]
            if rate >= 60.0:
                patterns.append(
                    CodingBehaviorPattern(
                        pattern_id=f"pat_first_pass_{uuid.uuid4().hex[:8]}",
                        category=BehaviorCategory.ATTEMPT_PATTERN,
                        name="High First-Attempt Accuracy",
                        description="Frequently solves problems on the initial attempt without prior trial-and-error.",
                        frequency=rate,
                        sample_count=attempt_metrics["total_problems_attempted"],
                        evidence_summary=f"{rate}% first-attempt pass rate across {attempt_metrics['total_problems_attempted']} problems.",
                    )
                )

        # 2. Tenacious Debugger
        if attempt_metrics["problems_failed_initially"] >= 2:
            persistence = attempt_metrics["persistence_rate"]
            if persistence >= 75.0:
                patterns.append(
                    CodingBehaviorPattern(
                        pattern_id=f"pat_persistence_{uuid.uuid4().hex[:8]}",
                        category=BehaviorCategory.DEBUGGING,
                        name="Tenacious Debugging Persistence",
                        description="Consistently iterates and resolves initial failing submissions until accepted.",
                        frequency=persistence,
                        sample_count=attempt_metrics["problems_failed_initially"],
                        evidence_summary=f"{persistence}% eventual success rate on initially failed problems.",
                    )
                )

        # 3. Dominant Syntax/Compile Iteration
        if debugging_metrics["total_failures"] >= self.MIN_SAMPLE_THRESHOLD:
            dom = debugging_metrics.get("dominant_error")
            if dom == "compile_error":
                comp_ratio = debugging_metrics.get("compile_vs_runtime_ratio", 0.0)
                patterns.append(
                    CodingBehaviorPattern(
                        pattern_id=f"pat_syntax_iter_{uuid.uuid4().hex[:8]}",
                        category=BehaviorCategory.DEBUGGING,
                        name="Frequent Syntax Iteration",
                        description="High proportion of test runs fail due to syntax or compilation errors rather than logical bugs.",
                        frequency=comp_ratio,
                        sample_count=debugging_metrics["total_failures"],
                        evidence_summary=f"{debugging_metrics['error_distribution']['compile_error']} of {debugging_metrics['total_failures']} failures were compilation/syntax errors.",
                    )
                )
            elif dom == "timeout":
                patterns.append(
                    CodingBehaviorPattern(
                        pattern_id=f"pat_timeout_{uuid.uuid4().hex[:8]}",
                        category=BehaviorCategory.DEBUGGING,
                        name="Algorithmic Time Complexity Bottlenecks",
                        description="Submissions frequently encounter execution timeouts on larger input scales.",
                        frequency=round((debugging_metrics['error_distribution']['timeout'] / debugging_metrics['total_failures']) * 100.0, 1),
                        sample_count=debugging_metrics["total_failures"],
                        evidence_summary=f"{debugging_metrics['error_distribution']['timeout']} timeout failures recorded.",
                    )
                )

        # 4. Session Discipline & Follow-Through
        if session_metrics["total_sessions"] >= self.MIN_SAMPLE_THRESHOLD:
            comp_rate = session_metrics["completion_rate"]
            if comp_rate >= 80.0:
                patterns.append(
                    CodingBehaviorPattern(
                        pattern_id=f"pat_session_followthrough_{uuid.uuid4().hex[:8]}",
                        category=BehaviorCategory.SESSION_BEHAVIOR,
                        name="Disciplined Session Follow-Through",
                        description="High completion rate for started practice sessions with minimal abandonment.",
                        frequency=comp_rate,
                        sample_count=session_metrics["total_sessions"],
                        evidence_summary=f"{comp_rate}% session completion rate across {session_metrics['total_sessions']} sessions.",
                    )
                )
            elif session_metrics["abandonment_rate"] >= 35.0:
                patterns.append(
                    CodingBehaviorPattern(
                        pattern_id=f"pat_session_abandon_{uuid.uuid4().hex[:8]}",
                        category=BehaviorCategory.SESSION_BEHAVIOR,
                        name="Frequent Session Discontinuation",
                        description="Notable portion of initiated practice sessions are abandoned before task completion.",
                        frequency=session_metrics["abandonment_rate"],
                        sample_count=session_metrics["total_sessions"],
                        evidence_summary=f"{session_metrics['abandonment_rate']}% abandonment rate across {session_metrics['total_sessions']} sessions.",
                    )
                )

        # 5. Spaced Revision Backlog
        if revision_metrics["total_tracked_items"] >= self.MIN_SAMPLE_THRESHOLD:
            if revision_metrics["overdue_count"] >= 2:
                patterns.append(
                    CodingBehaviorPattern(
                        pattern_id=f"pat_rev_backlog_{uuid.uuid4().hex[:8]}",
                        category=BehaviorCategory.REVISION_BEHAVIOR,
                        name="Spaced Revision Backlog",
                        description="Overdue revision queue items indicate delayed recall practice for older problems.",
                        frequency=round((revision_metrics["overdue_count"] / revision_metrics["total_tracked_items"]) * 100.0, 1),
                        sample_count=revision_metrics["total_tracked_items"],
                        evidence_summary=f"{revision_metrics['overdue_count']} overdue revision items in queue.",
                    )
                )

        return patterns

    def generate_insights(
        self,
        sample_adequate: bool,
        attempt_metrics: Dict[str, Any],
        debugging_metrics: Dict[str, Any],
        problem_solving_metrics: Dict[str, Any],
        session_metrics: Dict[str, Any],
        revision_metrics: Dict[str, Any],
        interview_metrics: Dict[str, Any],
    ) -> List[CodingBehaviorInsight]:
        """Generate non-trivial, deterministic insights and recommended practice actions."""
        insights: List[CodingBehaviorInsight] = []

        if not sample_adequate:
            insights.append(
                CodingBehaviorInsight(
                    insight_id=f"ins_baseline_{uuid.uuid4().hex[:8]}",
                    category=BehaviorCategory.ATTEMPT_PATTERN,
                    severity=InsightSeverity.INFO,
                    title="Establishing Behavioral Baseline",
                    description="Insufficient practice events have been recorded to infer recurring behavioral patterns with statistical reliability.",
                    evidence=f"Only {attempt_metrics['total_attempts']} total executions logged (minimum 3 required).",
                    sample_count=attempt_metrics["total_attempts"],
                    recommended_action="Complete at least 3 practice sessions or mock interviews to unlock personalized behavioral intelligence.",
                )
            )
            return insights

        # Attempt pattern insights
        if attempt_metrics["total_problems_attempted"] >= self.MIN_SAMPLE_THRESHOLD:
            first_pass = attempt_metrics["first_attempt_pass_rate"]
            if first_pass >= 70.0:
                insights.append(
                    CodingBehaviorInsight(
                        insight_id=f"ins_strong_first_pass_{uuid.uuid4().hex[:8]}",
                        category=BehaviorCategory.ATTEMPT_PATTERN,
                        severity=InsightSeverity.POSITIVE,
                        title="Strong Initial Solution Correctness",
                        description="You frequently pass all test cases on your first test run, demonstrating careful planning before coding.",
                        evidence=f"{first_pass}% first-attempt pass rate across {attempt_metrics['total_problems_attempted']} problems.",
                        sample_count=attempt_metrics["total_problems_attempted"],
                        recommended_action="Consider challenging yourself with higher difficulty tiers (Medium or Hard) to test edge cases further.",
                    )
                )
            elif first_pass < 35.0:
                insights.append(
                    CodingBehaviorInsight(
                        insight_id=f"ins_low_first_pass_{uuid.uuid4().hex[:8]}",
                        category=BehaviorCategory.ATTEMPT_PATTERN,
                        severity=InsightSeverity.RECOMMENDATION,
                        title="Pre-Execution Tracing Recommended",
                        description="Submissions frequently fail on initial run. Tracing your algorithm manually with small edge cases before running the judge will save debugging iterations.",
                        evidence=f"{first_pass}% first-attempt pass rate across {attempt_metrics['total_problems_attempted']} problems.",
                        sample_count=attempt_metrics["total_problems_attempted"],
                        recommended_action="Dry run 2 manual test cases (including 1 boundary case) before hitting 'Run Code'.",
                    )
                )

        # Debugging error insights
        if debugging_metrics["total_failures"] >= self.MIN_SAMPLE_THRESHOLD:
            dom = debugging_metrics.get("dominant_error")
            if dom == "compile_error" and debugging_metrics["error_distribution"]["compile_error"] >= 2:
                insights.append(
                    CodingBehaviorInsight(
                        insight_id=f"ins_syntax_dbg_{uuid.uuid4().hex[:8]}",
                        category=BehaviorCategory.DEBUGGING,
                        severity=InsightSeverity.ATTENTION,
                        title="Frequent Compilation/Syntax Interruptions",
                        description="Compilation errors dominate your test failures. Using local linter or checking basic syntax prior to execution will streamline problem solving.",
                        evidence=f"{debugging_metrics['error_distribution']['compile_error']} compile errors recorded out of {debugging_metrics['total_failures']} total failures.",
                        sample_count=debugging_metrics["total_failures"],
                        recommended_action="Review language syntax conventions and function signatures before running test cases.",
                    )
                )
            elif dom == "timeout" and debugging_metrics["error_distribution"]["timeout"] >= 2:
                insights.append(
                    CodingBehaviorInsight(
                        insight_id=f"ins_timeout_dbg_{uuid.uuid4().hex[:8]}",
                        category=BehaviorCategory.DEBUGGING,
                        severity=InsightSeverity.ATTENTION,
                        title="Time Complexity Bottlenecks Detected",
                        description="Timeouts occur regularly, indicating potential O(N^2) or nested iteration when O(N) or O(N log N) is expected.",
                        evidence=f"{debugging_metrics['error_distribution']['timeout']} timeout errors recorded.",
                        sample_count=debugging_metrics["total_failures"],
                        recommended_action="Analyze input constraints (e.g. N <= 10^5) and select optimal data structures (e.g. hash tables, two pointers) before implementation.",
                    )
                )

        # Complexity awareness insights
        if problem_solving_metrics["total_complexity_opportunities"] >= self.MIN_SAMPLE_THRESHOLD:
            comp_rate = problem_solving_metrics["complexity_awareness_rate"]
            if comp_rate < 50.0:
                insights.append(
                    CodingBehaviorInsight(
                        insight_id=f"ins_complexity_habits_{uuid.uuid4().hex[:8]}",
                        category=BehaviorCategory.PROBLEM_SOLVING,
                        severity=InsightSeverity.RECOMMENDATION,
                        title="Formalize Big-O Complexity Annotations",
                        description="Your session reflection notes rarely document asymptotic time and space complexity.",
                        evidence=f"Complexity recorded in only {comp_rate}% of practice opportunities.",
                        sample_count=problem_solving_metrics["total_complexity_opportunities"],
                        recommended_action="State the Big-O time and space complexity in session notes immediately after solving.",
                    )
                )

        # Revision queue insights
        if revision_metrics["total_tracked_items"] >= self.MIN_SAMPLE_THRESHOLD and revision_metrics["overdue_count"] >= 2:
            insights.append(
                CodingBehaviorInsight(
                    insight_id=f"ins_rev_overdue_{uuid.uuid4().hex[:8]}",
                    category=BehaviorCategory.REVISION_BEHAVIOR,
                    severity=InsightSeverity.ATTENTION,
                    title="Spaced Repetition Overdue Backlog",
                    description="Multiple scheduled revision problems have slipped past their target review date.",
                    evidence=f"{revision_metrics['overdue_count']} items overdue out of {revision_metrics['total_tracked_items']} tracked problems.",
                    sample_count=revision_metrics["total_tracked_items"],
                    recommended_action="Dedicate your next coding session to clearing overdue items from the Spaced Repetition queue.",
                )
            )

        # Session abandonment insights
        if session_metrics["total_sessions"] >= self.MIN_SAMPLE_THRESHOLD and session_metrics["abandonment_rate"] >= 30.0:
            insights.append(
                CodingBehaviorInsight(
                    insight_id=f"ins_session_abandon_{uuid.uuid4().hex[:8]}",
                    category=BehaviorCategory.SESSION_BEHAVIOR,
                    severity=InsightSeverity.ATTENTION,
                    title="Elevated Session Abandonment Rate",
                    description="Nearly a third of started practice sessions are abandoned before explicit task confirmation.",
                    evidence=f"{session_metrics['abandonment_rate']}% abandonment rate ({session_metrics['abandoned_count']} of {session_metrics['total_sessions']} sessions).",
                    sample_count=session_metrics["total_sessions"],
                    recommended_action="Select shorter problem sessions (15-20 min) or break complex problems into discrete milestones to sustain focus.",
                )
            )

        return insights

    def generate_recommendations(
        self,
        insights: List[CodingBehaviorInsight],
        attempt_metrics: Dict[str, Any],
        revision_metrics: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Generate structured previewable recommendations that do not silently overwrite plans."""
        recommendations: List[Dict[str, Any]] = []

        # Derive recommendations from high-severity insights
        for ins in insights:
            if ins.severity in (InsightSeverity.ATTENTION, InsightSeverity.RECOMMENDATION):
                prio = "P0" if ins.severity == InsightSeverity.ATTENTION else "P1"
                recommendations.append({
                    "recommendation_id": f"rec_{uuid.uuid4().hex[:8]}",
                    "category": ins.category.value,
                    "title": ins.title,
                    "rationale": ins.description,
                    "suggested_action": ins.recommended_action,
                    "priority": prio,
                    "evidence": ins.evidence,
                })

        # Add default positive reinforcement if empty
        if not recommendations:
            recommendations.append({
                "recommendation_id": f"rec_{uuid.uuid4().hex[:8]}",
                "category": BehaviorCategory.PROBLEM_SOLVING.value,
                "title": "Maintain Balanced Practice Cadence",
                "rationale": "Current behavioral metrics show consistent performance without severe friction points.",
                "suggested_action": "Continue progressing through the DSA skill roadmap and periodic mock interviews.",
                "priority": "P2",
                "evidence": "All behavioral metrics within healthy operational tolerances.",
            })

        return recommendations

    def analyze(self, save: bool = True) -> BehaviorAnalysisReport:
        """Execute complete offline behavioral intelligence analysis."""
        evidence = self.extract_evidence()

        attempt_metrics = self.analyze_attempt_patterns(evidence)
        debugging_metrics = self.analyze_debugging_patterns(evidence)
        problem_solving_metrics = self.analyze_problem_solving(evidence)
        session_metrics = self.analyze_session_behavior(evidence)
        revision_metrics = self.analyze_revision_behavior(evidence)
        interview_metrics = self.analyze_interview_behavior(evidence)

        total_evidence_events = (
            attempt_metrics["total_attempts"]
            + session_metrics["total_sessions"]
            + revision_metrics["total_tracked_items"]
            + interview_metrics["total_interviews"]
        )

        sample_adequate = total_evidence_events >= self.MIN_SAMPLE_THRESHOLD

        if not sample_adequate:
            confidence = "insufficient_data"
        elif total_evidence_events >= self.HIGH_CONFIDENCE_THRESHOLD:
            confidence = "high"
        elif total_evidence_events >= self.MEDIUM_CONFIDENCE_THRESHOLD:
            confidence = "medium"
        else:
            confidence = "low"

        limitations: List[str] = [
            "All metrics are calculated strictly from local execution logs, test outputs, and session audit history.",
            "This intelligence engine strictly avoids psychological, personality, or hiring suitability assessments.",
        ]

        if not sample_adequate:
            limitations.insert(
                0,
                f"Sample size is below the minimum threshold ({total_evidence_events}/{self.MIN_SAMPLE_THRESHOLD} events). Metrics represent preliminary baseline observations.",
            )
        elif confidence == "low":
            limitations.insert(
                0,
                f"Sample size is modest ({total_evidence_events} events). Metrics will stabilize as more sessions are logged.",
            )

        patterns = self.detect_patterns(
            attempt_metrics, debugging_metrics, session_metrics, revision_metrics
        )

        profile_id = f"cbp_{uuid.uuid4().hex[:12]}"
        created_at = _get_utc_now_iso()

        profile = CodingBehaviorProfile(
            profile_id=profile_id,
            created_at=created_at,
            total_evidence_events=total_evidence_events,
            sample_adequate=sample_adequate,
            confidence=confidence,
            attempt_patterns=attempt_metrics,
            debugging_patterns=debugging_metrics,
            problem_solving_progression=problem_solving_metrics,
            session_behavior=session_metrics,
            revision_behavior=revision_metrics,
            interview_behavior=interview_metrics,
            patterns=patterns,
            limitations=limitations,
        )

        insights = self.generate_insights(
            sample_adequate,
            attempt_metrics,
            debugging_metrics,
            problem_solving_metrics,
            session_metrics,
            revision_metrics,
            interview_metrics,
        )

        recommendations = self.generate_recommendations(
            insights, attempt_metrics, revision_metrics
        )

        summary = (
            f"Behavioral intelligence analysis evaluated {total_evidence_events} evidence events "
            f"with {confidence.upper()} confidence. "
            f"First-attempt accuracy is {attempt_metrics['first_attempt_pass_rate']}%, "
            f"debugging persistence is {attempt_metrics['persistence_rate']}%, "
            f"and session completion rate is {session_metrics['completion_rate']}%."
        )

        report_id = f"cbr_{uuid.uuid4().hex[:12]}"
        report = BehaviorAnalysisReport(
            report_id=report_id,
            created_at=created_at,
            profile=profile,
            summary=summary,
            insights=insights,
            recommendations=recommendations,
            limitations=limitations,
        )

        if save:
            self._save_report(report)

        return report

    def _save_report(self, report: BehaviorAnalysisReport) -> None:
        """Persist profile, report, and individual insights non-destructively in session_tracking.db."""
        profile = report.profile
        profile_json = json.dumps(asdict(profile))

        dimensions = {
            "attempt_patterns": profile.attempt_patterns,
            "debugging_patterns": profile.debugging_patterns,
            "problem_solving_progression": profile.problem_solving_progression,
            "session_behavior": profile.session_behavior,
            "revision_behavior": profile.revision_behavior,
            "interview_behavior": profile.interview_behavior,
        }

        with self.get_tracking_connection() as conn:
            cur = conn.cursor()

            # Insert profile
            cur.execute(
                """
                INSERT OR REPLACE INTO coding_behavior_profiles
                (profile_id, created_at, total_evidence_events, sample_adequate, confidence, profile_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.profile_id,
                    profile.created_at,
                    profile.total_evidence_events,
                    1 if profile.sample_adequate else 0,
                    profile.confidence,
                    profile_json,
                ),
            )

            # Insert report
            cur.execute(
                """
                INSERT OR REPLACE INTO coding_behavior_reports
                (report_id, created_at, profile_id, summary, dimensions_json, insights_json, recommendations_json, limitations_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.created_at,
                    profile.profile_id,
                    report.summary,
                    json.dumps(dimensions),
                    json.dumps([asdict(ins) for ins in report.insights]),
                    json.dumps(report.recommendations),
                    json.dumps(report.limitations),
                ),
            )

            # Insert individual insights for querying
            for ins in report.insights:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO coding_behavior_insights
                    (insight_id, report_id, category, severity, title, description, evidence, sample_count, recommended_action, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ins.insight_id,
                        report.report_id,
                        ins.category.value,
                        ins.severity.value,
                        ins.title,
                        ins.description,
                        ins.evidence,
                        ins.sample_count,
                        ins.recommended_action,
                        report.created_at,
                    ),
                )

            conn.commit()

    def get_latest_profile(self) -> Optional[CodingBehaviorProfile]:
        """Retrieve the most recently generated coding behavior profile."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT profile_json FROM coding_behavior_profiles ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                return None

            data = json.loads(row["profile_json"])
            patterns = [
                CodingBehaviorPattern(
                    pattern_id=p["pattern_id"],
                    category=BehaviorCategory(p["category"]),
                    name=p["name"],
                    description=p["description"],
                    frequency=p["frequency"],
                    sample_count=p["sample_count"],
                    evidence_summary=p["evidence_summary"],
                )
                for p in data.get("patterns", [])
            ]
            data["patterns"] = patterns
            return CodingBehaviorProfile(**data)

    def get_report(self, report_id: str) -> Optional[BehaviorAnalysisReport]:
        """Retrieve a specific behavioral analysis report by its ID."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT r.report_id, r.created_at, r.profile_id, r.summary,
                       r.dimensions_json, r.insights_json, r.recommendations_json,
                       r.limitations_json, p.profile_json
                FROM coding_behavior_reports r
                JOIN coding_behavior_profiles p ON r.profile_id = p.profile_id
                WHERE r.report_id = ?
                """,
                (report_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            prof_data = json.loads(row["profile_json"])
            patterns = [
                CodingBehaviorPattern(
                    pattern_id=p["pattern_id"],
                    category=BehaviorCategory(p["category"]),
                    name=p["name"],
                    description=p["description"],
                    frequency=p["frequency"],
                    sample_count=p["sample_count"],
                    evidence_summary=p["evidence_summary"],
                )
                for p in prof_data.get("patterns", [])
            ]
            prof_data["patterns"] = patterns
            profile = CodingBehaviorProfile(**prof_data)

            insights_data = json.loads(row["insights_json"])
            insights = [
                CodingBehaviorInsight(
                    insight_id=ins["insight_id"],
                    category=BehaviorCategory(ins["category"]),
                    severity=InsightSeverity(ins["severity"]),
                    title=ins["title"],
                    description=ins["description"],
                    evidence=ins["evidence"],
                    sample_count=ins["sample_count"],
                    recommended_action=ins["recommended_action"],
                )
                for ins in insights_data
            ]

            return BehaviorAnalysisReport(
                report_id=row["report_id"],
                created_at=row["created_at"],
                profile=profile,
                summary=row["summary"],
                insights=insights,
                recommendations=json.loads(row["recommendations_json"]),
                limitations=json.loads(row["limitations_json"]),
            )

    def list_reports(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List historical behavioral analysis reports in reverse chronological order."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT report_id, created_at, profile_id, summary
                FROM coding_behavior_reports
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_insights(
        self,
        category: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 20,
    ) -> List[CodingBehaviorInsight]:
        """Query persisted behavioral insights with optional category and severity filters."""
        query = (
            "SELECT insight_id, category, severity, title, description, evidence, sample_count, recommended_action "
            "FROM coding_behavior_insights WHERE 1=1"
        )
        params: List[Any] = []

        if category:
            query += " AND category = ?"
            params.append(category)
        if severity:
            query += " AND severity = ?"
            params.append(severity)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

            return [
                CodingBehaviorInsight(
                    insight_id=r["insight_id"],
                    category=BehaviorCategory(r["category"]),
                    severity=InsightSeverity(r["severity"]),
                    title=r["title"],
                    description=r["description"],
                    evidence=r["evidence"],
                    sample_count=r["sample_count"],
                    recommended_action=r["recommended_action"],
                )
                for r in rows
            ]

    def get_overview(self) -> Dict[str, Any]:
        """Fast summary dictionary for interactive dashboard visualization."""
        latest_profile = self.get_latest_profile()
        if not latest_profile:
            # Generate on the fly without forced persistence
            report = self.analyze(save=False)
            latest_profile = report.profile
            insights = report.insights
            recommendations = report.recommendations
        else:
            insights = self.get_insights(limit=10)
            # Fetch latest report for recommendations
            latest_reports = self.list_reports(limit=1)
            recommendations = []
            if latest_reports:
                rep = self.get_report(latest_reports[0]["report_id"])
                if rep:
                    recommendations = rep.recommendations

        return {
            "profile_id": latest_profile.profile_id,
            "created_at": latest_profile.created_at,
            "total_evidence_events": latest_profile.total_evidence_events,
            "sample_adequate": latest_profile.sample_adequate,
            "confidence": latest_profile.confidence,
            "attempt_patterns": latest_profile.attempt_patterns,
            "debugging_patterns": latest_profile.debugging_patterns,
            "problem_solving_progression": latest_profile.problem_solving_progression,
            "session_behavior": latest_profile.session_behavior,
            "revision_behavior": latest_profile.revision_behavior,
            "interview_behavior": latest_profile.interview_behavior,
            "patterns": [asdict(p) for p in latest_profile.patterns],
            "insights": [asdict(i) for i in insights],
            "recommendations": recommendations,
            "limitations": latest_profile.limitations,
        }
