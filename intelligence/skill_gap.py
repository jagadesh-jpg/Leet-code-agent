"""Personal Skill Gap & Focus Prioritization Engine.

Milestone 6.3.24: Personal Skill Gap & Focus Prioritization Engine.
Provides:
1. Evidence-based algorithmic skill gap analysis across all standard and custom topics.
2. Transparent, deterministic prioritization scoring formula distinguishing:
   - Demonstrated weakness (high failure rate, unresolved attempts).
   - Inconsistent performance (mixed success, multiple attempts required).
   - Outdated evidence (overdue spaced repetition, historical decay).
   - Insufficient practice (0 attempts or low sample size; never labeled as weak).
   - Demonstrated strength (high success rate, multiple distinct solves).
3. Conservative confidence tiers (insufficient_data, low, medium, high) backed by evidence counts.
4. Deterministic focus queue mapping prioritized topics to real available problems and suggested difficulties.
5. Exportable, preview-only recommendations that never silently alter preparation plans.
6. Non-destructive persistence in session_tracking.db (skill_gap_reports, skill_gap_items).
   Production progress.db remains strictly read-only.

100% offline, local-first, zero external API or LLM calls.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from intelligence.topics import CURATED_PROBLEM_TOPICS, STANDARD_TOPICS, get_problem_topics
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from problems import load_problems
import store


class SkillGapPriority(str, Enum):
    """Categorized priority levels for algorithmic focus."""
    P0_CRITICAL = "P0"  # Severe unresolved bugs, high failure rate, or overdue weak topics
    P1_HIGH = "P1"      # Demonstrated weakness or low success rate on core topics
    P2_MEDIUM = "P2"    # Under-practiced topics, inconsistent performance, or stale practice
    P3_LOW = "P3"       # Demonstrated strengths or well-maintained topics


class SkillGapConfidence(str, Enum):
    """Statistical confidence based strictly on verified evidence count."""
    HIGH = "high"                       # >= 12 evidence events
    MEDIUM = "medium"                   # 5 - 11 evidence events
    LOW = "low"                         # 2 - 4 evidence events
    INSUFFICIENT_DATA = "insufficient_data"  # 0 - 1 evidence events


class SkillGapType(str, Enum):
    """Objective classification of the learner's skill state for a topic."""
    DEMONSTRATED_WEAKNESS = "demonstrated_weakness"
    INCONSISTENT_PERFORMANCE = "inconsistent_performance"
    OUTDATED_EVIDENCE = "outdated_evidence"
    INSUFFICIENT_PRACTICE = "insufficient_practice"
    DEMONSTRATED_STRENGTH = "demonstrated_strength"


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_utc_now_iso() -> str:
    return _get_utc_now().isoformat()


@dataclass
class SkillEvidence:
    """Detailed evidence backing a topic's skill gap assessment."""
    topic: str
    total_problems_available: int
    attempted_problems_count: int
    solved_problems_count: int
    unsolved_problems_count: int
    total_runs: int
    passed_runs: int
    failed_runs: int
    wrong_answer_count: int
    compile_error_count: int
    runtime_error_count: int
    timeout_count: int
    success_rate: float                   # Percentage (0.0 - 100.0)
    unresolved_problem_ids: List[str] = field(default_factory=list)
    solved_problem_ids: List[str] = field(default_factory=list)
    overdue_revision_count: int = 0
    practice_sessions_count: int = 0
    mock_interview_evaluations: int = 0
    total_evidence_events: int = 0
    last_practiced_at: Optional[str] = None


@dataclass
class SkillGap:
    """Evaluated skill gap for a specific algorithmic topic."""
    topic: str
    priority_score: float                 # 0.0 to 100.0 transparent deterministic score
    priority_tier: SkillGapPriority
    gap_type: SkillGapType
    confidence: SkillGapConfidence
    evidence: SkillEvidence
    score_breakdown: Dict[str, float]     # Component scores explaining priority_score
    reason: str
    suggested_difficulty: str             # "Easy", "Medium", "Hard"
    suggested_action: str
    recommended_problem_ids: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)


@dataclass
class PrioritizedFocusItem:
    """An actionable entry in the deterministic prioritized focus queue."""
    rank: int
    topic: str
    priority_score: float
    priority_tier: SkillGapPriority
    gap_type: SkillGapType
    confidence: SkillGapConfidence
    reason: str
    suggested_difficulty: str
    suggested_action: str
    evidence_count: int
    related_problem_ids: List[str] = field(default_factory=list)


@dataclass
class SkillGapReport:
    """Exportable comprehensive report on personal skill gaps and focus priorities."""
    report_id: str
    created_at: str
    total_topics_evaluated: int
    coverage_summary: Dict[str, Any]
    highest_priority_gaps: List[SkillGap]
    insufficient_evidence_topics: List[SkillGap]
    demonstrated_strengths: List[SkillGap]
    all_topic_gaps: List[SkillGap]
    focus_queue: List[PrioritizedFocusItem]
    recommendations: List[Dict[str, Any]]
    limitations: List[str]


class SkillGapAnalyzer:
    """Analyzes multi-source local coding evidence to compute deterministic skill gaps and focus priorities."""

    # Confidence event thresholds
    HIGH_CONFIDENCE_THRESHOLD = 12
    MEDIUM_CONFIDENCE_THRESHOLD = 5
    LOW_CONFIDENCE_THRESHOLD = 2

    # Scoring weights (sum to 100 max potential friction)
    WEIGHT_FAILURE_RATE = 35.0
    WEIGHT_UNRESOLVED = 25.0
    WEIGHT_OVERDUE = 20.0
    WEIGHT_UNDER_PRACTICE = 10.0
    WEIGHT_STALENESS = 10.0

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
        """Create skill gap persistence tables non-destructively in session_tracking.db."""
        with self.get_tracking_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_gap_reports (
                    report_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    total_topics_evaluated INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL,
                    report_json TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_gap_items (
                    item_id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    priority_score REAL NOT NULL,
                    priority_tier TEXT NOT NULL,
                    gap_type TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    evidence_count INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    suggested_difficulty TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (report_id) REFERENCES skill_gap_reports(report_id)
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sg_reports_created ON skill_gap_reports(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sg_items_rep ON skill_gap_items(report_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sg_items_topic ON skill_gap_items(topic)")
            conn.commit()

    def _load_all_problems(self) -> List[Dict[str, Any]]:
        """Load curated and custom problems without modifying databases."""
        problems = list(load_problems())
        if self.progress_db_path.exists():
            try:
                custom_probs = store.get_custom_problems(db_path=self.progress_db_path)
                problems.extend(custom_probs)
            except Exception:
                pass
        return problems

    def _collect_raw_evidence(self) -> Dict[str, Any]:
        """Collect observational raw data safely across progress.db and session_tracking.db."""
        evidence: Dict[str, Any] = {
            "attempts": [],
            "workspace_runs": [],
            "practice_sessions": [],
            "revision_items": [],
            "mock_interviews": [],
        }

        # 1. progress.db (attempts) - strictly read-only
        if self.progress_db_path.exists():
            try:
                with self.get_progress_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attempts'")
                    if cur.fetchone():
                        cur.execute("SELECT id, problem_id, attempt_no, status, error, created_at FROM attempts")
                        evidence["attempts"] = [dict(r) for r in cur.fetchall()]
            except Exception:
                pass

        # 2. session_tracking.db
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
                                   compile_error, execution_error, created_at
                            FROM workspace_runs
                            """
                        )
                        evidence["workspace_runs"] = [dict(r) for r in cur.fetchall()]

                    # practice_sessions
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='practice_sessions'")
                    if cur.fetchone():
                        cur.execute(
                            """
                            SELECT session_id, problem_id, status, submissions_count, passed_submissions_count,
                                   failed_submissions_count, final_submission_passed, created_at
                            FROM practice_sessions
                            """
                        )
                        evidence["practice_sessions"] = [dict(r) for r in cur.fetchall()]

                    # revision_items
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='revision_items'")
                    if cur.fetchone():
                        cur.execute(
                            """
                            SELECT problem_id, difficulty, topics_json, status, interval_days, ease_factor
                            FROM revision_items
                            """
                        )
                        evidence["revision_items"] = [dict(r) for r in cur.fetchall()]

                    # mock_interviews
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mock_interviews'")
                    if cur.fetchone():
                        cur.execute(
                            """
                            SELECT interview_id, status, total_score, correctness_score, complexity_score, created_at
                            FROM mock_interviews
                            """
                        )
                        evidence["mock_interviews"] = [dict(r) for r in cur.fetchall()]
            except Exception:
                pass

        return evidence

    def extract_topic_evidence(self) -> Dict[str, SkillEvidence]:
        """Map raw observational evidence to distinct topics."""
        all_problems = self._load_all_problems()
        problem_by_id = {p["id"]: p for p in all_problems if "id" in p}

        # Build topic-to-problems mapping
        topic_to_pids: Dict[str, Set[str]] = {}
        for p in all_problems:
            topics = get_problem_topics(p)
            for t in topics:
                t_clean = t.strip()
                if t_clean:
                    topic_to_pids.setdefault(t_clean, set()).add(p["id"])

        # Ensure all standard topics exist even if 0 problems in current inventory
        for st in STANDARD_TOPICS:
            topic_to_pids.setdefault(st, set())

        raw = self._collect_raw_evidence()
        attempts = raw.get("attempts", [])
        workspace_runs = raw.get("workspace_runs", [])
        practice_sessions = raw.get("practice_sessions", [])
        revision_items = raw.get("revision_items", [])

        # Structure problem outcomes: pid -> {runs, passed, failures, solved, last_time}
        problem_stats: Dict[str, Dict[str, Any]] = {}

        def get_prob_stat(pid: str) -> Dict[str, Any]:
            if pid not in problem_stats:
                problem_stats[pid] = {
                    "total_runs": 0,
                    "passed_runs": 0,
                    "failed_runs": 0,
                    "wrong_answer": 0,
                    "compile_error": 0,
                    "runtime_error": 0,
                    "timeout": 0,
                    "solved": False,
                    "last_time": None,
                }
            return problem_stats[pid]

        # Process progress.db attempts
        for a in attempts:
            pid = a.get("problem_id")
            if not pid:
                continue
            ps = get_prob_stat(pid)
            ps["total_runs"] += 1
            status = str(a.get("status", "")).lower()
            t_str = a.get("created_at")
            if t_str and (not ps["last_time"] or t_str > ps["last_time"]):
                ps["last_time"] = t_str

            if status in ("passed", "success", "accepted"):
                ps["passed_runs"] += 1
                ps["solved"] = True
            else:
                ps["failed_runs"] += 1
                err = str(a.get("error", "")).lower()
                if "syntax" in err or "compile" in err:
                    ps["compile_error"] += 1
                elif "timeout" in err:
                    ps["timeout"] += 1
                elif "assertion" in err or "wrong" in status:
                    ps["wrong_answer"] += 1
                else:
                    ps["runtime_error"] += 1

        # Process workspace_runs
        for r in workspace_runs:
            pid = r.get("problem_id")
            if not pid:
                continue
            ps = get_prob_stat(pid)
            ps["total_runs"] += 1
            status = str(r.get("status", "")).lower()
            t_str = r.get("created_at")
            if t_str and (not ps["last_time"] or t_str > ps["last_time"]):
                ps["last_time"] = t_str

            if status in ("passed", "success", "accepted"):
                ps["passed_runs"] += 1
                ps["solved"] = True
            else:
                ps["failed_runs"] += 1
                if status in ("wrong_answer", "failed", "fail"):
                    ps["wrong_answer"] += 1
                elif status in ("compile_error", "compilation_error"):
                    ps["compile_error"] += 1
                elif status in ("timeout", "time_limit_exceeded"):
                    ps["timeout"] += 1
                else:
                    ps["runtime_error"] += 1

        # Process practice_sessions
        for s in practice_sessions:
            pid = s.get("problem_id")
            if not pid:
                continue
            ps = get_prob_stat(pid)
            if s.get("final_submission_passed"):
                ps["solved"] = True
            t_str = s.get("created_at")
            if t_str and (not ps["last_time"] or t_str > ps["last_time"]):
                ps["last_time"] = t_str

        # Map revision items to problem IDs
        overdue_pids: Set[str] = set()
        for rev in revision_items:
            pid = rev.get("problem_id")
            if pid and rev.get("status") == "overdue":
                overdue_pids.add(pid)

        # Build SkillEvidence per topic
        topic_evidence: Dict[str, SkillEvidence] = {}

        for topic, pids in topic_to_pids.items():
            attempted_pids: Set[str] = set()
            solved_pids: Set[str] = set()
            unsolved_pids: Set[str] = set()
            total_runs = 0
            passed_runs = 0
            failed_runs = 0
            wa_cnt = 0
            ce_cnt = 0
            re_cnt = 0
            to_cnt = 0
            last_practiced = None
            overdue_cnt = 0

            for pid in pids:
                if pid in overdue_pids:
                    overdue_cnt += 1

                if pid in problem_stats:
                    ps = problem_stats[pid]
                    if ps["total_runs"] > 0:
                        attempted_pids.add(pid)
                        total_runs += ps["total_runs"]
                        passed_runs += ps["passed_runs"]
                        failed_runs += ps["failed_runs"]
                        wa_cnt += ps["wrong_answer"]
                        ce_cnt += ps["compile_error"]
                        re_cnt += ps["runtime_error"]
                        to_cnt += ps["timeout"]

                        if ps["solved"]:
                            solved_pids.add(pid)
                        else:
                            unsolved_pids.add(pid)

                        if ps["last_time"] and (not last_practiced or ps["last_time"] > last_practiced):
                            last_practiced = ps["last_time"]

            # Success rate on attempted problems or runs
            if len(attempted_pids) > 0:
                success_rate = round((len(solved_pids) / len(attempted_pids)) * 100.0, 1)
            else:
                success_rate = 0.0

            total_events = total_runs + overdue_cnt

            topic_evidence[topic] = SkillEvidence(
                topic=topic,
                total_problems_available=len(pids),
                attempted_problems_count=len(attempted_pids),
                solved_problems_count=len(solved_pids),
                unsolved_problems_count=len(unsolved_pids),
                total_runs=total_runs,
                passed_runs=passed_runs,
                failed_runs=failed_runs,
                wrong_answer_count=wa_cnt,
                compile_error_count=ce_cnt,
                runtime_error_count=re_cnt,
                timeout_count=to_cnt,
                success_rate=success_rate,
                unresolved_problem_ids=sorted(list(unsolved_pids)),
                solved_problem_ids=sorted(list(solved_pids)),
                overdue_revision_count=overdue_cnt,
                practice_sessions_count=len(attempted_pids),
                mock_interview_evaluations=0,
                total_evidence_events=total_events,
                last_practiced_at=last_practiced,
            )

        return topic_evidence

    def calculate_priority_score(
        self, ev: SkillEvidence
    ) -> Tuple[float, SkillGapType, Dict[str, float], str]:
        """Calculate deterministic priority score (0.0 to 100.0) and gap classification.

        Transparent scoring components:
        1. Failure Rate Penalty (0 - 35 pts): Proportion of failing runs/unsolved attempts.
        2. Unresolved Problems Penalty (0 - 25 pts): 12.5 pts per problem with 0 passes (max 25).
        3. Overdue Revision Penalty (0 - 20 pts): 10 pts per overdue spaced repetition problem (max 20).
        4. Under-practice / Coverage Penalty (0 - 10 pts): Low coverage on available problems.
        5. Staleness / Inactivity Penalty (0 - 10 pts): Decay if practice is older than 14 days or never practiced.
        6. Strength Discount (-10 to -30 pts): Subtracted if topic has >= 2 solved and >= 80% success rate.
        """
        score_breakdown: Dict[str, float] = {
            "failure_rate_penalty": 0.0,
            "unresolved_penalty": 0.0,
            "overdue_penalty": 0.0,
            "under_practice_penalty": 0.0,
            "staleness_penalty": 0.0,
            "strength_discount": 0.0,
        }

        # 0 attempts and 0 revisions -> INSUFFICIENT_PRACTICE (never demonstrated weakness)
        if ev.attempted_problems_count == 0 and ev.overdue_revision_count == 0:
            score_breakdown["under_practice_penalty"] = 10.0
            score_breakdown["staleness_penalty"] = 5.0
            total_score = 15.0
            gap_type = SkillGapType.INSUFFICIENT_PRACTICE
            reason = (
                f"No practice attempts recorded for {ev.topic}. "
                f"{ev.total_problems_available} problems available in library."
            )
            return round(total_score, 1), gap_type, score_breakdown, reason

        # 1. Failure rate penalty (0 - 35 pts)
        if ev.total_runs > 0:
            fail_ratio = ev.failed_runs / ev.total_runs
            fail_pts = round(fail_ratio * self.WEIGHT_FAILURE_RATE, 1)
        else:
            fail_pts = 0.0
        score_breakdown["failure_rate_penalty"] = fail_pts

        # 2. Unresolved problems penalty (0 - 25 pts)
        unres_cnt = len(ev.unresolved_problem_ids)
        unres_pts = min(unres_cnt * 12.5, self.WEIGHT_UNRESOLVED)
        score_breakdown["unresolved_penalty"] = round(unres_pts, 1)

        # 3. Overdue revision penalty (0 - 20 pts)
        overdue_pts = min(ev.overdue_revision_count * 10.0, self.WEIGHT_OVERDUE)
        score_breakdown["overdue_penalty"] = round(overdue_pts, 1)

        # 4. Under-practice / Coverage penalty (0 - 10 pts)
        if ev.total_problems_available > 0:
            unsolved_ratio = (ev.total_problems_available - ev.solved_problems_count) / ev.total_problems_available
            coverage_pts = round(max(0.0, unsolved_ratio) * self.WEIGHT_UNDER_PRACTICE, 1)
        else:
            coverage_pts = 0.0
        score_breakdown["under_practice_penalty"] = coverage_pts

        # 5. Staleness penalty (0 - 10 pts)
        staleness_pts = 0.0
        if ev.last_practiced_at:
            try:
                last_dt = datetime.fromisoformat(ev.last_practiced_at.replace("Z", "+00:00"))
                days_diff = (_get_utc_now() - last_dt).days
                if days_diff > 30:
                    staleness_pts = 10.0
                elif days_diff > 14:
                    staleness_pts = 5.0
            except Exception:
                pass
        else:
            staleness_pts = 5.0
        score_breakdown["staleness_penalty"] = staleness_pts

        # Calculate base raw score
        raw_score = fail_pts + unres_pts + overdue_pts + coverage_pts + staleness_pts

        # 6. Classify gap type and strength discount
        if ev.solved_problems_count >= 2 and ev.success_rate >= 80.0 and unres_cnt == 0 and ev.overdue_revision_count == 0:
            gap_type = SkillGapType.DEMONSTRATED_STRENGTH
            discount = 25.0
            score_breakdown["strength_discount"] = -discount
            final_score = max(0.0, raw_score - discount)
            reason = (
                f"Strong proficiency demonstrated: {ev.solved_problems_count} problems solved with "
                f"{ev.success_rate}% success rate and 0 unresolved issues."
            )
        elif unres_cnt >= 1 or (ev.failed_runs > ev.passed_runs and ev.total_runs >= 2):
            gap_type = SkillGapType.DEMONSTRATED_WEAKNESS
            final_score = min(100.0, raw_score)
            reasons = []
            if unres_cnt > 0:
                reasons.append(f"{unres_cnt} unresolved problem(s) ({', '.join(ev.unresolved_problem_ids)})")
            if ev.failed_runs > 0:
                reasons.append(f"{ev.failed_runs} failed test run(s) ({ev.success_rate}% success rate)")
            if ev.overdue_revision_count > 0:
                reasons.append(f"{ev.overdue_revision_count} overdue revision(s)")
            reason = f"Demonstrated weakness: {'; '.join(reasons)}."
        elif ev.overdue_revision_count >= 1:
            gap_type = SkillGapType.OUTDATED_EVIDENCE
            final_score = min(100.0, raw_score)
            reason = f"Outdated evidence: {ev.overdue_revision_count} scheduled revision item(s) are overdue."
        elif ev.total_runs >= 3 and 40.0 <= ev.success_rate <= 75.0:
            gap_type = SkillGapType.INCONSISTENT_PERFORMANCE
            final_score = min(100.0, raw_score)
            reason = f"Inconsistent performance: {ev.success_rate}% success rate across {ev.total_runs} test runs."
        else:
            gap_type = SkillGapType.INSUFFICIENT_PRACTICE
            final_score = min(100.0, raw_score)
            reason = f"Limited practice: only {ev.attempted_problems_count} problem(s) attempted so far."

        return round(final_score, 1), gap_type, score_breakdown, reason

    def determine_confidence(self, event_count: int) -> SkillGapConfidence:
        """Assign conservative confidence based strictly on verified evidence count."""
        if event_count >= self.HIGH_CONFIDENCE_THRESHOLD:
            return SkillGapConfidence.HIGH
        elif event_count >= self.MEDIUM_CONFIDENCE_THRESHOLD:
            return SkillGapConfidence.MEDIUM
        elif event_count >= self.LOW_CONFIDENCE_THRESHOLD:
            return SkillGapConfidence.LOW
        else:
            return SkillGapConfidence.INSUFFICIENT_DATA

    def determine_priority_tier(self, priority_score: float, gap_type: SkillGapType) -> SkillGapPriority:
        """Map score and gap type to actionable priority tier."""
        if gap_type == SkillGapType.DEMONSTRATED_STRENGTH:
            return SkillGapPriority.P3_LOW
        if priority_score >= 65.0 or (gap_type == SkillGapType.DEMONSTRATED_WEAKNESS and priority_score >= 50.0):
            return SkillGapPriority.P0_CRITICAL
        elif priority_score >= 45.0:
            return SkillGapPriority.P1_HIGH
        elif priority_score >= 25.0:
            return SkillGapPriority.P2_MEDIUM
        else:
            return SkillGapPriority.P3_LOW

    def suggest_next_practice(
        self, topic: str, ev: SkillEvidence, gap_type: SkillGapType
    ) -> Tuple[str, str, List[str]]:
        """Determine recommended difficulty, suggested action, and real problem candidates."""
        all_problems = self._load_all_problems()
        topic_problems = [
            p for p in all_problems if topic in get_problem_topics(p) and "id" in p
        ]

        # 1. If unresolved problems exist, prioritize them first
        if ev.unresolved_problem_ids:
            unresolved = ev.unresolved_problem_ids
            prob = next((p for p in topic_problems if p["id"] == unresolved[0]), None)
            diff = (prob.get("difficulty") or "Medium").capitalize() if prob else "Medium"
            action = f"Debug and resolve failing test cases on '{unresolved[0]}'."
            return diff, action, unresolved

        # 2. If overdue revision items exist, suggest revision
        if ev.overdue_revision_count > 0:
            action = f"Complete scheduled spaced repetition review for overdue {topic} problem(s)."
            return "Medium", action, ev.solved_problem_ids[:2]

        # 3. Based on gap_type
        if gap_type == SkillGapType.INSUFFICIENT_PRACTICE:
            # Pick easiest available unattempted problem
            unattempted = [
                p for p in topic_problems if p["id"] not in ev.solved_problem_ids
            ]
            easy_probs = [p for p in unattempted if p.get("difficulty") == "easy"]
            candidate = easy_probs[0] if easy_probs else (unattempted[0] if unattempted else None)
            if candidate:
                diff = candidate.get("difficulty", "easy").capitalize()
                action = f"Solve foundational problem '{candidate['id']}' to establish baseline technique."
                return diff, action, [candidate["id"]]
            else:
                return "Easy", f"Practice foundational {topic} problem.", []

        elif gap_type == SkillGapType.DEMONSTRATED_WEAKNESS:
            # Practice Easy or Medium problem
            unsolved = [p for p in topic_problems if p["id"] not in ev.solved_problem_ids]
            candidate = unsolved[0] if unsolved else (topic_problems[0] if topic_problems else None)
            diff = (candidate.get("difficulty") or "Easy").capitalize() if candidate else "Easy"
            action = f"Strengthen fundamentals with targeted practice on {topic}."
            rec_ids = [candidate["id"]] if candidate else []
            return diff, action, rec_ids

        elif gap_type == SkillGapType.DEMONSTRATED_STRENGTH:
            # Challenge with Hard problem or maintain
            hard_probs = [p for p in topic_problems if p.get("difficulty") == "hard"]
            candidate = hard_probs[0] if hard_probs else None
            diff = "Hard" if candidate else "Medium"
            action = f"Maintain mastery with advanced problem challenges or mock interview sets."
            rec_ids = [candidate["id"]] if candidate else ev.solved_problem_ids[:1]
            return diff, action, rec_ids

        else:
            # Medium default
            action = f"Consolidate {topic} algorithmic patterns through targeted practice."
            rec_ids = [p["id"] for p in topic_problems[:2]]
            return "Medium", action, rec_ids

    def analyze(self, save: bool = True) -> SkillGapReport:
        """Run complete skill gap analysis across all available algorithmic topics."""
        topic_evidence_map = self.extract_topic_evidence()
        all_gaps: List[SkillGap] = []

        for topic, ev in topic_evidence_map.items():
            prio_score, gap_type, breakdown, reason = self.calculate_priority_score(ev)
            confidence = self.determine_confidence(ev.total_evidence_events)
            prio_tier = self.determine_priority_tier(prio_score, gap_type)
            sugg_diff, sugg_action, rec_pids = self.suggest_next_practice(topic, ev, gap_type)

            limitations: List[str] = [
                "Score is 100% deterministic, computed exclusively from verified local test executions and session tracking.",
                "Does not reflect general cognitive ability, personality, or hiring suitability.",
            ]
            if confidence == SkillGapConfidence.INSUFFICIENT_DATA:
                limitations.insert(
                    0,
                    f"Sample size is insufficient ({ev.total_evidence_events} event(s)). Assessment is a baseline placeholder.",
                )

            all_gaps.append(
                SkillGap(
                    topic=topic,
                    priority_score=prio_score,
                    priority_tier=prio_tier,
                    gap_type=gap_type,
                    confidence=confidence,
                    evidence=ev,
                    score_breakdown=breakdown,
                    reason=reason,
                    suggested_difficulty=sugg_diff,
                    suggested_action=sugg_action,
                    recommended_problem_ids=rec_pids,
                    limitations=limitations,
                )
            )

        # Sort all gaps by priority score descending
        all_gaps.sort(key=lambda g: g.priority_score, reverse=True)

        # Build categorized slices
        highest_priority = [g for g in all_gaps if g.priority_tier in (SkillGapPriority.P0_CRITICAL, SkillGapPriority.P1_HIGH)]
        insufficient_evidence = [g for g in all_gaps if g.gap_type == SkillGapType.INSUFFICIENT_PRACTICE]
        demonstrated_strengths = [g for g in all_gaps if g.gap_type == SkillGapType.DEMONSTRATED_STRENGTH]

        # Build prioritized focus queue (distinct topics only, ranked 1 to N)
        focus_queue: List[PrioritizedFocusItem] = []
        seen_topics: Set[str] = set()
        rank = 1

        for g in all_gaps:
            if g.topic not in seen_topics:
                seen_topics.add(g.topic)
                focus_queue.append(
                    PrioritizedFocusItem(
                        rank=rank,
                        topic=g.topic,
                        priority_score=g.priority_score,
                        priority_tier=g.priority_tier,
                        gap_type=g.gap_type,
                        confidence=g.confidence,
                        reason=g.reason,
                        suggested_difficulty=g.suggested_difficulty,
                        suggested_action=g.suggested_action,
                        evidence_count=g.evidence.total_evidence_events,
                        related_problem_ids=g.recommended_problem_ids,
                    )
                )
                rank += 1

        # Coverage summary
        total_topics = len(all_gaps)
        practiced_topics = sum(1 for g in all_gaps if g.evidence.attempted_problems_count > 0)
        unpracticed_topics = total_topics - practiced_topics
        coverage_pct = round((practiced_topics / total_topics * 100.0), 1) if total_topics > 0 else 0.0

        coverage_summary = {
            "total_topics": total_topics,
            "practiced_topics": practiced_topics,
            "unpracticed_topics": unpracticed_topics,
            "coverage_percentage": coverage_pct,
            "critical_gap_count": len([g for g in all_gaps if g.priority_tier == SkillGapPriority.P0_CRITICAL]),
            "strengths_count": len(demonstrated_strengths),
        }

        # Recommendations preview
        recommendations: List[Dict[str, Any]] = []
        for g in highest_priority[:3]:
            recommendations.append({
                "recommendation_id": f"rec_{uuid.uuid4().hex[:8]}",
                "topic": g.topic,
                "priority": g.priority_tier.value,
                "suggested_action": g.suggested_action,
                "suggested_difficulty": g.suggested_difficulty,
                "rationale": g.reason,
                "candidate_problems": g.recommended_problem_ids,
            })

        if not recommendations and demonstrated_strengths:
            recommendations.append({
                "recommendation_id": f"rec_{uuid.uuid4().hex[:8]}",
                "topic": demonstrated_strengths[0].topic,
                "priority": "P2",
                "suggested_action": demonstrated_strengths[0].suggested_action,
                "suggested_difficulty": demonstrated_strengths[0].suggested_difficulty,
                "rationale": "Maintain strong algorithmic proficiency with periodic revision.",
                "candidate_problems": demonstrated_strengths[0].recommended_problem_ids,
            })

        limitations = [
            "All skill gaps are calculated strictly from offline local execution records and tracking history.",
            "Missing topic practice is categorized as 'insufficient_practice', never as negative ability.",
            "This engine never alters active interview preparation plans automatically; all outputs are preview-only.",
        ]

        report_id = f"sgr_{uuid.uuid4().hex[:12]}"
        report = SkillGapReport(
            report_id=report_id,
            created_at=_get_utc_now_iso(),
            total_topics_evaluated=total_topics,
            coverage_summary=coverage_summary,
            highest_priority_gaps=highest_priority,
            insufficient_evidence_topics=insufficient_evidence,
            demonstrated_strengths=demonstrated_strengths,
            all_topic_gaps=all_gaps,
            focus_queue=focus_queue,
            recommendations=recommendations,
            limitations=limitations,
        )

        if save:
            self._save_report(report)

        return report

    def _save_report(self, report: SkillGapReport) -> None:
        """Persist report and queue items non-destructively in session_tracking.db."""
        report_dict = asdict(report)
        report_json = json.dumps(report_dict)

        summary = (
            f"Evaluated {report.total_topics_evaluated} algorithmic topics with {report.coverage_summary['coverage_percentage']}% coverage. "
            f"Identified {len(report.highest_priority_gaps)} high-priority gap(s) and {len(report.demonstrated_strengths)} strength(s)."
        )

        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO skill_gap_reports
                (report_id, created_at, total_topics_evaluated, summary, report_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.created_at,
                    report.total_topics_evaluated,
                    summary,
                    report_json,
                ),
            )

            for item in report.focus_queue:
                item_id = f"sgi_{uuid.uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO skill_gap_items
                    (item_id, report_id, topic, priority_score, priority_tier, gap_type, confidence, evidence_count, reason, suggested_difficulty, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        report.report_id,
                        item.topic,
                        item.priority_score,
                        item.priority_tier.value,
                        item.gap_type.value,
                        item.confidence.value,
                        item.evidence_count,
                        item.reason,
                        item.suggested_difficulty,
                        report.created_at,
                    ),
                )

            conn.commit()

    def get_latest_report(self) -> Optional[SkillGapReport]:
        """Retrieve most recently persisted SkillGapReport."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT report_json FROM skill_gap_reports ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                return None

            data = json.loads(row["report_json"])
            return self._deserialize_report(data)

    def get_report(self, report_id: str) -> Optional[SkillGapReport]:
        """Retrieve a specific SkillGapReport by its report_id."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT report_json FROM skill_gap_reports WHERE report_id = ?",
                (report_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            data = json.loads(row["report_json"])
            return self._deserialize_report(data)

    def list_reports(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List historical reports in reverse chronological order."""
        with self.get_tracking_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT report_id, created_at, total_topics_evaluated, summary
                FROM skill_gap_reports
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_focus_queue(self, limit: int = 20) -> List[PrioritizedFocusItem]:
        """Fetch current prioritized focus queue items."""
        latest = self.get_latest_report()
        if not latest:
            latest = self.analyze(save=False)
        return latest.focus_queue[:limit]

    def get_overview(self) -> Dict[str, Any]:
        """Fast summary dictionary for interactive dashboard rendering."""
        latest = self.get_latest_report()
        if not latest:
            latest = self.analyze(save=False)

        top_gaps = [asdict(g) for g in latest.highest_priority_gaps[:3]]
        strengths = [asdict(g) for g in latest.demonstrated_strengths[:3]]
        unpracticed = [asdict(g) for g in latest.insufficient_evidence_topics[:5]]
        queue = [asdict(it) for it in latest.focus_queue[:10]]

        return {
            "report_id": latest.report_id,
            "created_at": latest.created_at,
            "coverage_summary": latest.coverage_summary,
            "top_gaps": top_gaps,
            "strengths": strengths,
            "insufficient_evidence_topics": unpracticed,
            "focus_queue": queue,
            "recommendations": latest.recommendations,
            "limitations": latest.limitations,
        }

    def _deserialize_report(self, data: Dict[str, Any]) -> SkillGapReport:
        """Helper to reconstruct SkillGapReport dataclass from JSON dict."""
        def make_evidence(ev_dict: Dict[str, Any]) -> SkillEvidence:
            return SkillEvidence(**ev_dict)

        def make_gap(gap_dict: Dict[str, Any]) -> SkillGap:
            ev = make_evidence(gap_dict["evidence"])
            return SkillGap(
                topic=gap_dict["topic"],
                priority_score=gap_dict["priority_score"],
                priority_tier=SkillGapPriority(gap_dict["priority_tier"]),
                gap_type=SkillGapType(gap_dict["gap_type"]),
                confidence=SkillGapConfidence(gap_dict["confidence"]),
                evidence=ev,
                score_breakdown=gap_dict.get("score_breakdown", {}),
                reason=gap_dict.get("reason", ""),
                suggested_difficulty=gap_dict.get("suggested_difficulty", "Medium"),
                suggested_action=gap_dict.get("suggested_action", ""),
                recommended_problem_ids=gap_dict.get("recommended_problem_ids", []),
                limitations=gap_dict.get("limitations", []),
            )

        def make_queue_item(item_dict: Dict[str, Any]) -> PrioritizedFocusItem:
            return PrioritizedFocusItem(
                rank=item_dict["rank"],
                topic=item_dict["topic"],
                priority_score=item_dict["priority_score"],
                priority_tier=SkillGapPriority(item_dict["priority_tier"]),
                gap_type=SkillGapType(item_dict["gap_type"]),
                confidence=SkillGapConfidence(item_dict["confidence"]),
                reason=item_dict.get("reason", ""),
                suggested_difficulty=item_dict.get("suggested_difficulty", "Medium"),
                suggested_action=item_dict.get("suggested_action", ""),
                evidence_count=item_dict.get("evidence_count", 0),
                related_problem_ids=item_dict.get("related_problem_ids", []),
            )

        all_gaps = [make_gap(g) for g in data.get("all_topic_gaps", [])]
        high_prio = [make_gap(g) for g in data.get("highest_priority_gaps", [])]
        insufficient = [make_gap(g) for g in data.get("insufficient_evidence_topics", [])]
        strengths = [make_gap(g) for g in data.get("demonstrated_strengths", [])]
        queue = [make_queue_item(it) for it in data.get("focus_queue", [])]

        return SkillGapReport(
            report_id=data["report_id"],
            created_at=data["created_at"],
            total_topics_evaluated=data["total_topics_evaluated"],
            coverage_summary=data["coverage_summary"],
            highest_priority_gaps=high_prio,
            insufficient_evidence_topics=insufficient,
            demonstrated_strengths=strengths,
            all_topic_gaps=all_gaps,
            focus_queue=queue,
            recommendations=data.get("recommendations", []),
            limitations=data.get("limitations", []),
        )
