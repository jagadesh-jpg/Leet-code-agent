"""Offline Intelligent Coding Coach Engine.

Milestone 6.3.11: Offline Intelligent Coding Coach.
Provides personalized pedagogical coaching, structured problem-solving walkthroughs,
and progressive hints without Gemini, OpenAI, or external API dependencies.

100% offline, local-first, deterministic, and safe (never emits raw solutions).
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from intelligence.adaptive import AdaptiveLearningEngine
from intelligence.insights import LearningInsightsEngine
from intelligence.planner import SessionPlanner
from intelligence.selector import ProblemSelector
from intelligence.topics import TopicAnalyzer, get_problem_topics
from intelligence.tracker import SessionStatus, SessionTracker
from problems import load_problems
import store


class HintTier(int, Enum):
    """Progressive hint levels that guide without revealing full solutions."""
    CONCEPTUAL = 1      # Conceptual insight and problem re-framing
    DATA_STRUCTURE = 2  # Relevant data structures and algorithmic patterns
    ALGORITHMIC = 3     # Step-by-step logic and invariant considerations
    PSEUDOCODE = 4      # High-level pseudocode structure (strictly non-executable)


@dataclass
class ProblemCoachingGuide:
    """Comprehensive 8-point problem-solving framework for independent implementation."""
    problem_id: str
    title: str
    difficulty: str
    topics: List[str]
    understanding: str
    inputs_and_outputs: str
    constraints: str
    relevant_patterns: List[str]
    step_by_step_approach: List[str]
    complexity_considerations: str
    test_recommendations: List[str]
    encouragement: str


@dataclass
class ProgressiveHint:
    """A single tier hint in the progressive sequence."""
    tier: int
    tier_name: str
    content: str
    has_more: bool


@dataclass
class PersonalizedCoachInsight:
    """Personalized learning observation based on verified historical evidence."""
    category: str       # "weak_topic", "retry_candidate", "fatigue", "progression", "review"
    headline: str
    advice: str
    evidence: str
    suggested_action: str


@dataclass
class CoachOverview:
    """Overall coaching summary, recommended problem, and learning observations."""
    overview_summary: str
    recommended_problem: Optional[Dict[str, Any]]
    personalized_insights: List[PersonalizedCoachInsight]
    recommended_session_size: int
    readiness_assessment: str


# Deterministic curated hint database mapping problem IDs to 4-tier progressive hints
CURATED_PROBLEM_HINTS: Dict[str, Dict[int, str]] = {
    "two-sum": {
        1: "Think about the complement: for each number x, what exact value (target - x) must exist elsewhere in the array?",
        2: "A Hash Map allows O(1) average-time lookups. As you iterate through the array, can you store each number and its index?",
        3: "In a single pass: check if (target - num) is already in your hash map. If yes, you found the pair. If not, record num: index.",
        4: "Pseudocode:\nlookup = {}\nfor index, num in enumerate(nums):\n    diff = target - num\n    if diff in lookup:\n        return [lookup[diff], index]\n    lookup[num] = index",
    },
    "valid-parentheses": {
        1: "Notice the Last-In, First-Out (LIFO) property: the most recently opened bracket must be the first one to be closed.",
        2: "A Stack data structure is ideal for tracking open brackets. A dictionary mapping closing brackets to opening brackets clarifies matching.",
        3: "Iterate through characters: if opening bracket, push to stack. If closing bracket, check if stack is non-empty and top matches; then pop. At the end, stack must be empty.",
        4: "Pseudocode:\nstack = []\nmapping = {')': '(', '}': '{', ']': '['}\nfor ch in s:\n    if ch in mapping:\n        top = stack.pop() if stack else '#'\n        if top != mapping[ch]: return False\n    else: stack.append(ch)\nreturn len(stack) == 0",
    },
    "contains-duplicate": {
        1: "You only need to know if any element appears more than once, not how many times or where.",
        2: "A Hash Set stores unique items and provides O(1) membership checks, or sorting the array groups identical items adjacently in O(N log N).",
        3: "Iterate through elements: if element is already present in your seen set, return true immediately. Otherwise add it.",
        4: "Pseudocode:\nseen = set()\nfor num in nums:\n    if num in seen:\n        return True\n    seen.add(num)\nreturn False",
    },
    "maximum-subarray": {
        1: "If the running sum becomes negative, does carrying it forward help maximize future subarrays?",
        2: "Kadane's Algorithm (Dynamic Programming). At each index, decide whether to extend the existing subarray or start fresh from the current element.",
        3: "Maintain current_sum and max_sum. Update current_sum = max(num, current_sum + num), and max_sum = max(max_sum, current_sum).",
        4: "Pseudocode:\nmax_sum = current_sum = nums[0]\nfor num in nums[1:]:\n    current_sum = max(num, current_sum + num)\n    max_sum = max(max_sum, current_sum)\nreturn max_sum",
    },
    "reverse-linked-list": {
        1: "Each node's pointer currently points forward. To reverse the list, each node must point backwards to its predecessor.",
        2: "Iterative pointer manipulation using three pointers: prev, curr, and next_node.",
        3: "Before changing curr.next, save next_node = curr.next. Then set curr.next = prev. Advance prev = curr and curr = next_node.",
        4: "Pseudocode:\nprev = None\ncurr = head\nwhile curr is not None:\n    nxt = curr.next\n    curr.next = prev\n    prev = curr\n    curr = nxt\nreturn prev",
    },
    "merge-two-sorted-lists": {
        1: "Both input lists are already sorted. Which node must come first in the combined list?",
        2: "Use a dummy head node to simplify edge cases, along with a pointer tracking the tail of the merged list.",
        3: "Compare the values at list1 and list2. Attach the smaller node to tail.next and advance that list's pointer. When one list empties, attach the remainder of the other.",
        4: "Pseudocode:\ndummy = ListNode(0)\ntail = dummy\nwhile l1 and l2:\n    if l1.val <= l2.val:\n        tail.next = l1; l1 = l1.next\n    else:\n        tail.next = l2; l2 = l2.next\n    tail = tail.next\ntail.next = l1 or l2\nreturn dummy.next",
    },
    "longest-substring-without-repeating-characters": {
        1: "As you scan through the string, how can you maintain a window of unique characters without starting from scratch after each duplicate?",
        2: "The Sliding Window technique combined with a Hash Map storing the last seen index of each character.",
        3: "Move the right pointer. If char was seen within the current window (index >= left), jump left pointer to seen[char] + 1. Update max_length = max(max_length, right - left + 1).",
        4: "Pseudocode:\nseen = {}\nleft = max_len = 0\nfor right, ch in enumerate(s):\n    if ch in seen and seen[ch] >= left:\n        left = seen[ch] + 1\n    seen[ch] = right\n    max_len = max(max_len, right - left + 1)\nreturn max_len",
    },
    "climbing-stairs": {
        1: "To reach step n, you must have come from either step (n - 1) with a 1-step jump or step (n - 2) with a 2-step jump.",
        2: "Dynamic Programming or Fibonacci sequence recurrence: ways(n) = ways(n - 1) + ways(n - 2).",
        3: "Notice that you only need the previous two values, so you can solve this in O(N) time and O(1) space using two variables.",
        4: "Pseudocode:\nif n <= 2: return n\none_back = 2\ntwo_back = 1\nfor i in range(3, n + 1):\n    current = one_back + two_back\n    two_back = one_back\n    one_back = current\nreturn one_back",
    },
    "best-time-to-buy-and-sell-stock": {
        1: "You must buy before you can sell. For any given selling day, what buying day yields the maximum profit?",
        2: "Single-pass greedy tracking of the minimum price encountered so far.",
        3: "Track min_price and max_profit. For each price: min_price = min(min_price, price) and max_profit = max(max_profit, price - min_price).",
        4: "Pseudocode:\nmin_price = float('inf')\nmax_profit = 0\nfor p in prices:\n    if p < min_price: min_price = p\n    elif p - min_price > max_profit: max_profit = p - min_price\nreturn max_profit",
    },
    "binary-search": {
        1: "The array is sorted in ascending order. Comparing the target with the middle element immediately eliminates half the search space.",
        2: "Two Pointers representing the search boundaries: left and right.",
        3: "Calculate mid = left + (right - left) // 2. If nums[mid] == target, return mid. If nums[mid] < target, left = mid + 1. Otherwise right = mid - 1.",
        4: "Pseudocode:\nleft, right = 0, len(nums) - 1\nwhile left <= right:\n    mid = (left + right) // 2\n    if nums[mid] == target: return mid\n    elif nums[mid] < target: left = mid + 1\n    else: right = mid - 1\nreturn -1",
    },
}


class OfflineCodingCoach:
    """Offline, deterministic pedagogical coach guiding independent problem-solving."""

    def __init__(
        self,
        progress_db_path: Optional[str | Path] = None,
        tracking_db_path: Optional[str | Path] = None,
        language: str = "python",
    ):
        self.progress_db_path = progress_db_path
        self.tracking_db_path = tracking_db_path
        self.language = (language or "python").strip().lower()

        self.selector = ProblemSelector(db_path=self.progress_db_path, language=self.language)
        self.topic_analyzer = TopicAnalyzer(db_path=self.progress_db_path, language=self.language)
        self.adaptive_engine = AdaptiveLearningEngine(
            progress_db_path=self.progress_db_path,
            tracking_db_path=self.tracking_db_path,
            language=self.language,
        )
        self.insights_engine = LearningInsightsEngine(
            progress_db_path=self.progress_db_path,
            tracking_db_path=self.tracking_db_path,
            language=self.language,
        )
        self.tracker = SessionTracker(db_path=self.tracking_db_path)

    def get_coach_overview(self) -> CoachOverview:
        """Synthesize overall coaching advice, recommended next challenge, and observations."""
        all_problems = load_problems()
        insights_rep = self.insights_engine.generate_report()
        adaptive_rep = self.adaptive_engine.analyze_and_recommend(candidate_problems=all_problems)

        # 1. Select the top recommended problem
        ranked = self.selector.prioritize_candidates(all_problems, skip_solved=True)
        recommended_prob = None
        if ranked:
            p_obj, p_bd = ranked[0]
            recommended_prob = {
                "id": p_obj["id"],
                "title": p_obj["title"],
                "difficulty": p_obj["difficulty"],
                "topics": p_bd.all_topics or get_problem_topics(p_obj),
                "priority_score": p_bd.total_score,
                "rationale": p_bd.rationale,
            }

        # 2. Derive Evidence-Based Personalized Observations
        observations: List[PersonalizedCoachInsight] = []

        # Observation A: Weak Topic Reinforcement
        if insights_rep.topics_needing_practice:
            weak_t = insights_rep.topics_needing_practice[0]
            observations.append(
                PersonalizedCoachInsight(
                    category="weak_topic",
                    headline=f"Focus Area: {weak_t}",
                    advice=f"Your practice history shows recent friction in {weak_t}. Before writing code, outline the invariant rules and boundary conditions.",
                    evidence=f"Flagged as 'needs_practice' with logged failed attempts.",
                    suggested_action=f"Practice 1-2 Easy/Medium problems tagged with {weak_t}.",
                )
            )

        # Observation B: Session Completion Fatigue Check
        if adaptive_rep.session_sizing and adaptive_rep.session_sizing.has_sufficient_evidence:
            if adaptive_rep.session_sizing.recommended_size < adaptive_rep.session_sizing.default_size:
                observations.append(
                    PersonalizedCoachInsight(
                        category="fatigue",
                        headline="Pacing Adjustment: Lighten Session Load",
                        advice="Recent sessions were cancelled or left incomplete. Focus on completing 1 or 2 high-quality problems per sitting to rebuild consistency.",
                        evidence=adaptive_rep.session_sizing.rationale,
                        suggested_action=f"Set session size to {adaptive_rep.session_sizing.recommended_size} problem(s).",
                    )
                )

        # Observation C: Progression Confidence
        if insights_rep.strongest_topics and not insights_rep.topics_needing_practice:
            strong_str = ", ".join(insights_rep.strongest_topics[:2])
            observations.append(
                PersonalizedCoachInsight(
                    category="progression",
                    headline="Strong Foundations: Ready to Step Up",
                    advice=f"You demonstrate steady proficiency in {strong_str}. Consider tackling Medium or Challenge-tier problems to push your algorithmic boundaries.",
                    evidence=f"{len(insights_rep.strongest_topics)} topic(s) mastered/proficient.",
                    suggested_action="Step up difficulty progression.",
                )
            )

        # Observation D: Baseline Fallback if zero history
        if not observations:
            observations.append(
                PersonalizedCoachInsight(
                    category="review",
                    headline="Welcome: Building Your Problem-Solving Foundation",
                    advice="Begin with an Easy problem. Focus on breaking down the inputs, identifying edge cases, and verifying complexity before coding.",
                    evidence="Initial baseline state with clean history.",
                    suggested_action="Select a warm-up problem and inspect the coaching walkthrough.",
                )
            )

        # 3. Overall Readiness Assessment
        if insights_rep.total_problems_solved >= 5 and not insights_rep.topics_needing_practice:
            readiness = "Advanced Practice: Strong mastery across core DSA patterns."
        elif insights_rep.total_problems_solved > 0:
            readiness = "Steady Development: Solid progress with opportunities for targeted drills."
        else:
            readiness = "Baseline Assessment: Establish an initial rhythm with warm-up problems."

        summary_text = (
            f"Coach ready with {len(all_problems)} candidate problems. "
            f"Primary focus: {adaptive_rep.primary_recommendation.title}."
        )

        return CoachOverview(
            overview_summary=summary_text,
            recommended_problem=recommended_prob,
            personalized_insights=observations,
            recommended_session_size=adaptive_rep.session_sizing.recommended_size if adaptive_rep.session_sizing else 3,
            readiness_assessment=readiness,
        )

    def get_problem_guidance(self, problem_id: str) -> Optional[ProblemCoachingGuide]:
        """Generate structured 8-point pedagogical guide for a problem without revealing solutions."""
        all_problems = load_problems()
        p = next((prob for prob in all_problems if prob["id"] == problem_id), None)
        if not p:
            # Check custom problems
            cp = store.get_custom_problem(problem_id, db_path=self.progress_db_path)
            if cp:
                p = cp
            else:
                return None

        title = p.get("title", problem_id)
        diff = p.get("difficulty", "medium").title()
        topics = get_problem_topics(p) or ["Standard Algorithms"]

        # Derive 8 structured coaching points
        understanding = (
            f"Carefully read the problem statement for '{title}'. "
            "Restate the requirement in your own words: what transformation or search is requested?"
        )
        inputs_and_outputs = (
            f"Signature: {p.get('signature', 'N/A')}. "
            "Identify the exact types: are inputs primitive, array collections, or pointer structures?"
        )
        constraints = (
            "Analyze scale: What is the maximum input size N? "
            "If N <= 10^4, aim for O(N) or O(N log N). If N <= 100, O(N^2) may be acceptable."
        )
        relevant_patterns = topics

        # Step by step guidance
        step_by_step = [
            "1. Clarify the brute force: What is the most straightforward O(N^2) or exhaustive way to solve this?",
            "2. Identify bottlenecks: Are you repeatedly searching? (Use Hash Map/Set). Is the array sorted? (Use Two Pointers/Binary Search).",
            "3. Formulate the core loop and state variables before touching syntax.",
            "4. Trace with a minimal test input on paper or scratchpad.",
        ]

        complexity = (
            "Time Complexity target: O(N) linear time for standard array/hash problems; O(N log N) if sorting. "
            "Space Complexity: aim for O(1) auxiliary space or O(N) if caching states."
        )

        test_recs = [
            "Empty or single-element inputs.",
            "Inputs with duplicate values.",
            "Worst-case boundary extremes (maximum/minimum values).",
        ]

        encouragement = "Take your time to implement this independently. Use progressive hints only if you reach an impasse!"

        return ProblemCoachingGuide(
            problem_id=problem_id,
            title=title,
            difficulty=diff,
            topics=topics,
            understanding=understanding,
            inputs_and_outputs=inputs_and_outputs,
            constraints=constraints,
            relevant_patterns=relevant_patterns,
            step_by_step_approach=step_by_step,
            complexity_considerations=complexity,
            test_recommendations=test_recs,
            encouragement=encouragement,
        )

    def get_progressive_hint(self, problem_id: str, tier: int = 1) -> Optional[ProgressiveHint]:
        """Fetch a specific progressive hint tier (1 to 4) for a problem."""
        if tier < 1 or tier > 4:
            return None

        tier_names = {
            1: "Conceptual Direction",
            2: "Data Structure & Pattern",
            3: "Algorithmic Invariant",
            4: "Pseudocode Logic",
        }

        # Check curated hint mapping
        if problem_id in CURATED_PROBLEM_HINTS:
            content = CURATED_PROBLEM_HINTS[problem_id].get(tier)
            if content:
                return ProgressiveHint(
                    tier=tier,
                    tier_name=tier_names[tier],
                    content=content,
                    has_more=tier < 4,
                )

        # Fallback heuristic hint progression for custom or non-curated problems
        all_problems = load_problems()
        p = next((prob for prob in all_problems if prob["id"] == problem_id), None)
        if not p:
            cp = store.get_custom_problem(problem_id, db_path=self.progress_db_path)
            if cp:
                p = cp
            else:
                return None

        topics = get_problem_topics(p) or ["General Algorithms"]
        topic_str = ", ".join(topics)

        fallback_hints = {
            1: f"Consider the core problem type: this problem relates to [{topic_str}]. What invariant can simplify your search?",
            2: f"Evaluate if a Hash Map or Two Pointers can reduce lookups from O(N^2) to O(N).",
            3: "Break the problem down into two phases: state initialization and iterative update based on constraints.",
            4: "High-level structure:\nInitialize trackers -> Iterate through input elements -> Check condition and update result -> Return final computed value.",
        }

        return ProgressiveHint(
            tier=tier,
            tier_name=tier_names[tier],
            content=fallback_hints.get(tier, "No further hints available."),
            has_more=tier < 4,
        )
