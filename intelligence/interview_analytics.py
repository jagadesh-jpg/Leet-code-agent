"""Interview Performance Trends & Benchmark Analytics Engine.

Milestone 6.3.20: Interview Performance Trends & Benchmark Analytics.
Provides:
1. Multi-category score trend tracking:
   - Overall Assessment Score (0-100), Correctness (0-40), Problem Completion (0-20),
     Code Structure & Readability (0-15), Complexity Awareness (0-15), Time Management (0-10).
   - Historical averages, latest, highest, lowest, and period delta improvements.
2. Performance pattern and weakness detection:
   - Identifies recurring issues (low correctness, low completion, weak complexity awareness,
     time management penalties, score volatility) with explicit evidence and practice actions.
3. Track and language benchmark comparisons:
   - Beginner, Intermediate, Advanced, Mixed tracks with sample size reliability checks.
   - Python, C, C++, Java benchmarks with neutral sample-size caveats.
4. Problem and topic analytics:
   - Maps interview problems to algorithmic topics to track mastery vs practice needs.
   - Integrates with DsaRoadmapEngine and SpacedRevisionEngine for targeted next actions.
5. Configurable interview practice goals:
   - Dedicated persistence in interview_analytics_goals table with deterministic progress tracking.
6. Multi-window date filtering:
   - all_time, last_7_days, last_30_days, last_90_days, custom range.

100% offline, deterministic, zero external API or LLM calls.
Never fabricates metrics, credentials, or statistical claims unsupported by sample sizes.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from intelligence.roadmap import DsaRoadmapEngine
from intelligence.revision import SpacedRevisionEngine
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from problems import load_problems
import store


class GoalType(str, Enum):
    TARGET_AVERAGE_SCORE = "target_average_score"
    TARGET_CORRECTNESS = "target_correctness"
    TARGET_COMPLETION_RATIO = "target_completion_ratio"
    INTERVIEWS_PER_MONTH = "interviews_per_month"
    TARGET_COMPLEXITY = "target_complexity"


class GoalStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"
    ARCHIVED = "archived"


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_utc_now_iso() -> str:
    return _get_utc_now().isoformat()


@dataclass
class ScoreCategoryTrend:
    """Historical scores, extremes, and trend deltas for an evaluation category."""
    category_name: str
    max_possible: float
    average_score: float
    latest_score: Optional[float]
    highest_score: Optional[float]
    lowest_score: Optional[float]
    delta_score: Optional[float]          # Absolute score change between older and newer periods
    delta_pct: Optional[float]            # Percentage change
    sample_count: int
    trend_direction: str                  # "improving", "declining", "stable", "insufficient_data"


@dataclass
class PerformanceInsight:
    """Objective pattern or recurring weakness identified from assessment records."""
    insight_id: str
    metric_name: str
    pattern_type: str                     # "weakness", "strength", "consistency"
    title: str
    description: str
    evidence: str
    sample_count: int
    rule_applied: str
    suggested_action: str


@dataclass
class TrackBenchmarkMetric:
    """Performance breakdown across difficulty tracks."""
    track: str
    assessment_count: int
    average_score: float
    highest_score: float
    average_completion_rate: float
    average_correctness: float
    average_time_management: float
    is_statistically_reliable: bool       # True if assessment_count >= 3
    reliability_note: str


@dataclass
class LanguageBenchmarkMetric:
    """Performance breakdown across programming languages."""
    language: str
    interview_count: int
    average_score: float
    average_correctness: float
    average_completion: float
    average_structure: float
    average_complexity: float
    sample_size_note: str


@dataclass
class TopicInterviewMetric:
    """Topic-level performance based on interview problems encountered."""
    topic: str
    problems_encountered: int
    problems_solved: int
    success_rate_pct: float
    status: str                           # "mastered", "needs_practice", "insufficient_history"


@dataclass
class InterviewAnalyticsGoal:
    """Configurable target goal for interview performance and consistency."""
    goal_id: str
    goal_type: str
    target_value: float
    current_value: float
    period: str
    status: str
    progress_pct: float
    is_achieved: bool
    created_at: str
    updated_at: str
    description: str


@dataclass
class InterviewAnalyticsOverview:
    """Full aggregated performance trends, benchmarks, and actionable insights."""
    total_completed_interviews: int
    average_score: float
    latest_score: Optional[float]
    highest_score: Optional[float]
    lowest_score: Optional[float]
    completion_rate_pct: float
    score_trends: Dict[str, ScoreCategoryTrend]
    track_benchmarks: List[TrackBenchmarkMetric]
    language_benchmarks: List[LanguageBenchmarkMetric]
    insights: List[PerformanceInsight]
    topic_analytics: List[TopicInterviewMetric]
    recommended_roadmap_topics: List[str]
    recommended_revisions: List[str]
    active_goals: List[InterviewAnalyticsGoal]
    date_filter_applied: str


class InterviewAnalyticsManager:
    """Coordinates performance trend calculation, pattern detection, benchmarks, and analytics goals."""

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
        """Create analytics goal tables non-destructively in session_tracking.db."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS interview_analytics_goals (
                    goal_id TEXT PRIMARY KEY,
                    goal_type TEXT NOT NULL,
                    target_value REAL NOT NULL,
                    period TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # -------------------------------------------------------------------------
    # Date Filtering Helpers
    # -------------------------------------------------------------------------

    def _resolve_date_bounds(
        self,
        date_preset: str = "all_time",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Compute ISO date boundaries from preset or custom values."""
        now = _get_utc_now()
        preset = date_preset.strip().lower() if date_preset else "all_time"

        if preset == "last_7_days":
            return (now - timedelta(days=7)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")
        elif preset == "last_30_days":
            return (now - timedelta(days=30)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")
        elif preset == "last_90_days":
            return (now - timedelta(days=90)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")
        elif preset == "custom" and start_date:
            return start_date, (end_date or now.strftime("%Y-%m-%d"))
        return None, None

    # -------------------------------------------------------------------------
    # Data Extraction: Completed Interviews
    # -------------------------------------------------------------------------

    def get_completed_interviews(
        self,
        date_preset: str = "all_time",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch completed/evaluated mock interviews within date range ordered chronologically."""
        start_bound, end_bound = self._resolve_date_bounds(date_preset, start_date, end_date)

        query = (
            "SELECT * FROM mock_interviews "
            "WHERE status IN ('completed', 'expired') AND total_score IS NOT NULL"
        )
        params: List[Any] = []

        if start_bound and end_bound:
            query += " AND created_at >= ? AND created_at <= ?"
            params.extend([f"{start_bound} 00:00:00", f"{end_bound} 23:59:59"])

        query += " ORDER BY created_at ASC"

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            # Table does not exist in bare database
            return []

    # -------------------------------------------------------------------------
    # Score Trend Analytics (Section 3)
    # -------------------------------------------------------------------------

    def calculate_score_trends(
        self,
        interviews: List[Dict[str, Any]],
    ) -> Dict[str, ScoreCategoryTrend]:
        """Calculate historical averages, extremes, and period-over-period deltas across all categories."""
        categories = {
            "overall": ("Overall Assessment Score", 100.0, "total_score"),
            "correctness": ("Correctness", 40.0, "correctness_score"),
            "completion": ("Problem Completion", 20.0, "completion_score"),
            "structure": ("Code Structure & Readability", 15.0, "structure_score"),
            "complexity": ("Complexity Awareness", 15.0, "complexity_score"),
            "time_management": ("Time Management", 10.0, "time_management_score"),
        }

        trends: Dict[str, ScoreCategoryTrend] = {}
        n = len(interviews)

        for cat_key, (name, max_val, col_name) in categories.items():
            scores = [float(row[col_name]) for row in interviews if row.get(col_name) is not None]

            if not scores:
                trends[cat_key] = ScoreCategoryTrend(
                    category_name=name,
                    max_possible=max_val,
                    average_score=0.0,
                    latest_score=None,
                    highest_score=None,
                    lowest_score=None,
                    delta_score=None,
                    delta_pct=None,
                    sample_count=0,
                    trend_direction="insufficient_data",
                )
                continue

            avg_score = round(sum(scores) / len(scores), 1)
            latest = round(scores[-1], 1)
            highest = round(max(scores), 1)
            lowest = round(min(scores), 1)

            delta_score = None
            delta_pct = None
            trend_dir = "insufficient_data"

            if len(scores) >= 2:
                # Compare latest half vs older half
                mid = len(scores) // 2
                older_half = scores[:mid]
                newer_half = scores[mid:]
                older_avg = sum(older_half) / len(older_half)
                newer_avg = sum(newer_half) / len(newer_half)
                diff = round(newer_avg - older_avg, 1)
                delta_score = diff

                if older_avg > 0:
                    delta_pct = round((diff / older_avg) * 100.0, 1)
                else:
                    delta_pct = 100.0 if diff > 0 else 0.0

                threshold = 0.5 if max_val <= 20.0 else 2.0
                if diff >= threshold:
                    trend_dir = "improving"
                elif diff <= -threshold:
                    trend_dir = "declining"
                else:
                    trend_dir = "stable"

            trends[cat_key] = ScoreCategoryTrend(
                category_name=name,
                max_possible=max_val,
                average_score=avg_score,
                latest_score=latest,
                highest_score=highest,
                lowest_score=lowest,
                delta_score=delta_score,
                delta_pct=delta_pct,
                sample_count=len(scores),
                trend_direction=trend_dir,
            )

        return trends

    # -------------------------------------------------------------------------
    # Performance Pattern Analysis (Section 4)
    # -------------------------------------------------------------------------

    def analyze_performance_patterns(
        self,
        interviews: List[Dict[str, Any]],
        trends: Dict[str, ScoreCategoryTrend],
    ) -> List[PerformanceInsight]:
        """Detect recurring weaknesses, improvements, and volatility using transparent rules."""
        insights: List[PerformanceInsight] = []
        n = len(interviews)
        if n == 0:
            return []

        # Rule 1: Low Correctness (< 60% of max, i.e. < 24.0 / 40)
        corr_trend = trends.get("correctness")
        if corr_trend and corr_trend.sample_count >= 2:
            if corr_trend.average_score < 24.0:
                insights.append(
                    PerformanceInsight(
                        insight_id="weakness_correctness",
                        metric_name="Correctness",
                        pattern_type="weakness",
                        title="Sub-optimal Test Pass Rate",
                        description=f"Average correctness is {corr_trend.average_score}/40 across {corr_trend.sample_count} assessments.",
                        evidence=f"Average score of {corr_trend.average_score} is below the 24.0 threshold (60%).",
                        sample_count=corr_trend.sample_count,
                        rule_applied="Average correctness score < 24.0 across 2 or more assessments.",
                        suggested_action="Perform thorough dry-runs with edge case inputs before running code.",
                    )
                )

        # Rule 2: Low Problem Completion (< 60% of max, i.e. < 12.0 / 20)
        comp_trend = trends.get("completion")
        if comp_trend and comp_trend.sample_count >= 2:
            if comp_trend.average_score < 12.0:
                insights.append(
                    PerformanceInsight(
                        insight_id="weakness_completion",
                        metric_name="Problem Completion",
                        pattern_type="weakness",
                        title="Incomplete Problem Solutions",
                        description=f"Average completion score is {comp_trend.average_score}/20 across {comp_trend.sample_count} assessments.",
                        evidence=f"Average completion score {comp_trend.average_score} is below the 12.0 benchmark.",
                        sample_count=comp_trend.sample_count,
                        rule_applied="Average completion score < 12.0 across 2 or more assessments.",
                        suggested_action="Prioritize writing a working brute-force solution to secure base completion before optimizing.",
                    )
                )

        # Rule 3: Weak Complexity Awareness (< 60% of max, i.e. < 9.0 / 15)
        cplx_trend = trends.get("complexity")
        if cplx_trend and cplx_trend.sample_count >= 2:
            if cplx_trend.average_score < 9.0:
                insights.append(
                    PerformanceInsight(
                        insight_id="weakness_complexity",
                        metric_name="Complexity Awareness",
                        pattern_type="weakness",
                        title="Limited Time-Space Tradeoff Awareness",
                        description=f"Average complexity score is {cplx_trend.average_score}/15 across {cplx_trend.sample_count} assessments.",
                        evidence=f"Average complexity score {cplx_trend.average_score} is below 9.0.",
                        sample_count=cplx_trend.sample_count,
                        rule_applied="Average complexity score < 9.0 across 2 or more assessments.",
                        suggested_action="State Big-O time and space complexity explicitly for every drafted function.",
                    )
                )

        # Rule 4: Poor Time Management (< 6.0 / 10 or >= 50% expired)
        tm_trend = trends.get("time_management")
        expired_count = sum(1 for i in interviews if i.get("status") == "expired")
        expired_ratio = expired_count / n if n > 0 else 0.0

        if (tm_trend and tm_trend.sample_count >= 2 and tm_trend.average_score < 6.0) or (n >= 2 and expired_ratio >= 0.5):
            insights.append(
                PerformanceInsight(
                    insight_id="weakness_time_management",
                    metric_name="Time Management",
                    pattern_type="weakness",
                    title="Time Constraint Pacing Pressure",
                    description=f"{expired_count} of {n} ({expired_ratio * 100:.0f}%) assessments exceeded allotted time limits.",
                    evidence=f"Expired ratio of {expired_ratio * 100:.0f}% with average time score {tm_trend.average_score if tm_trend else 0.0}/10.",
                    sample_count=n,
                    rule_applied="Average time management score < 6.0 or >= 50% interviews expired.",
                    suggested_action="Timebox initial problem analysis and pseudo-coding to the first 5 minutes per question.",
                )
            )

        # Rule 5: Improving Readability / Structure
        struct_trend = trends.get("structure")
        if struct_trend and struct_trend.sample_count >= 2 and struct_trend.delta_score and struct_trend.delta_score >= 1.5:
            insights.append(
                PerformanceInsight(
                    insight_id="strength_readability",
                    metric_name="Code Structure",
                    pattern_type="strength",
                    title="Measurable Readability Improvement",
                    description=f"Code structure scores improved by +{struct_trend.delta_score} points over recent sessions.",
                    evidence=f"Latest score {struct_trend.latest_score}/15 exceeds older average by {struct_trend.delta_score} points.",
                    sample_count=struct_trend.sample_count,
                    rule_applied="Structure score improved by >= 1.5 points between evaluation periods.",
                    suggested_action="Continue using clean variable identifiers, modular helpers, and bounded nesting.",
                )
            )

        # Rule 6: Inconsistent Performance (Variance > 25.0 points across >= 3 sessions)
        all_totals = [float(i["total_score"]) for i in interviews if i.get("total_score") is not None]
        if len(all_totals) >= 3:
            score_spread = max(all_totals) - min(all_totals)
            if score_spread >= 25.0:
                insights.append(
                    PerformanceInsight(
                        insight_id="consistency_spread",
                        metric_name="Performance Consistency",
                        pattern_type="consistency",
                        title="High Score Variance Across Sessions",
                        description=f"Assessment scores fluctuate by {score_spread:.1f} points (High: {max(all_totals):.1f}, Low: {min(all_totals):.1f}).",
                        evidence=f"Range between highest ({max(all_totals):.1f}) and lowest ({min(all_totals):.1f}) is {score_spread:.1f} (>= 25.0).",
                        sample_count=len(all_totals),
                        rule_applied="Score variance >= 25.0 between highest and lowest assessment scores.",
                        suggested_action="Standardize your interview checklist: clarify inputs, sketch approach, trace code with test cases.",
                    )
                )

        return insights

    # -------------------------------------------------------------------------
    # Interview Track Analysis (Section 5)
    # -------------------------------------------------------------------------

    def analyze_tracks(
        self,
        interviews: List[Dict[str, Any]],
    ) -> List[TrackBenchmarkMetric]:
        """Aggregate performance broken down by difficulty track."""
        tracks = ["beginner", "intermediate", "advanced", "mixed"]
        results: List[TrackBenchmarkMetric] = []

        for tr in tracks:
            track_items = [i for i in interviews if (i.get("track") or "").lower() == tr]
            cnt = len(track_items)

            if cnt == 0:
                results.append(
                    TrackBenchmarkMetric(
                        track=tr,
                        assessment_count=0,
                        average_score=0.0,
                        highest_score=0.0,
                        average_completion_rate=0.0,
                        average_correctness=0.0,
                        average_time_management=0.0,
                        is_statistically_reliable=False,
                        reliability_note="No completed assessments recorded in this track.",
                    )
                )
                continue

            scores = [float(i["total_score"]) for i in track_items if i.get("total_score") is not None]
            completions = [float(i["completion_score"]) for i in track_items if i.get("completion_score") is not None]
            correctness = [float(i["correctness_score"]) for i in track_items if i.get("correctness_score") is not None]
            times = [float(i["time_management_score"]) for i in track_items if i.get("time_management_score") is not None]

            avg_score = round(sum(scores) / cnt, 1) if scores else 0.0
            high_score = round(max(scores), 1) if scores else 0.0
            avg_comp_rate = round((sum(completions) / (cnt * 20.0)) * 100.0, 1) if completions else 0.0
            avg_corr = round(sum(correctness) / cnt, 1) if correctness else 0.0
            avg_time = round(sum(times) / cnt, 1) if times else 0.0

            is_reliable = (cnt >= 3)
            rel_note = (
                f"Statistically supported sample size ({cnt} assessments)."
                if is_reliable
                else f"Insufficient sample size ({cnt} assessment{'s' if cnt != 1 else ''}). Need >= 3 for reliability."
            )

            results.append(
                TrackBenchmarkMetric(
                    track=tr,
                    assessment_count=cnt,
                    average_score=avg_score,
                    highest_score=high_score,
                    average_completion_rate=avg_comp_rate,
                    average_correctness=avg_corr,
                    average_time_management=avg_time,
                    is_statistically_reliable=is_reliable,
                    reliability_note=rel_note,
                )
            )

        return results

    # -------------------------------------------------------------------------
    # Programming Language Analytics (Section 6)
    # -------------------------------------------------------------------------

    def analyze_languages(
        self,
        interviews: List[Dict[str, Any]],
    ) -> List[LanguageBenchmarkMetric]:
        """Aggregate performance broken down by programming language."""
        languages = ["python", "cpp", "c", "java"]
        results: List[LanguageBenchmarkMetric] = []

        for lang in languages:
            lang_items = [i for i in interviews if (i.get("language") or "").lower() == lang]
            cnt = len(lang_items)

            if cnt == 0:
                results.append(
                    LanguageBenchmarkMetric(
                        language=lang,
                        interview_count=0,
                        average_score=0.0,
                        average_correctness=0.0,
                        average_completion=0.0,
                        average_structure=0.0,
                        average_complexity=0.0,
                        sample_size_note="No completed assessments in this language.",
                    )
                )
                continue

            scores = [float(i["total_score"]) for i in lang_items if i.get("total_score") is not None]
            corr = [float(i["correctness_score"]) for i in lang_items if i.get("correctness_score") is not None]
            comp = [float(i["completion_score"]) for i in lang_items if i.get("completion_score") is not None]
            struct = [float(i["structure_score"]) for i in lang_items if i.get("structure_score") is not None]
            cplx = [float(i["complexity_score"]) for i in lang_items if i.get("complexity_score") is not None]

            avg_score = round(sum(scores) / cnt, 1) if scores else 0.0
            avg_corr = round(sum(corr) / cnt, 1) if corr else 0.0
            avg_comp = round(sum(comp) / cnt, 1) if comp else 0.0
            avg_struct = round(sum(struct) / cnt, 1) if struct else 0.0
            avg_cplx = round(sum(cplx) / cnt, 1) if cplx else 0.0

            note = (
                f"Sample of {cnt} interview{'s' if cnt != 1 else ''}. "
                "Differences may reflect problem difficulty and small sample size."
            )

            results.append(
                LanguageBenchmarkMetric(
                    language=lang,
                    interview_count=cnt,
                    average_score=avg_score,
                    average_correctness=avg_corr,
                    average_completion=avg_comp,
                    average_structure=avg_struct,
                    average_complexity=avg_cplx,
                    sample_size_note=note,
                )
            )

        return results

    # -------------------------------------------------------------------------
    # Problem and Topic Analytics (Section 7)
    # -------------------------------------------------------------------------

    def analyze_topics(
        self,
        interviews: List[Dict[str, Any]],
    ) -> Tuple[List[TopicInterviewMetric], List[str], List[str]]:
        """Map interview problems to algorithmic topics to identify strengths and weaknesses."""
        if not interviews:
            return [], [], []

        interview_ids = [i["interview_id"] for i in interviews]
        all_problems = load_problems()
        prob_map = {p["id"]: p for p in all_problems if p.get("id")}

        # Merge custom problems from progress_db if available
        if self.progress_db_path:
            try:
                custom_probs = store.list_custom_problems(db_path=self.progress_db_path)
                for cp in custom_probs:
                    if cp.get("id") and cp["id"] not in prob_map:
                        prob_map[cp["id"]] = cp
            except Exception:
                pass

        # Query assigned problems for these interviews
        prob_records: List[Dict[str, Any]] = []
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ",".join("?" for _ in interview_ids)
                cursor.execute(
                    f"SELECT interview_id, problem_id, status FROM mock_interview_problems WHERE interview_id IN ({placeholders})",
                    interview_ids,
                )
                prob_records = [dict(r) for r in cursor.fetchall()]
        except sqlite3.OperationalError:
            pass

        topic_stats: Dict[str, Dict[str, int]] = {}

        for rec in prob_records:
            pid = rec["problem_id"]
            p_meta = prob_map.get(pid, {})
            topics = p_meta.get("topics") or ["Core DSA"]
            is_solved = (rec["status"] == "passed")

            for t in topics:
                if t not in topic_stats:
                    topic_stats[t] = {"encountered": 0, "solved": 0}
                topic_stats[t]["encountered"] += 1
                if is_solved:
                    topic_stats[t]["solved"] += 1

        topic_metrics: List[TopicInterviewMetric] = []
        for t, stat in topic_stats.items():
            enc = stat["encountered"]
            sol = stat["solved"]
            rate = round((sol / max(1, enc)) * 100.0, 1)

            if enc >= 2 and rate >= 70.0:
                status = "mastered"
            elif enc >= 1 and rate < 70.0:
                status = "needs_practice"
            else:
                status = "insufficient_history"

            topic_metrics.append(
                TopicInterviewMetric(
                    topic=t,
                    problems_encountered=enc,
                    problems_solved=sol,
                    success_rate_pct=rate,
                    status=status,
                )
            )

        topic_metrics.sort(key=lambda x: (x.success_rate_pct, -x.problems_encountered))

        # Generate roadmap and revision recommendations
        rec_topics: List[str] = []
        try:
            rm_engine = DsaRoadmapEngine(
                progress_db_path=self.progress_db_path,
                tracking_db_path=self.tracking_db_path,
            )
            recs = rm_engine.generate_recommendations(limit=3)
            rec_topics = [f"{r.topic_name} ({r.stage_name})" for r in recs]
        except Exception:
            rec_topics = ["Arrays & Hashing", "Two Pointers", "Binary Search"]

        rec_revisions: List[str] = []
        try:
            rev_engine = SpacedRevisionEngine(
                tracking_db_path=self.tracking_db_path,
                progress_db_path=self.progress_db_path,
            )
            rev_queue = rev_engine.get_revision_queue()
            rec_revisions = [r.problem_id for r in rev_queue[:3]]
        except Exception:
            rec_revisions = []

        return topic_metrics, rec_topics, rec_revisions

    # -------------------------------------------------------------------------
    # Interview Goals Management (Section 8 & 11)
    # -------------------------------------------------------------------------

    def create_goal(
        self,
        goal_type: str,
        target_value: float,
        period: str = "all_time",
    ) -> InterviewAnalyticsGoal:
        """Create a new configurable interview performance target."""
        valid_types = [t.value for t in GoalType]
        if goal_type not in valid_types:
            raise ValueError(f"Invalid goal_type '{goal_type}'. Must be one of {valid_types}.")

        if target_value <= 0:
            raise ValueError("target_value must be greater than zero.")

        goal_id = f"igoal_{uuid.uuid4().hex[:10]}"
        now_str = _get_utc_now_iso()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO interview_analytics_goals (
                    goal_id, goal_type, target_value, period, created_at, updated_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (goal_id, goal_type, float(target_value), period, now_str, now_str, GoalStatus.ACTIVE.value),
            )
            conn.commit()

        return self.get_goal(goal_id)

    def get_goal(self, goal_id: str) -> Optional[InterviewAnalyticsGoal]:
        """Fetch a specific interview goal and evaluate current progress."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM interview_analytics_goals WHERE goal_id = ?", (goal_id,))
            row = cursor.fetchone()
            if not row:
                return None

        # Calculate live progress
        completed_interviews = self.get_completed_interviews(date_preset="all_time")
        trends = self.calculate_score_trends(completed_interviews)

        g_type = row["goal_type"]
        target = float(row["target_value"])
        status = row["status"]

        current_val = 0.0
        desc = ""

        if g_type == GoalType.TARGET_AVERAGE_SCORE.value:
            current_val = trends["overall"].average_score
            desc = f"Achieve average assessment score of {target}/100"
        elif g_type == GoalType.TARGET_CORRECTNESS.value:
            current_val = trends["correctness"].average_score
            desc = f"Achieve average correctness score of {target}/40"
        elif g_type == GoalType.TARGET_COMPLETION_RATIO.value:
            solved_all = sum(float(i.get("completion_score", 0)) for i in completed_interviews)
            tot_max = len(completed_interviews) * 20.0
            current_val = round((solved_all / max(1.0, tot_max)) * 100.0, 1) if tot_max > 0 else 0.0
            desc = f"Achieve problem completion rate of {target}%"
        elif g_type == GoalType.INTERVIEWS_PER_MONTH.value:
            thirty_days_ago = (_get_utc_now() - timedelta(days=30)).isoformat()
            current_val = float(sum(1 for i in completed_interviews if i["created_at"] >= thirty_days_ago))
            desc = f"Complete {int(target)} mock interviews per month"
        elif g_type == GoalType.TARGET_COMPLEXITY.value:
            current_val = trends["complexity"].average_score
            desc = f"Achieve average complexity score of {target}/15"

        progress_pct = min(100.0, round((current_val / max(0.01, target)) * 100.0, 1))
        is_achieved = (progress_pct >= 100.0)

        # Auto-update status if achieved and active
        if is_achieved and status == GoalStatus.ACTIVE.value:
            status = GoalStatus.COMPLETED.value
            with self.get_connection() as conn:
                conn.execute(
                    "UPDATE interview_analytics_goals SET status = ?, updated_at = ? WHERE goal_id = ?",
                    (status, _get_utc_now_iso(), goal_id),
                )
                conn.commit()

        return InterviewAnalyticsGoal(
            goal_id=row["goal_id"],
            goal_type=g_type,
            target_value=target,
            current_value=round(current_val, 1),
            period=row["period"],
            status=status,
            progress_pct=progress_pct,
            is_achieved=is_achieved,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            description=desc,
        )

    def update_goal(
        self,
        goal_id: str,
        target_value: Optional[float] = None,
        status: Optional[str] = None,
        period: Optional[str] = None,
    ) -> InterviewAnalyticsGoal:
        """Update existing goal parameters safely."""
        existing = self.get_goal(goal_id)
        if not existing:
            raise ValueError(f"Goal '{goal_id}' not found.")

        new_target = float(target_value) if target_value is not None else existing.target_value
        if new_target <= 0:
            raise ValueError("target_value must be greater than zero.")

        new_status = existing.status
        if status is not None:
            valid_statuses = [s.value for s in GoalStatus]
            if status not in valid_statuses:
                raise ValueError(f"Invalid status '{status}'. Must be one of {valid_statuses}.")
            new_status = status

        new_period = period if period is not None else existing.period
        now_str = _get_utc_now_iso()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE interview_analytics_goals
                SET target_value = ?, status = ?, period = ?, updated_at = ?
                WHERE goal_id = ?
                """,
                (new_target, new_status, new_period, now_str, goal_id),
            )
            conn.commit()

        return self.get_goal(goal_id)

    def list_goals(self, status_filter: Optional[str] = None) -> List[InterviewAnalyticsGoal]:
        """List all goals with current evaluated progress."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if status_filter:
                cursor.execute(
                    "SELECT goal_id FROM interview_analytics_goals WHERE status = ? ORDER BY created_at DESC",
                    (status_filter,),
                )
            else:
                cursor.execute("SELECT goal_id FROM interview_analytics_goals ORDER BY created_at DESC")
            rows = cursor.fetchall()

        goals = []
        for r in rows:
            g = self.get_goal(r["goal_id"])
            if g:
                goals.append(g)
        return goals

    # -------------------------------------------------------------------------
    # Comprehensive Overview Synthesis (Section 2 & 9)
    # -------------------------------------------------------------------------

    def get_analytics_overview(
        self,
        date_preset: str = "all_time",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> InterviewAnalyticsOverview:
        """Synthesize comprehensive, honest performance trends, benchmarks, and goals."""
        interviews = self.get_completed_interviews(
            date_preset=date_preset,
            start_date=start_date,
            end_date=end_date,
        )

        n = len(interviews)
        scores = [float(i["total_score"]) for i in interviews if i.get("total_score") is not None]
        avg_score = round(sum(scores) / n, 1) if n > 0 else 0.0
        latest_score = round(scores[-1], 1) if scores else None
        highest_score = round(max(scores), 1) if scores else None
        lowest_score = round(min(scores), 1) if scores else None

        # Completion rate across all assigned problems
        comp_scores = [float(i.get("completion_score", 0)) for i in interviews]
        completion_rate = round((sum(comp_scores) / max(1.0, n * 20.0)) * 100.0, 1) if n > 0 else 0.0

        # Trends
        trends = self.calculate_score_trends(interviews)

        # Insights
        insights = self.analyze_performance_patterns(interviews, trends)

        # Track benchmarks
        track_benchmarks = self.analyze_tracks(interviews)

        # Language benchmarks
        language_benchmarks = self.analyze_languages(interviews)

        # Topic analytics
        topic_metrics, rec_topics, rec_revisions = self.analyze_topics(interviews)

        # Goals
        active_goals = self.list_goals(status_filter=GoalStatus.ACTIVE.value)

        return InterviewAnalyticsOverview(
            total_completed_interviews=n,
            average_score=avg_score,
            latest_score=latest_score,
            highest_score=highest_score,
            lowest_score=lowest_score,
            completion_rate_pct=completion_rate,
            score_trends=trends,
            track_benchmarks=track_benchmarks,
            language_benchmarks=language_benchmarks,
            insights=insights,
            topic_analytics=topic_metrics,
            recommended_roadmap_topics=rec_topics,
            recommended_revisions=rec_revisions,
            active_goals=active_goals,
            date_filter_applied=date_preset,
        )
