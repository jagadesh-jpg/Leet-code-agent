"""Learning Insights & Performance Analytics Engine.

Milestone 6.3.10: Learning Insights & Performance Analytics.
Computes historical learning trends, activity timelines, topic comparisons,
difficulty progressions, and safe, sanitised export data (CSV & JSON).

100% offline, local-first, zero-leakage (excludes code, API keys, credentials, file paths).
"""

import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from intelligence.adaptive import AdaptiveLearningEngine
from intelligence.topics import TopicAnalyzer, get_problem_topics
from intelligence.tracker import ProblemProgressStatus, SessionStatus, SessionTracker
from problems import load_problems
import store


@dataclass
class DailyActivityMetric:
    """Learning activity aggregated by calendar day."""
    date: str  # YYYY-MM-DD
    problems_solved: int = 0
    attempts_logged: int = 0
    sessions_completed: int = 0
    sessions_planned: int = 0


@dataclass
class TopicImprovementMetric:
    """Historical topic improvement evaluation based on verifiable local evidence."""
    topic: str
    mastery_status: str
    total_problems: int
    solved_problems: int
    success_rate: float
    total_attempts: int
    failed_attempts: int
    evidence_level: str  # "sufficient", "preliminary", "none"
    improvement_trend: str  # "improving", "steady", "needs_focus", "insufficient_data"
    assessment: str


@dataclass
class LearningInsightsReport:
    """Comprehensive performance insights and analytics synthesis."""
    generated_at: str
    target_language: str
    total_problems_solved: int
    total_attempts_logged: int
    overall_pass_rate: float
    difficulty_breakdown: Dict[str, int]
    daily_activity: List[DailyActivityMetric]
    topic_metrics: List[TopicImprovementMetric]
    strongest_topics: List[str]
    topics_needing_practice: List[str]
    untouched_topics: List[str]
    session_completion_rate: float
    total_sessions_tracked: int
    completed_vs_skipped_problems: Dict[str, int]
    primary_recommendation: Dict[str, Any]
    summary: str


class LearningInsightsEngine:
    """Analyzes historical trends across attempts, solved problems, and learning sessions."""

    def __init__(
        self,
        progress_db_path: Optional[str | Path] = None,
        tracking_db_path: Optional[str | Path] = None,
        language: str = "python",
    ):
        self.progress_db_path = progress_db_path
        self.tracking_db_path = tracking_db_path
        self.language = (language or "python").strip().lower()

        self.topic_analyzer = TopicAnalyzer(
            db_path=self.progress_db_path,
            language=self.language,
        )
        self.tracker = SessionTracker(db_path=self.tracking_db_path)
        self.adaptive_engine = AdaptiveLearningEngine(
            progress_db_path=self.progress_db_path,
            tracking_db_path=self.tracking_db_path,
            language=self.language,
        )

    def generate_report(self) -> LearningInsightsReport:
        """Calculate complete learning insights report from existing local records."""
        all_problems = load_problems()
        now_str = datetime.utcnow().isoformat()

        # 1. Fetch Solved Problems & Difficulty Breakdown
        store.init(db_path=self.progress_db_path)
        solved_by_diff = {"easy": 0, "medium": 0, "hard": 0}
        total_solved = 0

        # Map problems by id for difficulty lookup
        prob_diff_map = {p["id"]: p.get("difficulty", "medium").lower() for p in all_problems}

        try:
            with store.get_connection(self.progress_db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT problem_id, solved_at FROM language_progress WHERE language = ? AND status = 'solved'",
                    (self.language,),
                )
                solved_rows = cur.fetchall()
                if not solved_rows:
                    cur.execute("SELECT problem_id, solved_at FROM progress WHERE status = 'solved'")
                    solved_rows = cur.fetchall()

                for r in solved_rows:
                    pid = r["problem_id"]
                    total_solved += 1
                    d = prob_diff_map.get(pid, "medium")
                    if d in solved_by_diff:
                        solved_by_diff[d] += 1
                    else:
                        solved_by_diff["medium"] += 1
        except Exception:
            solved_rows = []

        # 2. Fetch Attempts & Daily Activity Timestamps
        daily_map: Dict[str, DailyActivityMetric] = {}
        total_attempts = 0
        passed_attempts = 0

        try:
            with store.get_connection(self.progress_db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT status, created_at FROM attempts WHERE created_at IS NOT NULL")
                att_rows = cur.fetchall()
                for a in att_rows:
                    total_attempts += 1
                    if a["status"] == "passed":
                        passed_attempts += 1
                    c_date = a["created_at"][:10] if a["created_at"] else None
                    if c_date and len(c_date) == 10:
                        if c_date not in daily_map:
                            daily_map[c_date] = DailyActivityMetric(date=c_date)
                        daily_map[c_date].attempts_logged += 1
        except Exception:
            pass

        # Also map solved_at to daily activity
        for r in solved_rows:
            s_at = r["solved_at"]
            if s_at and len(s_at) >= 10:
                s_date = s_at[:10]
                if s_date not in daily_map:
                    daily_map[s_date] = DailyActivityMetric(date=s_date)
                daily_map[s_date].problems_solved += 1

        # 3. Session Activity by Day & Session Counts
        sessions = self.tracker.list_sessions(limit=100)
        completed_sessions_count = 0
        total_problems_completed = 0
        total_problems_skipped = 0

        for s in sessions:
            if s.status == SessionStatus.COMPLETED:
                completed_sessions_count += 1
            total_problems_completed += s.completed_count
            total_problems_skipped += s.skipped_count

            s_date = s.created_at[:10] if s.created_at else None
            if s_date and len(s_date) == 10:
                if s_date not in daily_map:
                    daily_map[s_date] = DailyActivityMetric(date=s_date)
                daily_map[s_date].sessions_planned += 1
                if s.status == SessionStatus.COMPLETED:
                    daily_map[s_date].sessions_completed += 1

        daily_activity = sorted(daily_map.values(), key=lambda d: d.date)

        # 4. Topic Improvement Analytics
        topic_metrics = self.topic_analyzer.analyze_topics(all_problems, include_curated=True)
        topic_insights: List[TopicImprovementMetric] = []
        strongest_topics: List[str] = []
        weak_topics: List[str] = []
        untouched_topics: List[str] = []

        for t_name, m in topic_metrics.items():
            if not m.has_history:
                untouched_topics.append(t_name)
                trend = "insufficient_data"
                evidence = "none"
                assessment = "Untouched: no recorded attempts."
            elif m.mastery_status == "needs_practice":
                weak_topics.append(t_name)
                trend = "needs_focus"
                evidence = "sufficient" if m.total_attempts >= 3 else "preliminary"
                assessment = f"Requires practice: {m.failed_attempts} failed attempt(s) recorded."
            elif m.mastery_status in ("mastered", "proficient"):
                strongest_topics.append(t_name)
                trend = "improving" if m.failed_attempts > 0 else "steady"
                evidence = "sufficient" if m.total_attempts >= 2 else "preliminary"
                assessment = f"Proficient: {m.solved_problems}/{m.total_problems} solved with {round(m.success_rate * 100)}% pass rate."
            else:
                trend = "steady"
                evidence = "preliminary"
                assessment = "Practice in progress."

            topic_insights.append(
                TopicImprovementMetric(
                    topic=m.topic,
                    mastery_status=m.mastery_status,
                    total_problems=m.total_problems,
                    solved_problems=m.solved_problems,
                    success_rate=round(m.success_rate, 2),
                    total_attempts=m.total_attempts,
                    failed_attempts=m.failed_attempts,
                    evidence_level=evidence,
                    improvement_trend=trend,
                    assessment=assessment,
                )
            )

        # Sort topic insights: weak topics first, then by solved count descending
        topic_insights.sort(key=lambda x: (0 if x.improvement_trend == "needs_focus" else 1, -x.solved_problems, x.topic))

        # 5. Adaptive Recommendation
        adaptive_rep = self.adaptive_engine.analyze_and_recommend(candidate_problems=all_problems)
        rec_dict = {
            "action_type": adaptive_rep.primary_recommendation.action_type.value,
            "title": adaptive_rep.primary_recommendation.title,
            "target": adaptive_rep.primary_recommendation.target_identifier,
            "confidence": adaptive_rep.primary_recommendation.confidence,
            "rationale": adaptive_rep.primary_recommendation.rationale,
            "evidence": adaptive_rep.primary_recommendation.evidence,
        }

        # 6. Rates and Summary
        overall_pass_rate = (passed_attempts / total_attempts) if total_attempts > 0 else 0.0
        session_completion_rate = (completed_sessions_count / len(sessions)) if sessions else 0.0

        summary_parts = []
        summary_parts.append(f"{total_solved} total unique problem(s) solved across {len(topic_metrics)} tracked topics.")
        if len(sessions) > 0:
            summary_parts.append(f"{completed_sessions_count}/{len(sessions)} session(s) completed ({round(session_completion_rate * 100)}% completion rate).")
        if weak_topics:
            summary_parts.append(f"Attention needed in: {', '.join(weak_topics[:3])}.")
        else:
            summary_parts.append("Balanced progression maintained across standard algorithm domains.")

        return LearningInsightsReport(
            generated_at=now_str,
            target_language=self.language,
            total_problems_solved=total_solved,
            total_attempts_logged=total_attempts,
            overall_pass_rate=round(overall_pass_rate, 2),
            difficulty_breakdown=solved_by_diff,
            daily_activity=daily_activity,
            topic_metrics=topic_insights,
            strongest_topics=strongest_topics,
            topics_needing_practice=weak_topics,
            untouched_topics=untouched_topics,
            session_completion_rate=round(session_completion_rate, 2),
            total_sessions_tracked=len(sessions),
            completed_vs_skipped_problems={
                "completed": total_problems_completed,
                "skipped": total_problems_skipped,
            },
            primary_recommendation=rec_dict,
            summary=" ".join(summary_parts),
        )

    def export_json(self) -> str:
        """Export sanitized learning analytics and session summaries as JSON string."""
        report = self.generate_report()
        # Convert dataclasses to clean dicts
        data = asdict(report)
        return json.dumps(data, indent=2)

    def export_csv(self) -> str:
        """Export sanitized topic-level analytics and session metrics as CSV string."""
        report = self.generate_report()
        out = io.StringIO()
        writer = csv.writer(out)

        # Section 1: Summary Key-Values
        writer.writerow(["# LEETCODE AGENT - LEARNING PERFORMANCE METRICS"])
        writer.writerow(["Generated At", report.generated_at])
        writer.writerow(["Language", report.target_language])
        writer.writerow(["Problems Solved", report.total_problems_solved])
        writer.writerow(["Attempts Logged", report.total_attempts_logged])
        writer.writerow(["Pass Rate", f"{round(report.overall_pass_rate * 100)}%"])
        writer.writerow(["Easy Solved", report.difficulty_breakdown.get("easy", 0)])
        writer.writerow(["Medium Solved", report.difficulty_breakdown.get("medium", 0)])
        writer.writerow(["Hard Solved", report.difficulty_breakdown.get("hard", 0)])
        writer.writerow(["Sessions Completed", f"{round(report.session_completion_rate * 100)}% ({report.total_sessions_tracked} total)"])
        writer.writerow([])

        # Section 2: Topic Analytics Table
        writer.writerow(["# TOPIC PERFORMANCE BREAKDOWN"])
        writer.writerow([
            "Topic",
            "Mastery Status",
            "Solved Problems",
            "Total Problems",
            "Success Rate",
            "Attempts Logged",
            "Failed Attempts",
            "Trend",
            "Evidence Level",
        ])
        for t in report.topic_metrics:
            writer.writerow([
                t.topic,
                t.mastery_status,
                t.solved_problems,
                t.total_problems,
                f"{round(t.success_rate * 100)}%",
                t.total_attempts,
                t.failed_attempts,
                t.improvement_trend,
                t.evidence_level,
            ])
        writer.writerow([])

        # Section 3: Daily Activity History
        writer.writerow(["# DAILY LEARNING TIMELINE"])
        writer.writerow(["Date", "Problems Solved", "Attempts Logged", "Sessions Completed", "Sessions Planned"])
        for d in report.daily_activity:
            writer.writerow([d.date, d.problems_solved, d.attempts_logged, d.sessions_completed, d.sessions_planned])

        return out.getvalue()
