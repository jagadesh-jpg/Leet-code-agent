"""Personalized Learning Session Planner.

Milestone 6.3.5: Personalized Learning Session Planner.
Creates structured, balanced practice sessions (warm-up, main practice, challenge)
derived from the deterministic ProblemSelector and TopicAnalyzer.

100% offline, explainable, and preview-only (does not run or submit problems).
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from intelligence.selector import ProblemScoreBreakdown, ProblemSelector
from intelligence.topics import TopicAnalyzer, TopicPerformanceMetric, get_problem_topics
import store


class SessionProblemRole(str, Enum):
    """Categorized pedagogical role for a problem within a structured practice session."""
    WARM_UP = "warm_up"
    MAIN_PRACTICE = "main_practice"
    CHALLENGE = "challenge"


@dataclass
class PlannedProblem:
    """A problem planned for inclusion in a learning session with pedagogical context."""
    rank: int
    problem: Dict[str, Any]
    score_breakdown: ProblemScoreBreakdown
    role: SessionProblemRole
    reason: str

    @property
    def problem_id(self) -> str:
        return self.problem.get("id", "")

    @property
    def title(self) -> str:
        return self.problem.get("title", self.problem_id)

    @property
    def difficulty(self) -> str:
        return self.problem.get("difficulty", "medium").lower()

    @property
    def topics(self) -> List[str]:
        return self.score_breakdown.all_topics or get_problem_topics(self.problem)

    @property
    def priority_score(self) -> float:
        return self.score_breakdown.total_score


@dataclass
class LearningSessionPlan:
    """Structured offline learning session plan."""
    target_language: str
    target_size: int
    planned_problems: List[PlannedProblem]
    weak_topics: List[str]
    covered_topics: List[str]
    session_summary: str
    difficulty_distribution: Dict[str, int] = field(default_factory=dict)

    @property
    def total_problems(self) -> int:
        return len(self.planned_problems)


class SessionPlanner:
    """Generates structured, balanced learning sessions without network or AI calls."""

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        language: str = "python",
        preferred_difficulty: Optional[str] = None,
        enable_topic_intelligence: bool = True,
    ):
        self.db_path = db_path
        self.language = language
        self.preferred_difficulty = preferred_difficulty.strip().lower() if preferred_difficulty else None
        self.enable_topic_intelligence = enable_topic_intelligence

        self.selector = ProblemSelector(
            db_path=self.db_path,
            language=self.language,
            preferred_difficulty=self.preferred_difficulty,
            enable_topic_intelligence=self.enable_topic_intelligence,
        )
        self.topic_analyzer = TopicAnalyzer(
            db_path=self.db_path,
            language=self.language,
        )

    def plan_session(
        self,
        candidates: List[Dict[str, Any]],
        session_size: int = 3,
        skip_solved: bool = True,
    ) -> LearningSessionPlan:
        """Create a balanced, structured learning session from candidate problems.

        Session Structure:
        - If session_size == 1:
          1 problem: Main Practice (highest priority overall).
        - If session_size == 2:
          1 Warm-up (easier or high-scoring confidence builder), 1 Main Practice.
        - If session_size >= 3:
          1 Warm-up (typically Easy or lower-tier Medium),
          N-2 Main Practice (prioritizing weak topics and topic diversity),
          1 Challenge (higher difficulty or complex topic, if justified by queue).
        """
        session_size = max(1, session_size)
        if not candidates:
            return LearningSessionPlan(
                target_language=self.language,
                target_size=session_size,
                planned_problems=[],
                weak_topics=[],
                covered_topics=[],
                session_summary="No candidate problems available to plan a session.",
                difficulty_distribution={},
            )

        # 1. Rank all candidates using the deterministic ProblemSelector
        ranked_candidates = self.selector.prioritize_candidates(
            candidates,
            skip_solved=skip_solved,
        )

        if not ranked_candidates:
            return LearningSessionPlan(
                target_language=self.language,
                target_size=session_size,
                planned_problems=[],
                weak_topics=[],
                covered_topics=[],
                session_summary="No eligible problems remaining after filtering (all candidates may be solved).",
                difficulty_distribution={},
            )

        # 2. Extract topic metrics and identify weak topics
        topic_metrics = self.topic_analyzer.analyze_topics(candidates, include_curated=True)
        weak_topics = [t for t, m in topic_metrics.items() if m.mastery_status == "needs_practice"]

        # If candidates are fewer than session_size, adjust target
        actual_pool = list(ranked_candidates)

        selected_problems: List[PlannedProblem] = []
        used_pids: Set[str] = set()
        covered_topics_set: Set[str] = set()

        # Helper to assign
        def add_plan_item(prob: Dict[str, Any], breakdown: ProblemScoreBreakdown, role: SessionProblemRole, reason: str):
            pid = prob["id"]
            used_pids.add(pid)
            for t in breakdown.all_topics:
                covered_topics_set.add(t)
            selected_problems.append(
                PlannedProblem(
                    rank=len(selected_problems) + 1,
                    problem=prob,
                    score_breakdown=breakdown,
                    role=role,
                    reason=reason,
                )
            )

        # Single problem case
        if session_size == 1 or len(actual_pool) == 1:
            best_prob, best_bd = actual_pool[0]
            reason = "Top priority candidate for focused single-problem session."
            if any(t in weak_topics for t in best_bd.all_topics):
                reason += f" Reinforces weak topic ({', '.join(t for t in best_bd.all_topics if t in weak_topics)})."
            add_plan_item(best_prob, best_bd, SessionProblemRole.MAIN_PRACTICE, reason)
            return self._build_plan_result(session_size, selected_problems, weak_topics, covered_topics_set)

        # Multi-problem session: Warm-up selection
        # Criteria for warm-up:
        # Prefer Easy problem with highest score; fallback to lowest difficulty among candidates
        warm_up_candidate = None
        for prob, bd in actual_pool:
            if bd.difficulty == "easy":
                warm_up_candidate = (prob, bd)
                break
        if not warm_up_candidate:
            # Pick the lowest difficulty available (e.g. Medium before Hard)
            sorted_by_diff = sorted(
                actual_pool,
                key=lambda x: ({"easy": 1, "medium": 2, "hard": 3}.get(x[1].difficulty, 2), -x[1].total_score),
            )
            warm_up_candidate = sorted_by_diff[0]

        warm_up_prob, warm_up_bd = warm_up_candidate
        warm_reasons = [f"Confidence-building warm-up problem ({warm_up_bd.difficulty.title()})"]
        matching_warm_weak = [t for t in warm_up_bd.all_topics if t in weak_topics]
        if matching_warm_weak:
            warm_reasons.append(f"reinforces weak topic ({', '.join(matching_warm_weak)})")
        if warm_up_bd.unsolved_attempt_penalty_or_bonus > 15.0:
            warm_reasons.append("retries previously unfinished candidate")

        add_plan_item(
            warm_up_prob,
            warm_up_bd,
            SessionProblemRole.WARM_UP,
            "; ".join(warm_reasons) + ".",
        )

        # Challenge problem selection (if session_size >= 3 and suitable candidate exists)
        has_challenge_slot = (session_size >= 3 and len(actual_pool) > len(selected_problems) + 1)
        challenge_candidate = None

        if has_challenge_slot:
            # Look for a harder candidate (Hard or higher Medium) not already used
            remaining = [c for c in actual_pool if c[0]["id"] not in used_pids]
            # Try Hard first
            hard_candidates = [c for c in remaining if c[1].difficulty == "hard"]
            if hard_candidates:
                challenge_candidate = hard_candidates[0]
            elif self.preferred_difficulty == "hard":
                # User specifically requested hard, pick top remaining
                challenge_candidate = remaining[0]
            elif any(c[1].difficulty == "medium" for c in remaining):
                # If warm up was easy, a medium problem can be the challenge
                med_candidates = [c for c in remaining if c[1].difficulty == "medium"]
                challenge_candidate = med_candidates[0]

        # Main practice slots
        # Fill remaining slots up to target_size (reserving 1 for challenge if selected)
        target_main_count = session_size - len(selected_problems) - (1 if challenge_candidate else 0)

        for prob, bd in actual_pool:
            pid = prob["id"]
            if pid in used_pids:
                continue
            if challenge_candidate and pid == challenge_candidate[0]["id"]:
                continue
            if target_main_count <= 0:
                break

            # Reason synthesis
            reasons = []
            matching_weak = [t for t in bd.all_topics if t in weak_topics]
            if matching_weak:
                reasons.append(f"Reinforces weak topic ({', '.join(matching_weak)})")
            
            # Topic diversity check
            new_topics = [t for t in bd.all_topics if t not in covered_topics_set]
            if new_topics:
                reasons.append(f"Expands coverage into ({', '.join(new_topics)})")
            elif not matching_weak:
                reasons.append(f"Solidifies practice in ({', '.join(bd.all_topics) or 'standard patterns'})")

            if bd.unsolved_attempt_penalty_or_bonus > 15.0:
                reasons.append("Retries previously unfinished candidate")

            reason_str = "; ".join(reasons) if reasons else "High-ranking practice problem."
            add_plan_item(prob, bd, SessionProblemRole.MAIN_PRACTICE, reason_str)
            target_main_count -= 1

        # Add challenge if designated
        if challenge_candidate and len(selected_problems) < session_size:
            c_prob, c_bd = challenge_candidate
            c_reasons = [f"Challenge problem to push problem-solving bounds ({c_bd.difficulty.title()})"]
            c_weak = [t for t in c_bd.all_topics if t in weak_topics]
            if c_weak:
                c_reasons.append(f"Tests deeper mastery of weak topic ({', '.join(c_weak)})")
            add_plan_item(c_prob, c_bd, SessionProblemRole.CHALLENGE, "; ".join(c_reasons))

        # If still short of session_size and pool has remaining, fill them in rank order
        if len(selected_problems) < session_size:
            for prob, bd in actual_pool:
                if len(selected_problems) >= session_size:
                    break
                if prob["id"] not in used_pids:
                    add_plan_item(
                        prob,
                        bd,
                        SessionProblemRole.MAIN_PRACTICE,
                        "Additional high-priority practice problem to reach requested session size.",
                    )

        # Sort the final session problems to follow logical progression:
        # Warm-up -> Main Practice -> Challenge
        role_order = {
            SessionProblemRole.WARM_UP: 1,
            SessionProblemRole.MAIN_PRACTICE: 2,
            SessionProblemRole.CHALLENGE: 3,
        }
        selected_problems.sort(
            key=lambda item: (
                role_order.get(item.role, 2),
                {"easy": 1, "medium": 2, "hard": 3}.get(item.difficulty, 2),
                -item.priority_score,
                item.problem_id,
            )
        )

        # Re-number ranks after progression ordering
        for idx, item in enumerate(selected_problems, 1):
            item.rank = idx

        return self._build_plan_result(session_size, selected_problems, weak_topics, covered_topics_set)

    def _build_plan_result(
        self,
        target_size: int,
        problems: List[PlannedProblem],
        weak_topics: List[str],
        covered_topics: Set[str],
    ) -> LearningSessionPlan:
        """Construct the LearningSessionPlan object with summary metadata."""
        diff_dist: Dict[str, int] = {}
        for p in problems:
            d = p.difficulty
            diff_dist[d] = diff_dist.get(d, 0) + 1

        # Build explainable session summary
        summary_lines = []
        if not problems:
            summary_lines.append("Empty session plan.")
        else:
            diff_summary = ", ".join(f"{cnt} {diff.title()}" for diff, cnt in sorted(diff_dist.items()))
            summary_lines.append(f"Curated {len(problems)}-problem session ({diff_summary}).")

            roles_count: Dict[str, int] = {}
            for p in problems:
                roles_count[p.role.value] = roles_count.get(p.role.value, 0) + 1
            roles_summary = []
            if roles_count.get("warm_up"):
                roles_summary.append("1 Warm-Up")
            if roles_count.get("main_practice"):
                roles_summary.append(f"{roles_count['main_practice']} Main Practice")
            if roles_count.get("challenge"):
                roles_summary.append(f"{roles_count['challenge']} Challenge")
            if roles_summary:
                summary_lines.append(f"Structure: {' -> '.join(roles_summary)}.")

            covered_weak = [t for t in weak_topics if t in covered_topics]
            if covered_weak:
                summary_lines.append(f"Directly targets weak topics: {', '.join(covered_weak)}.")
            elif weak_topics:
                summary_lines.append(f"Identified weak topics: {', '.join(weak_topics)} (no candidate problems matched).")
            else:
                summary_lines.append("Focuses on broad skill reinforcement across balanced algorithm domains.")

        return LearningSessionPlan(
            target_language=self.language,
            target_size=target_size,
            planned_problems=problems,
            weak_topics=weak_topics,
            covered_topics=sorted(covered_topics),
            session_summary=" ".join(summary_lines),
            difficulty_distribution=diff_dist,
        )
