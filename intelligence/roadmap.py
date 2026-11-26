"""Personalized DSA Skill Roadmap & Mastery Map Engine.

Milestone 6.3.14: Personalized DSA Skill Roadmap & Mastery Map.
Provides:
1. Structured 5-stage DSA skill roadmap taxonomy with topics and prerequisite dependencies.
2. Transparent, deterministic topic mastery score calculation based on verified local evidence.
3. Dependency-aware readiness evaluation (prerequisite gap and readiness detection, cycle detection).
4. Personalized learning recommendations (strengthen fundamentals, learn new topic, practice weak topic,
   revise overdue topic, progress difficulty, review prerequisites).
5. Comprehensive roadmap progress and stage analytics.

100% offline, local-first, zero external API calls, read-only on progress.db, isolated.
Never fabricates metrics, streaks, or completion history.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from intelligence.topics import STANDARD_TOPICS, TopicAnalyzer, get_problem_topics
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from problems import load_problems
import store


class TopicMasteryStatus(str, Enum):
    """Progressive mastery status for a roadmap topic."""
    LOCKED = "locked"               # Prerequisites not satisfied
    NOT_STARTED = "not_started"     # Prerequisites met or stage 1, but 0 attempts
    LEARNING = "learning"           # Attempted or 1 solve, building understanding
    PRACTICING = "practicing"       # Multiple solves, consolidating technique
    PROFICIENT = "proficient"       # High success rate across varied problems/difficulties


class RoadmapRecommendationType(str, Enum):
    """Categorized roadmap recommendation actions."""
    STRENGTHEN_FUNDAMENTALS = "strengthen_fundamentals"
    LEARN_NEW_TOPIC = "learn_new_topic"
    PRACTICE_WEAK_TOPIC = "practice_weak_topic"
    REVISE_OVERDUE_TOPIC = "revise_overdue_topic"
    PROGRESS_DIFFICULTY = "progress_difficulty"
    REVIEW_PREREQUISITES = "review_prerequisites"


@dataclass
class TopicRoadmapNode:
    """Definition of a topic node in the DSA roadmap."""
    topic_id: str                   # e.g., "arrays", "binary-search"
    display_name: str               # e.g., "Arrays", "Binary Search"
    stage_id: int                   # 1 to 5
    stage_name: str                 # e.g., "Programming Foundations"
    prerequisites: List[str]        # List of topic_ids that should precede this
    description: str
    recommended_min_solves: int = 2


@dataclass
class TopicMasteryRecord:
    """Computed transparent mastery indicators for a specific topic."""
    topic_id: str
    display_name: str
    stage_id: int
    stage_name: str
    mastery_score: float            # 0.0 to 100.0 transparent deterministic score
    confidence_level: str           # "low", "medium", "high" based on attempt/solve volume
    status: TopicMasteryStatus
    distinct_solved: int
    total_problems_available: int
    total_attempts: int
    failed_attempts: int
    success_rate: float             # 0.0 to 100.0
    easy_solves: int
    medium_solves: int
    hard_solves: int
    prerequisites: List[str]
    prerequisites_met: bool
    missing_prerequisites: List[str]
    has_active_revision_due: bool
    recommended_action: str
    score_explanation: str


@dataclass
class RoadmapStageSummary:
    """Aggregated status and mastery for a roadmap stage."""
    stage_id: int
    stage_name: str
    total_topics: int
    completed_topics: int           # Topics with status == PROFICIENT
    in_progress_topics: int         # LEARNING or PRACTICING
    not_started_topics: int
    locked_topics: int
    stage_progress_pct: float       # Percentage of topics completed/proficient
    average_mastery_score: float
    topics: List[TopicMasteryRecord] = field(default_factory=list)


@dataclass
class RoadmapRecommendation:
    """Actionable personalized recommendation for progressing on the roadmap."""
    recommendation_type: RoadmapRecommendationType
    topic_id: str
    topic_name: str
    stage_id: int
    stage_name: str
    priority: int                   # 1 (highest) to 5 (lowest)
    title: str
    rationale: str
    suggested_problems: List[str] = field(default_factory=list)


@dataclass
class RoadmapOverviewReport:
    """Complete roadmap intelligence and progression overview."""
    total_stages: int
    total_topics: int
    proficient_topics_count: int
    learning_topics_count: int
    not_started_topics_count: int
    locked_topics_count: int
    overall_roadmap_progress_pct: float
    strongest_topics: List[str]
    weakest_topics: List[str]
    topics_needing_revision: List[str]
    ready_to_learn_topics: List[str]
    blocked_topics: List[str]
    stages: List[RoadmapStageSummary] = field(default_factory=list)
    recommendations: List[RoadmapRecommendation] = field(default_factory=list)
    summary: str = ""


# =============================================================================
# Standard 5-Stage DSA Roadmap Taxonomy & Prerequisites
# =============================================================================

ROADMAP_STAGES_CONFIG: Dict[int, str] = {
    1: "Programming Foundations",
    2: "Core Data Structures",
    3: "Core Algorithms",
    4: "Advanced Data Structures",
    5: "Advanced Algorithms",
}

ROADMAP_TOPIC_NODES: List[TopicRoadmapNode] = [
    # Stage 1: Programming Foundations
    TopicRoadmapNode(
        topic_id="arrays",
        display_name="Arrays",
        stage_id=1,
        stage_name=ROADMAP_STAGES_CONFIG[1],
        prerequisites=[],
        description="Sequential memory contiguous elements, index access, linear iteration.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="strings",
        display_name="Strings",
        stage_id=1,
        stage_name=ROADMAP_STAGES_CONFIG[1],
        prerequisites=["arrays"],
        description="Character sequences, string manipulation, ASCII/Unicode comparisons.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="hashing",
        display_name="Basic Hashing",
        stage_id=1,
        stage_name=ROADMAP_STAGES_CONFIG[1],
        prerequisites=["arrays"],
        description="Hash tables, key-value lookup in O(1) average time, frequency counters.",
        recommended_min_solves=2,
    ),

    # Stage 2: Core Data Structures
    TopicRoadmapNode(
        topic_id="linked-list",
        display_name="Linked Lists",
        stage_id=2,
        stage_name=ROADMAP_STAGES_CONFIG[2],
        prerequisites=["arrays"],
        description="Node pointers, singly/doubly linked chains, fast insertions/deletions.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="stack",
        display_name="Stacks",
        stage_id=2,
        stage_name=ROADMAP_STAGES_CONFIG[2],
        prerequisites=["arrays"],
        description="LIFO data structure, bracket validation, monotonic stacks.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="queues",
        display_name="Queues",
        stage_id=2,
        stage_name=ROADMAP_STAGES_CONFIG[2],
        prerequisites=["linked-list"],
        description="FIFO data structure, deque, double-ended queues for BFS traversal.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="trees",
        display_name="Trees",
        stage_id=2,
        stage_name=ROADMAP_STAGES_CONFIG[2],
        prerequisites=["linked-list", "stack"],
        description="Hierarchical nodes, binary trees, DFS/BFS traversals, depth/height.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="binary-search-trees",
        display_name="Binary Search Trees",
        stage_id=2,
        stage_name=ROADMAP_STAGES_CONFIG[2],
        prerequisites=["trees"],
        description="Ordered binary trees, in-order sorted traversal, BST validation & search.",
        recommended_min_solves=2,
    ),

    # Stage 3: Core Algorithms
    TopicRoadmapNode(
        topic_id="binary-search",
        display_name="Binary Search",
        stage_id=3,
        stage_name=ROADMAP_STAGES_CONFIG[3],
        prerequisites=["arrays"],
        description="Logarithmic O(log N) search on sorted arrays and monotonic solution spaces.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="sorting",
        display_name="Sorting",
        stage_id=3,
        stage_name=ROADMAP_STAGES_CONFIG[3],
        prerequisites=["arrays"],
        description="Comparison sorts, divide-and-conquer mergesort/quicksort, custom comparators.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="two-pointers",
        display_name="Two Pointers",
        stage_id=3,
        stage_name=ROADMAP_STAGES_CONFIG[3],
        prerequisites=["arrays"],
        description="Opposite-end and same-direction traversal pointers on sorted collections.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="sliding-window",
        display_name="Sliding Window",
        stage_id=3,
        stage_name=ROADMAP_STAGES_CONFIG[3],
        prerequisites=["arrays", "two-pointers"],
        description="Dynamic contiguous subarray/substring tracking for optimization.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="recursion",
        display_name="Recursion",
        stage_id=3,
        stage_name=ROADMAP_STAGES_CONFIG[3],
        prerequisites=["stack"],
        description="Base cases, call stack mechanics, divide and conquer.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="backtracking",
        display_name="Backtracking",
        stage_id=3,
        stage_name=ROADMAP_STAGES_CONFIG[3],
        prerequisites=["recursion"],
        description="Systematic search state trees, permutations, combinations, prune branches.",
        recommended_min_solves=2,
    ),

    # Stage 4: Advanced Data Structures
    TopicRoadmapNode(
        topic_id="heap",
        display_name="Heaps",
        stage_id=4,
        stage_name=ROADMAP_STAGES_CONFIG[4],
        prerequisites=["trees", "binary-search"],
        description="Priority queues, min-heap/max-heap, top-k elements, running medians.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="tries",
        display_name="Tries",
        stage_id=4,
        stage_name=ROADMAP_STAGES_CONFIG[4],
        prerequisites=["trees", "strings"],
        description="Prefix trees, fast string search, prefix matching, word dictionaries.",
        recommended_min_solves=1,
    ),
    TopicRoadmapNode(
        topic_id="graphs",
        display_name="Graphs",
        stage_id=4,
        stage_name=ROADMAP_STAGES_CONFIG[4],
        prerequisites=["trees", "queues"],
        description="Adjacency list/matrix representation, connected components, cycles, BFS/DFS.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="union-find",
        display_name="Union Find",
        stage_id=4,
        stage_name=ROADMAP_STAGES_CONFIG[4],
        prerequisites=["graphs"],
        description="Disjoint set union (DSU), path compression, rank/size optimization.",
        recommended_min_solves=1,
    ),

    # Stage 5: Advanced Algorithms
    TopicRoadmapNode(
        topic_id="greedy",
        display_name="Greedy Algorithms",
        stage_id=5,
        stage_name=ROADMAP_STAGES_CONFIG[5],
        prerequisites=["sorting", "heap"],
        description="Locally optimal choices leading to globally optimal solutions, intervals.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="dynamic-programming",
        display_name="Dynamic Programming",
        stage_id=5,
        stage_name=ROADMAP_STAGES_CONFIG[5],
        prerequisites=["recursion", "arrays"],
        description="Overlapping subproblems, optimal substructure, memoization, tabulation.",
        recommended_min_solves=2,
    ),
    TopicRoadmapNode(
        topic_id="graph-algorithms",
        display_name="Graph Algorithms",
        stage_id=5,
        stage_name=ROADMAP_STAGES_CONFIG[5],
        prerequisites=["graphs", "heap"],
        description="Dijkstra's shortest path, topological sorting, Bellman-Ford, Kruskal/Prim MST.",
        recommended_min_solves=1,
    ),
    TopicRoadmapNode(
        topic_id="advanced-problem-solving",
        display_name="Advanced Problem Solving",
        stage_id=5,
        stage_name=ROADMAP_STAGES_CONFIG[5],
        prerequisites=["dynamic-programming", "graphs"],
        description="Multi-paradigm algorithmic synthesis, complex constraints, state machine DP.",
        recommended_min_solves=1,
    ),
]


class DsaRoadmapEngine:
    """Offline engine for DSA roadmap tracking, mastery calculation, and recommendations."""

    def __init__(
        self,
        progress_db_path: Optional[str | Path] = None,
        tracking_db_path: Optional[str | Path] = None,
        language: str = "python",
        custom_nodes: Optional[List[TopicRoadmapNode]] = None,
    ):
        self.progress_db_path = progress_db_path
        self.tracking_db_path = Path(tracking_db_path) if tracking_db_path is not None else DEFAULT_TRACKING_DB_PATH
        self.language = (language or "python").strip().lower()
        self.nodes = custom_nodes if custom_nodes is not None else list(ROADMAP_TOPIC_NODES)
        self._validate_dependency_graph()

    def _validate_dependency_graph(self) -> None:
        """Verify that prerequisites point to known nodes and that no circular dependencies exist."""
        node_map = {n.topic_id: n for n in self.nodes}

        # 1. Check for missing prerequisite targets
        for node in self.nodes:
            for prereq in node.prerequisites:
                if prereq not in node_map:
                    raise ValueError(f"Invalid prerequisite '{prereq}' defined for topic '{node.topic_id}' (topic does not exist).")

        # 2. Cycle detection via DFS
        visited: Dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=visited

        def dfs(curr_id: str, path: List[str]) -> None:
            visited[curr_id] = 1
            node = node_map[curr_id]
            for p in node.prerequisites:
                if visited.get(p, 0) == 1:
                    cycle = " -> ".join(path + [p])
                    raise ValueError(f"Circular dependency detected in DSA roadmap: {cycle}")
                if visited.get(p, 0) == 0:
                    dfs(p, path + [p])
            visited[curr_id] = 2

        for node in self.nodes:
            if visited.get(node.topic_id, 0) == 0:
                dfs(node.topic_id, [node.topic_id])

    def _get_solved_problem_ids(self) -> Set[str]:
        """Fetch distinct solved problem IDs from progress.db without altering database."""
        solved: Set[str] = set()
        if not self.progress_db_path:
            return solved
        try:
            with sqlite3.connect(str(self.progress_db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if "attempts" in tables:
                    cur.execute("SELECT DISTINCT problem_id FROM attempts WHERE passed = total AND total > 0")
                    for r in cur.fetchall():
                        solved.add(r["problem_id"])
                if "language_progress" in tables:
                    cur.execute("SELECT DISTINCT problem_id FROM language_progress WHERE status = 'solved'")
                    for r in cur.fetchall():
                        solved.add(r["problem_id"])
                if "progress" in tables:
                    cur.execute("SELECT DISTINCT problem_id FROM progress WHERE status = 'solved'")
                    for r in cur.fetchall():
                        solved.add(r["problem_id"])
        except Exception:
            pass
        return solved

    def _get_attempt_stats(self) -> Dict[str, Dict[str, int]]:
        """Fetch attempt counts and failure counts per problem."""
        stats: Dict[str, Dict[str, int]] = {}
        if not self.progress_db_path:
            return stats
        try:
            with sqlite3.connect(str(self.progress_db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if "attempts" in tables:
                    cur.execute("SELECT problem_id, passed, total FROM attempts")
                    for r in cur.fetchall():
                        pid = r["problem_id"]
                        if pid not in stats:
                            stats[pid] = {"total": 0, "failed": 0, "passed": 0}
                        stats[pid]["total"] += 1
                        if r["passed"] < r["total"]:
                            stats[pid]["failed"] += 1
                        else:
                            stats[pid]["passed"] += 1
        except Exception:
            pass
        return stats

    def _get_revision_due_topics(self) -> Set[str]:
        """Fetch topics that currently have overdue or due spaced revisions in tracking DB."""
        due_topics: Set[str] = set()
        if not self.tracking_db_path or not self.tracking_db_path.exists():
            return due_topics
        try:
            with sqlite3.connect(str(self.tracking_db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if "spaced_revisions" in tables:
                    now_str = datetime.now(timezone.utc).isoformat()
                    cur.execute(
                        "SELECT topics FROM spaced_revisions WHERE status = 'active' AND next_review_at <= ?",
                        (now_str,),
                    )
                    for r in cur.fetchall():
                        t_str = r["topics"]
                        if t_str:
                            for t in t_str.split(","):
                                cleaned = t.strip().lower().replace(" ", "-")
                                if cleaned:
                                    due_topics.add(cleaned)
        except Exception:
            pass
        return due_topics

    def _get_active_goals_by_topic(self) -> Set[str]:
        """Fetch active goal target topics."""
        goal_topics: Set[str] = set()
        if not self.tracking_db_path or not self.tracking_db_path.exists():
            return goal_topics
        try:
            with sqlite3.connect(str(self.tracking_db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if "learning_goals" in tables:
                    cur.execute(
                        "SELECT target_parameter FROM learning_goals WHERE status = 'active' AND goal_type = 'practice_topic'"
                    )
                    for r in cur.fetchall():
                        param = r["target_parameter"]
                        if param:
                            goal_topics.add(param.strip().lower().replace(" ", "-"))
        except Exception:
            pass
        return goal_topics

    def _match_problem_to_node(self, problem: Dict[str, Any], node: TopicRoadmapNode) -> bool:
        """Determine if a problem belongs to the roadmap node topic."""
        node_id_clean = node.topic_id.lower().replace("-", " ")
        display_clean = node.display_name.lower().replace("-", " ")

        # Match via get_problem_topics
        topics = [t.lower().replace("-", " ") for t in get_problem_topics(problem)]
        for t in topics:
            if t == node_id_clean or t == display_clean:
                return True
            # Substring/plural handling
            if (node_id_clean in t) or (t in node_id_clean):
                return True
            if (display_clean in t) or (t in display_clean):
                return True

        # Check explicit problem pattern or type
        pattern = str(problem.get("pattern", "")).lower().replace("_", " ")
        if pattern and (node_id_clean in pattern or pattern in node_id_clean):
            return True

        return False

    def compute_topic_mastery(self, node: TopicRoadmapNode) -> TopicMasteryRecord:
        """Calculate transparent, deterministic mastery indicators for a roadmap topic."""
        all_problems = load_problems()
        solved_ids = self._get_solved_problem_ids()
        attempt_stats = self._get_attempt_stats()
        revision_due_topics = self._get_revision_due_topics()

        # Find problems associated with this topic
        topic_problems = [p for p in all_problems if self._match_problem_to_node(p, node)]
        total_available = len(topic_problems)

        solved_in_topic = [p for p in topic_problems if p.get("id") in solved_ids]
        distinct_solved = len(solved_in_topic)

        # Difficulties breakdown
        easy_solves = sum(1 for p in solved_in_topic if p.get("difficulty", "").lower() == "easy")
        medium_solves = sum(1 for p in solved_in_topic if p.get("difficulty", "").lower() == "medium")
        hard_solves = sum(1 for p in solved_in_topic if p.get("difficulty", "").lower() == "hard")

        # Attempts & failures
        total_attempts = 0
        failed_attempts = 0
        for p in topic_problems:
            pid = p.get("id")
            if pid in attempt_stats:
                total_attempts += attempt_stats[pid]["total"]
                failed_attempts += attempt_stats[pid]["failed"]

        # Success rate
        if total_attempts > 0:
            success_rate = round(max(0.0, ((total_attempts - failed_attempts) / total_attempts) * 100.0), 1)
        elif distinct_solved > 0:
            success_rate = 100.0
        else:
            success_rate = 0.0

        # Confidence level based on attempt and solve volume
        if distinct_solved >= 4 or total_attempts >= 8:
            confidence = "high"
        elif distinct_solved >= 2 or total_attempts >= 3:
            confidence = "medium"
        else:
            confidence = "low"

        # Check prerequisite readiness
        node_map = {n.topic_id: n for n in self.nodes}
        missing_prereqs = []
        for prereq_id in node.prerequisites:
            prereq_node = node_map.get(prereq_id)
            if prereq_node:
                # To satisfy a prerequisite, the learner should have solved at least 1 problem in it
                # or have stage 1 foundational familiarity
                p_problems = [p for p in all_problems if self._match_problem_to_node(p, prereq_node)]
                p_solved = [p for p in p_problems if p.get("id") in solved_ids]
                if len(p_solved) == 0 and prereq_node.stage_id > 1:
                    missing_prereqs.append(prereq_node.display_name)
                elif len(p_solved) == 0 and prereq_node.stage_id == 1 and distinct_solved == 0:
                    # Missing stage 1 foundation
                    missing_prereqs.append(prereq_node.display_name)

        prerequisites_met = (len(missing_prereqs) == 0)

        # ---------------------------------------------------------------------
        # Deterministic Mastery Scoring Formula:
        # Base Points:
        # - Solved problems volume: 30 pts (up to 3 solves * 10 pts)
        # - Difficulty tier bonus: 30 pts (Easy = 5 pts, Medium = 12 pts, Hard = 20 pts)
        # - Success rate component: 25 pts (success_rate% * 0.25)
        # - Consistency & practice volume: 15 pts (attempt presence & low failure ratio)
        # Total Max = 100.0
        # ---------------------------------------------------------------------
        solve_score = min(30.0, distinct_solved * 10.0)
        diff_score = min(30.0, (easy_solves * 5.0) + (medium_solves * 12.0) + (hard_solves * 20.0))
        rate_score = (success_rate / 100.0) * 25.0

        if total_attempts > 0:
            fail_ratio = failed_attempts / total_attempts
            consistency_score = max(0.0, 15.0 * (1.0 - fail_ratio))
        elif distinct_solved > 0:
            consistency_score = 15.0
        else:
            consistency_score = 0.0

        raw_score = solve_score + diff_score + rate_score + consistency_score
        mastery_score = round(min(100.0, max(0.0, raw_score)), 1)

        # Determine Topic Status
        if not prerequisites_met and distinct_solved == 0 and total_attempts == 0:
            status = TopicMasteryStatus.LOCKED
        elif distinct_solved == 0 and total_attempts == 0:
            status = TopicMasteryStatus.NOT_STARTED
        elif mastery_score >= 70.0 and distinct_solved >= node.recommended_min_solves:
            status = TopicMasteryStatus.PROFICIENT
        elif distinct_solved >= 1 or total_attempts >= 2:
            status = TopicMasteryStatus.PRACTICING if distinct_solved >= 2 else TopicMasteryStatus.LEARNING
        else:
            status = TopicMasteryStatus.LEARNING

        # Overdue revision indicator
        has_active_revision_due = (
            node.topic_id in revision_due_topics
            or node.display_name.lower().replace(" ", "-") in revision_due_topics
        )

        # Recommended Action & Score Explanation
        if status == TopicMasteryStatus.LOCKED:
            recommended_action = f"Complete prerequisites first: {', '.join(missing_prereqs)}"
            score_explanation = f"Locked topic. Unmet prerequisites: {', '.join(missing_prereqs)}. Current score: {mastery_score}/100."
        elif has_active_revision_due:
            recommended_action = "Spaced revision due: Review and solve a practice problem."
            score_explanation = f"Mastery score {mastery_score}/100 with scheduled spaced revision overdue."
        elif status == TopicMasteryStatus.NOT_STARTED:
            recommended_action = "Begin topic: Solve an introductory Easy problem."
            score_explanation = f"Ready to learn! Prerequisites are met, but no problems attempted yet (0/100)."
        elif status == TopicMasteryStatus.LEARNING:
            recommended_action = "Strengthen fundamentals: Solve 1-2 foundational Easy problems."
            score_explanation = f"Building initial grasp ({distinct_solved} solved, {total_attempts} attempts). Mastery score: {mastery_score}/100."
        elif status == TopicMasteryStatus.PRACTICING:
            recommended_action = "Deepen mastery: Practice Medium difficulty problems to solidify patterns."
            score_explanation = f"Solid foundation ({distinct_solved} solved, {easy_solves} easy, {medium_solves} med). Mastery score: {mastery_score}/100."
        else:  # PROFICIENT
            recommended_action = "Proficient: Ready to progress to dependent topics or Hard challenge problems."
            score_explanation = f"High proficiency achieved ({distinct_solved} solved, {success_rate}% success rate). Mastery score: {mastery_score}/100."

        return TopicMasteryRecord(
            topic_id=node.topic_id,
            display_name=node.display_name,
            stage_id=node.stage_id,
            stage_name=node.stage_name,
            mastery_score=mastery_score,
            confidence_level=confidence,
            status=status,
            distinct_solved=distinct_solved,
            total_problems_available=total_available,
            total_attempts=total_attempts,
            failed_attempts=failed_attempts,
            success_rate=success_rate,
            easy_solves=easy_solves,
            medium_solves=medium_solves,
            hard_solves=hard_solves,
            prerequisites=node.prerequisites,
            prerequisites_met=prerequisites_met,
            missing_prerequisites=missing_prereqs,
            has_active_revision_due=has_active_revision_due,
            recommended_action=recommended_action,
            score_explanation=score_explanation,
        )

    def get_stage_summaries(self) -> List[RoadmapStageSummary]:
        """Aggregate roadmap metrics across each stage."""
        stage_map: Dict[int, List[TopicMasteryRecord]] = {s_id: [] for s_id in ROADMAP_STAGES_CONFIG}
        for node in self.nodes:
            rec = self.compute_topic_mastery(node)
            stage_map[node.stage_id].append(rec)

        summaries: List[RoadmapStageSummary] = []
        for s_id, s_name in sorted(ROADMAP_STAGES_CONFIG.items()):
            recs = stage_map.get(s_id, [])
            tot = len(recs)
            comp = sum(1 for r in recs if r.status == TopicMasteryStatus.PROFICIENT)
            in_prog = sum(1 for r in recs if r.status in (TopicMasteryStatus.LEARNING, TopicMasteryStatus.PRACTICING))
            not_start = sum(1 for r in recs if r.status == TopicMasteryStatus.NOT_STARTED)
            locked = sum(1 for r in recs if r.status == TopicMasteryStatus.LOCKED)
            pct = round((comp / tot) * 100.0, 1) if tot > 0 else 0.0
            avg_mastery = round(sum(r.mastery_score for r in recs) / tot, 1) if tot > 0 else 0.0

            summaries.append(
                RoadmapStageSummary(
                    stage_id=s_id,
                    stage_name=s_name,
                    total_topics=tot,
                    completed_topics=comp,
                    in_progress_topics=in_prog,
                    not_started_topics=not_start,
                    locked_topics=locked,
                    stage_progress_pct=pct,
                    average_mastery_score=avg_mastery,
                    topics=recs,
                )
            )

        return summaries

    def get_topic_detail(self, topic_id: str) -> Optional[TopicMasteryRecord]:
        """Fetch detail and mastery computation for a specific topic."""
        clean_id = topic_id.strip().lower()
        node = next((n for n in self.nodes if n.topic_id == clean_id), None)
        if not node:
            return None
        return self.compute_topic_mastery(node)

    def generate_recommendations(self, limit: int = 5) -> List[RoadmapRecommendation]:
        """Generate evidence-backed learner-specific roadmap recommendations."""
        summaries = self.get_stage_summaries()
        all_recs: List[TopicMasteryRecord] = []
        for s in summaries:
            all_recs.extend(s.topics)

        all_problems = load_problems()
        solved_ids = self._get_solved_problem_ids()
        active_goal_topics = self._get_active_goals_by_topic()
        recommendations: List[RoadmapRecommendation] = []

        # 1. Overdue Spaced Revisions (Priority 1)
        for r in all_recs:
            if r.has_active_revision_due:
                node = next((n for n in self.nodes if n.topic_id == r.topic_id), None)
                cand_probs = [
                    p.get("id") for p in all_problems
                    if node and self._match_problem_to_node(p, node)
                ]
                recommendations.append(
                    RoadmapRecommendation(
                        recommendation_type=RoadmapRecommendationType.REVISE_OVERDUE_TOPIC,
                        topic_id=r.topic_id,
                        topic_name=r.display_name,
                        stage_id=r.stage_id,
                        stage_name=r.stage_name,
                        priority=1,
                        title=f"Spaced Revision Due: {r.display_name}",
                        rationale=f"Topic '{r.display_name}' has scheduled spaced revision due to reinforce long-term algorithmic recall.",
                        suggested_problems=cand_probs[:2],
                    )
                )

        # 2. Active Learning Goal Focus (Priority 2)
        for r in all_recs:
            if r.topic_id in active_goal_topics or r.display_name.lower().replace(" ", "-") in active_goal_topics:
                if r.status != TopicMasteryStatus.PROFICIENT:
                    node = next((n for n in self.nodes if n.topic_id == r.topic_id), None)
                    unsolved = [
                        p.get("id") for p in all_problems
                        if node and self._match_problem_to_node(p, node) and p.get("id") not in solved_ids
                    ]
                    recommendations.append(
                        RoadmapRecommendation(
                            recommendation_type=RoadmapRecommendationType.PRACTICE_WEAK_TOPIC,
                            topic_id=r.topic_id,
                            topic_name=r.display_name,
                            stage_id=r.stage_id,
                            stage_name=r.stage_name,
                            priority=2,
                            title=f"Learning Goal Focus: {r.display_name}",
                            rationale=f"You have an active personal goal targeting '{r.display_name}'. Practice problems to advance goal completion.",
                            suggested_problems=unsolved[:2],
                        )
                    )

        # 3. Strengthen Weak / High-Failure Topics (Priority 2)
        for r in all_recs:
            if r.status in (TopicMasteryStatus.LEARNING, TopicMasteryStatus.PRACTICING):
                if r.failed_attempts > 0 and r.success_rate < 60.0:
                    node = next((n for n in self.nodes if n.topic_id == r.topic_id), None)
                    unsolved_easy = [
                        p.get("id") for p in all_problems
                        if node and self._match_problem_to_node(p, node) and p.get("id") not in solved_ids
                    ]
                    recommendations.append(
                        RoadmapRecommendation(
                            recommendation_type=RoadmapRecommendationType.STRENGTHEN_FUNDAMENTALS,
                            topic_id=r.topic_id,
                            topic_name=r.display_name,
                            stage_id=r.stage_id,
                            stage_name=r.stage_name,
                            priority=2,
                            title=f"Strengthen Technique: {r.display_name}",
                            rationale=f"Topic '{r.display_name}' has a lower success rate ({r.success_rate}%) with {r.failed_attempts} failed attempt(s). Review core concepts.",
                            suggested_problems=unsolved_easy[:2],
                        )
                    )

        # 4. Ready-to-Learn Stage 1/Prerequisites Met Topics (Priority 3)
        for r in all_recs:
            if r.status == TopicMasteryStatus.NOT_STARTED and r.prerequisites_met:
                node = next((n for n in self.nodes if n.topic_id == r.topic_id), None)
                unsolved = [
                    p.get("id") for p in all_problems
                    if node and self._match_problem_to_node(p, node) and p.get("id") not in solved_ids
                ]
                recommendations.append(
                    RoadmapRecommendation(
                        recommendation_type=RoadmapRecommendationType.LEARN_NEW_TOPIC,
                        topic_id=r.topic_id,
                        topic_name=r.display_name,
                        stage_id=r.stage_id,
                        stage_name=r.stage_name,
                        priority=3,
                        title=f"Start Next Skill: {r.display_name}",
                        rationale=f"All prerequisites for '{r.display_name}' are satisfied. Ready to begin foundational problem solving.",
                        suggested_problems=unsolved[:2],
                    )
                )

        # 5. Progress to Harder Difficulty (Priority 4)
        for r in all_recs:
            if r.status == TopicMasteryStatus.PRACTICING and r.medium_solves == 0 and r.easy_solves >= 2:
                node = next((n for n in self.nodes if n.topic_id == r.topic_id), None)
                med_probs = [
                    p.get("id") for p in all_problems
                    if node and self._match_problem_to_node(p, node) and p.get("difficulty", "").lower() == "medium" and p.get("id") not in solved_ids
                ]
                recommendations.append(
                    RoadmapRecommendation(
                        recommendation_type=RoadmapRecommendationType.PROGRESS_DIFFICULTY,
                        topic_id=r.topic_id,
                        topic_name=r.display_name,
                        stage_id=r.stage_id,
                        stage_name=r.stage_name,
                        priority=4,
                        title=f"Step Up to Medium: {r.display_name}",
                        rationale=f"Strong grasp on Easy {r.display_name} problems ({r.easy_solves} solved). Advance to Medium problems to deepen pattern recognition.",
                        suggested_problems=med_probs[:2],
                    )
                )

        # De-duplicate by topic_id preserving highest priority
        seen_topics: Set[str] = set()
        deduped: List[RoadmapRecommendation] = []
        for rec in sorted(recommendations, key=lambda x: x.priority):
            if rec.topic_id not in seen_topics:
                seen_topics.add(rec.topic_id)
                deduped.append(rec)

        # Fallback if no specific condition triggered (e.g. fresh state or all proficient)
        if not deduped:
            first_not_started = next((r for r in all_recs if r.status == TopicMasteryStatus.NOT_STARTED), None)
            if first_not_started:
                deduped.append(
                    RoadmapRecommendation(
                        recommendation_type=RoadmapRecommendationType.LEARN_NEW_TOPIC,
                        topic_id=first_not_started.topic_id,
                        topic_name=first_not_started.display_name,
                        stage_id=first_not_started.stage_id,
                        stage_name=first_not_started.stage_name,
                        priority=3,
                        title=f"Begin Roadmap: {first_not_started.display_name}",
                        rationale="Start your DSA journey with foundational data structures.",
                        suggested_problems=["two-sum"],
                    )
                )

        return deduped[:limit]

    def get_roadmap_overview(self) -> RoadmapOverviewReport:
        """Compile complete roadmap analytics and progression report."""
        summaries = self.get_stage_summaries()
        all_topics: List[TopicMasteryRecord] = []
        for s in summaries:
            all_topics.extend(s.topics)

        total_topics = len(all_topics)
        proficient = sum(1 for t in all_topics if t.status == TopicMasteryStatus.PROFICIENT)
        learning = sum(1 for t in all_topics if t.status in (TopicMasteryStatus.LEARNING, TopicMasteryStatus.PRACTICING))
        not_started = sum(1 for t in all_topics if t.status == TopicMasteryStatus.NOT_STARTED)
        locked = sum(1 for t in all_topics if t.status == TopicMasteryStatus.LOCKED)

        overall_progress = round((proficient / total_topics) * 100.0, 1) if total_topics > 0 else 0.0

        # Strongest & Weakest topics
        scored_topics = [t for t in all_topics if t.distinct_solved > 0 or t.total_attempts > 0]
        scored_topics.sort(key=lambda x: x.mastery_score, reverse=True)

        strongest = [t.display_name for t in scored_topics[:3] if t.mastery_score >= 50.0]
        weakest = [t.display_name for t in sorted(scored_topics, key=lambda x: x.mastery_score)[:3] if t.mastery_score < 50.0]

        needing_revision = [t.display_name for t in all_topics if t.has_active_revision_due]
        ready_to_learn = [t.display_name for t in all_topics if t.status == TopicMasteryStatus.NOT_STARTED and t.prerequisites_met]
        blocked = [t.display_name for t in all_topics if t.status == TopicMasteryStatus.LOCKED]

        recommendations = self.generate_recommendations(limit=5)

        summary_parts = [
            f"Overall DSA Roadmap Progress: {overall_progress}% ({proficient}/{total_topics} topics proficient).",
            f"{learning} topic(s) currently being practiced.",
            f"{ready_to_learn[0] if ready_to_learn else 'None'} ready to learn next.",
        ]

        return RoadmapOverviewReport(
            total_stages=len(ROADMAP_STAGES_CONFIG),
            total_topics=total_topics,
            proficient_topics_count=proficient,
            learning_topics_count=learning,
            not_started_topics_count=not_started,
            locked_topics_count=locked,
            overall_roadmap_progress_pct=overall_progress,
            strongest_topics=strongest,
            weakest_topics=weakest,
            topics_needing_revision=needing_revision,
            ready_to_learn_topics=ready_to_learn,
            blocked_topics=blocked,
            stages=summaries,
            recommendations=recommendations,
            summary=" ".join(summary_parts),
        )
