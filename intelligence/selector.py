"""Deterministic & Explainable Problem Prioritization Engine.

Milestone 6.3.3: Intelligent Problem Selection Engine.
Prioritizes problem candidates for autonomous solving based on transparent,
rule-based heuristics without machine learning, external network requests, or
unfounded metadata assumptions.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import store


@dataclass
class ProblemScoreBreakdown:
    """Detailed and explainable score components for a candidate problem."""
    problem_id: str
    title: str
    difficulty: str
    topic_or_pattern: Optional[str]
    topic_available: bool
    base_difficulty_score: float
    difficulty_preference_score: float
    unsolved_attempt_penalty_or_bonus: float
    repeat_selection_penalty: float
    total_score: float
    rationale: str
    historical_attempts: int = 0
    historical_status: Optional[str] = None


class ProblemSelector:
    """Rule-based, deterministic problem prioritization engine."""

    # Base difficulty scores (defaults prefer progressive ramp: Easy -> Medium -> Hard)
    DEFAULT_DIFFICULTY_WEIGHTS = {
        "easy": 30.0,
        "medium": 20.0,
        "hard": 10.0,
    }

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        language: str = "python",
        preferred_difficulty: Optional[str] = None,
        prioritize_failed_attempts: bool = True,
        max_attempt_threshold: int = 5,
    ):
        self.db_path = db_path
        self.language = (language or "python").strip().lower()
        self.preferred_difficulty = preferred_difficulty.strip().lower() if preferred_difficulty else None
        self.prioritize_failed_attempts = prioritize_failed_attempts
        self.max_attempt_threshold = max_attempt_threshold

    def get_problem_history(self, problem_id: str) -> Dict[str, Any]:
        """Fetch attempt count and last status from database safely (read-only)."""
        history = {
            "attempts_count": 0,
            "status": None,
            "is_solved": False,
        }
        try:
            with store.get_connection(self.db_path) as conn:
                cursor = conn.cursor()
                # 1. Check language_progress
                cursor.execute(
                    "SELECT status, attempts FROM language_progress WHERE problem_id = ? AND language = ?",
                    (problem_id, self.language),
                )
                row = cursor.fetchone()
                if row:
                    history["status"] = row["status"]
                    history["attempts_count"] = row["attempts"] or 0
                    history["is_solved"] = (row["status"] == "solved")
                else:
                    # Check legacy progress if python
                    if self.language in ["python", "py", "python3"]:
                        cursor.execute("SELECT status, attempts FROM progress WHERE problem_id = ?", (problem_id,))
                        row_p = cursor.fetchone()
                        if row_p:
                            history["status"] = row_p["status"]
                            history["attempts_count"] = row_p["attempts"] or 0
                            history["is_solved"] = (row_p["status"] == "solved")

                # Count distinct logged attempts
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM attempts WHERE problem_id = ?",
                    (problem_id,),
                )
                cnt_row = cursor.fetchone()
                if cnt_row and cnt_row["cnt"]:
                    history["attempts_count"] = max(history["attempts_count"], cnt_row["cnt"])
        except Exception:
            # Table might not exist yet if DB is completely uninitialized
            pass

        return history

    def score_problem(
        self,
        problem: Dict[str, Any],
        recent_selected_ids: Optional[List[str]] = None,
    ) -> ProblemScoreBreakdown:
        """Calculate deterministic priority score and rationale for a problem candidate."""
        pid = problem["id"]
        title = problem.get("title", pid)
        diff = problem.get("difficulty", "medium").strip().lower()

        # Check topic or pattern metadata without making assumptions
        # Only use metadata explicitly present in the problem dict
        topic = problem.get("pattern") or problem.get("topic") or problem.get("type")
        topic_available = bool(topic)

        # 1. Base difficulty score
        base_diff_score = self.DEFAULT_DIFFICULTY_WEIGHTS.get(diff, 15.0)

        # 2. Preferred difficulty matching
        diff_pref_score = 0.0
        if self.preferred_difficulty:
            if diff == self.preferred_difficulty:
                diff_pref_score = 50.0  # Strong boost for matching user preference
            else:
                diff_pref_score = -20.0  # Lower priority for non-preferred difficulty

        # 3. Historical attempts and failure recovery
        hist = self.get_problem_history(pid)
        attempts = hist["attempts_count"]
        status = hist["status"]
        attempt_adjustment = 0.0

        rationale_parts: List[str] = []
        rationale_parts.append(f"Base difficulty: {diff} (+{base_diff_score:.0f})")

        if diff_pref_score > 0:
            rationale_parts.append(f"Matches preferred difficulty '{self.preferred_difficulty}' (+{diff_pref_score:.0f})")
        elif diff_pref_score < 0:
            rationale_parts.append(f"Does not match preferred difficulty '{self.preferred_difficulty}' ({diff_pref_score:.0f})")

        if topic_available:
            rationale_parts.append(f"Topic: {topic}")
        else:
            rationale_parts.append("Topic metadata: unavailable")

        if status == "failed" or (attempts > 0 and not hist["is_solved"]):
            if attempts >= self.max_attempt_threshold:
                # Exhausted attempts: deprioritize to avoid getting permanently stuck
                attempt_adjustment = -40.0
                rationale_parts.append(f"Exhausted prior attempts ({attempts} attempts): deprioritized ({attempt_adjustment:.0f})")
            elif self.prioritize_failed_attempts:
                # Unfinished / failed problem: high priority for correction and mastery
                attempt_adjustment = 35.0
                rationale_parts.append(f"Unfinished candidate ({attempts} prior attempts): prioritized for retry (+{attempt_adjustment:.0f})")
            else:
                attempt_adjustment = -10.0
                rationale_parts.append(f"Prior failed attempt ({attempts}): deprioritized")
        elif attempts == 0:
            # Fresh untouched problem
            attempt_adjustment = 10.0
            rationale_parts.append("Fresh untouched problem (+10)")

        # 4. Repeat selection penalty in current session/queue
        repeat_penalty = 0.0
        if recent_selected_ids and pid in recent_selected_ids:
            repeat_penalty = -25.0
            rationale_parts.append("Selected recently in active queue (-25)")

        total = base_diff_score + diff_pref_score + attempt_adjustment + repeat_penalty
        rationale = "; ".join(rationale_parts)

        return ProblemScoreBreakdown(
            problem_id=pid,
            title=title,
            difficulty=diff,
            topic_or_pattern=topic,
            topic_available=topic_available,
            base_difficulty_score=base_diff_score,
            difficulty_preference_score=diff_pref_score,
            unsolved_attempt_penalty_or_bonus=attempt_adjustment,
            repeat_selection_penalty=repeat_penalty,
            total_score=total,
            rationale=rationale,
            historical_attempts=attempts,
            historical_status=status,
        )

    def prioritize_candidates(
        self,
        candidates: List[Dict[str, Any]],
        skip_solved: bool = True,
        max_problems: Optional[int] = None,
        recent_selected_ids: Optional[List[str]] = None,
    ) -> List[Tuple[Dict[str, Any], ProblemScoreBreakdown]]:
        """Filter and rank candidate problems deterministically by priority score."""
        if not candidates:
            return []

        scored_candidates: List[Tuple[Dict[str, Any], ProblemScoreBreakdown]] = []

        for p in candidates:
            pid = p["id"]
            # Solved problem filtering
            if skip_solved:
                hist = self.get_problem_history(pid)
                if hist["is_solved"] or store.is_solved(pid, language=self.language, db_path=self.db_path):
                    continue

            breakdown = self.score_problem(p, recent_selected_ids=recent_selected_ids)
            scored_candidates.append((p, breakdown))

        # Deterministic sort order:
        # 1. Total score descending
        # 2. Problem difficulty ranking
        # 3. Problem ID ascending (tie-breaker for absolute determinism)
        diff_order = {"easy": 1, "medium": 2, "hard": 3}
        scored_candidates.sort(
            key=lambda item: (
                -item[1].total_score,
                diff_order.get(item[1].difficulty, 99),
                item[1].problem_id,
            )
        )

        if max_problems is not None:
            return scored_candidates[:max_problems]
        return scored_candidates
