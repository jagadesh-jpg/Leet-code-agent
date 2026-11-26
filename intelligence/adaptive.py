"""Adaptive Learning & Progress Intelligence.

Milestone 6.3.7: Adaptive Learning & Progress Intelligence.
Synthesizes local problem history, topic analytics, and tracked learning-session
outcomes to recommend next learning actions and adaptive session sizing.

100% offline, explainable, rule-based, and read-only.
Never overrides user intent silently and never infers ability without sufficient evidence.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from intelligence.planner import SessionPlanner
from intelligence.selector import ProblemSelector
from intelligence.topics import TopicAnalyzer, TopicPerformanceMetric, get_problem_topics
from intelligence.tracker import SessionStatus, SessionTracker, TrackingAnalytics
import store


class RecommendedActionType(str, Enum):
    """Categorized pedagogical next action."""
    PRACTICE_WEAK_TOPIC = "practice_weak_topic"
    RETRY_UNFINISHED_PROBLEM = "retry_unfinished_problem"
    EXPAND_TOPIC_COVERAGE = "expand_topic_coverage"
    PROGRESS_DIFFICULTY = "progress_difficulty"
    REDUCE_SESSION_SIZE = "reduce_session_size"
    MAINTAIN_PRACTICE = "maintain_practice"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class NextActionRecommendation:
    """A concrete, explainable recommendation for the user's next learning step."""
    action_type: RecommendedActionType
    title: str
    target_identifier: Optional[str]  # topic name, problem_id, or difficulty level
    rationale: str
    evidence: List[str] = field(default_factory=list)
    confidence: str = "moderate"  # "high", "moderate", "low" (labeled clearly)


@dataclass
class AdaptiveSessionSizing:
    """Recommended session size based on tracked completion history."""
    recommended_size: int
    default_size: int
    rationale: str
    evidence_count: int
    has_sufficient_evidence: bool


@dataclass
class AdaptiveLearningReport:
    """Comprehensive offline synthesis of learner progress and next steps."""
    target_language: str
    overall_status: str
    topics_needing_practice: List[str]
    proficient_topics: List[str]
    untouched_topics: List[str]
    recent_session_completion_rate: float
    total_sessions_tracked: int
    primary_recommendation: NextActionRecommendation
    secondary_recommendations: List[NextActionRecommendation] = field(default_factory=list)
    session_sizing: Optional[AdaptiveSessionSizing] = None


class AdaptiveLearningEngine:
    """Rule-based, deterministic engine synthesizing multi-source practice evidence."""

    MIN_SESSION_SIZE = 1
    MAX_SESSION_SIZE = 6
    DEFAULT_SESSION_SIZE = 3

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

    def analyze_and_recommend(
        self,
        candidate_problems: Optional[List[Dict[str, Any]]] = None,
        user_specified_size: Optional[int] = None,
    ) -> AdaptiveLearningReport:
        """Synthesize evidence and generate deterministic next-action recommendations."""
        # 1. Topic-level analytics
        topic_metrics = self.topic_analyzer.analyze_topics(
            candidate_problems,
            include_curated=True,
        )

        weak_topics = [t for t, m in topic_metrics.items() if m.mastery_status == "needs_practice"]
        proficient_topics = [t for t, m in topic_metrics.items() if m.mastery_status in ("proficient", "mastered")]
        untouched_topics = [t for t, m in topic_metrics.items() if m.mastery_status == "no_history"]

        # 2. Tracking analytics & recent sessions
        tracking_analytics = self.tracker.get_analytics()
        recent_sessions = self.tracker.list_sessions(limit=5)

        # 3. Analyze problem-level history (unsolved failed problems)
        unfinished_problems: List[Dict[str, Any]] = []
        if candidate_problems:
            for p in candidate_problems:
                pid = p["id"]
                is_solved = store.is_solved(pid, language=self.language, db_path=self.progress_db_path)
                if not is_solved:
                    # check for attempts
                    try:
                        with store.get_connection(self.progress_db_path) as conn:
                            cur = conn.cursor()
                            cur.execute(
                                "SELECT COUNT(*) as cnt FROM attempts WHERE problem_id = ? AND status != 'passed'",
                                (pid,),
                            )
                            row = cur.fetchone()
                            if row and row["cnt"] > 0:
                                unfinished_problems.append({
                                    "id": pid,
                                    "title": p.get("title", pid),
                                    "difficulty": p.get("difficulty", "medium"),
                                    "failures": row["cnt"],
                                })
                    except Exception:
                        pass

        # 4. Compute Adaptive Session Sizing
        sizing = self._compute_session_sizing(recent_sessions, user_specified_size)

        # 5. Formulate primary and secondary recommendations
        primary_rec, secondary_recs = self._formulate_recommendations(
            weak_topics=weak_topics,
            proficient_topics=proficient_topics,
            untouched_topics=untouched_topics,
            unfinished_problems=unfinished_problems,
            recent_sessions=recent_sessions,
            tracking_analytics=tracking_analytics,
            sizing=sizing,
        )

        # 6. Overall status synthesis
        overall_status = self._synthesize_overall_status(
            topic_metrics=topic_metrics,
            weak_topics=weak_topics,
            proficient_topics=proficient_topics,
            tracking_analytics=tracking_analytics,
        )

        return AdaptiveLearningReport(
            target_language=self.language,
            overall_status=overall_status,
            topics_needing_practice=weak_topics,
            proficient_topics=proficient_topics,
            untouched_topics=untouched_topics,
            recent_session_completion_rate=tracking_analytics.session_completion_rate,
            total_sessions_tracked=tracking_analytics.total_sessions_planned,
            primary_recommendation=primary_rec,
            secondary_recommendations=secondary_recs,
            session_sizing=sizing,
        )

    def _compute_session_sizing(
        self,
        recent_sessions: List[Any],
        user_specified_size: Optional[int],
    ) -> AdaptiveSessionSizing:
        """Calculate rule-based adaptive session size recommendation."""
        default_size = user_specified_size if user_specified_size is not None else self.DEFAULT_SESSION_SIZE

        # Insufficient evidence: need at least 3 recent tracked sessions
        if len(recent_sessions) < 3:
            return AdaptiveSessionSizing(
                recommended_size=default_size,
                default_size=default_size,
                rationale="Insufficient session history (minimum 3 tracked sessions required). Maintaining standard size.",
                evidence_count=len(recent_sessions),
                has_sufficient_evidence=False,
            )

        # Evaluate last 3-5 sessions
        sample = recent_sessions[:5]
        completed_count = sum(1 for s in sample if s.status == SessionStatus.COMPLETED)
        cancelled_or_incomplete = sum(
            1 for s in sample if s.status in (SessionStatus.CANCELLED, SessionStatus.IN_PROGRESS) or s.skipped_count > 0
        )

        # Rule 1: High incompletion rate (>= 60% incomplete or cancelled) -> Recommend decreasing size cautiously by 1
        if cancelled_or_incomplete >= 3:
            adjusted = max(self.MIN_SESSION_SIZE, default_size - 1)
            return AdaptiveSessionSizing(
                recommended_size=adjusted,
                default_size=default_size,
                rationale=f"Recent sessions show fatigue or frequent incompletions ({cancelled_or_incomplete}/{len(sample)} incomplete/cancelled). Cautiously reducing session size from {default_size} to {adjusted} to improve consistency.",
                evidence_count=len(sample),
                has_sufficient_evidence=True,
            )

        # Rule 2: Sustained 100% completion rate over at least 3 sessions with high problem pass rate -> Recommend increasing size cautiously by 1
        if completed_count == len(sample) and len(sample) >= 3:
            adjusted = min(self.MAX_SESSION_SIZE, default_size + 1)
            return AdaptiveSessionSizing(
                recommended_size=adjusted,
                default_size=default_size,
                rationale=f"Sustained 100% completion rate across {len(sample)} consecutive sessions. Cautiously expanding session size from {default_size} to {adjusted} for greater challenge capacity.",
                evidence_count=len(sample),
                has_sufficient_evidence=True,
            )

        return AdaptiveSessionSizing(
            recommended_size=default_size,
            default_size=default_size,
            rationale=f"Balanced session completion pace ({completed_count}/{len(sample)} completed). Maintaining current session size {default_size}.",
            evidence_count=len(sample),
            has_sufficient_evidence=True,
        )

    def _formulate_recommendations(
        self,
        weak_topics: List[str],
        proficient_topics: List[str],
        untouched_topics: List[str],
        unfinished_problems: List[Dict[str, Any]],
        recent_sessions: List[Any],
        tracking_analytics: TrackingAnalytics,
        sizing: AdaptiveSessionSizing,
    ) -> tuple[NextActionRecommendation, List[NextActionRecommendation]]:
        """Formulate prioritized, deterministic pedagogical actions."""
        recs: List[NextActionRecommendation] = []

        # Priority 1: Unfinished problems with failure history (active failure recovery)
        if unfinished_problems:
            top_prob = sorted(unfinished_problems, key=lambda x: -x["failures"])[0]
            recs.append(
                NextActionRecommendation(
                    action_type=RecommendedActionType.RETRY_UNFINISHED_PROBLEM,
                    title=f"Retry unfinished problem: {top_prob['title']}",
                    target_identifier=top_prob["id"],
                    rationale=f"Problem '{top_prob['id']}' has {top_prob['failures']} prior recorded failure(s). Retrying it solidifies debugging insights.",
                    evidence=[f"{top_prob['failures']} prior failed attempt(s) on problem {top_prob['id']}"],
                    confidence="high",
                )
            )

        # Priority 2: Weak topics identified via performance metrics
        if weak_topics:
            primary_weak = weak_topics[0]
            recs.append(
                NextActionRecommendation(
                    action_type=RecommendedActionType.PRACTICE_WEAK_TOPIC,
                    title=f"Reinforce weak topic: {primary_weak}",
                    target_identifier=primary_weak,
                    rationale=f"Topic '{primary_weak}' has recorded attempts with an unsatisfactory pass rate. Focused drills will improve mastery.",
                    evidence=[f"Topic '{primary_weak}' flagged with status 'needs_practice'"],
                    confidence="high",
                )
            )

        # Priority 3: Session sizing adjustment if session fatigue is evident
        if sizing.has_sufficient_evidence and sizing.recommended_size < sizing.default_size:
            recs.append(
                NextActionRecommendation(
                    action_type=RecommendedActionType.REDUCE_SESSION_SIZE,
                    title=f"Adopt lighter session size ({sizing.recommended_size} problems)",
                    target_identifier=str(sizing.recommended_size),
                    rationale=sizing.rationale,
                    evidence=[f"Recent incomplete/skipped sessions in tracking database ({sizing.evidence_count} sessions evaluated)"],
                    confidence="moderate",
                )
            )

        # Priority 4: Progress difficulty or expand coverage
        if proficient_topics and not weak_topics:
            if untouched_topics:
                first_untouched = untouched_topics[0]
                recs.append(
                    NextActionRecommendation(
                        action_type=RecommendedActionType.EXPAND_TOPIC_COVERAGE,
                        title=f"Expand topic coverage into: {first_untouched}",
                        target_identifier=first_untouched,
                        rationale=f"Core covered topics ({', '.join(proficient_topics[:3])}) are proficient. Expanding into '{first_untouched}' broadens pattern recognition.",
                        evidence=[f"Topic '{first_untouched}' currently has 0 practice attempts"],
                        confidence="moderate",
                    )
                )
            else:
                recs.append(
                    NextActionRecommendation(
                        action_type=RecommendedActionType.PROGRESS_DIFFICULTY,
                        title="Step up difficulty progression",
                        target_identifier="medium/hard",
                        rationale="All covered topics are proficient. Increase proportion of Medium and Hard problems in upcoming sessions.",
                        evidence=[f"{len(proficient_topics)} topic(s) categorized as proficient/mastered"],
                        confidence="moderate",
                    )
                )

        # Priority 5: Fallback if minimal or no history exists
        if not recs:
            if not weak_topics and not proficient_topics:
                recs.append(
                    NextActionRecommendation(
                        action_type=RecommendedActionType.INSUFFICIENT_DATA,
                        title="Begin baseline practice session",
                        target_identifier="warm_up",
                        rationale="Insufficient attempt and tracking history recorded. Complete an initial practice session to establish a performance baseline.",
                        evidence=["No recorded problem attempts or tracked sessions in isolated database"],
                        confidence="low",
                    )
                )
            else:
                recs.append(
                    NextActionRecommendation(
                        action_type=RecommendedActionType.MAINTAIN_PRACTICE,
                        title="Maintain balanced practice",
                        target_identifier="general",
                        rationale="Practice pace is balanced across known topics. Continue standard sessions.",
                        evidence=[f"{len(proficient_topics)} proficient topic(s)"],
                        confidence="moderate",
                    )
                )

        primary = recs[0]
        secondary = recs[1:]
        return primary, secondary

    def _synthesize_overall_status(
        self,
        topic_metrics: Dict[str, TopicPerformanceMetric],
        weak_topics: List[str],
        proficient_topics: List[str],
        tracking_analytics: TrackingAnalytics,
    ) -> str:
        """Generate concise natural language status summary."""
        total_topics = len(topic_metrics)
        if total_topics == 0 or (len(weak_topics) == 0 and len(proficient_topics) == 0):
            return "Baseline Assessment: Insufficient local history to establish topic trends."

        parts = []
        if weak_topics:
            parts.append(f"Requires attention in {len(weak_topics)} topic(s) ({', '.join(weak_topics[:2])}).")
        if proficient_topics:
            parts.append(f"Demonstrating proficiency in {len(proficient_topics)} topic(s).")
        if tracking_analytics.total_sessions_planned > 0:
            rate_pct = tracking_analytics.session_completion_rate * 100
            parts.append(f"Session completion rate: {rate_pct:.0f}% ({tracking_analytics.total_sessions_completed}/{tracking_analytics.total_sessions_planned}).")

        return " ".join(parts) if parts else "Steady progress across standard algorithm topics."
