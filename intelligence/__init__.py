"""Intelligence and problem selection package for LeetCode Agent."""

from intelligence.adaptive import (
    AdaptiveLearningEngine,
    AdaptiveLearningReport,
    AdaptiveSessionSizing,
    NextActionRecommendation,
    RecommendedActionType,
)
from intelligence.coach import (
    CoachOverview,
    CURATED_PROBLEM_HINTS,
    HintTier,
    OfflineCodingCoach,
    PersonalizedCoachInsight,
    ProblemCoachingGuide,
    ProgressiveHint,
)
from intelligence.insights import (
    DailyActivityMetric,
    LearningInsightsEngine,
    LearningInsightsReport,
    TopicImprovementMetric,
)
from intelligence.planner import (
    LearningSessionPlan,
    PlannedProblem,
    SessionPlanner,
    SessionProblemRole,
)
from intelligence.selector import ProblemScoreBreakdown, ProblemSelector
from intelligence.topics import (
    CURATED_PROBLEM_TOPICS,
    STANDARD_TOPICS,
    TopicAnalyzer,
    TopicPerformanceMetric,
    get_problem_topics,
)
from intelligence.tracker import (
    DEFAULT_TRACKING_DB_PATH,
    ProblemProgressStatus,
    SessionStatus,
    SessionTracker,
    TrackedProblemItem,
    TrackedSessionRecord,
    TrackingAnalytics,
)

__all__ = [
    "ProblemSelector",
    "ProblemScoreBreakdown",
    "TopicAnalyzer",
    "TopicPerformanceMetric",
    "get_problem_topics",
    "STANDARD_TOPICS",
    "CURATED_PROBLEM_TOPICS",
    "PlannedProblem",
    "LearningSessionPlan",
    "SessionProblemRole",
    "SessionPlanner",
    "SessionTracker",
    "SessionStatus",
    "ProblemProgressStatus",
    "TrackedProblemItem",
    "TrackedSessionRecord",
    "TrackingAnalytics",
    "DEFAULT_TRACKING_DB_PATH",
    "AdaptiveLearningEngine",
    "AdaptiveLearningReport",
    "AdaptiveSessionSizing",
    "NextActionRecommendation",
    "RecommendedActionType",
    "LearningInsightsEngine",
    "LearningInsightsReport",
    "TopicImprovementMetric",
    "DailyActivityMetric",
    "OfflineCodingCoach",
    "HintTier",
    "ProblemCoachingGuide",
    "ProgressiveHint",
    "PersonalizedCoachInsight",
    "CoachOverview",
    "CURATED_PROBLEM_HINTS",
]
