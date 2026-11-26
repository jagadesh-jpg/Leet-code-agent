"""Topic Metadata and Performance Analysis Engine.

Milestone 6.3.4: Topic-Aware Learning Intelligence.
Provides:
1. Standardized algorithm topic taxonomy.
2. Curated problem topic metadata mapping (supporting multiple topics per problem).
3. Topic performance analysis (solved, unsolved, attempts, mastery indicators).
4. Safe handling of missing topic and history metadata.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import store


# Standardized Algorithmic Topic Taxonomy
STANDARD_TOPICS = [
    "Arrays",
    "Hashing",
    "Two Pointers",
    "Sliding Window",
    "Stack",
    "Binary Search",
    "Linked List",
    "Trees",
    "Graphs",
    "Heap",
    "Greedy",
    "Dynamic Programming",
    "Backtracking",
    "Math",
]

# Accurate, maintainable mapping for curated problems based on algorithmic structure
# Supports multiple topics per problem without altering required schema keys of problems.json
CURATED_PROBLEM_TOPICS: Dict[str, List[str]] = {
    "two-sum": ["Arrays", "Hashing"],
    "valid-parentheses": ["Stack", "Hashing"],
    "contains-duplicate": ["Arrays", "Hashing"],
    "longest-substring-without-repeating-characters": ["Sliding Window", "Hashing", "Two Pointers"],
    "group-anagrams": ["Arrays", "Hashing"],
    "product-of-array-except-self": ["Arrays"],
    "trapping-rain-water": ["Two Pointers", "Stack", "Arrays"],
    "longest-valid-parentheses": ["Stack", "Dynamic Programming"],
    "minimum-window-substring": ["Sliding Window", "Hashing"],
}


def get_problem_topics(problem: Dict[str, Any]) -> List[str]:
    """Retrieve normalized list of topics for a problem.

    Priority order:
    1. Explicit 'topics' key in problem dict (list or string).
    2. Explicit 'pattern' or 'topic' or 'type' key.
    3. Curated lookup in CURATED_PROBLEM_TOPICS for standard problems.
    4. Empty list if unclassified (no fabricated topics).
    """
    topics: List[str] = []

    # 1. Explicit 'topics' list or string
    raw_topics = problem.get("topics")
    if raw_topics:
        if isinstance(raw_topics, list):
            topics.extend([str(t).strip() for t in raw_topics if str(t).strip()])
        elif isinstance(raw_topics, str):
            topics.extend([t.strip() for t in raw_topics.split(",") if t.strip()])

    # 2. Explicit single topic / pattern / type
    for key in ("pattern", "topic", "type"):
        val = problem.get(key)
        if val and isinstance(val, str) and val.strip():
            # Format nicely, e.g. "two_pointers" -> "Two Pointers"
            cleaned = val.strip().replace("_", " ").title()
            if cleaned not in topics:
                topics.append(cleaned)

    # 3. Known curated problem lookup
    pid = problem.get("id")
    if pid and pid in CURATED_PROBLEM_TOPICS:
        for t in CURATED_PROBLEM_TOPICS[pid]:
            if t not in topics:
                topics.append(t)

    return topics


@dataclass
class TopicPerformanceMetric:
    """Calculated mastery and performance statistics for a specific topic."""
    topic: str
    total_problems: int
    solved_problems: int
    unsolved_problems: int
    total_attempts: int
    failed_attempts: int
    success_rate: float  # Solved / (Solved + Failed) or 0.0
    mastery_status: str  # "mastered", "in_progress", "needs_practice", "no_history"
    has_history: bool
    summary: str


class TopicAnalyzer:
    """Offline analyzer that computes topic metrics and coverage opportunities."""

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        language: str = "python",
    ):
        self.db_path = db_path
        self.language = (language or "python").strip().lower()

    def analyze_topics(
        self,
        all_problems: Optional[List[Dict[str, Any]]] = None,
        include_curated: bool = False,
    ) -> Dict[str, TopicPerformanceMetric]:
        """Compute performance metrics across all topics represented in the candidate problem set."""
        # 1. Map problems to topics
        problem_pool: List[Dict[str, Any]] = list(all_problems) if all_problems is not None else []
        if include_curated:
            seen_pids = {p.get("id") for p in problem_pool if p.get("id")}
            for curated_id in CURATED_PROBLEM_TOPICS:
                if curated_id not in seen_pids:
                    problem_pool.append({"id": curated_id})

        topic_to_pids: Dict[str, Set[str]] = {}
        for p in problem_pool:
            topics = get_problem_topics(p)
            for t in topics:
                if t not in topic_to_pids:
                    topic_to_pids[t] = set()
                topic_to_pids[t].add(p["id"])

        # 2. Fetch history for all problems in batch
        store.init(db_path=self.db_path)
        metrics: Dict[str, TopicPerformanceMetric] = {}

        for topic, pids in topic_to_pids.items():
            total_probs = len(pids)
            solved_count = 0
            unsolved_count = 0
            total_attempts = 0
            failed_attempts = 0
            has_history = False

            for pid in pids:
                is_solved = store.is_solved(pid, language=self.language, db_path=self.db_path)
                if is_solved:
                    solved_count += 1
                else:
                    unsolved_count += 1

                # Query attempts from DB
                try:
                    with store.get_connection(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT status FROM attempts WHERE problem_id = ?",
                            (pid,),
                        )
                        rows = cursor.fetchall()
                        if rows:
                            has_history = True
                            total_attempts += len(rows)
                            failed_attempts += sum(1 for r in rows if r["status"] != "passed")
                except Exception:
                    pass

            # Calculate meaningful success rate
            # Rate of successful attempts vs total logged attempts
            if total_attempts > 0:
                success_rate = (total_attempts - failed_attempts) / total_attempts
            else:
                success_rate = 0.0

            # Deterministic mastery status:
            # - "mastered": All problems solved with high success rate
            # - "needs_practice": Multiple failures or unsolved problems with history
            # - "in_progress": Some solved, minimal failures
            # - "no_history": No attempts logged yet
            if not has_history and solved_count == 0:
                mastery = "no_history"
                summary = "Untouched (no practice history recorded)"
            elif solved_count == total_probs and failed_attempts == 0:
                mastery = "mastered"
                summary = f"Mastered ({solved_count}/{total_probs} solved, 100% clean passes)"
            elif solved_count == total_probs:
                mastery = "proficient"
                summary = f"Proficient ({solved_count}/{total_probs} solved after {failed_attempts} initial failure(s))"
            elif failed_attempts >= 2 or (failed_attempts > 0 and solved_count == 0):
                mastery = "needs_practice"
                summary = f"Needs Practice ({solved_count}/{total_probs} solved, {failed_attempts} failed attempts)"
            elif solved_count > 0:
                mastery = "in_progress"
                summary = f"In Progress ({solved_count}/{total_probs} solved)"
            else:
                mastery = "no_history"
                summary = "Untouched"

            metrics[topic] = TopicPerformanceMetric(
                topic=topic,
                total_problems=total_probs,
                solved_problems=solved_count,
                unsolved_problems=unsolved_count,
                total_attempts=total_attempts,
                failed_attempts=failed_attempts,
                success_rate=success_rate,
                mastery_status=mastery,
                has_history=has_history or (solved_count > 0),
                summary=summary,
            )

        return metrics
