"""Local Unified Learning Dashboard & Interactive Command Center Web Server.

Milestone 6.3.9: Interactive Learning Command Center.
Provides an interactive, local-first web interface to:
- Preview personalized learning sessions with customizable size and difficulty.
- Save preview sessions directly to the isolated tracking database.
- Inspect and monitor active session progress.
- Start sessions, mark problems completed/skipped, complete, or cancel sessions.
- Automatically refresh dashboard analytics and progress visualization.

100% offline, local-only (binds exclusively to 127.0.0.1), and safe (zero external APIs).
"""

from pathlib import Path
import re
from typing import Any, Dict, Optional

from flask import Flask, Response, jsonify, render_template_string, request, send_file

from dashboard import get_dashboard_data, _get_learning_intelligence_data
from intelligence.adaptive import AdaptiveLearningEngine
from intelligence.coach import OfflineCodingCoach
from intelligence.daily_mission import (
    DailyMission,
    DailyMissionAnalytics,
    DailyMissionManager,
    DailyMissionTask,
    MissionStatus,
    MissionSummaryReport,
    MissionTaskStatus,
    MissionTaskType,
)
from intelligence.goals import (
    GoalPlanRecommendation,
    GoalStatus,
    GoalType,
    GoalsAnalyticsReport,
    GoalsManager,
    LearningGoal,
    MilestoneAchievement,
)
from intelligence.insights import LearningInsightsEngine
from intelligence.interview_analytics import (
    InterviewAnalyticsGoal,
    InterviewAnalyticsManager,
    InterviewAnalyticsOverview,
)
from intelligence.mock_interview import (
    AssessmentReport,
    InterviewManager,
    InterviewStatus,
    InterviewTrack,
    MockInterviewSession,
)
from intelligence.coding_behavior import (
    BehaviorAnalysisReport,
    BehaviorCategory,
    BehaviorEvidence,
    CodingBehaviorAnalyzer,
    CodingBehaviorInsight,
    CodingBehaviorPattern,
    CodingBehaviorProfile,
    InsightSeverity,
)
from intelligence.skill_gap import (
    PrioritizedFocusItem,
    SkillEvidence,
    SkillGap,
    SkillGapAnalyzer,
    SkillGapConfidence,
    SkillGapPriority,
    SkillGapReport,
    SkillGapType,
)
from intelligence.learning_loop import (
    AdaptiveLearningLoop,
    LearningLoopAction,
    LearningLoopChangeProposal,
    LearningLoopEvidence,
    LearningLoopPhase,
    LearningLoopRecommendation,
    LearningLoopReport,
    LearningLoopSnapshot,
    ProposalActionType,
    ProposalStatus,
)
from intelligence.daily_practice import (
    DailyPracticeEvidence,
    DailyPracticeOrchestrator,
    DailyPracticeProgress,
    DailyPracticeReport,
    DailyPracticeSchedule,
    DailyPracticeSession,
    DailyPracticeSessionStatus,
    DailyPracticeTask,
    DailyPracticeTaskStatus,
    DailyPracticeTaskType,
)
from intelligence.command_center import (
    CommandCenterManager,
    CommandCenterOverview,
    PrimaryAction,
    PrimaryActionType,
)
from intelligence.planner import SessionPlanner
from intelligence.portfolio import (
    DEFAULT_PORTFOLIO_EXPORTS_DIR,
    PortfolioConfig,
    PortfolioManager,
)
from intelligence.practice_session import (
    PracticeSession,
    PracticeSessionEvent,
    PracticeSessionManager,
    PracticeSessionNotes,
    PracticeSessionStatus,
    SessionSummary,
)
from intelligence.preparation_planner import (
    IntensityLevel,
    PlanProgress,
    PlanStatus,
    PlannerSettings,
    PreparationDay,
    PreparationPlan,
    PreparationPlanner,
    PreparationTask,
    PreparationWeek,
    TaskPriority,
    TaskStatus,
    TaskType,
)
from intelligence.revision import (
    RevisionOutcome,
    RevisionStatus,
    SpacedRevisionEngine,
)
from intelligence.roadmap import (
    DsaRoadmapEngine,
    ROADMAP_STAGES_CONFIG,
    RoadmapOverviewReport,
    RoadmapStageSummary,
    TopicMasteryRecord,
    TopicMasteryStatus,
)
from intelligence.solution_review import (
    AttemptComparison,
    CodeQualityMetrics,
    ComplexityReview,
    ProblemSolvingChecklist,
    SolutionReviewEngine,
    SolutionReviewReport,
    normalize_complexity_str,
)
from intelligence.tracker import (
    DEFAULT_TRACKING_DB_PATH,
    ProblemProgressStatus,
    SessionStatus,
    SessionTracker,
)
from intelligence.workspace import (
    ProblemWorkspaceContext,
    WorkspaceDraft,
    WorkspaceManager,
    WorkspaceRunResult,
)
from problems import load_problems
import store

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LeetCode Agent - Interactive Command Center</title>
    <style>
        :root {
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-hover: #334155;
            --surface-accent: #0f2744;
            --primary: #38bdf8;
            --primary-dark: #0284c7;
            --accent: #a855f7;
            --success: #22c55e;
            --success-dark: #15803d;
            --warning: #eab308;
            --danger: #ef4444;
            --danger-dark: #b91c1c;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --border: #334155;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
            padding: 24px;
        }
        .container { max-width: 1240px; margin: 0 auto; }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 24px;
        }
        .title-group h1 { font-size: 1.8rem; font-weight: 700; color: var(--primary); }
        .title-group p { color: var(--text-muted); font-size: 0.9rem; }
        .badge-offline {
            background: #14532d;
            color: #86efac;
            padding: 6px 14px;
            border-radius: 9999px;
            font-size: 0.8rem;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .alert-banner {
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 0.9rem;
            margin-bottom: 20px;
            display: none;
        }
        .alert-success { background: #064e3b; color: #a7f3d0; border: 1px solid #059669; }
        .alert-error { background: #7f1d1d; color: #fecaca; border: 1px solid #dc2626; }

        .grid-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .stat-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
        }
        .stat-card .label { color: var(--text-muted); font-size: 0.85rem; font-weight: 500; }
        .stat-card .value { font-size: 2rem; font-weight: 700; margin-top: 4px; color: var(--text); }
        .stat-card .subtext { font-size: 0.8rem; color: var(--primary); margin-top: 4px; }

        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .card-header h2 { font-size: 1.25rem; font-weight: 600; }

        /* Interactive controls & forms */
        .controls-bar {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            align-items: center;
            margin-bottom: 16px;
            background: rgba(15, 23, 42, 0.6);
            padding: 12px 16px;
            border-radius: 8px;
            border: 1px solid var(--border);
        }
        .controls-bar label { font-size: 0.85rem; color: var(--text-muted); font-weight: 600; }
        .controls-bar select, .controls-bar input {
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.85rem;
        }
        button, .btn {
            background: var(--primary-dark);
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            text-decoration: none;
        }
        button:hover, .btn:hover { background: var(--primary); color: #0f172a; }
        .btn-success { background: var(--success-dark); }
        .btn-success:hover { background: var(--success); color: #0f172a; }
        .btn-danger { background: var(--danger-dark); }
        .btn-danger:hover { background: var(--danger); color: #fff; }
        .btn-secondary { background: var(--surface-hover); color: var(--text); }
        .btn-secondary:hover { background: var(--border); color: #fff; }
        .btn-sm { padding: 4px 10px; font-size: 0.75rem; border-radius: 4px; }

        .rec-box {
            background: #022c22;
            border: 1px solid #065f46;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
        }
        .rec-box .action-title { font-size: 1.1rem; font-weight: 600; color: #a7f3d0; }
        .rec-box .action-desc { color: #d1fae5; font-size: 0.9rem; margin-top: 4px; }
        .evidence-tag {
            display: inline-block;
            background: rgba(167, 243, 208, 0.15);
            color: #a7f3d0;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            margin-top: 8px;
            margin-right: 6px;
        }

        table { width: 100%; border-collapse: collapse; text-align: left; }
        th, td { padding: 12px 14px; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
        th { color: var(--text-muted); font-weight: 600; }
        tr:hover { background: var(--surface-hover); }
        .status-badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .badge-mastered { background: #1e3a8a; color: #93c5fd; }
        .badge-proficient { background: #064e3b; color: #6ee7b7; }
        .badge-needs_practice { background: #7c2d12; color: #fdba74; }
        .badge-no_history { background: #374151; color: #9ca3af; }
        .badge-planned { background: #374151; color: #9ca3af; }
        .badge-in_progress { background: #1e3a8a; color: #93c5fd; }
        .badge-completed { background: #064e3b; color: #6ee7b7; }
        .badge-cancelled { background: #7c2d12; color: #fdba74; }
        .badge-pending { background: #334155; color: #94a3b8; }
        .badge-skipped { background: #475569; color: #cbd5e1; }
        .badge-easy { color: #86efac; font-weight: 600; }
        .badge-medium { color: #fde047; font-weight: 600; }
        .badge-hard { color: #fca5a5; font-weight: 600; }

        .progress-bar-container {
            width: 100%;
            height: 8px;
            background: #334155;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 6px;
        }
        .progress-bar-fill {
            height: 100%;
            background: var(--success);
            transition: width 0.3s ease;
        }

        /* Modal dialog for session inspect */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0; top: 0; width: 100%; height: 100%;
            background: rgba(0, 0, 0, 0.75);
            align-items: center;
            justify-content: center;
        }
        .modal-content {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            width: 90%;
            max-width: 850px;
            padding: 24px;
            max-height: 85vh;
            overflow-y: auto;
        }
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 12px;
        }
        .modal-close {
            background: transparent;
            color: var(--text-muted);
            font-size: 1.4rem;
            cursor: pointer;
            padding: 0 6px;
        }
        .modal-close:hover { color: #fff; background: transparent; }
        footer {
            text-align: center;
            color: var(--text-muted);
            font-size: 0.8rem;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid var(--border);
        }

        /* Milestone 6.3.27: Unified Learning Command Center Navigation & UX */
        .command-nav {
            display: flex;
            gap: 6px;
            overflow-x: auto;
            padding: 10px 0;
            margin-bottom: 20px;
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            background: rgba(15, 23, 42, 0.95);
            z-index: 100;
            backdrop-filter: blur(8px);
        }
        .nav-tab {
            background: rgba(30, 41, 59, 0.6);
            color: var(--text-muted);
            border: 1px solid var(--border);
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            white-space: nowrap;
            transition: all 0.2s ease;
        }
        .nav-tab:hover {
            color: #fff;
            background: rgba(51, 65, 85, 0.8);
            border-color: rgba(148, 163, 184, 0.3);
        }
        .nav-tab.active {
            background: var(--primary);
            color: #fff;
            border-color: var(--primary);
            box-shadow: 0 0 12px rgba(59, 130, 246, 0.35);
        }
        .nav-badge {
            background: #ef4444;
            color: #fff;
            border-radius: 10px;
            padding: 1px 6px;
            font-size: 0.7rem;
            font-weight: 700;
        }
        .tab-content-pane {
            animation: fadeIn 0.2s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: translateY(0); }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="title-group">
                <h1>Autonomous LeetCode Agent</h1>
                <p>Unified Command Center & Learning Intelligence Dashboard</p>
            </div>
            <div class="badge-offline">
                <span>●</span> Local-First / Zero External APIs / 127.0.0.1
            </div>
        </header>

        <div id="alertBanner" class="alert-banner"></div>

        <!-- Navigation Bar (Milestone 6.3.27) -->
        <nav class="command-nav">
            <button class="nav-tab active" data-tab="overview" onclick="switchTab('overview')">
                <span>🌟</span> Overview
            </button>
            <button class="nav-tab" data-tab="daily-practice" onclick="switchTab('daily-practice')">
                <span>📅</span> Today's Learning
            </button>
            <button class="nav-tab" data-tab="skills" onclick="switchTab('skills')">
                <span>🎯</span> My Skill Focus
            </button>
            <button class="nav-tab" data-tab="adaptive-learning" onclick="switchTab('adaptive-learning')">
                <span>🔄</span> Adaptive Learning <span id="tabLoopBadge" class="nav-badge" style="display: none;">0</span>
            </button>
            <button class="nav-tab" data-tab="learning-plan" onclick="switchTab('learning-plan')">
                <span>🗓️</span> Learning Plan
            </button>
            <button class="nav-tab" data-tab="coding-performance" onclick="switchTab('coding-performance')">
                <span>📊</span> Coding Analytics
            </button>
            <button class="nav-tab" data-tab="interviews" onclick="switchTab('interviews')">
                <span>💼</span> Mock Interviews
            </button>
            <button class="nav-tab" data-tab="revision" onclick="switchTab('revision')">
                <span>🔁</span> Revision <span id="tabRevBadge" class="nav-badge" style="display: none;">0</span>
            </button>
            <button class="nav-tab" data-tab="reports" onclick="switchTab('reports')">
                <span>📑</span> Reports & Goals
            </button>
            <button class="nav-tab" data-tab="all" onclick="switchTab('all')" style="margin-left: auto;">
                <span>🗂️</span> All Sections
            </button>
        </nav>

        <!-- Section: Overview (Command Center Hub) -->
        <div class="tab-content-pane" id="pane-overview" data-tab="overview">
            <!-- Unified Action Flow Hero Banner (Milestone 6.3.27) -->
            <div id="unifiedActionBanner" class="card" style="border: 2px solid #3b82f6; background: linear-gradient(135deg, rgba(30, 58, 138, 0.35) 0%, rgba(15, 23, 42, 0.85) 100%); margin-bottom: 20px; padding: 18px 22px;">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px;">
                    <div style="display: flex; align-items: center; gap: 14px; flex: 1; min-width: 280px;">
                        <div id="uafIcon" style="font-size: 2.2rem; line-height: 1; background: rgba(59, 130, 246, 0.2); padding: 10px; border-radius: 10px; border: 1px solid rgba(59, 130, 246, 0.4);">🎯</div>
                        <div>
                            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                                <span style="font-size: 0.75rem; font-weight: 700; color: #93c5fd; text-transform: uppercase; letter-spacing: 0.05em;">Recommended Next Action</span>
                                <span id="uafPriorityBadge" class="badge" style="background: rgba(239, 68, 68, 0.2); color: #fca5a5; font-size: 0.7rem; font-weight: 700;">P0 IMMEDIATE</span>
                            </div>
                            <h2 id="uafTitle" style="margin: 0 0 4px 0; font-size: 1.25rem; color: #fff; font-weight: 700;">Loading action flow...</h2>
                            <p id="uafDescription" style="margin: 0; font-size: 0.85rem; color: #cbd5e1;">Evaluating evidence across local sessions, skill gaps, and revision items...</p>
                            <div id="uafEvidence" style="margin-top: 6px; font-size: 0.75rem; color: #94a3b8; font-style: italic;"></div>
                        </div>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <button id="uafCtaBtn" class="btn btn-primary" onclick="executePrimaryAction()" style="font-size: 0.9rem; padding: 10px 18px; font-weight: 600; box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);">
                            Resume Practice
                        </button>
                    </div>
                </div>
            </div>

            <!-- Top Stat Cards -->
            <div class="grid-stats">
                <div class="stat-card">
                    <div class="label">Problems Solved</div>
                    <div class="value" id="statSolved">{{ data.summary.unique_problems_solved }}</div>
                    <div class="subtext" id="statSolvedSubtext">{{ data.summary.by_difficulty_solved.Easy }} Easy, {{ data.summary.by_difficulty_solved.Medium }} Med, {{ data.summary.by_difficulty_solved.Hard }} Hard</div>
                </div>
                <div class="stat-card">
                    <div class="label">Total Attempts</div>
                    <div class="value" id="statAttempts">{{ data.summary.attempts_summary.total_attempts }}</div>
                    <div class="subtext" id="statAttemptsSubtext">{{ data.summary.attempts_summary.passed_attempts }} Passed / {{ data.summary.attempts_summary.failed_attempts }} Failed</div>
                </div>
                <div class="stat-card">
                    <div class="label">Tracked Sessions</div>
                    <div class="value" id="statSessions">{{ data.learning_intelligence.session_analytics.total_sessions_planned }}</div>
                    <div class="subtext" id="statSessionRate">{{ (data.learning_intelligence.session_analytics.session_completion_rate * 100)|round(0) }}% Completion Rate</div>
                </div>
                <div class="stat-card">
                    <div class="label">Adaptive Session Sizing</div>
                    <div class="value">{{ data.learning_intelligence.suggested_session_sizing.recommended_size }} <span style="font-size: 1rem; color: var(--text-muted);">problems</span></div>
                    <div class="subtext">{{ data.learning_intelligence.suggested_session_sizing.rationale[:40] }}...</div>
                </div>
            </div>

            <!-- Overview Command Center Grid -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-bottom: 20px;">
                <!-- Widget 1: Today's Learning Practice -->
                <div class="card" style="margin-bottom: 0; border-top: 3px solid #10b981;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div style="font-weight: 700; font-size: 1rem; color: var(--text); display: flex; align-items: center; gap: 8px;">
                            <span>📅</span> Today's Learning Practice
                        </div>
                        <span id="ovTodayStatusBadge" class="badge" style="background: rgba(16, 185, 129, 0.2); color: #6ee7b7; font-size: 0.7rem;">NO SESSION</span>
                    </div>
                    <div style="font-size: 0.85rem; color: #cbd5e1; margin-bottom: 8px;" id="ovTodayTitle">No study session active today.</div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 6px;">
                        <span>Time Spent: <strong id="ovTodayTime" style="color: #6ee7b7;">0 / 45m</strong></span>
                        <span>Progress: <strong id="ovTodayProgress" style="color: var(--primary);">0%</strong></span>
                    </div>
                    <div class="progress-bar-container" style="height: 6px; margin-bottom: 12px;">
                        <div class="progress-bar-fill" id="ovTodayProgressBar" style="width: 0%; background: #10b981;"></div>
                    </div>
                    <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 12px;" id="ovTodayCurrentTask">
                        Current Focus: <strong>None</strong>
                    </div>
                    <button class="btn btn-secondary btn-sm" style="width: 100%;" onclick="switchTab('daily-practice')">
                        Open Today's Learning →
                    </button>
                </div>

                <!-- Widget 2: My Skill Focus -->
                <div class="card" style="margin-bottom: 0; border-top: 3px solid #8b5cf6;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div style="font-weight: 700; font-size: 1rem; color: var(--text); display: flex; align-items: center; gap: 8px;">
                            <span>🎯</span> Algorithmic Skill Focus
                        </div>
                        <span id="ovSkillPriorityBadge" class="badge" style="background: rgba(139, 92, 246, 0.2); color: #c4b5fd; font-size: 0.7rem;">PRIORITY GAP</span>
                    </div>
                    <div style="font-size: 0.85rem; color: #cbd5e1; margin-bottom: 6px;">
                        Top Target: <strong id="ovSkillTopTopic" style="color: #c4b5fd;">General</strong> (<span id="ovSkillTopDiff">Medium</span>)
                    </div>
                    <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 10px;" id="ovSkillEvidence">
                        Analyzing algorithmic topic distributions and failure patterns.
                    </div>
                    <div style="background: rgba(15, 23, 42, 0.5); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border); font-size: 0.75rem; color: var(--text-muted); margin-bottom: 12px;" id="ovSkillSuggestedBox">
                        Suggested Drill: <strong id="ovSkillSuggestedProblem" style="color: #93c5fd;">two-sum</strong>
                    </div>
                    <button class="btn btn-secondary btn-sm" style="width: 100%;" onclick="switchTab('skills')">
                        Inspect Skill Gaps →
                    </button>
                </div>

                <!-- Widget 3: Adaptive Learning Loop -->
                <div class="card" style="margin-bottom: 0; border-top: 3px solid #06b6d4;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div style="font-weight: 700; font-size: 1rem; color: var(--text); display: flex; align-items: center; gap: 8px;">
                            <span>🔄</span> Adaptive Learning Loop
                        </div>
                        <span id="ovLoopPhaseBadge" class="badge" style="background: rgba(6, 182, 212, 0.2); color: #67e8f9; font-size: 0.7rem;">DIAGNOSIS</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 8px;">
                        <span style="color: var(--text-muted);">Pending Proposals:</span>
                        <strong id="ovLoopProposalsCount" style="color: #fde047;">0 awaiting review</strong>
                    </div>
                    <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 12px;" id="ovLoopLastEval">
                        Last evaluation: Baseline established.
                    </div>
                    <div style="background: rgba(15, 23, 42, 0.5); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border); font-size: 0.75rem; color: #a5f3fc; margin-bottom: 12px;" id="ovLoopSummaryText">
                        Proposals require explicit acceptance before modifying active plan.
                    </div>
                    <button class="btn btn-secondary btn-sm" style="width: 100%;" onclick="switchTab('adaptive-learning')">
                        Review Plan Reconciliation →
                    </button>
                </div>

                <!-- Widget 4: Interview & Preparation -->
                <div class="card" style="margin-bottom: 0; border-top: 3px solid #f59e0b;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div style="font-weight: 700; font-size: 1rem; color: var(--text); display: flex; align-items: center; gap: 8px;">
                            <span>💼</span> Interview & Preparation
                        </div>
                        <span id="ovPlanStatusBadge" class="badge" style="background: rgba(245, 158, 11, 0.2); color: #fcd34d; font-size: 0.7rem;">PLANNER</span>
                    </div>
                    <div style="font-size: 0.85rem; color: #cbd5e1; margin-bottom: 6px;" id="ovPlanTitle">
                        No active preparation plan.
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 6px;">
                        <span>Tasks Completed: <strong id="ovPlanTasks" style="color: #fcd34d;">0 / 0</strong></span>
                        <span>Overdue Revisions: <strong id="ovOverdueRevisions" style="color: #f87171;">0</strong></span>
                    </div>
                    <div class="progress-bar-container" style="height: 6px; margin-bottom: 12px;">
                        <div class="progress-bar-fill" id="ovPlanProgressBar" style="width: 0%; background: #f59e0b;"></div>
                    </div>
                    <button class="btn btn-secondary btn-sm" style="width: 100%;" onclick="switchTab('learning-plan')">
                        Open Learning Plan →
                    </button>
                </div>

                <!-- Widget 5: Coding Performance & Languages -->
                <div class="card" style="margin-bottom: 0; border-top: 3px solid #3b82f6;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div style="font-weight: 700; font-size: 1rem; color: var(--text); display: flex; align-items: center; gap: 8px;">
                            <span>📊</span> Coding Performance & Analytics
                        </div>
                        <span class="badge" style="background: rgba(59, 130, 246, 0.2); color: #93c5fd; font-size: 0.7rem;">ANALYTICS</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 8px;">
                        <span style="color: var(--text-muted);">First-Attempt Pass Rate:</span>
                        <strong id="ovFirstPassRate" style="color: #6ee7b7;">0.0%</strong>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 8px;">
                        <span style="color: var(--text-muted);">Overall Accuracy:</span>
                        <strong id="ovOverallAccuracy" style="color: #93c5fd;">0.0%</strong>
                    </div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 12px;" id="ovLanguageBreakdown">
                        Languages: Python
                    </div>
                    <button class="btn btn-secondary btn-sm" style="width: 100%;" onclick="switchTab('coding-performance')">
                        View Coding Analytics →
                    </button>
                </div>

                <!-- Widget 6: Recent Activity Stream -->
                <div class="card" style="margin-bottom: 0; border-top: 3px solid #ec4899;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div style="font-weight: 700; font-size: 1rem; color: var(--text); display: flex; align-items: center; gap: 8px;">
                            <span>📋</span> Recent Activity Stream
                        </div>
                        <button class="btn btn-secondary btn-sm" style="font-size: 0.7rem; padding: 2px 6px;" onclick="reloadCommandCenter()">🔄</button>
                    </div>
                    <div id="ovRecentActivityList" style="max-height: 145px; overflow-y: auto; font-size: 0.75rem;">
                        <div style="padding: 8px 0; color: var(--text-muted); text-align: center;">Loading activity...</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Adaptive Learning Recommendation -->
        <div class="card tab-content-pane" style="display: none;" data-tab="adaptive-learning">
            <div class="card-header">
                <h2>Adaptive Next Learning Action</h2>
                <span class="status-badge badge-proficient">Confidence: {{ data.learning_intelligence.primary_recommendation.confidence|upper }}</span>
            </div>
            <div class="rec-box">
                <div class="action-title">[{{ data.learning_intelligence.primary_recommendation.action_type|upper }}] {{ data.learning_intelligence.primary_recommendation.title }}</div>
                <div class="action-desc">{{ data.learning_intelligence.primary_recommendation.rationale }}</div>
                {% for ev in data.learning_intelligence.primary_recommendation.evidence %}
                    <span class="evidence-tag">Evidence: {{ ev }}</span>
                {% endfor %}
            </div>
            <p style="color: var(--text-muted); font-size: 0.85rem;">Overall Status: {{ data.learning_intelligence.overall_status }}</p>
        </div>

        <!-- Interactive Session Planner & Preview Workspace -->
        <div class="card tab-content-pane" id="sessionPlannerCard" style="display: none;" data-tab="reports">
            <div class="card-header">
                <h2>Session Planner & Interactive Preview</h2>
                <div>
                    <button class="btn btn-success" id="btnSavePreview" onclick="saveCurrentPreview()">Save Plan as Tracked Session</button>
                </div>
            </div>

            <!-- Controls for dynamic previewing -->
            <div class="controls-bar">
                <label for="planSize">Session Size:</label>
                <select id="planSize" onchange="refreshPlanPreview()">
                    <option value="1">1 Problem (Single Focus)</option>
                    <option value="2">2 Problems (Warm-up + Main)</option>
                    <option value="3" selected>3 Problems (Balanced Default)</option>
                    <option value="4">4 Problems (Extended Practice)</option>
                    <option value="5">5 Problems (Full Workout)</option>
                    <option value="6">6 Problems (Max Session)</option>
                </select>

                <label for="planDifficulty" style="margin-left: 8px;">Preferred Difficulty:</label>
                <select id="planDifficulty" onchange="refreshPlanPreview()">
                    <option value="" selected>Balanced Auto-Progression</option>
                    <option value="easy">Easy (Fundamentals Focus)</option>
                    <option value="medium">Medium (Core Problem Solving)</option>
                    <option value="hard">Hard (Advanced Challenge)</option>
                </select>

                <label style="margin-left: 8px; display: inline-flex; align-items: center; gap: 6px;">
                    <input type="checkbox" id="skipSolved" checked onchange="refreshPlanPreview()">
                    Exclude Already Solved
                </label>

                <button class="btn btn-secondary btn-sm" onclick="refreshPlanPreview()">Regenerate Preview</button>
            </div>

            <div id="planSummaryBox" style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 16px;">
                {{ data.learning_intelligence.preview_session.summary }}
            </div>

            <table id="planTable">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Role</th>
                        <th>Problem ID</th>
                        <th>Difficulty</th>
                        <th>Topics</th>
                        <th>Priority Score</th>
                        <th>Rationale</th>
                    </tr>
                </thead>
                <tbody id="planTableBody">
                    {% for p in data.learning_intelligence.preview_session.problems %}
                    <tr>
                        <td>{{ p.rank }}</td>
                        <td style="font-weight: 600; color: var(--primary);">{{ p.role|replace('_', ' ')|title }}</td>
                        <td>{{ p.problem_id }}</td>
                        <td><span class="badge-{{ p.difficulty }}">{{ p.difficulty|title }}</span></td>
                        <td>{{ p.topics|join(', ') }}</td>
                        <td>{{ p.priority_score }}</td>
                        <td style="color: var(--text-muted);">{{ p.reason }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <!-- Tracked Learning Sessions Management -->
        <div class="card tab-content-pane" id="trackedSessionsCard" style="display: none;" data-tab="coding-performance">
            <div class="card-header">
                <h2>Tracked Learning Sessions</h2>
                <button class="btn btn-secondary btn-sm" onclick="reloadSessionsTable()">Refresh Sessions</button>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Session ID</th>
                        <th>Status</th>
                        <th>Progress</th>
                        <th>Created</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="sessionsTableBody">
                    {% for s in data.learning_intelligence.recent_sessions %}
                    <tr id="row-{{ s.session_id }}">
                        <td style="font-family: monospace; font-weight: 600;">{{ s.session_id }}</td>
                        <td><span class="status-badge badge-{{ s.status }}">{{ s.status|title }}</span></td>
                        <td>
                            <div>{{ s.completed_count }} done, {{ s.skipped_count }} skipped / {{ s.total_problems }} total</div>
                            <div class="progress-bar-container">
                                <div class="progress-bar-fill" style="width: {{ (s.completed_count / s.total_problems * 100)|round(0) if s.total_problems else 0 }}%;"></div>
                            </div>
                        </td>
                        <td style="color: var(--text-muted);">{{ s.created_at[:10] }}</td>
                        <td>
                            <button class="btn btn-secondary btn-sm" onclick="inspectSession('{{ s.session_id }}')">Inspect</button>
                            {% if s.status == 'planned' %}
                                <button class="btn btn-success btn-sm" onclick="updateSessionStatus('{{ s.session_id }}', 'start')">Start</button>
                                <button class="btn btn-danger btn-sm" onclick="confirmCancelSession('{{ s.session_id }}')">Cancel</button>
                            {% elif s.status == 'in_progress' %}
                                <button class="btn btn-success btn-sm" onclick="updateSessionStatus('{{ s.session_id }}', 'completed')">Complete</button>
                                <button class="btn btn-danger btn-sm" onclick="confirmCancelSession('{{ s.session_id }}')">Cancel</button>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <!-- Algorithmic Topic Mastery Table -->
        <div class="card tab-content-pane" id="topicMasteryCard" style="display: none;" data-tab="skills">
            <div class="card-header">
                <h2>Algorithmic Topic Mastery</h2>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Topic</th>
                        <th>Status</th>
                        <th>Solved / Total</th>
                        <th>Attempts (Pass/Fail)</th>
                        <th>Success Rate</th>
                        <th>Assessment</th>
                    </tr>
                </thead>
                <tbody>
                    {% for t in data.learning_intelligence.topics_mastery %}
                    <tr>
                        <td style="font-weight: 600;">{{ t.topic }}</td>
                        <td><span class="status-badge badge-{{ t.mastery_status }}">{{ t.mastery_status|replace('_', ' ')|title }}</span></td>
                        <td>{{ t.solved_problems }} / {{ t.total_problems }}</td>
                        <td>{{ t.total_attempts }} ({{ t.total_attempts - t.failed_attempts }} / {{ t.failed_attempts }})</td>
                        <td>{{ (t.success_rate * 100)|round(0) }}%</td>
                        <td style="color: var(--text-muted);">{{ t.summary }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <!-- Learning Insights & Performance Analytics Export Section (Milestone 6.3.10) -->
        <div class="card tab-content-pane" id="insightsExportCard" style="display: none;" data-tab="coding-performance">
            <div class="card-header">
                <h2>Learning Insights & Sanitized Performance Export</h2>
                <div>
                    <a href="/api/export/csv" class="btn btn-secondary btn-sm" download>Export CSV</a>
                    <a href="/api/export/json" class="btn btn-secondary btn-sm" download style="margin-left: 6px;">Export JSON</a>
                </div>
            </div>
            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 16px;">
                Download complete, privacy-safe analytics of your practice activity, topic mastery, and session progression. All credentials, API tokens, internal paths, and raw code solutions are strictly excluded.
            </p>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px;">
                <div style="background: rgba(15, 23, 42, 0.6); padding: 16px; border-radius: 8px; border: 1px solid var(--border);">
                    <h3 style="font-size: 0.95rem; color: var(--primary); margin-bottom: 6px;">Activity Timeline</h3>
                    <p style="font-size: 0.85rem; color: var(--text-muted);">Tracks learning intensity, problems solved, and session completions mapped across recorded calendar dates.</p>
                </div>
                <div style="background: rgba(15, 23, 42, 0.6); padding: 16px; border-radius: 8px; border: 1px solid var(--border);">
                    <h3 style="font-size: 0.95rem; color: var(--success); margin-bottom: 6px;">Topic Improvement</h3>
                    <p style="font-size: 0.85rem; color: var(--text-muted);">Evaluates verified pass rates and failure reductions to identify strongest domains versus areas needing practice.</p>
                </div>
                <div style="background: rgba(15, 23, 42, 0.6); padding: 16px; border-radius: 8px; border: 1px solid var(--border);">
                    <h3 style="font-size: 0.95rem; color: var(--accent); margin-bottom: 6px;">Session Completion</h3>
                    <p style="font-size: 0.85rem; color: var(--text-muted);">Measures completed vs skipped problem ratios and pacing to prevent fatigue and support adaptive sizing.</p>
                </div>
            </div>
        </div>

        <!-- Offline Intelligent Coding Coach Workspace (Milestone 6.3.11) -->
        <div class="card tab-content-pane" id="coachCard" style="display: none;" data-tab="daily-practice">
            <div class="card-header">
                <h2>Offline Intelligent Coding Coach</h2>
                <span class="status-badge badge-mastered">100% Offline AI double / Zero Cloud APIs</span>
            </div>
            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 16px;">
                Personalized problem-solving feedback, 8-point pedagogical frameworks, and progressive hints designed to foster independent algorithmic implementation.
            </p>
            <div style="background: rgba(15, 23, 42, 0.6); padding: 16px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div style="font-weight: 600; color: var(--primary);">Coach Readiness Assessment</div>
                    <span style="font-size: 0.8rem; color: var(--text-muted);" id="coachReadiness">Analyzing local history...</span>
                </div>
                <div style="font-size: 0.85rem; color: #cbd5e1;" id="coachOverviewSummary">Loading personalized coaching profile...</div>
            </div>

            <!-- Problem selector for progressive hint inspection -->
            <div class="controls-bar">
                <label for="coachProblemSelect">Select Target Problem:</label>
                <select id="coachProblemSelect" onchange="onCoachProblemChange()">
                    <option value="two-sum" selected>Two Sum (Easy - Arrays, Hashing)</option>
                    <option value="valid-parentheses">Valid Parentheses (Easy - Stack)</option>
                    <option value="contains-duplicate">Contains Duplicate (Easy - Arrays, Hashing)</option>
                    <option value="maximum-subarray">Maximum Subarray (Medium - Dynamic Programming)</option>
                    <option value="reverse-linked-list">Reverse Linked List (Easy - Linked List)</option>
                    <option value="merge-two-sorted-lists">Merge Two Sorted Lists (Easy - Linked List)</option>
                    <option value="longest-substring-without-repeating-characters">Longest Substring Without Repeating Characters (Medium - Sliding Window)</option>
                    <option value="climbing-stairs">Climbing Stairs (Easy - Dynamic Programming)</option>
                    <option value="best-time-to-buy-and-sell-stock">Best Time to Buy and Sell Stock (Easy - Greedy)</option>
                    <option value="binary-search">Binary Search (Easy - Binary Search)</option>
                </select>
                <button class="btn btn-secondary btn-sm" onclick="fetchNextProgressiveHint()">Reveal Next Hint</button>
                <button class="btn btn-secondary btn-sm" onclick="resetHintProgression()">Reset Hints</button>
            </div>

            <!-- Hint box container -->
            <div id="coachHintContainer" style="display: none; background: #082f49; border: 1px solid #0284c7; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div id="coachHintTierLabel" style="font-size: 0.95rem; font-weight: 600; color: #38bdf8;">Hint Tier 1: Conceptual Direction</div>
                    <span id="coachHintRemaining" style="font-size: 0.75rem; color: #7dd3fc;">Progress: Tier 1 of 4</span>
                </div>
                <div id="coachHintText" style="color: #f0f9ff; font-size: 0.9rem; white-space: pre-wrap; font-family: monospace;"></div>
            </div>

            <!-- 8-Point Structured Walkthrough Container -->
            <div id="coachWalkthroughContainer" style="background: rgba(30, 41, 59, 0.7); border: 1px solid var(--border); border-radius: 8px; padding: 16px;">
                <h3 style="font-size: 1rem; color: var(--text); margin-bottom: 12px;" id="walkthroughTitle">Problem-Solving Coaching Framework</h3>
                <div id="walkthroughContent" style="font-size: 0.85rem; color: var(--text-muted); line-height: 1.6;">
                    Loading structured pedagogical walkthrough...
                </div>
            </div>
        </div>

        <!-- Spaced Repetition & Smart Revision Center (Milestone 6.3.12) -->
        <div class="card tab-content-pane" id="revisionCard" style="display: none;" data-tab="revision">
            <div class="card-header">
                <h2>Spaced Repetition & Smart Revision Center</h2>
                <button class="btn btn-secondary btn-sm" onclick="reloadRevisionQueue()">Refresh Queue</button>
            </div>
            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 16px;">
                Long-term algorithmic concept retention system based on deterministic Leitner intervals. Retention indicators reflect learning history proxies, not scientific memory measurements.
            </p>

            <div class="grid-stats" style="margin-bottom: 16px;">
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Due Today</div>
                    <div class="value" id="revDueToday" style="font-size: 1.5rem; color: #fde047;">0</div>
                    <div class="subtext">Ready for review</div>
                </div>
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Overdue</div>
                    <div class="value" id="revOverdue" style="font-size: 1.5rem; color: #fca5a5;">0</div>
                    <div class="subtext">Urgent catch-up</div>
                </div>
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Upcoming</div>
                    <div class="value" id="revUpcoming" style="font-size: 1.5rem; color: #93c5fd;">0</div>
                    <div class="subtext">Future revision dates</div>
                </div>
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Reviews Completed</div>
                    <div class="value" id="revCompleted" style="font-size: 1.5rem; color: #86efac;">0</div>
                    <div class="subtext" id="revStreak">0 day streak</div>
                </div>
            </div>

            <!-- Schedule new problem into revision queue controls -->
            <div class="controls-bar">
                <label for="revScheduleSelect">Add Problem to Revision Queue:</label>
                <select id="revScheduleSelect">
                    <option value="two-sum">Two Sum (Easy)</option>
                    <option value="valid-parentheses">Valid Parentheses (Easy)</option>
                    <option value="contains-duplicate">Contains Duplicate (Easy)</option>
                    <option value="maximum-subarray">Maximum Subarray (Medium)</option>
                    <option value="reverse-linked-list">Reverse Linked List (Easy)</option>
                    <option value="merge-two-sorted-lists">Merge Two Sorted Lists (Easy)</option>
                    <option value="longest-substring-without-repeating-characters">Longest Substring (Medium)</option>
                    <option value="climbing-stairs">Climbing Stairs (Easy)</option>
                    <option value="best-time-to-buy-and-sell-stock">Best Time to Buy and Sell Stock (Easy)</option>
                    <option value="binary-search">Binary Search (Easy)</option>
                </select>
                <button class="btn btn-success btn-sm" onclick="scheduleSelectedRevision()">Schedule Revision</button>
            </div>

            <!-- Revision Queue Table -->
            <table>
                <thead>
                    <tr>
                        <th>Problem ID</th>
                        <th>Difficulty</th>
                        <th>Topics</th>
                        <th>Interval</th>
                        <th>Next Review</th>
                        <th>Status</th>
                        <th>Log Outcome</th>
                    </tr>
                </thead>
                <tbody id="revisionTableBody">
                    <tr><td colspan="7" style="text-align: center; color: var(--text-muted);">Loading revision queue...</td></tr>
                </tbody>
            </table>
        </div>

        <!-- Personal Learning Goals & Milestone Achievements (Milestone 6.3.13) -->
        <div class="card tab-content-pane" id="goalsCard" style="display: none;" data-tab="reports">
            <div class="card-header">
                <h2>Learning Goals & Milestone Achievements</h2>
                <button class="btn btn-secondary btn-sm" onclick="reloadGoalsAndMilestones()">Refresh Goals</button>
            </div>
            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 16px;">
                Measurable, offline goal management and verified milestone tracking. Progress is calculated strictly from verified local problem attempts and learning session records.
            </p>

            <div class="grid-stats" style="margin-bottom: 16px;">
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Active Goals</div>
                    <div class="value" id="goalActiveCount" style="font-size: 1.5rem; color: #38bdf8;">0</div>
                    <div class="subtext">In-progress learning targets</div>
                </div>
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Completed Goals</div>
                    <div class="value" id="goalCompletedCount" style="font-size: 1.5rem; color: #86efac;">0</div>
                    <div class="subtext">Successfully fulfilled targets</div>
                </div>
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Unlocked Milestones</div>
                    <div class="value" id="goalMilestonesCount" style="font-size: 1.5rem; color: #fde047;">0</div>
                    <div class="subtext">Evidence-based achievement badges</div>
                </div>
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Completion Rate</div>
                    <div class="value" id="goalCompletionRate" style="font-size: 1.5rem; color: #c084fc;">0%</div>
                    <div class="subtext">Overall goal achievement</div>
                </div>
            </div>

            <!-- Create New Goal Form -->
            <div style="background: rgba(30, 41, 59, 0.7); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-bottom: 20px;">
                <h3 style="font-size: 0.95rem; color: var(--text); margin-bottom: 10px;">Create a New Learning Goal</h3>
                <div style="display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end;">
                    <div>
                        <label style="display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">Goal Title:</label>
                        <input type="text" id="goalTitle" placeholder="e.g. Master Binary Search" style="background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 6px 10px; font-size: 0.85rem; width: 200px;">
                    </div>
                    <div>
                        <label style="display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">Goal Type:</label>
                        <select id="goalType" style="background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 6px 10px; font-size: 0.85rem;">
                            <option value="solve_problems">Solve Problems Count</option>
                            <option value="solve_difficulty">Solve by Difficulty</option>
                            <option value="practice_topic">Practice Algorithmic Topic</option>
                            <option value="complete_sessions">Complete Sessions</option>
                            <option value="complete_revisions">Complete Revisions</option>
                            <option value="weekly_target">Weekly Target</option>
                        </select>
                    </div>
                    <div>
                        <label style="display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">Target Value:</label>
                        <input type="number" id="goalTarget" value="5" min="1" max="1000" style="background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 6px 10px; font-size: 0.85rem; width: 80px;">
                    </div>
                    <div>
                        <label style="display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">Parameter (Diff/Topic):</label>
                        <input type="text" id="goalParam" placeholder="e.g. medium or dynamic-programming" style="background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 6px 10px; font-size: 0.85rem; width: 170px;">
                    </div>
                    <div>
                        <label style="display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">Deadline (Days):</label>
                        <input type="number" id="goalDays" value="14" min="1" max="365" style="background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 6px 10px; font-size: 0.85rem; width: 75px;">
                    </div>
                    <button class="btn btn-success btn-sm" onclick="createNewGoal()">Create Goal</button>
                </div>
            </div>

            <!-- Active Goals List -->
            <h3 style="font-size: 1rem; color: var(--text); margin-bottom: 10px;">Active Learning Targets</h3>
            <div id="goalsListContainer" style="display: flex; flex-direction: column; gap: 12px; margin-bottom: 24px;">
                <div style="text-align: center; color: var(--text-muted); padding: 12px;">Loading active goals...</div>
            </div>

            <!-- Milestone Achievements Badges -->
            <h3 style="font-size: 1rem; color: var(--text); margin-bottom: 10px;">Unlocked Milestones & Badges</h3>
            <div id="milestonesContainer" style="display: flex; flex-wrap: wrap; gap: 10px;">
                <div style="color: var(--text-muted); font-size: 0.85rem;">Checking verified achievements...</div>
            </div>
        </div>

        <!-- Personalized DSA Skill Roadmap & Mastery Map (Milestone 6.3.14) -->
        <div class="card tab-content-pane" id="roadmapCard" style="display: none;" data-tab="skills">
            <div class="card-header">
                <h2>Personalized DSA Skill Roadmap & Mastery Map</h2>
                <button class="btn btn-secondary btn-sm" onclick="reloadRoadmapData()">Refresh Roadmap</button>
            </div>
            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 16px;">
                Evidence-based progression across 5 structured DSA stages. Mastery scores and dependency readiness are calculated transparently from verified problem attempts, revisions, and learning goals.
            </p>

            <div class="grid-stats" style="margin-bottom: 16px;">
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Roadmap Progress</div>
                    <div class="value" id="roadmapProgressPct" style="font-size: 1.5rem; color: #38bdf8;">0%</div>
                    <div class="subtext" id="roadmapProficientCount">0 of 22 topics proficient</div>
                </div>
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">In Practice</div>
                    <div class="value" id="roadmapLearningCount" style="font-size: 1.5rem; color: #fde047;">0</div>
                    <div class="subtext">Active learning / practicing</div>
                </div>
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Ready to Learn</div>
                    <div class="value" id="roadmapReadyCount" style="font-size: 1.5rem; color: #86efac;">0</div>
                    <div class="subtext">Prerequisites satisfied</div>
                </div>
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Locked Topics</div>
                    <div class="value" id="roadmapLockedCount" style="font-size: 1.5rem; color: #94a3b8;">0</div>
                    <div class="subtext">Prerequisites incomplete</div>
                </div>
            </div>

            <!-- Personalized Recommendations Banner -->
            <div id="roadmapRecsContainer" style="background: rgba(30, 41, 59, 0.7); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-bottom: 20px;">
                <h3 style="font-size: 0.95rem; color: var(--primary); margin-bottom: 8px;">Recommended Next Learning Actions</h3>
                <div id="roadmapRecsList" style="display: flex; flex-direction: column; gap: 8px;">
                    <div style="color: var(--text-muted); font-size: 0.85rem;">Analyzing skill readiness...</div>
                </div>
            </div>

            <!-- 5 Stages Roadmap View -->
            <div id="roadmapStagesContainer" style="display: flex; flex-direction: column; gap: 16px;">
                <div style="text-align: center; color: var(--text-muted); padding: 16px;">Loading DSA skill stages...</div>
            </div>
        </div>

        <!-- Daily Learning Mission & Focus Mode (Milestone 6.3.15) -->
        <div class="card tab-content-pane" id="dailyMissionCard" style="display: none;" data-tab="daily-practice">
            <div class="card-header">
                <h2>Daily Learning Mission & Focus Mode</h2>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-secondary btn-sm" onclick="reloadDailyMission()">Refresh Mission</button>
                    <button class="btn btn-primary btn-sm" onclick="generateNewMission()">Generate Mission</button>
                </div>
            </div>
            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 16px;">
                Personalized, bite-sized daily practice missions synthesizing overdue spaced revisions, active goals, and roadmap advancement into a 30-45 minute guided focus workflow.
            </p>

            <div class="grid-stats" style="margin-bottom: 16px;">
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Mission Status</div>
                    <div class="value" id="missionStatusText" style="font-size: 1.4rem; color: #38bdf8; text-transform: uppercase;">NONE</div>
                    <div class="subtext" id="missionDateSub">Today</div>
                </div>
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Completion</div>
                    <div class="value" id="missionProgressPct" style="font-size: 1.4rem; color: #86efac;">0%</div>
                    <div class="subtext" id="missionTasksRatio">0 of 0 tasks completed</div>
                </div>
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Estimated Time</div>
                    <div class="value" id="missionEstTime" style="font-size: 1.4rem; color: #fde047;">0 min</div>
                    <div class="subtext">Daily practice duration</div>
                </div>
                <div class="stat-card" style="padding: 14px;">
                    <div class="label">Practice Streak</div>
                    <div class="value" id="missionStreakDays" style="font-size: 1.4rem; color: #c084fc;">0 Days</div>
                    <div class="subtext">Consecutive daily missions</div>
                </div>
            </div>

            <!-- Focus Mode Active Task Banner -->
            <div id="focusModeContainer" style="background: rgba(15, 23, 42, 0.8); border: 2px solid var(--primary); border-radius: 8px; padding: 16px; margin-bottom: 20px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                    <div>
                        <span style="font-size: 0.75rem; background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid #0284c7; padding: 2px 8px; border-radius: 9999px; text-transform: uppercase; font-weight: 600;">Current Focus Task</span>
                        <h3 id="currentTaskTitle" style="font-size: 1.1rem; color: var(--text); margin-top: 6px;">No Active Mission</h3>
                        <p id="currentTaskDesc" style="font-size: 0.85rem; color: var(--text-muted); margin-top: 4px;">Generate or start today's mission to activate Focus Mode.</p>
                    </div>
                    <div id="missionActionButtons" style="display: flex; gap: 8px;">
                        <button class="btn btn-success btn-sm" id="btnStartMission" onclick="startDailyMissionAction()">Start Mission</button>
                    </div>
                </div>
                <div id="currentTaskMeta" style="font-size: 0.8rem; color: var(--text-muted); display: flex; gap: 16px; border-top: 1px solid var(--border); padding-top: 8px; margin-top: 8px;">
                    <span id="currentTaskTopic">Topic: None</span>
                    <span id="currentTaskDiff">Difficulty: None</span>
                    <span id="currentTaskEst">Est: 0 min</span>
                </div>
            </div>

            <!-- Task Sequence Table -->
            <h3 style="font-size: 1rem; color: var(--text); margin-bottom: 10px;">Mission Task Sequence</h3>
            <table style="margin-bottom: 20px;">
                <thead>
                    <tr>
                        <th style="width: 50px;">#</th>
                        <th>Task Title</th>
                        <th>Type</th>
                        <th>Topic</th>
                        <th>Diff</th>
                        <th>Est</th>
                        <th>Status</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody id="missionTasksTableBody">
                    <tr><td colspan="8" style="text-align: center; color: var(--text-muted);">No mission loaded.</td></tr>
                </tbody>
            </table>

            <!-- Mission History Summary -->
            <h3 style="font-size: 1rem; color: var(--text); margin-bottom: 10px;">Recent Missions History</h3>
            <div id="missionHistoryList" style="display: flex; flex-direction: column; gap: 8px;">
                <div style="color: var(--text-muted); font-size: 0.85rem;">No historical missions recorded.</div>
            </div>
        </div>

        <!-- Mission-Integrated Coding Workspace (Milestone 6.3.16) -->
        <div class="card tab-content-pane" id="codingWorkspaceCard" style="display: none;" data-tab="daily-practice">
            <div class="card-header">
                <h2>Mission-Integrated Coding Workspace</h2>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-secondary btn-sm" onclick="returnToDailyMission()">Focus Mode</button>
                    <button class="btn btn-success btn-sm" id="btnConfirmTaskCompletion" style="display: none;" onclick="confirmTaskCompletionAction()">Confirm Task Completion</button>
                </div>
            </div>
            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 16px;">
                Local-first coding environment connected directly to Daily Mission tasks. Edit solutions, run local test suites with UnifiedJudge, view diagnostic errors, and receive coach feedback.
            </p>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;">
                <!-- Problem Context Panel -->
                <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid var(--border); border-radius: 8px; padding: 14px; max-height: 480px; overflow-y: auto;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                        <h3 id="wsProblemTitle" style="color: var(--text); font-size: 1.05rem;">Select a Problem</h3>
                        <span id="wsProblemDiff" class="badge-easy" style="display: none;">Easy</span>
                    </div>
                    <div id="wsProblemMeta" style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 10px;">
                        <span id="wsProblemTopics">Topics: -</span>
                    </div>
                    <div id="wsTaskReasonBanner" style="display: none; background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 6px; padding: 8px; font-size: 0.8rem; color: #7dd3fc; margin-bottom: 12px;">
                    </div>
                    <div id="wsProblemDesc" style="font-size: 0.85rem; color: var(--text); line-height: 1.5; white-space: pre-wrap; margin-bottom: 14px;">
                        Select a problem from your Daily Mission tasks above, or choose one to start solving.
                    </div>
                    <div id="wsExamplesContainer" style="font-size: 0.8rem; color: var(--text-muted);">
                    </div>
                </div>

                <!-- Code Editor Panel -->
                <div style="display: flex; flex-direction: column;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <label style="font-size: 0.8rem; color: var(--text-muted);">Language:</label>
                            <select id="wsLanguageSelect" onchange="switchWorkspaceLanguage()" style="background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 4px 8px; font-size: 0.85rem;">
                                <option value="python">Python</option>
                                <option value="c">C</option>
                                <option value="cpp">C++</option>
                                <option value="java">Java</option>
                            </select>
                        </div>
                        <div style="display: flex; gap: 6px;">
                            <button class="btn btn-secondary btn-sm" onclick="saveCurrentDraft()">Save Draft</button>
                            <button class="btn btn-primary btn-sm" onclick="runWorkspaceCode()">Run Local Tests</button>
                        </div>
                    </div>
                    <textarea id="wsCodeEditor" spellcheck="false" style="flex: 1; min-height: 400px; background: #090d16; border: 1px solid var(--border); border-radius: 8px; color: #f8fafc; font-family: 'Consolas', 'Courier New', monospace; font-size: 0.85rem; padding: 12px; resize: vertical; line-height: 1.4;"></textarea>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 6px; display: flex; justify-content: space-between;">
                        <span id="wsDraftSavedStatus">Draft auto-loaded</span>
                        <span>Ctrl+Enter to Run</span>
                    </div>
                </div>
            </div>

            <!-- Execution Results Panel -->
            <div id="wsResultCard" style="display: none; background: rgba(15, 23, 42, 0.8); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <h3 style="font-size: 0.95rem; color: var(--text);" id="wsResultTitle">Test Execution Results</h3>
                    <span id="wsResultStatusBadge" style="font-size: 0.75rem; font-weight: 600; padding: 2px 8px; border-radius: 9999px; text-transform: uppercase;"></span>
                </div>
                <div id="wsResultFeedback" style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 8px;"></div>
                <div id="wsResultDiagnostics" style="font-size: 0.8rem; background: #000; border-radius: 6px; padding: 8px; font-family: monospace; color: #fca5a5; white-space: pre-wrap; display: none;"></div>
                <div id="wsCoachGuidance" style="font-size: 0.8rem; color: #93c5fd; background: rgba(59, 130, 246, 0.1); border-left: 3px solid #38bdf8; padding: 8px; margin-top: 8px; display: none;"></div>
            </div>

            <!-- Solution Quality Analyzer & Complexity Review Panel (Milestone 6.3.17) -->
            <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-top: 14px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <h3 style="font-size: 1rem; color: var(--primary);">Solution Quality & Complexity Review</h3>
                    <button class="btn btn-secondary btn-sm" onclick="analyzeCurrentSolutionReview()">Analyze Code Quality</button>
                </div>

                <div id="solutionReviewOutput" style="display: none;">
                    <div class="grid-stats" style="margin-bottom: 14px;">
                        <div class="stat-card" style="padding: 10px;">
                            <div class="label">Readability</div>
                            <div class="value" id="srReadabilityScore" style="font-size: 1.3rem; color: #38bdf8;">0/100</div>
                            <div class="subtext">Naming & format</div>
                        </div>
                        <div class="stat-card" style="padding: 10px;">
                            <div class="label">Structure</div>
                            <div class="value" id="srStructuralScore" style="font-size: 1.3rem; color: #4ade80;">0/100</div>
                            <div class="subtext" id="srNestingText">Max depth: 0</div>
                        </div>
                        <div class="stat-card" style="padding: 10px;">
                            <div class="label">Est. Time</div>
                            <div class="value" id="srEstTime" style="font-size: 1.3rem; color: #fde047;">O(1)</div>
                            <div class="subtext" id="srTimeMatch">Analyzer assessment</div>
                        </div>
                        <div class="stat-card" style="padding: 10px;">
                            <div class="label">Est. Space</div>
                            <div class="value" id="srEstSpace" style="font-size: 1.3rem; color: #c084fc;">O(1)</div>
                            <div class="subtext" id="srSpaceMatch">Auxiliary storage</div>
                        </div>
                    </div>

                    <!-- Complexity Self-Assessment Input -->
                    <div style="background: rgba(30, 41, 59, 0.4); border-radius: 6px; padding: 10px; margin-bottom: 12px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center;">
                        <span style="font-size: 0.8rem; color: var(--text); font-weight: 600;">Complexity Self-Assessment:</span>
                        <input type="text" id="srLearnerTimeInput" placeholder="Your time est. (e.g. O(N))" style="background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 4px; padding: 4px 8px; font-size: 0.8rem; width: 140px;">
                        <input type="text" id="srLearnerSpaceInput" placeholder="Your space est. (e.g. O(1))" style="background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 4px; padding: 4px 8px; font-size: 0.8rem; width: 140px;">
                        <button class="btn btn-secondary btn-sm" onclick="submitComplexitySelfAssessment()">Compare Estimate</button>
                        <span id="srComplexityCompareResult" style="font-size: 0.8rem; color: #7dd3fc;"></span>
                    </div>

                    <!-- Improvement Suggestions -->
                    <div style="margin-bottom: 12px;">
                        <h4 style="font-size: 0.85rem; color: var(--text); margin-bottom: 6px;">Key Suggestions & Observations:</h4>
                        <ul id="srSuggestionsList" style="padding-left: 20px; font-size: 0.8rem; color: var(--text-muted); line-height: 1.4;"></ul>
                    </div>

                    <!-- Attempt Comparison & Reflection -->
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; font-size: 0.8rem;">
                        <div style="background: rgba(30, 41, 59, 0.4); border-radius: 6px; padding: 8px;">
                            <strong style="color: var(--text);">Attempt Comparison:</strong>
                            <p id="srAttemptCompText" style="color: var(--text-muted); margin-top: 4px;">First recorded attempt.</p>
                        </div>
                        <div style="background: rgba(30, 41, 59, 0.4); border-radius: 6px; padding: 8px;">
                            <strong style="color: var(--text);">Algorithmic Reflection Prompt:</strong>
                            <p id="srReflectionText" style="color: #93c5fd; margin-top: 4px;">Think through space-time tradeoffs.</p>
                        </div>
                    </div>
                </div>
                <div id="solutionReviewEmptyText" style="text-align: center; color: var(--text-muted); font-size: 0.85rem; padding: 10px;">
                    Click 'Analyze Code Quality' to run static AST analysis, complexity checks, and structural evaluation.
                </div>
            </div>
        </div>

        <!-- Personal Learning Portfolio & Progress Report Generator (Milestone 6.3.18) -->
        <div class="card tab-content-pane" id="portfolioSection" style="display: none;" data-tab="reports">
            <div class="card-header">
                <div>
                    <h2>Personal Learning Portfolio & Progress Report Generator</h2>
                    <p style="color: var(--text-muted); font-size: 0.85rem; margin-top: 4px;">
                        Evidence-based, offline portfolio synthesis. Exports directly to GitHub-Flavored Markdown, structured JSON, and standalone HTML.
                    </p>
                </div>
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    <button class="btn btn-secondary btn-sm" onclick="exportPortfolio('markdown')">Export Markdown</button>
                    <button class="btn btn-secondary btn-sm" onclick="exportPortfolio('json')">Export JSON</button>
                    <button class="btn btn-primary btn-sm" onclick="exportPortfolio('html')">Export Standalone HTML</button>
                </div>
            </div>

            <!-- Profile and Report Customization Controls -->
            <div style="background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-bottom: 16px;">
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 12px;">
                    <div>
                        <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 4px;">Learner Name</label>
                        <input type="text" id="portLearnerName" value="Learner" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 0.85rem;">
                    </div>
                    <div>
                        <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 4px;">Portfolio Title</label>
                        <input type="text" id="portTitle" value="Developer Learning Portfolio" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 0.85rem;">
                    </div>
                    <div>
                        <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 4px;">Report Presentation Style</label>
                        <select id="portStyle" onchange="reloadPortfolioPreview()" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 0.85rem;">
                            <option value="developer_portfolio">Developer Learning Portfolio</option>
                            <option value="dsa_progress">DSA Progress Report</option>
                            <option value="weekly_summary">Weekly Learning Summary</option>
                            <option value="monthly_report">Monthly Learning Report</option>
                            <option value="goal_completion">Goal Completion Report</option>
                        </select>
                    </div>
                    <div>
                        <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 4px;">Date Range Filter</label>
                        <select id="portPreset" onchange="toggleCustomDatePreset(); reloadPortfolioPreview();" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 0.85rem;">
                            <option value="all_time">All Time</option>
                            <option value="last_7_days">Last 7 Days</option>
                            <option value="last_30_days">Last 30 Days</option>
                            <option value="last_90_days">Last 90 Days</option>
                            <option value="custom">Custom Range</option>
                        </select>
                    </div>
                </div>

                <div id="portCustomDateRow" style="display: none; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px;">
                    <div>
                        <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 4px;">Start Date (YYYY-MM-DD)</label>
                        <input type="date" id="portStartDate" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 0.85rem;">
                    </div>
                    <div>
                        <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 4px;">End Date (YYYY-MM-DD)</label>
                        <input type="date" id="portEndDate" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 0.85rem;">
                    </div>
                </div>

                <div style="display: flex; gap: 8px; justify-content: flex-end;">
                    <button class="btn btn-secondary btn-sm" onclick="savePortfolioConfig()">Save Profile Settings</button>
                    <button class="btn btn-primary btn-sm" onclick="reloadPortfolioPreview()">Refresh Live Preview</button>
                </div>
            </div>

            <!-- Summary & Metric Highlights -->
            <div id="portExecutiveSummary" style="background: rgba(56, 189, 248, 0.08); border-left: 3px solid var(--primary); padding: 12px; border-radius: 4px; margin-bottom: 16px; font-size: 0.9rem; color: #bae6fd;">
                Loading executive evidence summary...
            </div>

            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px;">
                <div style="background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 6px; border: 1px solid var(--border);">
                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Verified Solved</div>
                    <div id="portSolvedStat" style="font-size: 1.4rem; font-weight: 700; color: var(--text); margin-top: 4px;">0</div>
                    <div id="portDifficultyBreakdown" style="font-size: 0.8rem; color: var(--text-muted); margin-top: 2px;">0E / 0M / 0H</div>
                </div>
                <div style="background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 6px; border: 1px solid var(--border);">
                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Roadmap Progress</div>
                    <div id="portRoadmapProgressStat" style="font-size: 1.4rem; font-weight: 700; color: var(--primary); margin-top: 4px;">0%</div>
                    <div id="portProficientTopicsStat" style="font-size: 0.8rem; color: var(--text-muted); margin-top: 2px;">0 Topics Proficient</div>
                </div>
                <div style="background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 6px; border: 1px solid var(--border);">
                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Practice Consistency</div>
                    <div id="portConsistencyStat" style="font-size: 1.4rem; font-weight: 700; color: var(--success); margin-top: 4px;">0 Days</div>
                    <div id="portMissionsStat" style="font-size: 0.8rem; color: var(--text-muted); margin-top: 2px;">0 Missions Completed</div>
                </div>
                <div style="background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 6px; border: 1px solid var(--border);">
                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Solution Readability</div>
                    <div id="portReadabilityStat" style="font-size: 1.4rem; font-weight: 700; color: var(--accent); margin-top: 4px;">0.0/100</div>
                    <div id="portMilestonesStat" style="font-size: 0.8rem; color: var(--text-muted); margin-top: 2px;">0 Milestones Unlocked</div>
                </div>
            </div>

            <!-- Export History Section -->
            <div style="margin-top: 16px;">
                <h3 style="font-size: 0.95rem; color: var(--text); margin-bottom: 8px;">Recent Local Report Exports</h3>
                <div id="portExportHistoryList" style="font-size: 0.85rem; color: var(--text-muted);">
                    No exports generated yet.
                </div>
            </div>
        </div>

        <!-- Mock Interview & Assessment Mode (Milestone 6.3.19) -->
        <div class="card tab-content-pane" id="interviewSection" style="display: none;" data-tab="interviews">
            <div class="card-header">
                <div>
                    <h2>Mock Interview & Technical Assessment Mode</h2>
                    <p style="color: var(--text-muted); font-size: 0.85rem; margin-top: 4px;">
                        Timed offline coding interview simulations with measurable 5-tier rubric scoring and deterministic feedback.
                    </p>
                </div>
                <div id="interviewStatusHeader">
                    <span id="interviewActiveBadge" class="status-badge" style="background: rgba(148, 163, 184, 0.2); color: #94a3b8;">No Active Interview</span>
                </div>
            </div>

            <!-- Start Configuration View (visible when no active interview) -->
            <div id="interviewConfigView" style="background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <h3 style="font-size: 0.95rem; color: var(--text); margin-bottom: 12px;">Configure New Assessment Session</h3>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px;">
                    <div>
                        <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 4px;">Difficulty Track</label>
                        <select id="mockTrack" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 0.85rem;">
                            <option value="beginner">Beginner (Easy Fundamentals)</option>
                            <option value="intermediate" selected>Intermediate (Core Algorithms)</option>
                            <option value="advanced">Advanced (Hard & Optimization)</option>
                            <option value="mixed">Mixed (Progressive Multi-tier)</option>
                        </select>
                    </div>
                    <div>
                        <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 4px;">Time Limit</label>
                        <select id="mockDuration" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 0.85rem;">
                            <option value="30">30 Minutes (Quick Screen)</option>
                            <option value="45" selected>45 Minutes (Standard Technical)</option>
                            <option value="60">60 Minutes (Deep Dive Assessment)</option>
                        </select>
                    </div>
                    <div>
                        <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 4px;">Programming Language</label>
                        <select id="mockLanguage" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 0.85rem;">
                            <option value="python" selected>Python 3</option>
                            <option value="cpp">C++ (std::vector)</option>
                            <option value="c">C</option>
                            <option value="java">Java</option>
                        </select>
                    </div>
                    <div>
                        <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 4px;">Problem Count</label>
                        <select id="mockProblemCount" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 0.85rem;">
                            <option value="1">1 Problem Focus</option>
                            <option value="2" selected>2 Problems Sequence</option>
                            <option value="3">3 Problems Gauntlet</option>
                        </select>
                    </div>
                </div>
                <div style="display: flex; justify-content: flex-end;">
                    <button class="btn btn-primary" onclick="startMockInterview()">Start Mock Interview</button>
                </div>
            </div>

            <!-- Active Interview Workspace View (hidden by default) -->
            <div id="interviewActiveView" style="display: none;">
                <!-- Top Control Bar: Countdown, Problem Navigation & Finish -->
                <div style="background: rgba(30, 41, 59, 0.6); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
                    <div>
                        <span style="font-size: 0.8rem; color: var(--text-muted);">Assessment: </span>
                        <strong id="activeInterviewTitle" style="color: var(--text);">Technical Assessment</strong>
                        <span id="activeTrackBadge" class="status-badge" style="background: rgba(56, 189, 248, 0.2); color: var(--primary); margin-left: 6px;">Intermediate</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 16px;">
                        <div style="text-align: right;">
                            <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Time Remaining</div>
                            <div id="interviewTimerDisplay" style="font-size: 1.4rem; font-weight: 700; color: var(--success); font-family: monospace;">45:00</div>
                        </div>
                        <button class="btn btn-danger btn-sm" onclick="finishMockInterview()">Finish & Submit</button>
                    </div>
                </div>

                <!-- Problem Step Bar -->
                <div id="interviewProblemSteps" style="display: flex; gap: 8px; margin-bottom: 16px; overflow-x: auto;"></div>

                <!-- Problem Statement & Coding Editor Grid -->
                <div style="display: grid; grid-template-columns: 1fr 1.2fr; gap: 16px; margin-bottom: 16px;" id="interviewWorkGrid">
                    <!-- Left: Problem Description -->
                    <div style="background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border); border-radius: 8px; padding: 16px; max-height: 480px; overflow-y: auto;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <h3 id="activeProblemTitle" style="font-size: 1.1rem; color: var(--text); margin: 0;">Problem Title</h3>
                            <span id="activeProblemDiff" class="badge-medium">Medium</span>
                        </div>
                        <div id="activeProblemTopics" style="font-size: 0.8rem; color: var(--primary); margin-bottom: 12px;">Topics: Core DSA</div>
                        <div id="activeProblemDesc" style="font-size: 0.85rem; color: var(--text); line-height: 1.5; margin-bottom: 16px;">Description text...</div>

                        <h4 style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 6px;">Examples</h4>
                        <div id="activeProblemExamples" style="font-size: 0.8rem; font-family: monospace; background: rgba(0,0,0,0.3); padding: 8px; border-radius: 4px; margin-bottom: 12px;"></div>

                        <h4 style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 6px;">Constraints</h4>
                        <div id="activeProblemConstraints" style="font-size: 0.8rem; color: var(--text-muted);"></div>
                    </div>

                    <!-- Right: Solution Code Editor & Run Controls -->
                    <div style="display: flex; flex-direction: column;">
                        <textarea id="interviewCodeEditor" style="width: 100%; height: 360px; background: #0b0f19; color: #f8fafc; font-family: 'Consolas', monospace; font-size: 0.9rem; border: 1px solid var(--border); border-radius: 8px; padding: 12px; resize: vertical;" placeholder="# Write your solution here..."></textarea>

                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 10px;">
                            <div style="display: flex; gap: 8px;">
                                <button class="btn btn-secondary btn-sm" onclick="saveInterviewDraft()">Save Draft</button>
                                <button class="btn btn-success btn-sm" onclick="submitInterviewSolution()">Run & Submit Solution</button>
                            </div>
                            <button id="advanceProblemBtn" class="btn btn-secondary btn-sm" onclick="advanceInterviewProblem()">Next Problem &rarr;</button>
                        </div>

                        <!-- Submission Feedback Box -->
                        <div id="interviewRunFeedback" style="margin-top: 12px; background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border); border-radius: 6px; padding: 10px; font-size: 0.85rem; display: none;"></div>
                    </div>
                </div>
            </div>

            <!-- Assessment Report View (shown when finished or inspecting past interview) -->
            <div id="interviewReportView" style="display: none; background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div>
                        <h3 id="reportTitle" style="font-size: 1.1rem; color: var(--text); margin: 0;">Technical Assessment Report</h3>
                        <p id="reportSub" style="color: var(--text-muted); font-size: 0.8rem; margin-top: 2px;">Completed Assessment Details</p>
                    </div>
                    <div style="text-align: right;">
                        <span id="reportTotalScore" style="font-size: 1.8rem; font-weight: 800; color: var(--primary);">85</span>
                        <span style="font-size: 0.9rem; color: var(--text-muted);">/100</span>
                    </div>
                </div>

                <!-- 5 Rubric Category Cards -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin-bottom: 16px;">
                    <div style="background: rgba(30, 41, 59, 0.5); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border);">
                        <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">Correctness (40%)</div>
                        <div id="rubricCorrectness" style="font-size: 1.1rem; font-weight: 700; color: var(--text); margin-top: 2px;">0.0/40</div>
                    </div>
                    <div style="background: rgba(30, 41, 59, 0.5); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border);">
                        <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">Completion (20%)</div>
                        <div id="rubricCompletion" style="font-size: 1.1rem; font-weight: 700; color: var(--text); margin-top: 2px;">0.0/20</div>
                    </div>
                    <div style="background: rgba(30, 41, 59, 0.5); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border);">
                        <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">Structure (15%)</div>
                        <div id="rubricStructure" style="font-size: 1.1rem; font-weight: 700; color: var(--text); margin-top: 2px;">0.0/15</div>
                    </div>
                    <div style="background: rgba(30, 41, 59, 0.5); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border);">
                        <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">Complexity (15%)</div>
                        <div id="rubricComplexity" style="font-size: 1.1rem; font-weight: 700; color: var(--text); margin-top: 2px;">0.0/15</div>
                    </div>
                    <div style="background: rgba(30, 41, 59, 0.5); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border);">
                        <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">Pacing (10%)</div>
                        <div id="rubricTime" style="font-size: 1.1rem; font-weight: 700; color: var(--text); margin-top: 2px;">0.0/10</div>
                    </div>
                </div>

                <!-- Observations & Pedagogical Feedback -->
                <div id="reportFeedbackDetails" style="font-size: 0.85rem; line-height: 1.5; color: #bae6fd; background: rgba(56, 189, 248, 0.08); border-left: 3px solid var(--primary); padding: 10px; border-radius: 4px; margin-bottom: 12px;"></div>

                <!-- Next Recommendations (DSA Roadmap & Spaced Revision) -->
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px;">
                    <div style="background: rgba(30, 41, 59, 0.4); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                        <strong style="color: var(--text); font-size: 0.85rem;">Recommended Roadmap Topics</strong>
                        <ul id="reportRecommendedTopics" style="margin: 6px 0 0 16px; padding: 0; font-size: 0.8rem; color: var(--text-muted);"></ul>
                    </div>
                    <div style="background: rgba(30, 41, 59, 0.4); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                        <strong style="color: var(--text); font-size: 0.85rem;">Suggested Spaced Revisions</strong>
                        <ul id="reportRecommendedRevisions" style="margin: 6px 0 0 16px; padding: 0; font-size: 0.8rem; color: var(--text-muted);"></ul>
                    </div>
                </div>

                <!-- Disclaimer Banner -->
                <div style="font-size: 0.75rem; color: var(--text-muted); font-style: italic;">
                    * This assessment is calculated deterministically from local test runs and static code analysis. It does not measure real-world hiring probability or guarantee interview readiness.
                </div>
            </div>

            <!-- Historical Assessment Archive Table -->
            <div style="margin-top: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <h3 style="font-size: 0.95rem; color: var(--text); margin: 0;">Previous Mock Assessments</h3>
                    <button class="btn btn-secondary btn-sm" onclick="reloadInterviewHistory()">Refresh History</button>
                </div>
                <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem;">
                    <thead>
                        <tr style="border-bottom: 1px solid var(--border); text-align: left; color: var(--text-muted);">
                            <th style="padding: 6px 8px;">Date</th>
                            <th style="padding: 6px 8px;">Session Title</th>
                            <th style="padding: 6px 8px;">Track</th>
                            <th style="padding: 6px 8px;">Duration</th>
                            <th style="padding: 6px 8px;">Score</th>
                            <th style="padding: 6px 8px;">Status</th>
                            <th style="padding: 6px 8px; text-align: right;">Action</th>
                        </tr>
                    </thead>
                    <tbody id="interviewHistoryTableBody">
                        <tr><td colspan="7" style="padding: 8px; color: var(--text-muted); text-align: center;">No assessments recorded yet.</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Interview Performance Trends & Benchmark Analytics (Milestone 6.3.20) -->
        <div class="card tab-content-pane" id="interviewAnalyticsSection" style="display: none;" data-tab="interviews">
            <div class="card-header">
                <div>
                    <h2>Interview Performance Trends & Benchmark Analytics</h2>
                    <p style="color: var(--text-muted); font-size: 0.85rem; margin-top: 4px;">
                        Longitudinal score trend analytics, recurring weakness detection, track/language benchmarks, and practice goals.
                    </p>
                </div>
                <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                    <select id="ianalyticsPreset" onchange="reloadInterviewAnalytics()" style="background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 8px; font-size: 0.8rem;">
                        <option value="all_time" selected>All Time</option>
                        <option value="last_7_days">Last 7 Days</option>
                        <option value="last_30_days">Last 30 Days</option>
                        <option value="last_90_days">Last 90 Days</option>
                    </select>
                    <button class="btn btn-secondary btn-sm" onclick="reloadInterviewAnalytics()">Refresh Analytics</button>
                </div>
            </div>

            <!-- Top Summary Stats Grid -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px;">
                <div style="background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 6px; border: 1px solid var(--border);">
                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Completed Assessments</div>
                    <div id="iaTotalCount" style="font-size: 1.4rem; font-weight: 700; color: var(--text); margin-top: 4px;">0</div>
                    <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 2px;">Evaluated Sessions</div>
                </div>
                <div style="background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 6px; border: 1px solid var(--border);">
                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Average Score</div>
                    <div id="iaAvgScore" style="font-size: 1.4rem; font-weight: 700; color: var(--primary); margin-top: 4px;">0.0</div>
                    <div id="iaExtremes" style="font-size: 0.8rem; color: var(--text-muted); margin-top: 2px;">High: - | Low: -</div>
                </div>
                <div style="background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 6px; border: 1px solid var(--border);">
                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Latest Score</div>
                    <div id="iaLatestScore" style="font-size: 1.4rem; font-weight: 700; color: var(--accent); margin-top: 4px;">-</div>
                    <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 2px;">Most Recent Assessment</div>
                </div>
                <div style="background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 6px; border: 1px solid var(--border);">
                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Problem Completion Rate</div>
                    <div id="iaCompletionRate" style="font-size: 1.4rem; font-weight: 700; color: var(--success); margin-top: 4px;">0.0%</div>
                    <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 2px;">Fully Solved Problems</div>
                </div>
            </div>

            <!-- Category Trends Grid -->
            <div style="margin-bottom: 16px;">
                <h3 style="font-size: 0.95rem; color: var(--text); margin-bottom: 8px;">Rubric Category Performance & Trends</h3>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px;" id="iaCategoryTrendsGrid">
                    <!-- Populated dynamically via JS -->
                </div>
            </div>

            <!-- Two-Column Benchmarks Grid: Tracks & Languages -->
            <div style="display: grid; grid-template-columns: 1.1fr 1fr; gap: 16px; margin-bottom: 16px;" id="iaBenchmarksGrid">
                <!-- Track Benchmarks -->
                <div style="background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border); border-radius: 8px; padding: 12px;">
                    <h3 style="font-size: 0.9rem; color: var(--text); margin-bottom: 8px;">Difficulty Track Comparison</h3>
                    <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem;">
                        <thead>
                            <tr style="border-bottom: 1px solid var(--border); color: var(--text-muted); text-align: left;">
                                <th style="padding: 4px 6px;">Track</th>
                                <th style="padding: 4px 6px;">Count</th>
                                <th style="padding: 4px 6px;">Avg Score</th>
                                <th style="padding: 4px 6px;">High</th>
                                <th style="padding: 4px 6px;">Completion</th>
                                <th style="padding: 4px 6px;">Reliability</th>
                            </tr>
                        </thead>
                        <tbody id="iaTracksTableBody">
                            <tr><td colspan="6" style="padding: 6px; color: var(--text-muted); text-align: center;">No track data recorded yet.</td></tr>
                        </tbody>
                    </table>
                </div>

                <!-- Language Benchmarks -->
                <div style="background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border); border-radius: 8px; padding: 12px;">
                    <h3 style="font-size: 0.9rem; color: var(--text); margin-bottom: 8px;">Programming Language Benchmarks</h3>
                    <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem;">
                        <thead>
                            <tr style="border-bottom: 1px solid var(--border); color: var(--text-muted); text-align: left;">
                                <th style="padding: 4px 6px;">Language</th>
                                <th style="padding: 4px 6px;">Count</th>
                                <th style="padding: 4px 6px;">Avg Score</th>
                                <th style="padding: 4px 6px;">Correctness</th>
                                <th style="padding: 4px 6px;">Structure</th>
                            </tr>
                        </thead>
                        <tbody id="iaLanguagesTableBody">
                            <tr><td colspan="5" style="padding: 6px; color: var(--text-muted); text-align: center;">No language data recorded yet.</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Performance Insights & Weaknesses -->
            <div style="margin-bottom: 16px;">
                <h3 style="font-size: 0.95rem; color: var(--text); margin-bottom: 8px;">Performance Pattern & Weakness Detection</h3>
                <div id="iaInsightsContainer" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px;">
                    <div style="background: rgba(30, 41, 59, 0.4); padding: 10px; border-radius: 6px; border: 1px solid var(--border); color: var(--text-muted); font-size: 0.85rem;">
                        Complete at least 2 mock assessments to generate evidence-based pattern insights.
                    </div>
                </div>
            </div>

            <!-- Interview Practice Goals & Progress -->
            <div style="background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <h3 style="font-size: 0.95rem; color: var(--text); margin: 0;">Interview Practice Goals</h3>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <select id="newGoalType" style="background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 8px; font-size: 0.8rem;">
                            <option value="target_average_score">Target Average Score (/100)</option>
                            <option value="target_correctness">Target Correctness (/40)</option>
                            <option value="target_completion_ratio">Target Completion Rate (%)</option>
                            <option value="interviews_per_month">Monthly Assessments Count</option>
                            <option value="target_complexity">Target Complexity Score (/15)</option>
                        </select>
                        <input type="number" id="newGoalValue" placeholder="Target" style="width: 80px; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 8px; font-size: 0.8rem;">
                        <button class="btn btn-primary btn-sm" onclick="createInterviewGoal()">Set Goal</button>
                    </div>
                </div>
                <div id="iaGoalsList" style="font-size: 0.85rem; color: var(--text-muted);">
                    No interview practice goals configured yet.
                </div>
            </div>
        </div>

        <!-- Milestone 6.3.21: Adaptive Interview Preparation Planner Card -->
        <div class="card tab-content-pane" id="prepPlannerCard" style="display: none; margin-bottom: 24px;" data-tab="learning-plan">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div>
                    <h2 class="card-title" style="margin: 0; font-size: 1.15rem; display: flex; align-items: center; gap: 8px;">
                        <span>🗓️ Adaptive Interview Preparation Planner</span>
                        <span id="planStatusBadge" class="badge" style="background: var(--surface-light); color: var(--text-muted); font-size: 0.75rem; padding: 2px 8px; border-radius: 4px;">No Plan</span>
                    </h2>
                    <p style="margin: 4px 0 0 0; font-size: 0.85rem; color: var(--text-muted);">
                        Evidence-driven daily & weekly interview preparation schedules dynamically adapted to your progress, missed tasks, and weak areas.
                    </p>
                </div>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <button class="btn btn-secondary btn-sm" onclick="previewReplan()" id="btnPreviewReplan">⚡ Preview Adaptive Replan</button>
                    <button class="btn btn-primary btn-sm" onclick="generatePreparationPlan()" id="btnGeneratePlan">🎯 Generate New Plan</button>
                </div>
            </div>

            <!-- Planner Configuration Bar -->
            <div style="background: rgba(15, 23, 42, 0.5); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <h3 style="font-size: 0.85rem; color: var(--text); margin: 0; text-transform: uppercase; letter-spacing: 0.5px;">Plan Configuration</h3>
                    <button class="btn btn-secondary btn-sm" style="font-size: 0.75rem; padding: 2px 8px;" onclick="savePlannerSettings()">Save Settings</button>
                </div>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; font-size: 0.8rem;">
                    <div>
                        <label style="color: var(--text-muted); display: block; margin-bottom: 3px;">Daily Study (Min)</label>
                        <input type="number" id="plannerDailyMinutes" value="60" min="15" max="360" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;">
                    </div>
                    <div>
                        <label style="color: var(--text-muted); display: block; margin-bottom: 3px;">Horizon</label>
                        <select id="plannerHorizonDays" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;">
                            <option value="7">7 Days (1 Week)</option>
                            <option value="14">14 Days (2 Weeks)</option>
                            <option value="30">30 Days (1 Month)</option>
                        </select>
                    </div>
                    <div>
                        <label style="color: var(--text-muted); display: block; margin-bottom: 3px;">Track</label>
                        <select id="plannerTargetTrack" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;">
                            <option value="intermediate">Intermediate</option>
                            <option value="beginner">Beginner</option>
                            <option value="advanced">Advanced</option>
                            <option value="mixed">Mixed</option>
                        </select>
                    </div>
                    <div>
                        <label style="color: var(--text-muted); display: block; margin-bottom: 3px;">Language</label>
                        <select id="plannerLanguage" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;">
                            <option value="python">Python</option>
                            <option value="cpp">C++</option>
                            <option value="c">C</option>
                            <option value="java">Java</option>
                        </select>
                    </div>
                    <div>
                        <label style="color: var(--text-muted); display: block; margin-bottom: 3px;">Target Score</label>
                        <input type="number" id="plannerTargetScore" value="80" min="50" max="100" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;">
                    </div>
                    <div>
                        <label style="color: var(--text-muted); display: block; margin-bottom: 3px;">Intensity</label>
                        <select id="plannerIntensity" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;">
                            <option value="moderate">Moderate</option>
                            <option value="light">Light</option>
                            <option value="intensive">Intensive</option>
                        </select>
                    </div>
                </div>
            </div>

            <!-- Active Plan Progress Summary -->
            <div id="planSummaryBox" style="background: rgba(30, 41, 59, 0.4); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
                    <div>
                        <h3 id="activePlanTitle" style="margin: 0; font-size: 0.95rem; color: var(--text);">No Active Preparation Plan</h3>
                        <span id="activePlanDateRange" style="font-size: 0.8rem; color: var(--text-muted);">Configure settings and generate a plan to begin structured preparation.</span>
                    </div>
                    <div id="planActionBtnContainer" style="display: flex; gap: 6px;">
                        <!-- Apply plan button if draft -->
                    </div>
                </div>
                <!-- Progress bar -->
                <div style="margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 4px;">
                        <span style="color: var(--text-muted);">Tasks Completed: <strong id="planTasksCount" style="color: var(--text);">0 / 0</strong></span>
                        <span id="planPctText" style="color: var(--primary); font-weight: 600;">0%</span>
                    </div>
                    <div style="height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; overflow: hidden;">
                        <div id="planProgressBar" style="height: 100%; width: 0%; background: var(--primary); border-radius: 3px; transition: width 0.3s ease;"></div>
                    </div>
                </div>
                <!-- Mini Stats Grid -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; font-size: 0.8rem;">
                    <div style="background: rgba(15, 23, 42, 0.4); padding: 6px 10px; border-radius: 4px;">
                        <span style="color: var(--text-muted); display: block;">Planned Time</span>
                        <strong id="statPlannedTime" style="color: var(--text);">0m</strong>
                    </div>
                    <div style="background: rgba(15, 23, 42, 0.4); padding: 6px 10px; border-radius: 4px;">
                        <span style="color: var(--text-muted); display: block;">Actual Time</span>
                        <strong id="statActualTime" style="color: var(--text);">0m</strong>
                    </div>
                    <div style="background: rgba(15, 23, 42, 0.4); padding: 6px 10px; border-radius: 4px;">
                        <span style="color: var(--text-muted); display: block;">Study Streak</span>
                        <strong id="statStreakDays" style="color: var(--success);">0 days</strong>
                    </div>
                    <div style="background: rgba(15, 23, 42, 0.4); padding: 6px 10px; border-radius: 4px;">
                        <span style="color: var(--text-muted); display: block;">Overdue Tasks</span>
                        <strong id="statOverdueTasks" style="color: var(--warning);">0</strong>
                    </div>
                </div>
            </div>

            <!-- Replan Preview Alert Box (Hidden by default) -->
            <div id="replanPreviewBox" style="display: none; background: rgba(234, 179, 8, 0.1); border: 1px solid rgba(234, 179, 8, 0.4); border-radius: 8px; padding: 14px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                    <div>
                        <h4 style="margin: 0; color: #fde047; font-size: 0.9rem;">Adaptive Replan Preview</h4>
                        <p id="replanExplanation" style="margin: 4px 0 0 0; font-size: 0.8rem; color: var(--text-muted);"></p>
                    </div>
                    <div style="display: flex; gap: 6px;">
                        <button class="btn btn-secondary btn-sm" onclick="dismissReplanPreview()">Dismiss</button>
                        <button class="btn btn-primary btn-sm" onclick="applyReplan()">Apply Adaptive Changes</button>
                    </div>
                </div>
                <div id="replanChangesList" style="font-size: 0.8rem; color: var(--text);"></div>
            </div>

            <!-- Weekly Strategy Cards & Daily Schedule -->
            <div id="plannerScheduleContainer">
                <div style="color: var(--text-muted); font-size: 0.85rem; text-align: center; padding: 20px;">
                    No preparation schedule loaded. Click "Generate New Plan" to create your customized preparation schedule.
                </div>
            </div>
        </div>

        <!-- Milestone 6.3.22: Plan-to-Practice Execution Bridge Card -->
        <div class="card tab-content-pane" id="practiceSessionCard" style="display: none; margin-bottom: 24px;" data-tab="daily-practice">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div>
                    <h2 class="card-title" style="margin: 0; font-size: 1.15rem; display: flex; align-items: center; gap: 8px;">
                        <span>🎯 Plan-to-Practice Execution Bridge</span>
                        <span id="practiceSessionStatusBadge" class="badge" style="background: var(--surface-light); color: var(--text-muted); font-size: 0.75rem; padding: 2px 8px; border-radius: 4px;">NO ACTIVE SESSION</span>
                    </h2>
                    <p style="margin: 4px 0 0 0; font-size: 0.85rem; color: var(--text-muted);">
                        Bridge planner tasks to live coding sessions with timer tracking, submission evidence, notes reflection, and explicit task confirmation.
                    </p>
                </div>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <button class="btn btn-secondary btn-sm" onclick="showPracticeHistoryModal()">📜 Session History</button>
                </div>
            </div>

            <!-- Quick Start Standalone Practice Bar -->
            <div id="practiceStartBar" style="background: rgba(15, 23, 42, 0.5); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <h3 style="font-size: 0.85rem; color: var(--text); margin: 0; text-transform: uppercase; letter-spacing: 0.5px;">Standalone Practice Launch</h3>
                </div>
                <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                    <input type="text" id="standaloneProblemId" placeholder="Problem ID (e.g. two-sum)" value="two-sum" style="background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 0.85rem; min-width: 180px;">
                    <select id="standaloneLanguage" style="background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 0.85rem;">
                        <option value="python">Python</option>
                        <option value="cpp">C++</option>
                        <option value="c">C</option>
                        <option value="java">Java</option>
                    </select>
                    <button class="btn btn-primary btn-sm" onclick="startStandalonePracticeSession()">🚀 Start Practice Session</button>
                </div>
            </div>

            <!-- Active Practice Session Panel (Shown when session is active or paused) -->
            <div id="activePracticeSessionBox" style="display: none; background: rgba(30, 41, 59, 0.4); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-bottom: 16px;">
                <!-- Session Header Info -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                    <div>
                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                            <span id="activeSessTaskTypeBadge" class="badge" style="background: rgba(59, 130, 246, 0.2); color: #93c5fd; font-size: 0.75rem; padding: 2px 6px; border-radius: 4px;">TASK</span>
                            <h3 id="activeSessTitle" style="margin: 0; font-size: 1rem; color: var(--text);">Active Practice Session</h3>
                        </div>
                        <span id="activeSessSubtitle" style="font-size: 0.8rem; color: var(--text-muted);">Problem: None • Language: Python</span>
                    </div>

                    <!-- Live Timer Display and Quick Controls -->
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <div style="text-align: right;">
                            <span style="font-size: 0.75rem; color: var(--text-muted); display: block;">Session Elapsed</span>
                            <span id="activeSessTimerDisplay" style="font-size: 1.3rem; font-weight: bold; font-family: monospace; color: var(--success);">00:00</span>
                        </div>
                        <div style="display: flex; gap: 6px;">
                            <button id="btnPauseResumeSession" class="btn btn-secondary btn-sm" onclick="togglePauseResumeSession()">⏸️ Pause</button>
                            <button class="btn btn-warning btn-sm" style="background: rgba(239, 68, 68, 0.2); border-color: rgba(239, 68, 68, 0.5); color: #f87171;" onclick="endPracticeSession('abandoned')">Abandon</button>
                            <button class="btn btn-primary btn-sm" onclick="confirmTaskCompletion()">✅ Complete & Confirm Task</button>
                        </div>
                    </div>
                </div>

                <!-- Evidence & Metrics Strip -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin-bottom: 14px; font-size: 0.8rem;">
                    <div style="background: rgba(15, 23, 42, 0.5); padding: 8px; border-radius: 4px; border: 1px solid var(--border);">
                        <span style="color: var(--text-muted); display: block;">Total Runs</span>
                        <strong id="sessSubmissionsCount" style="color: var(--text);">0</strong>
                    </div>
                    <div style="background: rgba(15, 23, 42, 0.5); padding: 8px; border-radius: 4px; border: 1px solid var(--border);">
                        <span style="color: var(--text-muted); display: block;">Passed Runs</span>
                        <strong id="sessPassedCount" style="color: var(--success);">0</strong>
                    </div>
                    <div style="background: rgba(15, 23, 42, 0.5); padding: 8px; border-radius: 4px; border: 1px solid var(--border);">
                        <span style="color: var(--text-muted); display: block;">Failed Runs</span>
                        <strong id="sessFailedCount" style="color: var(--warning);">0</strong>
                    </div>
                    <div style="background: rgba(15, 23, 42, 0.5); padding: 8px; border-radius: 4px; border: 1px solid var(--border);">
                        <span style="color: var(--text-muted); display: block;">Final Status</span>
                        <strong id="sessFinalStatus" style="color: var(--text-muted);">None</strong>
                    </div>
                    <div style="background: rgba(15, 23, 42, 0.5); padding: 8px; border-radius: 4px; border: 1px solid var(--border); display: flex; align-items: center; justify-content: center;">
                        <button class="btn btn-secondary btn-sm" style="font-size: 0.75rem; width: 100%;" onclick="openActiveSessionInWorkspace()">💻 Open Editor</button>
                    </div>
                </div>

                <!-- Structured Reflection Notes Accordion -->
                <div style="background: rgba(15, 23, 42, 0.3); border: 1px solid var(--border); border-radius: 6px; padding: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <strong style="color: var(--text); font-size: 0.85rem;">📝 Reflection & Complexity Notes</strong>
                        <button class="btn btn-secondary btn-sm" style="font-size: 0.75rem; padding: 2px 8px;" onclick="saveActiveSessionNotes()">Save Notes</button>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 0.8rem;">
                        <div>
                            <label style="color: var(--text-muted); display: block; margin-bottom: 2px;">Initial Approach</label>
                            <input type="text" id="noteInitialApproach" placeholder="e.g. Hash map complement lookup" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;">
                        </div>
                        <div>
                            <label style="color: var(--text-muted); display: block; margin-bottom: 2px;">Mistakes Encountered</label>
                            <input type="text" id="noteMistakes" placeholder="e.g. Edge case with duplicate numbers" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;">
                        </div>
                        <div>
                            <label style="color: var(--text-muted); display: block; margin-bottom: 2px;">Time Complexity (Big-O)</label>
                            <input type="text" id="noteTimeCplx" placeholder="e.g. O(n)" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;">
                        </div>
                        <div>
                            <label style="color: var(--text-muted); display: block; margin-bottom: 2px;">Space Complexity (Big-O)</label>
                            <input type="text" id="noteSpaceCplx" placeholder="e.g. O(n)" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;">
                        </div>
                        <div style="grid-column: 1 / -1;">
                            <label style="color: var(--text-muted); display: block; margin-bottom: 2px;">Key Learning / Takeaway</label>
                            <input type="text" id="noteKeyLearning" placeholder="e.g. Single-pass hash table reduces runtime from O(n^2) to O(n)" style="width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;">
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Personal Coding Behavior Intelligence Panel (Milestone 6.3.23) -->
        <div class="card tab-content-pane" id="codingBehaviorCard" style="display: none; border-top: 3px solid #8b5cf6;" data-tab="coding-performance">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <h2 style="margin: 0; font-size: 1.2rem; color: var(--text);">🧠 Personal Coding Behavior Intelligence</h2>
                    <span id="cbConfidenceBadge" class="badge" style="background: rgba(139, 92, 246, 0.2); color: #c4b5fd; font-size: 0.75rem;">BASELINE</span>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-primary btn-sm" onclick="runBehaviorAnalysis()">⚡ Analyze Now</button>
                    <button class="btn btn-secondary btn-sm" onclick="reloadCodingBehavior()">🔄 Refresh</button>
                </div>
            </div>

            <!-- Quick Metrics Grid -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 16px;">
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Total Evidence Events</span>
                    <strong id="cbTotalEvents" style="font-size: 1.1rem; color: var(--text);">0</strong>
                </div>
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Confidence Level</span>
                    <strong id="cbConfidence" style="font-size: 1.1rem; color: #c4b5fd;">insufficient_data</strong>
                </div>
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">First-Attempt Pass Rate</span>
                    <strong id="cbFirstPassRate" style="font-size: 1.1rem; color: var(--success);">0%</strong>
                </div>
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Debugging Persistence</span>
                    <strong id="cbPersistenceRate" style="font-size: 1.1rem; color: var(--primary);">0%</strong>
                </div>
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Session Completion</span>
                    <strong id="cbSessionCompletion" style="font-size: 1.1rem; color: #38bdf8;">0%</strong>
                </div>
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Complexity Awareness</span>
                    <strong id="cbComplexityRate" style="font-size: 1.1rem; color: #f59e0b;">0%</strong>
                </div>
            </div>

            <!-- Multi-Dimension Behavioral Breakdown -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 16px;">
                <!-- Recurring Behavioral Patterns -->
                <div style="background: rgba(15, 23, 42, 0.3); border: 1px solid var(--border); border-radius: 6px; padding: 12px;">
                    <h4 style="margin: 0 0 8px 0; font-size: 0.9rem; color: var(--text); display: flex; align-items: center; gap: 6px;">
                        <span>🔍</span> Detected Behavioral Patterns
                    </h4>
                    <div id="cbPatternsList" style="font-size: 0.8rem; color: var(--text-muted);">
                        No recurring patterns identified yet.
                    </div>
                </div>

                <!-- Actionable Insights -->
                <div style="background: rgba(15, 23, 42, 0.3); border: 1px solid var(--border); border-radius: 6px; padding: 12px;">
                    <h4 style="margin: 0 0 8px 0; font-size: 0.9rem; color: var(--text); display: flex; align-items: center; gap: 6px;">
                        <span>💡</span> Actionable Behavioral Insights
                    </h4>
                    <div id="cbInsightsList" style="font-size: 0.8rem; color: var(--text-muted);">
                        No behavioral insights available.
                    </div>
                </div>

                <!-- Practice Recommendations -->
                <div style="background: rgba(15, 23, 42, 0.3); border: 1px solid var(--border); border-radius: 6px; padding: 12px;">
                    <h4 style="margin: 0 0 8px 0; font-size: 0.9rem; color: var(--text); display: flex; align-items: center; gap: 6px;">
                        <span>📋</span> Practice Recommendations
                    </h4>
                    <div id="cbRecommendationsList" style="font-size: 0.8rem; color: var(--text-muted);">
                        No active recommendations.
                    </div>
                </div>
            </div>

            <!-- Limitations and Scope Disclaimer -->
            <div style="background: rgba(30, 41, 59, 0.25); border: 1px dashed var(--border); border-radius: 6px; padding: 8px 12px; font-size: 0.75rem; color: var(--text-muted);">
                <strong style="color: #94a3b8;">Disclaimer & Scope:</strong>
                <span id="cbLimitationsText">Analysis is 100% offline and deterministic, derived purely from local test executions and session audit events. Strictly avoids psychological profiling, IQ evaluation, or external employment scoring.</span>
            </div>
        </div>

        <!-- Personal Skill Gap & Focus Prioritization Panel (Milestone 6.3.24) -->
        <div class="card tab-content-pane" id="skillGapCard" style="display: none; border-top: 3px solid #ec4899;" data-tab="skills">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <h2 style="margin: 0; font-size: 1.2rem; color: var(--text);">🎯 Personal Skill Gap & Focus Prioritization</h2>
                    <span id="sgCoverageBadge" class="badge" style="background: rgba(236, 72, 153, 0.2); color: #f472b6; font-size: 0.75rem;">0% COVERAGE</span>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-primary btn-sm" onclick="runSkillGapAnalysis()">⚡ Analyze Now</button>
                    <button class="btn btn-secondary btn-sm" onclick="reloadSkillGaps()">🔄 Refresh</button>
                </div>
            </div>

            <!-- Quick Metrics Grid -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 16px;">
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Evaluated Topics</span>
                    <strong id="sgTotalTopics" style="font-size: 1.1rem; color: var(--text);">0</strong>
                </div>
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Practiced Coverage</span>
                    <strong id="sgPracticedCoverage" style="font-size: 1.1rem; color: #f472b6;">0%</strong>
                </div>
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Critical (P0) Gaps</span>
                    <strong id="sgCriticalGaps" style="font-size: 1.1rem; color: var(--warning);">0</strong>
                </div>
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Demonstrated Strengths</span>
                    <strong id="sgStrengthsCount" style="font-size: 1.1rem; color: var(--success);">0</strong>
                </div>
            </div>

            <!-- Prioritized Focus Queue Table -->
            <div style="background: rgba(15, 23, 42, 0.3); border: 1px solid var(--border); border-radius: 6px; padding: 12px; margin-bottom: 16px;">
                <h4 style="margin: 0 0 10px 0; font-size: 0.95rem; color: var(--text); display: flex; align-items: center; gap: 6px;">
                    <span>📋</span> Prioritized Algorithmic Focus Queue
                </h4>
                <div style="overflow-x: auto;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem;">
                        <thead>
                            <tr style="border-bottom: 1px solid var(--border); color: var(--text-muted); text-align: left;">
                                <th style="padding: 6px 8px;">Rank</th>
                                <th style="padding: 6px 8px;">Priority</th>
                                <th style="padding: 6px 8px;">Topic</th>
                                <th style="padding: 6px 8px;">Category</th>
                                <th style="padding: 6px 8px;">Score</th>
                                <th style="padding: 6px 8px;">Difficulty</th>
                                <th style="padding: 6px 8px;">Suggested Action</th>
                                <th style="padding: 6px 8px;">Evidence & Reason</th>
                            </tr>
                        </thead>
                        <tbody id="sgFocusQueueBody">
                            <tr>
                                <td colspan="8" style="padding: 12px; text-align: center; color: var(--text-muted);">No focus queue generated yet. Click 'Analyze Now' to compute skill gaps.</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Two Columns: Strengths & Insufficient Evidence -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 16px;">
                <!-- Demonstrated Strengths -->
                <div style="background: rgba(15, 23, 42, 0.3); border: 1px solid var(--border); border-radius: 6px; padding: 12px;">
                    <h4 style="margin: 0 0 8px 0; font-size: 0.9rem; color: var(--text); display: flex; align-items: center; gap: 6px;">
                        <span>🌟</span> Demonstrated Strengths
                    </h4>
                    <div id="sgStrengthsList" style="font-size: 0.8rem; color: var(--text-muted);">
                        No confirmed strengths identified yet (requires >= 2 solves and >= 80% success rate).
                    </div>
                </div>

                <!-- Insufficient Evidence / Under-practiced -->
                <div style="background: rgba(15, 23, 42, 0.3); border: 1px solid var(--border); border-radius: 6px; padding: 12px;">
                    <h4 style="margin: 0 0 8px 0; font-size: 0.9rem; color: var(--text); display: flex; align-items: center; gap: 6px;">
                        <span>⏳</span> Insufficient Practice Topics
                    </h4>
                    <div id="sgInsufficientList" style="font-size: 0.8rem; color: var(--text-muted);">
                        All evaluated topics currently have practice evidence.
                    </div>
                </div>
            </div>

            <!-- Limitations and Scope Disclaimer -->
            <div style="background: rgba(30, 41, 59, 0.25); border: 1px dashed var(--border); border-radius: 6px; padding: 8px 12px; font-size: 0.75rem; color: var(--text-muted);">
                <strong style="color: #94a3b8;">Disclaimer & Scope:</strong>
                <span id="sgLimitationsText">Skill gaps are evaluated strictly from verified local executions and tracking history. Unpracticed topics represent lack of local evidence rather than poor ability. Recommendations are preview-only.</span>
            </div>
        </div>

        <!-- Adaptive Learning Loop & Plan Reconciliation Panel (Milestone 6.3.25) -->
        <div class="card tab-content-pane" id="learningLoopCard" style="display: none; border-top: 3px solid #06b6d4;" data-tab="adaptive-learning">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <h2 style="margin: 0; font-size: 1.2rem; color: var(--text);">🔄 Adaptive Learning Loop & Plan Reconciliation</h2>
                    <span id="llPhaseBadge" class="badge" style="background: rgba(6, 182, 212, 0.2); color: #67e8f9; font-size: 0.75rem;">DIAGNOSIS</span>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-primary btn-sm" onclick="runLearningLoopAnalysis()">⚡ Run Learning Cycle</button>
                    <button class="btn btn-secondary btn-sm" onclick="reloadLearningLoop()">🔄 Refresh</button>
                </div>
            </div>

            <!-- Quick Metrics Grid -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 16px;">
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Cycle Phase</span>
                    <strong id="llCurrentPhase" style="font-size: 1.1rem; color: #67e8f9;">re_evaluation</strong>
                </div>
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Active Plan</span>
                    <strong id="llPlanStatus" style="font-size: 1.1rem; color: var(--text);">None</strong>
                </div>
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Pending Proposals</span>
                    <strong id="llPendingProposalsCount" style="font-size: 1.1rem; color: #f59e0b;">0</strong>
                </div>
                <div style="background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                    <span style="color: var(--text-muted); font-size: 0.75rem; display: block;">Primary Focus</span>
                    <strong id="llTopFocus" style="font-size: 1.1rem; color: var(--primary);">None</strong>
                </div>
            </div>

            <!-- Next Recommended Action Banner -->
            <div id="llNextActionBox" style="background: rgba(6, 182, 212, 0.1); border: 1px solid rgba(6, 182, 212, 0.3); border-radius: 6px; padding: 12px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                    <div>
                        <span class="badge" style="background: rgba(6, 182, 212, 0.2); color: #67e8f9; font-size: 0.7rem; margin-bottom: 4px;">RECOMMENDED PRACTICE ACTION</span>
                        <h4 id="llActionTitle" style="margin: 2px 0; color: var(--text); font-size: 0.95rem;">No immediate action needed</h4>
                        <p id="llActionReason" style="margin: 0; color: var(--text-muted); font-size: 0.8rem;">All current learning tasks and skill gaps are reconciled.</p>
                    </div>
                    <button id="llActionLaunchBtn" class="btn btn-primary btn-sm" style="display: none;" onclick="launchLoopPracticeAction()">🚀 Start Practice Session</button>
                </div>
            </div>

            <!-- Pending Plan Reconciliation Proposals Table -->
            <div style="background: rgba(15, 23, 42, 0.3); border: 1px solid var(--border); border-radius: 6px; padding: 12px; margin-bottom: 16px;">
                <h4 style="margin: 0 0 10px 0; font-size: 0.95rem; color: var(--text); display: flex; align-items: center; gap: 6px;">
                    <span>📝</span> Plan Reconciliation Change Proposals (Explicit Approval Required)
                </h4>
                <div style="overflow-x: auto;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem;">
                        <thead>
                            <tr style="border-bottom: 1px solid var(--border); color: var(--text-muted); text-align: left;">
                                <th style="padding: 6px 8px;">Action Type</th>
                                <th style="padding: 6px 8px;">Topic</th>
                                <th style="padding: 6px 8px;">Proposed Change</th>
                                <th style="padding: 6px 8px;">Target Diff</th>
                                <th style="padding: 6px 8px;">Evidence & Rationale</th>
                                <th style="padding: 6px 8px;">Decision</th>
                            </tr>
                        </thead>
                        <tbody id="llProposalsBody">
                            <tr>
                                <td colspan="6" style="padding: 12px; text-align: center; color: var(--text-muted);">No pending plan proposals. Current preparation plan matches diagnosed skill gaps.</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Snapshot Progression & Comparison Summary -->
            <div style="background: rgba(15, 23, 42, 0.3); border: 1px solid var(--border); border-radius: 6px; padding: 12px; margin-bottom: 12px;">
                <h4 style="margin: 0 0 6px 0; font-size: 0.9rem; color: var(--text); display: flex; align-items: center; gap: 6px;">
                    <span>📊</span> Cycle-to-Cycle Snapshot Progression
                </h4>
                <p id="llComparisonText" style="margin: 0; font-size: 0.8rem; color: var(--text-muted);">
                    Run a learning cycle to establish baseline comparison.
                </p>
            </div>

            <!-- Limitations and Scope Disclaimer -->
            <div style="background: rgba(30, 41, 59, 0.25); border: 1px dashed var(--border); border-radius: 6px; padding: 8px 12px; font-size: 0.75rem; color: var(--text-muted);">
                <strong style="color: #94a3b8;">Disclaimer & Scope:</strong>
                <span id="llLimitationsText">The Adaptive Learning Loop operates 100% offline. Plan modifications require explicit user approval. Completed tasks and historical data are permanently preserved.</span>
            </div>
        </div>

        <!-- Guided Daily Practice & Study Session Orchestrator Panel (Milestone 6.3.26) -->
        <div class="card tab-content-pane" id="dailyPracticeCard" style="display: none; border-top: 3px solid #10b981;" data-tab="daily-practice">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <h2 style="margin: 0; font-size: 1.2rem; color: var(--text);">📅 Guided Daily Practice & Study Session</h2>
                    <span id="dpStatusBadge" class="badge" style="background: rgba(16, 185, 129, 0.2); color: #6ee7b7; font-size: 0.75rem;">NO SESSION</span>
                </div>
                <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                    <label style="font-size: 0.8rem; color: var(--text-muted); margin-right: -4px;">Budget:</label>
                    <select id="dpBudgetSelect" onchange="onDpBudgetChange()" style="background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 8px; font-size: 0.8rem;">
                        <option value="15">15 min (Sprint)</option>
                        <option value="30">30 min (Quick)</option>
                        <option value="45" selected>45 min (Standard)</option>
                        <option value="60">60 min (Deep)</option>
                        <option value="90">90 min (Extended)</option>
                        <option value="custom">Custom...</option>
                    </select>
                    <input type="number" id="dpCustomMinutes" placeholder="min" min="15" max="360" style="display: none; width: 60px; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px; font-size: 0.8rem;" />
                    <button class="btn btn-primary btn-sm" onclick="generateDailyPracticeSession()">⚡ Generate Today's Session</button>
                    <button class="btn btn-secondary btn-sm" onclick="reloadDailyPractice()">🔄 Refresh</button>
                </div>
            </div>

            <!-- Overview Metrics Grid -->
            <div class="metrics-grid" style="grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin-bottom: 12px;">
                <div class="metric-card" style="padding: 10px;">
                    <div class="metric-label" style="font-size: 0.75rem;">Active / Latest Session</div>
                    <div id="dpSessionTitle" style="font-weight: 600; font-size: 0.85rem; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">No session generated</div>
                </div>
                <div class="metric-card" style="padding: 10px;">
                    <div class="metric-label" style="font-size: 0.75rem;">Budget vs Elapsed</div>
                    <div id="dpTimeDisplay" style="font-weight: 700; font-size: 1rem; color: #6ee7b7;">0 / 45m</div>
                </div>
                <div class="metric-card" style="padding: 10px;">
                    <div class="metric-label" style="font-size: 0.75rem;">Progress</div>
                    <div id="dpProgressDisplay" style="font-weight: 700; font-size: 1rem; color: var(--primary);">0% (0/0)</div>
                </div>
                <div class="metric-card" style="padding: 10px;">
                    <div class="metric-label" style="font-size: 0.75rem;">Verified Passes</div>
                    <div id="dpVerifiedDisplay" style="font-weight: 700; font-size: 1rem; color: #10b981;">0</div>
                </div>
            </div>

            <!-- Session Controls Bar -->
            <div id="dpSessionControlsBar" style="background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div style="font-size: 0.8rem; color: var(--text-muted);">
                    <span id="dpCurrentTaskLabel">Current focus: <strong>None</strong></span>
                </div>
                <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                    <button id="dpStartBtn" class="btn btn-primary btn-sm" style="display: none;" onclick="startDailyPracticeSession()">▶️ Start Session</button>
                    <button id="dpPauseBtn" class="btn btn-secondary btn-sm" style="display: none;" onclick="pauseDailyPracticeSession()">⏸️ Pause</button>
                    <button id="dpResumeBtn" class="btn btn-primary btn-sm" style="display: none;" onclick="resumeDailyPracticeSession()">▶️ Resume</button>
                    <button id="dpCompleteBtn" class="btn btn-sm" style="display: none; background: #059669; color: white;" onclick="completeDailyPracticeSession()">✅ Complete</button>
                    <button id="dpAbandonBtn" class="btn btn-secondary btn-sm" style="display: none; color: #f87171;" onclick="abandonDailyPracticeSession()">⏹️ Abandon</button>
                    <button id="dpReevaluateBtn" class="btn btn-secondary btn-sm" style="display: none;" onclick="reevaluateDailyPracticeLoop()">🔄 Re-evaluate Loop</button>
                </div>
            </div>

            <!-- Task List Table -->
            <div style="overflow-x: auto; margin-bottom: 12px;">
                <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem;">
                    <thead>
                        <tr style="border-bottom: 1px solid var(--border); text-align: left; color: var(--text-muted);">
                            <th style="padding: 6px 8px; width: 30px;">#</th>
                            <th style="padding: 6px 8px; width: 110px;">Type</th>
                            <th style="padding: 6px 8px;">Task / Problem</th>
                            <th style="padding: 6px 8px; width: 80px;">Target</th>
                            <th style="padding: 6px 8px; width: 80px;">Actual</th>
                            <th style="padding: 6px 8px; width: 90px;">Status</th>
                            <th style="padding: 6px 8px; width: 150px;">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="dpTasksTableBody">
                        <tr><td colspan="7" style="padding: 12px; text-align: center; color: var(--text-muted);">No study session active. Click "Generate Today's Session" to schedule tasks based on learning evidence.</td></tr>
                    </tbody>
                </table>
            </div>

            <!-- Disclaimer & Scope -->
            <div style="background: rgba(30, 41, 59, 0.25); border: 1px dashed var(--border); border-radius: 6px; padding: 8px 12px; font-size: 0.75rem; color: var(--text-muted);">
                <strong style="color: #94a3b8;">Disclaimer & Verification:</strong>
                <span>Tasks are orchestrated offline from real learning evidence (preparation plan, spaced revision, skill gaps, unresolved attempts). Verified passes require local test run evidence. Progress database is strictly read-only.</span>
            </div>
        </div>

        <footer>
            LeetCode Agent • Local Interactive Learning Workspace • No Live Account Modification
        </footer>
    </div>

    <!-- Modal for Inspecting Session Details -->
    <div id="sessionModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3 id="modalSessionTitle" style="color: var(--primary);">Session Details</h3>
                <button class="modal-close" onclick="closeSessionModal()">&times;</button>
            </div>
            <div id="modalSessionBody">
                <p style="color: var(--text-muted);">Loading session data...</p>
            </div>
        </div>
    </div>

    <script>
        let currentPlanData = {{ data.learning_intelligence.preview_session|tojson }};

        function showAlert(msg, isSuccess = true) {
            const el = document.getElementById("alertBanner");
            el.className = "alert-banner " + (isSuccess ? "alert-success" : "alert-error");
            el.innerText = msg;
            el.style.display = "block";
            setTimeout(() => { el.style.display = "none"; }, 5000);
        }

        async function refreshPlanPreview() {
            const size = document.getElementById("planSize").value;
            const diff = document.getElementById("planDifficulty").value;
            const skipSolved = document.getElementById("skipSolved").checked;

            try {
                const res = await fetch(`/api/preview-plan?session_size=${size}&difficulty=${diff}&skip_solved=${skipSolved}`);
                const data = await res.json();
                if (!res.ok) {
                    showAlert(data.error || "Failed to preview plan", false);
                    return;
                }
                currentPlanData = data;
                renderPreviewTable(data);
                showAlert(`Plan generated: ${data.total_planned} problems planned.`);
            } catch (err) {
                showAlert("Error connecting to local server", false);
            }
        }

        function renderPreviewTable(plan) {
            document.getElementById("planSummaryBox").innerText = plan.summary;
            const tbody = document.getElementById("planTableBody");
            tbody.innerHTML = "";

            if (!plan.problems || plan.problems.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No candidate problems found matching the criteria.</td></tr>';
                return;
            }

            plan.problems.forEach(p => {
                const roleLabel = p.role.replace("_", " ").replace(/\b\w/g, l => l.toUpperCase());
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td>${p.rank}</td>
                    <td style="font-weight: 600; color: var(--primary);">${roleLabel}</td>
                    <td>${escapeHtml(p.problem_id)}</td>
                    <td><span class="badge-${p.difficulty}">${p.difficulty.charAt(0).toUpperCase() + p.difficulty.slice(1)}</span></td>
                    <td>${escapeHtml((p.topics || []).join(", "))}</td>
                    <td>${p.priority_score.toFixed(1)}</td>
                    <td style="color: var(--text-muted);">${escapeHtml(p.reason)}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        async function saveCurrentPreview() {
            if (!currentPlanData || !currentPlanData.problems || currentPlanData.problems.length === 0) {
                showAlert("No planned problems to save.", false);
                return;
            }

            try {
                const size = document.getElementById("planSize").value;
                const diff = document.getElementById("planDifficulty").value;
                const skipSolved = document.getElementById("skipSolved").checked;

                const res = await fetch("/api/save-session", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        session_size: parseInt(size),
                        difficulty: diff || null,
                        skip_solved: skipSolved
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert(`Session saved successfully with ID: ${data.session_id}!`);
                    reloadSessionsTable();
                } else {
                    showAlert(data.error || "Failed to save session", false);
                }
            } catch (err) {
                showAlert("Error saving session", false);
            }
        }

        async function reloadSessionsTable() {
            try {
                const res = await fetch("/api/sessions");
                const sessions = await res.json();
                const tbody = document.getElementById("sessionsTableBody");
                tbody.innerHTML = "";

                if (!sessions || sessions.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">(No tracked sessions found)</td></tr>';
                    return;
                }

                sessions.forEach(s => {
                    const pct = s.total_problems ? Math.round((s.completed_count / s.total_problems) * 100) : 0;
                    const tr = document.createElement("tr");
                    tr.id = `row-${s.session_id}`;
                    tr.innerHTML = `
                        <td style="font-family: monospace; font-weight: 600;">${escapeHtml(s.session_id)}</td>
                        <td><span class="status-badge badge-${s.status}">${s.status.charAt(0).toUpperCase() + s.status.slice(1)}</span></td>
                        <td>
                            <div>${s.completed_count} done, ${s.skipped_count} skipped / ${s.total_problems} total</div>
                            <div class="progress-bar-container">
                                <div class="progress-bar-fill" style="width: ${pct}%;"></div>
                            </div>
                        </td>
                        <td style="color: var(--text-muted);">${s.created_at.slice(0, 10)}</td>
                        <td>
                            <button class="btn btn-secondary btn-sm" onclick="inspectSession('${s.session_id}')">Inspect</button>
                            ${s.status === 'planned' ? `
                                <button class="btn btn-success btn-sm" onclick="updateSessionStatus('${s.session_id}', 'start')">Start</button>
                                <button class="btn btn-danger btn-sm" onclick="confirmCancelSession('${s.session_id}')">Cancel</button>
                            ` : ''}
                            ${s.status === 'in_progress' ? `
                                <button class="btn btn-success btn-sm" onclick="updateSessionStatus('${s.session_id}', 'completed')">Complete</button>
                                <button class="btn btn-danger btn-sm" onclick="confirmCancelSession('${s.session_id}')">Cancel</button>
                            ` : ''}
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            } catch (err) {
                showAlert("Failed to reload sessions", false);
            }
        }

        async function updateSessionStatus(sessionId, action) {
            try {
                const res = await fetch(`/api/session/${sessionId}/status`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ action: action })
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert(`Session '${sessionId}' updated to ${data.status.toUpperCase()}`);
                    reloadSessionsTable();
                } else {
                    showAlert(data.error || "Update failed", false);
                }
            } catch (err) {
                showAlert("Error updating session", false);
            }
        }

        function confirmCancelSession(sessionId) {
            if (confirm(`Are you sure you want to cancel session ${sessionId}? This cannot be undone.`)) {
                updateSessionStatus(sessionId, "cancel");
            }
        }

        async function inspectSession(sessionId) {
            const modal = document.getElementById("sessionModal");
            const modalTitle = document.getElementById("modalSessionTitle");
            const modalBody = document.getElementById("modalSessionBody");

            modalTitle.innerText = `Session Details: ${sessionId}`;
            modalBody.innerHTML = '<p style="color: var(--text-muted);">Loading session items...</p>';
            modal.style.display = "flex";

            try {
                const res = await fetch(`/api/session/${sessionId}`);
                const data = await res.json();
                if (!res.ok) {
                    modalBody.innerHTML = `<p style="color: var(--danger);">${data.error || "Failed to load"}</p>`;
                    return;
                }

                let itemsHtml = `
                    <div style="margin-bottom: 16px; font-size: 0.9rem;">
                        <p><strong>Status:</strong> <span class="status-badge badge-${data.status}">${data.status.toUpperCase()}</span></p>
                        <p><strong>Language:</strong> ${data.target_language} | <strong>Size:</strong> ${data.problems.length} problems</p>
                        <p><strong>Summary:</strong> ${escapeHtml(data.session_summary)}</p>
                    </div>
                    <table style="width: 100%;">
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Problem ID</th>
                                <th>Role</th>
                                <th>Difficulty</th>
                                <th>Status</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                `;

                data.problems.forEach(p => {
                    itemsHtml += `
                        <tr>
                            <td>${p.rank}</td>
                            <td style="font-weight: 600;">${escapeHtml(p.problem_id)}</td>
                            <td style="color: var(--primary);">${escapeHtml(p.role)}</td>
                            <td><span class="badge-${p.difficulty}">${p.difficulty}</span></td>
                            <td><span class="status-badge badge-${p.status}">${p.status}</span></td>
                            <td>
                                ${data.status !== 'cancelled' && p.status === 'pending' ? `
                                    <button class="btn btn-success btn-sm" onclick="updateProblemProgress('${sessionId}', '${p.problem_id}', 'completed')">Done</button>
                                    <button class="btn btn-secondary btn-sm" onclick="updateProblemProgress('${sessionId}', '${p.problem_id}', 'skipped')">Skip</button>
                                ` : '-'}
                            </td>
                        </tr>
                    `;
                });

                itemsHtml += '</tbody></table>';
                modalBody.innerHTML = itemsHtml;
            } catch (err) {
                modalBody.innerHTML = '<p style="color: var(--danger);">Failed to load session details.</p>';
            }
        }

        async function updateProblemProgress(sessionId, problemId, status) {
            try {
                const res = await fetch(`/api/session/${sessionId}/problem/${problemId}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ status: status })
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert(`Problem '${problemId}' marked as ${status.toUpperCase()}`);
                    inspectSession(sessionId);
                    reloadSessionsTable();
                } else {
                    showAlert(data.error || "Update failed", false);
                }
            } catch (err) {
                showAlert("Error updating problem", false);
            }
        }

        function closeSessionModal() {
            document.getElementById("sessionModal").style.display = "none";
        }

        function escapeHtml(str) {
            if (!str) return "";
            return str.replace(/[&<>'"]/g, tag => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
            }[tag] || tag));
        }

        // Coaching script interactions
        let currentHintTier = 0;

        async function initCoach() {
            try {
                const res = await fetch("/api/coach/overview");
                const data = await res.json();
                if (res.ok) {
                    document.getElementById("coachReadiness").innerText = data.readiness_assessment;
                    let summaryHtml = `<p>${escapeHtml(data.overview_summary)}</p>`;
                    if (data.personalized_insights && data.personalized_insights.length > 0) {
                        summaryHtml += '<div style="margin-top: 8px;">';
                        data.personalized_insights.forEach(ins => {
                            summaryHtml += `<div style="margin-top: 6px;"><strong style="color: var(--primary);">${escapeHtml(ins.headline)}:</strong> ${escapeHtml(ins.advice)} <em style="color: var(--text-muted); font-size: 0.8rem;">(${escapeHtml(ins.evidence)})</em></div>`;
                        });
                        summaryHtml += '</div>';
                    }
                    document.getElementById("coachOverviewSummary").innerHTML = summaryHtml;
                    if (data.recommended_problem) {
                        const sel = document.getElementById("coachProblemSelect");
                        for (let i = 0; i < sel.options.length; i++) {
                            if (sel.options[i].value === data.recommended_problem.id) {
                                sel.selectedIndex = i;
                                break;
                            }
                        }
                    }
                    onCoachProblemChange();
                }
            } catch (err) {
                console.error("Coach init failed", err);
            }
        }

        async function onCoachProblemChange() {
            resetHintProgression();
            const pid = document.getElementById("coachProblemSelect").value;
            const container = document.getElementById("walkthroughContent");
            container.innerHTML = "Loading coaching framework...";

            try {
                const res = await fetch(`/api/coach/problem/${pid}`);
                const guide = await res.json();
                if (!res.ok) {
                    container.innerHTML = `<p style="color: var(--danger);">${guide.error || "Failed to load coaching guide"}</p>`;
                    return;
                }

                document.getElementById("walkthroughTitle").innerText = `Pedagogical Framework: ${guide.title} (${guide.difficulty})`;
                container.innerHTML = `
                    <div style="margin-bottom: 10px;"><strong>1. Understand the Requirement:</strong> ${escapeHtml(guide.understanding)}</div>
                    <div style="margin-bottom: 10px;"><strong>2. Inputs & Outputs:</strong> <code>${escapeHtml(guide.inputs_and_outputs)}</code></div>
                    <div style="margin-bottom: 10px;"><strong>3. Scale & Constraints:</strong> ${escapeHtml(guide.constraints)}</div>
                    <div style="margin-bottom: 10px;"><strong>4. Algorithmic Patterns:</strong> <span style="color: var(--primary);">${escapeHtml((guide.relevant_patterns || []).join(", "))}</span></div>
                    <div style="margin-bottom: 10px;">
                        <strong>5. Step-by-Step Approach:</strong>
                        <ul style="margin-left: 20px; margin-top: 4px;">
                            ${(guide.step_by_step_approach || []).map(s => `<li>${escapeHtml(s)}</li>`).join("")}
                        </ul>
                    </div>
                    <div style="margin-bottom: 10px;"><strong>6. Complexity Target:</strong> ${escapeHtml(guide.complexity_considerations)}</div>
                    <div style="margin-bottom: 10px;">
                        <strong>7. Test Cases to Verify:</strong>
                        <ul style="margin-left: 20px; margin-top: 4px;">
                            ${(guide.test_recommendations || []).map(t => `<li>${escapeHtml(t)}</li>`).join("")}
                        </ul>
                    </div>
                    <div style="margin-top: 12px; color: #a7f3d0; font-style: italic;"><strong>8. Independent Execution:</strong> ${escapeHtml(guide.encouragement)}</div>
                `;
            } catch (err) {
                container.innerHTML = '<p style="color: var(--danger);">Failed to load guidance.</p>';
            }
        }

        async function fetchNextProgressiveHint() {
            const pid = document.getElementById("coachProblemSelect").value;
            const nextTier = currentHintTier + 1;
            if (nextTier > 4) {
                showAlert("All 4 hints have already been revealed for this problem.", false);
                return;
            }

            try {
                const res = await fetch(`/api/coach/problem/${pid}/hint?tier=${nextTier}`);
                const hint = await res.json();
                if (!res.ok) {
                    showAlert(hint.error || "Failed to load hint", false);
                    return;
                }

                currentHintTier = nextTier;
                const hintContainer = document.getElementById("coachHintContainer");
                document.getElementById("coachHintTierLabel").innerText = `Hint Tier ${hint.tier}: ${hint.tier_name}`;
                document.getElementById("coachHintRemaining").innerText = `Progress: Tier ${hint.tier} of 4`;
                document.getElementById("coachHintText").innerText = hint.content;
                hintContainer.style.display = "block";
                showAlert(`Revealed Hint Tier ${hint.tier}: ${hint.tier_name}`);
            } catch (err) {
                showAlert("Error fetching hint", false);
            }
        }

        function resetHintProgression() {
            currentHintTier = 0;
            const hintContainer = document.getElementById("coachHintContainer");
            if (hintContainer) {
                hintContainer.style.display = "none";
                document.getElementById("coachHintText").innerText = "";
            }
        }

        // Spaced Repetition interactions
        async function reloadRevisionQueue() {
            try {
                const res = await fetch("/api/revision/queue");
                const queue = await res.json();
                const analyticsRes = await fetch("/api/revision/analytics");
                const stats = await analyticsRes.json();

                if (analyticsRes.ok) {
                    document.getElementById("revDueToday").innerText = stats.reviews_due_today;
                    document.getElementById("revOverdue").innerText = stats.reviews_overdue;
                    document.getElementById("revUpcoming").innerText = stats.reviews_upcoming;
                    document.getElementById("revCompleted").innerText = stats.reviews_completed;
                    document.getElementById("revStreak").innerText = `${stats.active_streak_days} day streak`;
                }

                const tbody = document.getElementById("revisionTableBody");
                tbody.innerHTML = "";
                if (!queue || queue.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">(Spaced repetition queue is clear)</td></tr>';
                    return;
                }

                queue.forEach(item => {
                    const tr = document.createElement("tr");
                    tr.innerHTML = `
                        <td style="font-weight: 600;">${escapeHtml(item.problem_id)}</td>
                        <td><span class="badge-${item.difficulty}">${item.difficulty}</span></td>
                        <td>${escapeHtml((item.topics || []).join(", "))}</td>
                        <td>${item.interval_days} day(s)</td>
                        <td>${escapeHtml(item.next_review_at)}</td>
                        <td><span class="status-badge badge-${item.status}">${item.status.toUpperCase()}</span></td>
                        <td>
                            <button class="btn btn-success btn-sm" onclick="logRevisionOutcome('${item.problem_id}', 'easy_recall')" title="Easy Recall (SM-2 bonus)">Easy</button>
                            <button class="btn btn-secondary btn-sm" onclick="logRevisionOutcome('${item.problem_id}', 'effort_recall')" title="Deliberate Effort">Effort</button>
                            <button class="btn btn-secondary btn-sm" onclick="logRevisionOutcome('${item.problem_id}', 'needed_hints')" title="Needed Hints">Hints</button>
                            <button class="btn btn-danger btn-sm" onclick="logRevisionOutcome('${item.problem_id}', 'failed_to_solve')" title="Failed to Solve (reset)">Fail</button>
                            ${item.status === 'paused' ? `
                                <button class="btn btn-secondary btn-sm" onclick="togglePauseRevision('${item.problem_id}', false)">Resume</button>
                            ` : `
                                <button class="btn btn-secondary btn-sm" onclick="togglePauseRevision('${item.problem_id}', true)">Pause</button>
                            `}
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            } catch (err) {
                showAlert("Error loading revision queue", false);
            }
        }

        async function scheduleSelectedRevision() {
            const pid = document.getElementById("revScheduleSelect").value;
            try {
                const res = await fetch("/api/revision/schedule", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ problem_id: pid })
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert(`Problem '${pid}' scheduled for revision!`);
                    reloadRevisionQueue();
                } else {
                    showAlert(data.error || "Failed to schedule revision", false);
                }
            } catch (err) {
                showAlert("Error scheduling revision", false);
            }
        }

        async function logRevisionOutcome(problemId, outcome) {
            try {
                const res = await fetch(`/api/revision/${problemId}/outcome`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ outcome: outcome })
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert(`Outcome recorded for '${problemId}': Next review on ${data.next_review_at}`);
                    reloadRevisionQueue();
                } else {
                    showAlert(data.error || "Failed to record outcome", false);
                }
            } catch (err) {
                showAlert("Error recording outcome", false);
            }
        }

        async function togglePauseRevision(problemId, paused) {
            try {
                const res = await fetch(`/api/revision/${problemId}/pause`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ paused: paused })
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert(`Revision for '${problemId}' ${paused ? 'paused' : 'resumed'}`);
                    reloadRevisionQueue();
                } else {
                    showAlert(data.error || "Update failed", false);
                }
            } catch (err) {
                showAlert("Error updating status", false);
            }
        }

        // Goals & Milestones Functions (Milestone 6.3.13)
        async function reloadGoalsAndMilestones() {
            try {
                // Fetch analytics & goals
                const [goalsRes, analyticsRes, milestonesRes] = await Promise.all([
                    fetch("/api/goals"),
                    fetch("/api/goals/analytics"),
                    fetch("/api/milestones")
                ]);

                const goals = await goalsRes.json();
                const analytics = await analyticsRes.json();
                const milestones = await milestonesRes.json();

                // Update summary cards
                document.getElementById("goalActiveCount").innerText = analytics.active_goals || 0;
                document.getElementById("goalCompletedCount").innerText = analytics.completed_goals || 0;
                document.getElementById("goalMilestonesCount").innerText = (analytics.milestones_unlocked || 0) + "/" + (analytics.total_milestones || 5);
                document.getElementById("goalCompletionRate").innerText = (analytics.completion_rate_pct || 0) + "%";

                // Render Goals list
                const goalsContainer = document.getElementById("goalsListContainer");
                goalsContainer.innerHTML = "";

                if (!goals || goals.length === 0) {
                    goalsContainer.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 12px; background: rgba(30, 41, 59, 0.4); border-radius: 8px;">No active goals yet. Create one above to jumpstart your learning pacing!</div>';
                } else {
                    goals.forEach(g => {
                        const pct = Math.min(100, Math.round(g.percent_completed || 0));
                        const isDone = g.status === 'completed';
                        const isPaused = g.status === 'paused';
                        const badgeColor = isDone ? 'var(--success)' : (isPaused ? 'var(--warning)' : 'var(--primary)');
                        const progressColor = isDone ? '#22c55e' : (pct >= 75 ? '#38bdf8' : (pct >= 40 ? '#fde047' : '#94a3b8'));

                        const card = document.createElement("div");
                        card.style.cssText = "background: rgba(30, 41, 59, 0.7); border: 1px solid var(--border); border-radius: 8px; padding: 14px;";
                        card.innerHTML = `
                            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                                <div>
                                    <span style="font-weight: 600; font-size: 0.95rem; color: var(--text);">${escapeHtml(g.title)}</span>
                                    <span style="font-size: 0.75rem; background: rgba(56, 189, 248, 0.15); color: ${badgeColor}; border: 1px solid ${badgeColor}; padding: 2px 8px; border-radius: 9999px; margin-left: 8px; text-transform: uppercase;">${g.status}</span>
                                    <span style="font-size: 0.75rem; color: var(--text-muted); margin-left: 6px;">Type: ${escapeHtml(g.goal_type)}</span>
                                </div>
                                <div style="display: flex; gap: 6px;">
                                    ${!isDone ? `
                                        <button class="btn btn-secondary btn-sm" onclick="toggleGoalStatus('${g.goal_id}', '${isPaused ? 'active' : 'paused'}')">${isPaused ? 'Resume' : 'Pause'}</button>
                                        <button class="btn btn-success btn-sm" onclick="completeGoalAction('${g.goal_id}')">Mark Complete</button>
                                    ` : ''}
                                    <button class="btn btn-danger btn-sm" onclick="toggleGoalStatus('${g.goal_id}', 'archived')">Archive</button>
                                </div>
                            </div>
                            <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">
                                <span>Progress: ${g.current_value} / ${g.target_value} (${pct}%)</span>
                                <span>${g.days_remaining !== null ? (g.days_remaining + ' days remaining') : 'No deadline'}</span>
                            </div>
                            <div style="background: rgba(15, 23, 42, 0.6); height: 8px; border-radius: 4px; overflow: hidden; margin-bottom: 8px;">
                                <div style="background: ${progressColor}; height: 100%; width: ${pct}%; transition: width 0.3s ease;"></div>
                            </div>
                            ${g.description ? `<div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(g.description)}</div>` : ''}
                        `;
                        goalsContainer.appendChild(card);
                    });
                }

                // Render Milestones
                const milestonesContainer = document.getElementById("milestonesContainer");
                milestonesContainer.innerHTML = "";
                milestones.forEach(m => {
                    const badge = document.createElement("div");
                    const unlocked = m.is_unlocked;
                    badge.style.cssText = `padding: 10px 14px; border-radius: 8px; border: 1px solid ${unlocked ? 'rgba(34, 197, 94, 0.4)' : 'rgba(51, 65, 85, 0.6)'}; background: ${unlocked ? 'rgba(34, 197, 94, 0.1)' : 'rgba(15, 23, 42, 0.4)'}; display: flex; align-items: center; gap: 8px; opacity: ${unlocked ? '1' : '0.5'}; min-width: 220px; flex: 1 1 calc(33% - 10px);`;
                    badge.innerHTML = `
                        <div style="font-size: 1.4rem;">${unlocked ? '🏆' : '🔒'}</div>
                        <div>
                            <div style="font-weight: 600; font-size: 0.85rem; color: ${unlocked ? '#4ade80' : 'var(--text-muted)'};">${escapeHtml(m.title)}</div>
                            <div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(m.description)}</div>
                            ${unlocked ? `<div style="font-size: 0.7rem; color: #86efac; margin-top: 2px;">Unlocked: ${m.unlocked_at ? m.unlocked_at.slice(0, 10) : 'Active'}</div>` : ''}
                        </div>
                    `;
                    milestonesContainer.appendChild(badge);
                });

            } catch (err) {
                console.error("Error loading goals and milestones:", err);
            }
        }

        async function createNewGoal() {
            const title = document.getElementById("goalTitle").value.trim();
            const goal_type = document.getElementById("goalType").value;
            const target_value = parseInt(document.getElementById("goalTarget").value, 10);
            const param = document.getElementById("goalParam").value.trim();
            const days = parseInt(document.getElementById("goalDays").value, 10);

            if (!title) {
                showAlert("Please enter a goal title", false);
                return;
            }

            let target_difficulty = null;
            let target_topic = null;
            if (goal_type === "solve_difficulty") {
                target_difficulty = param.toLowerCase() || "easy";
            } else if (goal_type === "practice_topic") {
                target_topic = param.toLowerCase() || "arrays";
            }

            try {
                const res = await fetch("/api/goals/create", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        title: title,
                        goal_type: goal_type,
                        target_value: target_value,
                        target_difficulty: target_difficulty,
                        target_topic: target_topic,
                        days_to_complete: days || 14
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert(`Goal '${title}' created successfully!`);
                    document.getElementById("goalTitle").value = "";
                    document.getElementById("goalParam").value = "";
                    reloadGoalsAndMilestones();
                } else {
                    showAlert(data.error || "Failed to create goal", false);
                }
            } catch (err) {
                showAlert("Error creating goal", false);
            }
        }

        async function toggleGoalStatus(goalId, newStatus) {
            try {
                const res = await fetch(`/api/goals/${goalId}/status`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ status: newStatus })
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert(`Goal status updated to ${newStatus}`);
                    reloadGoalsAndMilestones();
                } else {
                    showAlert(data.error || "Failed to update status", false);
                }
            } catch (err) {
                showAlert("Error updating goal status", false);
            }
        }

        async function completeGoalAction(goalId) {
            try {
                const res = await fetch(`/api/goals/${goalId}/complete`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" }
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert("Goal marked as completed!");
                    reloadGoalsAndMilestones();
                } else {
                    showAlert(data.error || "Failed to complete goal", false);
                }
            } catch (err) {
                showAlert("Error completing goal", false);
            }
        }

        // Roadmap Functions (Milestone 6.3.14)
        async function reloadRoadmapData() {
            try {
                const [overviewRes, recsRes] = await Promise.all([
                    fetch("/api/roadmap/analytics"),
                    fetch("/api/roadmap/recommendations")
                ]);

                const overview = await overviewRes.json();
                const recs = await recsRes.json();

                // Stats
                document.getElementById("roadmapProgressPct").innerText = (overview.overall_roadmap_progress_pct || 0) + "%";
                document.getElementById("roadmapProficientCount").innerText = `${overview.proficient_topics_count || 0} of ${overview.total_topics || 22} topics proficient`;
                document.getElementById("roadmapLearningCount").innerText = overview.learning_topics_count || 0;
                document.getElementById("roadmapReadyCount").innerText = (overview.ready_to_learn_topics || []).length;
                document.getElementById("roadmapLockedCount").innerText = overview.locked_topics_count || 0;

                // Recommendations list
                const recsList = document.getElementById("roadmapRecsList");
                recsList.innerHTML = "";
                if (!recs || recs.length === 0) {
                    recsList.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">No immediate actions needed. Excellent progress!</div>';
                } else {
                    recs.forEach(r => {
                        const item = document.createElement("div");
                        item.style.cssText = "display: flex; justify-content: space-between; align-items: center; background: rgba(15, 23, 42, 0.6); padding: 8px 12px; border-radius: 6px; font-size: 0.85rem;";
                        item.innerHTML = `
                            <div>
                                <span style="font-weight: 600; color: #38bdf8;">${escapeHtml(r.title)}</span>
                                <span style="color: var(--text-muted); margin-left: 8px;">${escapeHtml(r.rationale)}</span>
                            </div>
                            <span style="font-size: 0.75rem; background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid #0284c7; padding: 2px 6px; border-radius: 4px;">P${r.priority}</span>
                        `;
                        recsList.appendChild(item);
                    });
                }

                // Stages rendering
                const stagesContainer = document.getElementById("roadmapStagesContainer");
                stagesContainer.innerHTML = "";
                const stages = overview.stages || [];
                stages.forEach(stg => {
                    const stageCard = document.createElement("div");
                    stageCard.style.cssText = "background: rgba(30, 41, 59, 0.7); border: 1px solid var(--border); border-radius: 8px; padding: 14px;";

                    const topicsHtml = (stg.topics || []).map(t => {
                        const score = t.mastery_score || 0;
                        let badgeColor = "var(--text-muted)";
                        let statusBg = "rgba(51, 65, 85, 0.4)";
                        if (t.status === "proficient") {
                            badgeColor = "#4ade80";
                            statusBg = "rgba(34, 197, 94, 0.15)";
                        } else if (t.status === "practicing") {
                            badgeColor = "#38bdf8";
                            statusBg = "rgba(56, 189, 248, 0.15)";
                        } else if (t.status === "learning") {
                            badgeColor = "#fde047";
                            statusBg = "rgba(234, 179, 8, 0.15)";
                        } else if (t.status === "not_started") {
                            badgeColor = "#93c5fd";
                            statusBg = "rgba(59, 130, 246, 0.1)";
                        }

                        return `
                            <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid var(--border); border-radius: 6px; padding: 10px; display: flex; flex-direction: column; justify-content: space-between;">
                                <div>
                                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px;">
                                        <span style="font-weight: 600; font-size: 0.9rem; color: var(--text);">${escapeHtml(t.display_name)}</span>
                                        <span style="font-size: 0.7rem; color: ${badgeColor}; background: ${statusBg}; border: 1px solid ${badgeColor}; padding: 1px 6px; border-radius: 9999px; text-transform: uppercase;">${t.status}</span>
                                    </div>
                                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 6px;">
                                        Solved: ${t.distinct_solved} | Attempts: ${t.total_attempts} | Score: ${score}/100
                                    </div>
                                    <div style="background: rgba(30, 41, 59, 0.8); height: 6px; border-radius: 3px; overflow: hidden; margin-bottom: 6px;">
                                        <div style="background: ${badgeColor}; height: 100%; width: ${score}%;"></div>
                                    </div>
                                    <div style="font-size: 0.75rem; color: var(--text-muted); line-height: 1.3;">
                                        ${escapeHtml(t.recommended_action)}
                                    </div>
                                </div>
                                ${t.missing_prerequisites && t.missing_prerequisites.length > 0 ? `
                                    <div style="font-size: 0.7rem; color: #fca5a5; margin-top: 6px;">Needs: ${escapeHtml(t.missing_prerequisites.join(", "))}</div>
                                ` : ''}
                            </div>
                        `;
                    }).join("");

                    stageCard.innerHTML = `
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                            <div>
                                <span style="font-weight: 600; font-size: 1rem; color: var(--primary);">Stage ${stg.stage_id}: ${escapeHtml(stg.stage_name)}</span>
                                <span style="font-size: 0.8rem; color: var(--text-muted); margin-left: 8px;">Avg Mastery: ${stg.average_mastery_score}/100</span>
                            </div>
                            <span style="font-size: 0.85rem; color: #86efac; font-weight: 600;">${stg.completed_topics} / ${stg.total_topics} Proficient (${stg.stage_progress_pct}%)</span>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px;">
                            ${topicsHtml}
                        </div>
                    `;
                    stagesContainer.appendChild(stageCard);
                });

            } catch (err) {
                console.error("Error loading roadmap data:", err);
            }
        }

        // Daily Mission & Focus Mode Functions (Milestone 6.3.15)
        let activeMissionData = null;

        async function reloadDailyMission() {
            try {
                const [missionRes, historyRes, analyticsRes] = await Promise.all([
                    fetch("/api/daily-mission/current"),
                    fetch("/api/daily-mission/history"),
                    fetch("/api/daily-mission/analytics")
                ]);

                const mission = await missionRes.json();
                const history = await historyRes.json();
                const analytics = await analyticsRes.json();

                activeMissionData = mission;

                // Stats
                const statusStr = mission ? mission.status : "NONE";
                document.getElementById("missionStatusText").innerText = statusStr;
                document.getElementById("missionDateSub").innerText = mission ? mission.mission_date : "Today";
                document.getElementById("missionProgressPct").innerText = (mission ? mission.completion_percentage : 0) + "%";
                document.getElementById("missionTasksRatio").innerText = `${mission ? mission.completed_tasks_count : 0} of ${mission ? mission.total_tasks : 0} tasks completed`;
                document.getElementById("missionEstTime").innerText = (mission ? mission.estimated_duration_min : 0) + " min";
                document.getElementById("missionStreakDays").innerText = (analytics.current_streak_days || 0) + " Days";

                // Focus Mode Card
                const btnContainer = document.getElementById("missionActionButtons");
                btnContainer.innerHTML = "";

                if (!mission) {
                    document.getElementById("currentTaskTitle").innerText = "No Active Mission";
                    document.getElementById("currentTaskDesc").innerText = "Click 'Generate Mission' above to assemble your personalized daily practice.";
                    btnContainer.innerHTML = '<button class="btn btn-primary btn-sm" onclick="generateNewMission()">Generate Mission</button>';
                } else if (mission.status === "completed") {
                    document.getElementById("currentTaskTitle").innerText = "Mission Accomplished! 🏆";
                    document.getElementById("currentTaskDesc").innerText = `Great job! All ${mission.total_tasks} tasks completed. Practice streak is maintained.`;
                    btnContainer.innerHTML = '<button class="btn btn-secondary btn-sm" onclick="generateNewMission(true)">New Mission</button>';
                } else {
                    // Mission is created, in_progress, or paused
                    const curTask = mission.current_task;
                    if (curTask) {
                        document.getElementById("currentTaskTitle").innerText = `${curTask.sequence_order}. ${curTask.title}`;
                        document.getElementById("currentTaskDesc").innerText = curTask.description + " — " + curTask.selection_reason;
                        document.getElementById("currentTaskTopic").innerText = "Topic: " + (curTask.topic || "General");
                        document.getElementById("currentTaskDiff").innerText = "Difficulty: " + (curTask.difficulty || "Easy");
                        document.getElementById("currentTaskEst").innerText = `Est: ${curTask.estimated_duration_min} min`;

                        if (mission.status === "paused") {
                            btnContainer.innerHTML = `
                                <button class="btn btn-success btn-sm" onclick="resumeMissionAction()">Resume Mission</button>
                                <button class="btn btn-danger btn-sm" onclick="cancelMissionAction()">Cancel</button>
                            `;
                        } else if (curTask.status === "in_progress") {
                            btnContainer.innerHTML = `
                                <button class="btn btn-success btn-sm" onclick="completeTaskAction('${curTask.task_id}')">Complete Task</button>
                                <button class="btn btn-secondary btn-sm" onclick="skipTaskAction('${curTask.task_id}')">Skip Task</button>
                                <button class="btn btn-secondary btn-sm" onclick="pauseMissionAction()">Pause</button>
                            `;
                        } else {
                            btnContainer.innerHTML = `
                                <button class="btn btn-primary btn-sm" onclick="startTaskAction('${curTask.task_id}')">Start Task</button>
                                <button class="btn btn-secondary btn-sm" onclick="skipTaskAction('${curTask.task_id}')">Skip</button>
                                <button class="btn btn-secondary btn-sm" onclick="pauseMissionAction()">Pause</button>
                            `;
                        }
                    } else {
                        document.getElementById("currentTaskTitle").innerText = mission.title;
                        document.getElementById("currentTaskDesc").innerText = mission.summary;
                        btnContainer.innerHTML = `
                            <button class="btn btn-success btn-sm" onclick="startDailyMissionAction()">Start Mission</button>
                        `;
                    }
                }

                // Tasks table
                const tbody = document.getElementById("missionTasksTableBody");
                tbody.innerHTML = "";
                if (!mission || !mission.tasks || mission.tasks.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted);">(No mission tasks loaded)</td></tr>';
                } else {
                    mission.tasks.forEach(t => {
                        let badgeColor = "var(--text-muted)";
                        if (t.status === "completed") badgeColor = "#4ade80";
                        else if (t.status === "in_progress") badgeColor = "#38bdf8";
                        else if (t.status === "skipped") badgeColor = "#fca5a5";

                        const tr = document.createElement("tr");
                        tr.innerHTML = `
                            <td>${t.sequence_order}</td>
                            <td style="font-weight: 600; color: var(--text);">${escapeHtml(t.title)}</td>
                            <td style="color: var(--text-muted); font-size: 0.8rem;">${escapeHtml(t.task_type.replace(/_/g, ' '))}</td>
                            <td>${escapeHtml(t.topic || '-')}</td>
                            <td>${t.difficulty ? `<span class="badge-${t.difficulty.toLowerCase()}">${t.difficulty}</span>` : '-'}</td>
                            <td>${t.estimated_duration_min}m</td>
                            <td><span style="color: ${badgeColor}; font-weight: 600; text-transform: uppercase; font-size: 0.75rem;">${t.status}</span></td>
                            <td>
                                ${t.status === "pending" ? `<button class="btn btn-primary btn-sm" onclick="startTaskAction('${t.task_id}')">Start</button>` : ''}
                                ${t.status === "in_progress" ? `<button class="btn btn-success btn-sm" onclick="completeTaskAction('${t.task_id}')">Complete</button>` : ''}
                                ${t.status !== "completed" && t.status !== "skipped" ? `<button class="btn btn-secondary btn-sm" onclick="skipTaskAction('${t.task_id}')">Skip</button>` : ''}
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                }

                // History rendering
                const histList = document.getElementById("missionHistoryList");
                histList.innerHTML = "";
                if (!history || history.length === 0) {
                    histList.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">No past missions found.</div>';
                } else {
                    history.forEach(m => {
                        const hItem = document.createElement("div");
                        hItem.style.cssText = "display: flex; justify-content: space-between; align-items: center; background: rgba(30, 41, 59, 0.5); padding: 8px 12px; border-radius: 6px; font-size: 0.85rem;";
                        hItem.innerHTML = `
                            <div>
                                <span style="font-weight: 600; color: var(--text);">${escapeHtml(m.mission_date)}: ${escapeHtml(m.title)}</span>
                                <span style="color: var(--text-muted); margin-left: 8px;">(${m.completed_tasks_count}/${m.total_tasks} tasks)</span>
                            </div>
                            <span style="font-size: 0.75rem; text-transform: uppercase; color: ${m.status === 'completed' ? '#4ade80' : 'var(--text-muted)'};">${m.status}</span>
                        `;
                        histList.appendChild(hItem);
                    });
                }

            } catch (err) {
                console.error("Error loading mission data:", err);
            }
        }

        async function generateNewMission(force = false) {
            try {
                const res = await fetch("/api/daily-mission/generate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ force_new: force })
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert("Daily mission generated successfully!");
                    reloadDailyMission();
                } else {
                    showAlert(data.error || "Failed to generate mission", false);
                }
            } catch (err) {
                showAlert("Error generating mission", false);
            }
        }

        async function startDailyMissionAction() {
            try {
                const res = await fetch("/api/daily-mission/start", { method: "POST" });
                const data = await res.json();
                if (res.ok) {
                    showAlert("Focus Mode Activated: Mission started!");
                    reloadDailyMission();
                } else {
                    showAlert(data.error || "Failed to start mission", false);
                }
            } catch (err) {
                showAlert("Error starting mission", false);
            }
        }

        async function startTaskAction(taskId) {
            try {
                const res = await fetch(`/api/daily-mission/task/${taskId}/start`, { method: "POST" });
                const data = await res.json();
                if (res.ok) {
                    showAlert("Task activated!");
                    reloadDailyMission();
                } else {
                    showAlert(data.error || "Failed to start task", false);
                }
            } catch (err) {
                showAlert("Error starting task", false);
            }
        }

        async function completeTaskAction(taskId) {
            try {
                const res = await fetch(`/api/daily-mission/task/${taskId}/complete`, { method: "POST" });
                const data = await res.json();
                if (res.ok) {
                    showAlert("Task completed! Progress recorded.");
                    reloadDailyMission();
                } else {
                    showAlert(data.error || "Failed to complete task", false);
                }
            } catch (err) {
                showAlert("Error completing task", false);
            }
        }

        async function skipTaskAction(taskId) {
            const reason = prompt("Reason for skipping task:", "Practicing other topic");
            if (reason === null) return;
            try {
                const res = await fetch(`/api/daily-mission/task/${taskId}/skip`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ reason: reason })
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert("Task skipped.");
                    reloadDailyMission();
                } else {
                    showAlert(data.error || "Failed to skip task", false);
                }
            } catch (err) {
                showAlert("Error skipping task", false);
            }
        }

        async function pauseMissionAction() {
            try {
                const res = await fetch("/api/daily-mission/pause", { method: "POST" });
                const data = await res.json();
                if (res.ok) {
                    showAlert("Mission paused.");
                    reloadDailyMission();
                } else {
                    showAlert(data.error || "Failed to pause mission", false);
                }
            } catch (err) {
                showAlert("Error pausing mission", false);
            }
        }

        async function resumeMissionAction() {
            try {
                const res = await fetch("/api/daily-mission/resume", { method: "POST" });
                const data = await res.json();
                if (res.ok) {
                    showAlert("Mission resumed!");
                    reloadDailyMission();
                } else {
                    showAlert(data.error || "Failed to resume mission", false);
                }
            } catch (err) {
                showAlert("Error resuming mission", false);
            }
        }

        async function cancelMissionAction() {
            if (!confirm("Are you sure you want to cancel today's mission?")) return;
            try {
                const res = await fetch("/api/daily-mission/cancel", { method: "POST" });
                const data = await res.json();
                if (res.ok) {
                    showAlert("Mission cancelled.");
                    reloadDailyMission();
                } else {
                    showAlert(data.error || "Failed to cancel mission", false);
                }
            } catch (err) {
                showAlert("Error cancelling mission", false);
            }
        }

        // Workspace Integration (Milestone 6.3.16)
        let activeWorkspacePid = "two-sum";
        let activeWorkspaceMissionId = null;
        let activeWorkspaceTaskId = null;
        let lastWorkspaceRunId = null;

        async function openProblemInWorkspace(problemId, missionId = null, taskId = null) {
            activeWorkspacePid = problemId;
            activeWorkspaceMissionId = missionId;
            activeWorkspaceTaskId = taskId;
            lastWorkspaceRunId = null;

            document.getElementById("btnConfirmTaskCompletion").style.display = "none";
            document.getElementById("wsResultCard").style.display = "none";

            // Scroll down to workspace card
            document.getElementById("codingWorkspaceCard").scrollIntoView({ behavior: 'smooth' });

            const lang = document.getElementById("wsLanguageSelect").value || "python";

            try {
                let url = `/api/workspace/problem/${problemId}`;
                if (missionId && taskId) {
                    url += `?mission_id=${missionId}&task_id=${taskId}`;
                }
                const [ctxRes, draftRes] = await Promise.all([
                    fetch(url),
                    fetch(`/api/workspace/draft/${problemId}?language=${lang}`)
                ]);

                const ctx = await ctxRes.json();
                const draft = await draftRes.json();

                // Populate Context Panel
                document.getElementById("wsProblemTitle").innerText = ctx.title || problemId;
                const diffBadge = document.getElementById("wsProblemDiff");
                diffBadge.className = `badge-${(ctx.difficulty || "medium").toLowerCase()}`;
                diffBadge.innerText = ctx.difficulty || "Medium";
                diffBadge.style.display = "inline-block";
                document.getElementById("wsProblemTopics").innerText = "Topics: " + (ctx.topics || []).join(", ");

                const reasonBanner = document.getElementById("wsTaskReasonBanner");
                if (ctx.task_selection_reason) {
                    reasonBanner.innerText = "Mission Goal: " + ctx.task_selection_reason;
                    reasonBanner.style.display = "block";
                } else {
                    reasonBanner.style.display = "none";
                }

                document.getElementById("wsProblemDesc").innerText = ctx.description || "No description.";

                const exContainer = document.getElementById("wsExamplesContainer");
                exContainer.innerHTML = "";
                if (ctx.examples && ctx.examples.length > 0) {
                    exContainer.innerHTML = "<strong style='color: var(--text);'>Examples:</strong>";
                    ctx.examples.forEach((ex, idx) => {
                        const exBox = document.createElement("div");
                        exBox.style.cssText = "background: rgba(30, 41, 59, 0.4); border-radius: 4px; padding: 6px; margin-top: 4px; font-family: monospace;";
                        exBox.innerHTML = `Input: ${escapeHtml(JSON.stringify(ex.input))}<br>Output: ${escapeHtml(JSON.stringify(ex.output))}`;
                        exContainer.appendChild(exBox);
                    });
                }

                // Populate Editor with Draft or Starter Code
                const editor = document.getElementById("wsCodeEditor");
                if (draft && draft.code) {
                    editor.value = draft.code;
                    document.getElementById("wsDraftSavedStatus").innerText = `Draft loaded (${draft.updated_at.slice(11, 19)})`;
                } else {
                    const starter = (ctx.starter_code && ctx.starter_code[lang]) || "";
                    editor.value = starter;
                    document.getElementById("wsDraftSavedStatus").innerText = "Default starter template";
                }

            } catch (err) {
                console.error("Error opening workspace:", err);
            }
        }

        async function switchWorkspaceLanguage() {
            if (activeWorkspacePid) {
                const lang = document.getElementById("wsLanguageSelect").value || "python";
                const draftRes = await fetch(`/api/workspace/draft/${activeWorkspacePid}?language=${lang}`);
                const draft = await draftRes.json();
                const editor = document.getElementById("wsCodeEditor");
                if (draft && draft.code) {
                    editor.value = draft.code;
                    document.getElementById("wsDraftSavedStatus").innerText = `Draft loaded (${draft.updated_at.slice(11, 19)})`;
                } else {
                    editor.value = "";
                    document.getElementById("wsDraftSavedStatus").innerText = "Empty draft";
                }
            }
        }

        async function saveCurrentDraft() {
            if (!activeWorkspacePid) return;
            const lang = document.getElementById("wsLanguageSelect").value || "python";
            const code = document.getElementById("wsCodeEditor").value;
            try {
                const res = await fetch("/api/workspace/draft/save", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        problem_id: activeWorkspacePid,
                        language: lang,
                        code: code
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert("Draft saved locally.");
                    document.getElementById("wsDraftSavedStatus").innerText = "Draft saved just now";
                } else {
                    showAlert(data.error || "Failed to save draft", false);
                }
            } catch (err) {
                showAlert("Error saving draft", false);
            }
        }

        async function runWorkspaceCode() {
            if (!activeWorkspacePid) return;
            const lang = document.getElementById("wsLanguageSelect").value || "python";
            const code = document.getElementById("wsCodeEditor").value;

            document.getElementById("wsResultCard").style.display = "block";
            document.getElementById("wsResultStatusBadge").innerText = "RUNNING...";
            document.getElementById("wsResultStatusBadge").style.background = "#334155";
            document.getElementById("wsResultFeedback").innerText = "Executing in local test harness...";
            document.getElementById("wsResultDiagnostics").style.display = "none";
            document.getElementById("wsCoachGuidance").style.display = "none";

            try {
                const res = await fetch("/api/workspace/run", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        problem_id: activeWorkspacePid,
                        language: lang,
                        code: code,
                        mission_id: activeWorkspaceMissionId,
                        task_id: activeWorkspaceTaskId
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    lastWorkspaceRunId = data.run_id;
                    const badge = document.getElementById("wsResultStatusBadge");
                    badge.innerText = data.status.toUpperCase();
                    if (data.status === "passed") {
                        badge.style.background = "rgba(34, 197, 94, 0.2)";
                        badge.style.color = "#4ade80";
                        badge.style.border = "1px solid #22c55e";
                        if (activeWorkspaceMissionId && activeWorkspaceTaskId) {
                            document.getElementById("btnConfirmTaskCompletion").style.display = "inline-block";
                        }
                    } else {
                        badge.style.background = "rgba(239, 68, 68, 0.2)";
                        badge.style.color = "#f87171";
                        badge.style.border = "1px solid #ef4444";
                        document.getElementById("btnConfirmTaskCompletion").style.display = "none";
                    }

                    document.getElementById("wsResultFeedback").innerText = `Passed: ${data.passed_count}/${data.total_tests} tests. ${data.suggested_next_action}`;

                    const diag = document.getElementById("wsResultDiagnostics");
                    if (data.compile_error || data.execution_error || data.failed_test_detail) {
                        diag.innerText = data.compile_error || data.execution_error || JSON.stringify(data.failed_test_detail, null, 2);
                        diag.style.display = "block";
                    }

                    const coachBox = document.getElementById("wsCoachGuidance");
                    if (data.coach_feedback) {
                        coachBox.innerText = data.coach_feedback;
                        coachBox.style.display = "block";
                    }

                } else {
                    showAlert(data.error || "Execution failed", false);
                }
            } catch (err) {
                showAlert("Error running test suite", false);
            }
        }

        async function confirmTaskCompletionAction() {
            if (!activeWorkspaceMissionId || !activeWorkspaceTaskId) return;
            try {
                const res = await fetch(`/api/daily-mission/task/${activeWorkspaceTaskId}/complete`, { method: "POST" });
                const data = await res.json();
                if (res.ok) {
                    showAlert("Mission task successfully confirmed as completed! 🏆");
                    document.getElementById("btnConfirmTaskCompletion").style.display = "none";
                    reloadDailyMission();
                    returnToDailyMission();
                } else {
                    showAlert(data.error || "Failed to confirm task completion", false);
                }
            } catch (err) {
                showAlert("Error confirming task completion", false);
            }
        }

        function returnToDailyMission() {
            document.getElementById("focusModeContainer").scrollIntoView({ behavior: 'smooth' });
        }

        // Solution Review JS (Milestone 6.3.17)
        let lastSolutionReviewId = null;

        async function analyzeCurrentSolutionReview() {
            if (!activeWorkspacePid) return;
            const lang = document.getElementById("wsLanguageSelect").value || "python";
            const code = document.getElementById("wsCodeEditor").value;

            try {
                const res = await fetch("/api/workspace/review", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        problem_id: activeWorkspacePid,
                        language: lang,
                        code: code,
                        linked_run_id: lastWorkspaceRunId,
                        learner_time: document.getElementById("srLearnerTimeInput").value,
                        learner_space: document.getElementById("srLearnerSpaceInput").value
                    })
                });
                const rev = await res.json();
                if (res.ok) {
                    lastSolutionReviewId = rev.review_id;
                    renderSolutionReview(rev);
                    showAlert("Solution review completed.");
                } else {
                    showAlert(rev.error || "Review failed", false);
                }
            } catch (err) {
                showAlert("Error analyzing code quality", false);
            }
        }

        function renderSolutionReview(rev) {
            document.getElementById("solutionReviewEmptyText").style.display = "none";
            document.getElementById("solutionReviewOutput").style.display = "block";

            const qm = rev.quality_metrics;
            const cr = rev.complexity_review;

            document.getElementById("srReadabilityScore").innerText = `${qm.readability_score}/100`;
            document.getElementById("srStructuralScore").innerText = `${qm.structural_score}/100`;
            document.getElementById("srNestingText").innerText = `Max depth: ${qm.max_nesting_depth} (${qm.lines_of_code} LOC)`;
            document.getElementById("srEstTime").innerText = cr.estimated_time_complexity;
            document.getElementById("srEstSpace").innerText = cr.estimated_space_complexity;

            if (cr.time_comparison) {
                document.getElementById("srComplexityCompareResult").innerText = cr.time_comparison;
            } else {
                document.getElementById("srComplexityCompareResult").innerText = "";
            }

            const sugList = document.getElementById("srSuggestionsList");
            sugList.innerHTML = "";
            (rev.improvement_suggestions || []).forEach(s => {
                const li = document.createElement("li");
                li.innerText = s;
                sugList.appendChild(li);
            });

            document.getElementById("srAttemptCompText").innerText = rev.attempt_comparison.summary_of_changes || "First recorded attempt.";
            document.getElementById("srReflectionText").innerText = (rev.reflection_prompts && rev.reflection_prompts[0]) || "Evaluate potential time-space tradeoffs.";
        }

        async function submitComplexitySelfAssessment() {
            if (!activeWorkspacePid) return;
            const lang = document.getElementById("wsLanguageSelect").value || "python";
            const code = document.getElementById("wsCodeEditor").value;
            const t = document.getElementById("srLearnerTimeInput").value;
            const s = document.getElementById("srLearnerSpaceInput").value;

            try {
                const res = await fetch("/api/workspace/review/complexity", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        problem_id: activeWorkspacePid,
                        language: lang,
                        code: code,
                        learner_time: t,
                        learner_space: s
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    document.getElementById("srComplexityCompareResult").innerText = data.time_comparison || "Estimate recorded.";
                    showAlert("Complexity comparison updated.");
                } else {
                    showAlert(data.error || "Complexity check failed", false);
                }
            } catch (err) {
                showAlert("Error submitting complexity estimate", false);
            }
        }

        // Portfolio Management Functions (Milestone 6.3.18)
        function toggleCustomDatePreset() {
            const preset = document.getElementById("portPreset").value;
            const row = document.getElementById("portCustomDateRow");
            if (row) {
                row.style.display = preset === "custom" ? "grid" : "none";
            }
        }

        async function reloadPortfolioPreview() {
            try {
                const style = document.getElementById("portStyle") ? document.getElementById("portStyle").value : "developer_portfolio";
                const preset = document.getElementById("portPreset") ? document.getElementById("portPreset").value : "all_time";
                const startDate = document.getElementById("portStartDate") ? document.getElementById("portStartDate").value : "";
                const endDate = document.getElementById("portEndDate") ? document.getElementById("portEndDate").value : "";
                const name = document.getElementById("portLearnerName") ? document.getElementById("portLearnerName").value : "";
                const title = document.getElementById("portTitle") ? document.getElementById("portTitle").value : "";

                let url = `/api/portfolio/preview?report_style=${encodeURIComponent(style)}&date_preset=${encodeURIComponent(preset)}`;
                if (preset === "custom" && startDate) {
                    url += `&start_date=${encodeURIComponent(startDate)}`;
                    if (endDate) url += `&end_date=${encodeURIComponent(endDate)}`;
                }

                const res = await fetch(url);
                if (!res.ok) return;
                const data = await res.json();
                const report = data.report || data;

                if (report.config) {
                    if (document.getElementById("portLearnerName") && (!name || name === "Learner")) {
                        document.getElementById("portLearnerName").value = report.config.learner_name || "Learner";
                    }
                    if (document.getElementById("portTitle") && (!title || title === "Developer Learning Portfolio")) {
                        document.getElementById("portTitle").value = report.config.portfolio_title || "Developer Learning Portfolio";
                    }
                }

                if (document.getElementById("portExecutiveSummary")) {
                    document.getElementById("portExecutiveSummary").textContent = report.executive_summary || "No verified evidence recorded.";
                }

                if (report.coding_stats) {
                    const cs = report.coding_stats;
                    if (document.getElementById("portSolvedStat")) document.getElementById("portSolvedStat").textContent = cs.total_verified_solved;
                    if (document.getElementById("portDifficultyBreakdown")) document.getElementById("portDifficultyBreakdown").textContent = `${cs.easy_count}E / ${cs.medium_count}M / ${cs.hard_count}H`;
                }

                if (report.dsa_mastery) {
                    const dm = report.dsa_mastery;
                    if (document.getElementById("portRoadmapProgressStat")) document.getElementById("portRoadmapProgressStat").textContent = `${dm.overall_roadmap_progress_pct}%`;
                    if (document.getElementById("portProficientTopicsStat")) document.getElementById("portProficientTopicsStat").textContent = `${dm.proficient_topics_count} of ${dm.total_roadmap_topics} Topics Proficient`;
                }

                if (report.consistency) {
                    const cn = report.consistency;
                    if (document.getElementById("portConsistencyStat")) document.getElementById("portConsistencyStat").textContent = `${cn.active_streak_days} Days`;
                    if (document.getElementById("portMissionsStat")) document.getElementById("portMissionsStat").textContent = `${cn.completed_missions_count} Missions Completed`;
                }

                if (report.solution_quality && report.goals) {
                    const sq = report.solution_quality;
                    const g = report.goals;
                    if (document.getElementById("portReadabilityStat")) document.getElementById("portReadabilityStat").textContent = `${sq.average_readability_score}/100`;
                    if (document.getElementById("portMilestonesStat")) document.getElementById("portMilestonesStat").textContent = `${g.unlocked_achievements ? g.unlocked_achievements.length : 0} Milestones Unlocked`;
                }

                reloadPortfolioHistory();
            } catch (err) {
                console.error("Failed to load portfolio preview:", err);
            }
        }

        async function savePortfolioConfig() {
            try {
                const name = document.getElementById("portLearnerName").value.trim();
                const title = document.getElementById("portTitle").value.trim();
                const style = document.getElementById("portStyle").value;
                const preset = document.getElementById("portPreset").value;
                const startDate = document.getElementById("portStartDate").value;
                const endDate = document.getElementById("portEndDate").value;

                const payload = {
                    learner_name: name || "Learner",
                    portfolio_title: title || "Developer Learning Portfolio",
                    report_style: style,
                    date_range_preset: preset,
                    start_date: preset === "custom" ? startDate : null,
                    end_date: preset === "custom" ? endDate : null
                };

                const res = await fetch("/api/portfolio/config", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    showToast("Profile configuration saved successfully!", "success");
                    reloadPortfolioPreview();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to save config", "error");
                }
            } catch (err) {
                showToast("Error saving profile config", "error");
            }
        }

        async function exportPortfolio(format) {
            try {
                const style = document.getElementById("portStyle").value;
                const preset = document.getElementById("portPreset").value;
                const startDate = document.getElementById("portStartDate").value;
                const endDate = document.getElementById("portEndDate").value;
                const name = document.getElementById("portLearnerName").value.trim();
                const title = document.getElementById("portTitle").value.trim();

                const payload = {
                    format: format,
                    report_style: style,
                    date_range_preset: preset,
                    start_date: preset === "custom" ? startDate : null,
                    end_date: preset === "custom" ? endDate : null,
                    learner_name: name,
                    portfolio_title: title
                };

                const res = await fetch("/api/portfolio/generate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    const data = await res.json();
                    showToast(`Exported ${data.filename} (${data.format.toUpperCase()})`, "success");
                    reloadPortfolioHistory();
                    if (data.download_url) {
                        window.open(data.download_url, "_blank");
                    }
                } else {
                    const err = await res.json();
                    showToast(err.error || "Export failed", "error");
                }
            } catch (err) {
                showToast("Error generating export", "error");
            }
        }

        async function reloadPortfolioHistory() {
            try {
                const res = await fetch("/api/portfolio/history?limit=5");
                if (!res.ok) return;
                const history = await res.json();
                const container = document.getElementById("portExportHistoryList");
                if (!container) return;

                if (!history || history.length === 0) {
                    container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">No exported reports yet.</div>';
                    return;
                }

                container.innerHTML = history.map(item => `
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.05);">
                        <div>
                            <span style="font-weight: 600; color: var(--text);">${item.filename}</span>
                            <span style="color: var(--text-muted); font-size: 0.75rem; margin-left: 8px;">${item.generated_at ? item.generated_at.substring(0, 10) : ""}</span>
                            <span class="status-badge" style="background: rgba(56, 189, 248, 0.2); color: var(--primary); font-size: 0.7rem; margin-left: 6px;">${item.format.toUpperCase()}</span>
                        </div>
                        <a href="/api/portfolio/export/${item.export_id}" class="btn btn-secondary btn-sm" download style="padding: 2px 8px; font-size: 0.75rem;">Download</a>
                    </div>
                `).join("");
            } catch (err) {
                console.error("Failed to load export history:", err);
            }
        }

        // Mock Interview Management Functions (Milestone 6.3.19)
        let activeInterviewId = null;
        let activeInterviewExpiresAt = null;
        let interviewTimerInterval = null;
        let activeInterviewCurrentProblem = null;

        function updateInterviewTimer() {
            if (!activeInterviewExpiresAt) return;
            const now = new Date();
            const expires = new Date(activeInterviewExpiresAt);
            const diffMs = expires - now;

            const timerEl = document.getElementById("interviewTimerDisplay");
            if (!timerEl) return;

            if (diffMs <= 0) {
                timerEl.textContent = "00:00 (Time Expired)";
                timerEl.style.color = "var(--danger)";
                return;
            }

            const totalSec = Math.floor(diffMs / 1000);
            const mins = Math.floor(totalSec / 60);
            const secs = totalSec % 60;
            timerEl.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;

            if (mins < 5) {
                timerEl.style.color = "var(--danger)";
            } else if (mins < 10) {
                timerEl.style.color = "var(--warning)";
            } else {
                timerEl.style.color = "var(--success)";
            }
        }

        async function reloadInterviewState() {
            try {
                const res = await fetch("/api/interview");
                if (!res.ok) return;
                const data = await res.json();

                const badge = document.getElementById("interviewActiveBadge");
                const configView = document.getElementById("interviewConfigView");
                const activeView = document.getElementById("interviewActiveView");
                const reportView = document.getElementById("interviewReportView");

                if (data.status === "in_progress" && data.interview_id) {
                    activeInterviewId = data.interview_id;
                    activeInterviewExpiresAt = data.expires_at;

                    if (badge) {
                        badge.textContent = `In Progress (${(data.track || '').toUpperCase()})`;
                        badge.style.background = "rgba(34, 197, 94, 0.2)";
                        badge.style.color = "var(--success)";
                    }
                    if (configView) configView.style.display = "none";
                    if (reportView) reportView.style.display = "none";
                    if (activeView) activeView.style.display = "block";

                    document.getElementById("activeInterviewTitle").textContent = data.title;
                    document.getElementById("activeTrackBadge").textContent = (data.track || '').toUpperCase();

                    // Start timer ticker
                    if (interviewTimerInterval) clearInterval(interviewTimerInterval);
                    updateInterviewTimer();
                    interviewTimerInterval = setInterval(updateInterviewTimer, 1000);

                    // Render problem steps
                    renderInterviewProblemSteps(data.problems, data.current_problem_index);
                    loadInterviewProblem(data.current_problem_index);
                } else {
                    activeInterviewId = null;
                    activeInterviewExpiresAt = null;
                    if (interviewTimerInterval) clearInterval(interviewTimerInterval);

                    if (badge) {
                        badge.textContent = "No Active Interview";
                        badge.style.background = "rgba(148, 163, 184, 0.2)";
                        badge.style.color = "#94a3b8";
                    }
                    if (configView) configView.style.display = "block";
                    if (activeView) activeView.style.display = "none";
                }
            } catch (err) {
                console.error("Failed to load interview state:", err);
            }
        }

        function renderInterviewProblemSteps(problems, currentIndex) {
            const container = document.getElementById("interviewProblemSteps");
            if (!container || !problems) return;

            container.innerHTML = problems.map((p, idx) => {
                const isCurrent = (idx === currentIndex);
                const isPassed = (p.status === "passed");
                let bg = isCurrent ? "var(--primary)" : (isPassed ? "var(--success)" : "rgba(30, 41, 59, 0.6)");
                let color = isCurrent ? "#0f172a" : "#f8fafc";
                return `
                    <button class="btn btn-sm" onclick="loadInterviewProblem(${idx})" style="background: ${bg}; color: ${color}; font-weight: 600; padding: 4px 12px;">
                        #${idx + 1}: ${p.title} ${isPassed ? '✓' : ''}
                    </button>
                `;
            }).join("");
        }

        async function loadInterviewProblem(index) {
            if (!activeInterviewId) return;
            try {
                const res = await fetch(`/api/interview/${activeInterviewId}/problem?index=${index}`);
                if (!res.ok) return;
                const ctx = await res.json();
                activeInterviewCurrentProblem = ctx;

                document.getElementById("activeProblemTitle").textContent = ctx.title;
                const diffBadge = document.getElementById("activeProblemDiff");
                diffBadge.textContent = ctx.difficulty.toUpperCase();
                diffBadge.className = `badge-${ctx.difficulty.toLowerCase()}`;

                document.getElementById("activeProblemTopics").textContent = "Topics: " + (ctx.topics || []).join(", ");
                document.getElementById("activeProblemDesc").textContent = ctx.description;

                // Examples
                const exBox = document.getElementById("activeProblemExamples");
                if (ctx.examples && ctx.examples.length > 0) {
                    exBox.innerHTML = ctx.examples.map(ex => `Input: ${JSON.stringify(ex.input || ex.args || '')}\nOutput: ${JSON.stringify(ex.output || ex.expected || '')}`).join("\n\n");
                } else {
                    exBox.textContent = "See problem description for test examples.";
                }

                // Constraints
                const constrBox = document.getElementById("activeProblemConstraints");
                if (ctx.constraints && ctx.constraints.length > 0) {
                    constrBox.innerHTML = ctx.constraints.map(c => `• ${c}`).join("<br>");
                } else {
                    constrBox.textContent = "Standard time and memory constraints apply.";
                }

                // Fetch draft or default starter code
                const draftRes = await fetch(`/api/workspace/draft/${ctx.problem_id}?language=python`);
                let draftCode = "";
                if (draftRes.ok) {
                    const draftData = await draftRes.json();
                    draftCode = draftData.code || "";
                }
                if (!draftCode && ctx.starter_code) {
                    draftCode = ctx.starter_code.python || Object.values(ctx.starter_code)[0] || "";
                }
                document.getElementById("interviewCodeEditor").value = draftCode;

                // Clear previous run feedback
                const feedbackEl = document.getElementById("interviewRunFeedback");
                if (feedbackEl) feedbackEl.style.display = "none";
            } catch (err) {
                console.error("Failed to load interview problem:", err);
            }
        }

        async function startMockInterview() {
            try {
                const track = document.getElementById("mockTrack").value;
                const duration = parseInt(document.getElementById("mockDuration").value);
                const language = document.getElementById("mockLanguage").value;
                const problemCount = parseInt(document.getElementById("mockProblemCount").value);

                const payload = {
                    track: track,
                    duration_minutes: duration,
                    language: language,
                    problem_count: problemCount
                };

                const res = await fetch("/api/interview/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });

                if (res.ok) {
                    showToast("Mock interview started! Good luck.", "success");
                    await reloadInterviewState();
                    reloadInterviewHistory();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to start interview", "error");
                }
            } catch (err) {
                showToast("Error starting interview session", "error");
            }
        }

        async function saveInterviewDraft() {
            if (!activeInterviewId) return;
            try {
                const code = document.getElementById("interviewCodeEditor").value;
                const res = await fetch(`/api/interview/${activeInterviewId}/draft`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ code: code })
                });
                if (res.ok) {
                    showToast("Draft saved locally", "success");
                }
            } catch (err) {
                showToast("Failed to save draft", "error");
            }
        }

        async function submitInterviewSolution() {
            if (!activeInterviewId) return;
            try {
                const code = document.getElementById("interviewCodeEditor").value;
                const feedbackEl = document.getElementById("interviewRunFeedback");
                if (feedbackEl) {
                    feedbackEl.style.display = "block";
                    feedbackEl.innerHTML = '<span style="color: var(--primary);">Running tests against local judge...</span>';
                }

                const res = await fetch(`/api/interview/${activeInterviewId}/submit`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ code: code })
                });

                if (res.ok) {
                    const sub = await res.json();
                    let statusColor = sub.status === "passed" ? "var(--success)" : "var(--danger)";
                    let statusText = sub.status === "passed" ? "PASSED (All test cases passed)" : `FAILED (${sub.status.toUpperCase()})`;

                    if (feedbackEl) {
                        feedbackEl.innerHTML = `
                            <div style="font-weight: 700; color: ${statusColor}; margin-bottom: 4px;">${statusText}</div>
                            <div style="color: var(--text-muted);">Tests: <strong>${sub.passed_count}/${sub.total_tests}</strong> passed | Readability: <strong>${sub.readability_score}/100</strong> | Big-O Time: <strong>${sub.estimated_time_complexity}</strong></div>
                            ${sub.error_detail ? `<div style="color: #f87171; margin-top: 4px; font-family: monospace; font-size: 0.8rem;">${sub.error_detail}</div>` : ''}
                        `;
                    }
                    showToast(sub.status === "passed" ? "Solution passed all tests!" : "Test run finished with errors", sub.status === "passed" ? "success" : "warning");
                    await reloadInterviewState();
                } else {
                    const err = await res.json();
                    if (feedbackEl) feedbackEl.innerHTML = `<span style="color: var(--danger);">${err.error || "Submission failed"}</span>`;
                }
            } catch (err) {
                showToast("Error submitting solution", "error");
            }
        }

        async function advanceInterviewProblem() {
            if (!activeInterviewId) return;
            try {
                const res = await fetch(`/api/interview/${activeInterviewId}/advance`, {
                    method: "POST"
                });
                if (res.ok) {
                    const data = await res.json();
                    loadInterviewProblem(data.current_problem_index);
                    renderInterviewProblemSteps(data.problems, data.current_problem_index);
                }
            } catch (err) {
                console.error("Failed to advance problem:", err);
            }
        }

        async function finishMockInterview() {
            if (!activeInterviewId) return;
            if (!confirm("Are you ready to submit your assessment and view your evaluation report?")) return;

            try {
                const res = await fetch(`/api/interview/${activeInterviewId}/finish`, {
                    method: "POST"
                });
                if (res.ok) {
                    const report = await res.json();
                    showToast("Interview completed! Generating report.", "success");
                    displayInterviewReport(report);
                    await reloadInterviewState();
                    reloadInterviewHistory();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to finish interview", "error");
                }
            } catch (err) {
                showToast("Error finishing interview", "error");
            }
        }

        function displayInterviewReport(report) {
            const reportView = document.getElementById("interviewReportView");
            if (!reportView) return;

            reportView.style.display = "block";
            document.getElementById("reportTitle").textContent = report.title || "Assessment Report";
            document.getElementById("reportSub").textContent = `${(report.track || '').toUpperCase()} Track • ${report.duration_minutes}m • Time Taken: ${Math.floor(report.time_taken_seconds / 60)}m ${report.time_taken_seconds % 60}s`;
            document.getElementById("reportTotalScore").textContent = Math.round(report.rubric.total_score);

            document.getElementById("rubricCorrectness").textContent = `${report.rubric.correctness_score}/40`;
            document.getElementById("rubricCompletion").textContent = `${report.rubric.completion_score}/20`;
            document.getElementById("rubricStructure").textContent = `${report.rubric.structure_score}/15`;
            document.getElementById("rubricComplexity").textContent = `${report.rubric.complexity_score}/15`;
            document.getElementById("rubricTime").textContent = `${report.rubric.time_management_score}/10`;

            const feedbackEl = document.getElementById("reportFeedbackDetails");
            feedbackEl.innerHTML = `
                <strong>Feedback Summary:</strong> ${report.summary_feedback}<br>
                ${(report.correctness_observations || []).map(o => `• ${o}`).join("<br>")}
                ${(report.time_management_observations || []).map(o => `<br>• ${o}`).join("")}
                ${(report.code_quality_observations || []).map(o => `<br>• ${o}`).join("")}
                ${(report.complexity_observations || []).map(o => `<br>• ${o}`).join("")}
            `;

            const recTopics = document.getElementById("reportRecommendedTopics");
            recTopics.innerHTML = (report.recommended_topics || []).map(t => `<li>${t}</li>`).join("") || '<li>Arrays & Hashing</li>';

            const recRevs = document.getElementById("reportRecommendedRevisions");
            recRevs.innerHTML = (report.recommended_revisions || []).map(r => `<li>${r}</li>`).join("") || '<li>Review previously solved problems</li>';

            reportView.scrollIntoView({ behavior: 'smooth' });
        }

        async function viewInterviewReport(interviewId) {
            try {
                const res = await fetch(`/api/interview/${interviewId}/report`);
                if (res.ok) {
                    const report = await res.json();
                    displayInterviewReport(report);
                } else {
                    showToast("No assessment report found for this session.", "warning");
                }
            } catch (err) {
                showToast("Failed to load assessment report", "error");
            }
        }

        async function reloadInterviewHistory() {
            try {
                const res = await fetch("/api/interview/history?limit=10");
                if (!res.ok) return;
                const history = await res.json();

                const tbody = document.getElementById("interviewHistoryTableBody");
                if (!tbody) return;

                if (!history || history.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="padding: 8px; color: var(--text-muted); text-align: center;">No assessments recorded yet.</td></tr>';
                    return;
                }

                tbody.innerHTML = history.map(h => {
                    const scoreDisplay = h.total_score !== null ? `<strong>${Math.round(h.total_score)}</strong>/100` : '-';
                    const dateStr = h.created_at ? h.created_at.substring(0, 10) : '';
                    let statusBadge = `<span class="status-badge badge-${h.status}">${h.status}</span>`;
                    return `
                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                            <td style="padding: 6px 8px; color: var(--text-muted);">${dateStr}</td>
                            <td style="padding: 6px 8px; font-weight: 600; color: var(--text);">${h.title}</td>
                            <td style="padding: 6px 8px;">${(h.track || '').toUpperCase()}</td>
                            <td style="padding: 6px 8px;">${h.duration_minutes}m</td>
                            <td style="padding: 6px 8px; color: var(--primary);">${scoreDisplay}</td>
                            <td style="padding: 6px 8px;">${statusBadge}</td>
                            <td style="padding: 6px 8px; text-align: right;">
                                <button class="btn btn-secondary btn-sm" onclick="viewInterviewReport('${h.interview_id}')" style="padding: 2px 8px; font-size: 0.75rem;">View Report</button>
                            </td>
                        </tr>
                    `;
                }).join("");
            } catch (err) {
                console.error("Failed to load interview history:", err);
            }
        }

        // Interview Performance Trends & Benchmark Analytics (Milestone 6.3.20)
        async function reloadInterviewAnalytics() {
            try {
                const presetEl = document.getElementById("ianalyticsPreset");
                const preset = presetEl ? presetEl.value : "all_time";

                const res = await fetch(`/api/interview-analytics?date_preset=${encodeURIComponent(preset)}`);
                if (!res.ok) return;
                const data = await res.json();

                // Top stats
                if (document.getElementById("iaTotalCount")) document.getElementById("iaTotalCount").textContent = data.total_completed_interviews;
                if (document.getElementById("iaAvgScore")) document.getElementById("iaAvgScore").textContent = data.average_score.toFixed(1);
                if (document.getElementById("iaLatestScore")) document.getElementById("iaLatestScore").textContent = data.latest_score !== null ? data.latest_score.toFixed(1) : "-";
                if (document.getElementById("iaExtremes")) document.getElementById("iaExtremes").textContent = `High: ${data.highest_score !== null ? data.highest_score : '-'} | Low: ${data.lowest_score !== null ? data.lowest_score : '-'}`;
                if (document.getElementById("iaCompletionRate")) document.getElementById("iaCompletionRate").textContent = `${data.completion_rate_pct.toFixed(1)}%`;

                // Category trends
                const trendsGrid = document.getElementById("iaCategoryTrendsGrid");
                if (trendsGrid && data.score_trends) {
                    trendsGrid.innerHTML = Object.entries(data.score_trends).map(([key, t]) => {
                        let arrow = "•";
                        let deltaColor = "var(--text-muted)";
                        if (t.trend_direction === "improving") {
                            arrow = "▲";
                            deltaColor = "var(--success)";
                        } else if (t.trend_direction === "declining") {
                            arrow = "▼";
                            deltaColor = "var(--danger)";
                        }
                        const deltaStr = t.delta_score !== null ? `${t.delta_score > 0 ? '+' : ''}${t.delta_score}` : 'N/A';
                        return `
                            <div style="background: rgba(30, 41, 59, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                                <div style="font-size: 0.75rem; color: var(--text-muted);">${t.category_name}</div>
                                <div style="font-size: 1.2rem; font-weight: 700; color: var(--text); margin-top: 2px;">${t.average_score} <span style="font-size: 0.8rem; color: var(--text-muted);">/ ${t.max_possible}</span></div>
                                <div style="font-size: 0.75rem; color: ${deltaColor}; margin-top: 4px;">
                                    ${arrow} ${deltaStr} (${t.trend_direction.replace('_', ' ')})
                                </div>
                            </div>
                        `;
                    }).join("");
                }

                // Track benchmarks table
                const tracksTbody = document.getElementById("iaTracksTableBody");
                if (tracksTbody && data.track_benchmarks) {
                    tracksTbody.innerHTML = data.track_benchmarks.map(b => `
                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                            <td style="padding: 4px 6px; font-weight: 600;">${b.track.toUpperCase()}</td>
                            <td style="padding: 4px 6px;">${b.assessment_count}</td>
                            <td style="padding: 4px 6px; color: var(--primary);">${b.average_score.toFixed(1)}</td>
                            <td style="padding: 4px 6px;">${b.highest_score.toFixed(1)}</td>
                            <td style="padding: 4px 6px;">${b.average_completion_rate.toFixed(1)}%</td>
                            <td style="padding: 4px 6px; font-size: 0.7rem; color: ${b.is_statistically_reliable ? 'var(--success)' : 'var(--text-muted)'};">
                                ${b.is_statistically_reliable ? 'Reliable (N>=3)' : 'Sample < 3'}
                            </td>
                        </tr>
                    `).join("");
                }

                // Language benchmarks table
                const langsTbody = document.getElementById("iaLanguagesTableBody");
                if (langsTbody && data.language_benchmarks) {
                    langsTbody.innerHTML = data.language_benchmarks.map(l => `
                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                            <td style="padding: 4px 6px; font-weight: 600;">${l.language.toUpperCase()}</td>
                            <td style="padding: 4px 6px;">${l.interview_count}</td>
                            <td style="padding: 4px 6px; color: var(--accent);">${l.average_score.toFixed(1)}</td>
                            <td style="padding: 4px 6px;">${l.average_correctness.toFixed(1)}/40</td>
                            <td style="padding: 4px 6px;">${l.average_structure.toFixed(1)}/15</td>
                        </tr>
                    `).join("");
                }

                // Insights & Weaknesses
                const insightsBox = document.getElementById("iaInsightsContainer");
                if (insightsBox) {
                    if (!data.insights || data.insights.length === 0) {
                        insightsBox.innerHTML = `
                            <div style="background: rgba(30, 41, 59, 0.4); padding: 10px; border-radius: 6px; border: 1px solid var(--border); color: var(--text-muted); font-size: 0.85rem;">
                                No recurring weaknesses identified yet. Complete additional assessments to detect patterns.
                            </div>
                        `;
                    } else {
                        insightsBox.innerHTML = data.insights.map(i => {
                            let typeColor = i.pattern_type === 'weakness' ? 'var(--danger)' : (i.pattern_type === 'strength' ? 'var(--success)' : 'var(--warning)');
                            return `
                                <div style="background: rgba(30, 41, 59, 0.5); padding: 12px; border-radius: 6px; border-left: 3px solid ${typeColor};">
                                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                        <strong style="color: var(--text); font-size: 0.9rem;">${i.title}</strong>
                                        <span class="status-badge" style="font-size: 0.7rem; background: rgba(0,0,0,0.3); color: ${typeColor};">${i.pattern_type.toUpperCase()}</span>
                                    </div>
                                    <div style="font-size: 0.8rem; color: #bae6fd; margin-bottom: 6px;">${i.description}</div>
                                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 6px;"><strong>Rule:</strong> ${i.rule_applied}</div>
                                    <div style="font-size: 0.8rem; color: #a5f3fc; background: rgba(0,0,0,0.25); padding: 6px 8px; border-radius: 4px;">
                                        <strong>Suggested Action:</strong> ${i.suggested_action}
                                    </div>
                                </div>
                            `;
                        }).join("");
                    }
                }

                // Goals List
                const goalsBox = document.getElementById("iaGoalsList");
                if (goalsBox) {
                    if (!data.active_goals || data.active_goals.length === 0) {
                        goalsBox.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">No active interview practice goals. Use the form above to add one.</div>';
                    } else {
                        goalsBox.innerHTML = data.active_goals.map(g => `
                            <div style="margin-bottom: 10px; background: rgba(15, 23, 42, 0.5); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                    <strong style="color: var(--text); font-size: 0.85rem;">${g.description}</strong>
                                    <span style="font-size: 0.8rem; font-weight: 600; color: ${g.is_achieved ? 'var(--success)' : 'var(--primary)'};">
                                        ${g.current_value} / ${g.target_value} (${g.progress_pct}%)
                                    </span>
                                </div>
                                <div class="progress-bar-container" style="height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; overflow: hidden;">
                                    <div style="height: 100%; width: ${g.progress_pct}%; background: ${g.is_achieved ? 'var(--success)' : 'var(--primary)'}; border-radius: 3px;"></div>
                                </div>
                            </div>
                        `).join("");
                    }
                }
            } catch (err) {
                console.error("Failed to reload interview analytics:", err);
            }
        }

        async function createInterviewGoal() {
            try {
                const type = document.getElementById("newGoalType").value;
                const val = parseFloat(document.getElementById("newGoalValue").value);
                if (isNaN(val) || val <= 0) {
                    showToast("Please enter a valid target value greater than 0", "warning");
                    return;
                }

                const res = await fetch("/api/interview-analytics/goals", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        goal_type: type,
                        target_value: val,
                        period: "all_time"
                    })
                });

                if (res.ok) {
                    showToast("Interview goal created successfully!", "success");
                    document.getElementById("newGoalValue").value = "";
                    reloadInterviewAnalytics();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to create goal", "error");
                }
            } catch (err) {
                showToast("Error creating interview goal", "error");
            }
        }

        // =========================================================================
        // Milestone 6.3.27: Unified Learning Command Center Client Functions
        // =========================================================================

        let currentPrimaryAction = null;

        function switchTab(tabId) {
            if (!tabId) tabId = 'overview';
            
            // Update active state on nav buttons
            const navTabs = document.querySelectorAll('.command-nav .nav-tab');
            navTabs.forEach(tab => {
                if (tab.getAttribute('data-tab') === tabId) {
                    tab.classList.add('active');
                } else {
                    tab.classList.remove('active');
                }
            });

            // Update content visibility
            const overviewPane = document.getElementById('pane-overview');
            const allPanes = document.querySelectorAll('.tab-content-pane');

            if (tabId === 'all') {
                if (overviewPane) overviewPane.style.display = 'block';
                allPanes.forEach(pane => {
                    pane.style.display = 'block';
                });
            } else if (tabId === 'overview') {
                if (overviewPane) overviewPane.style.display = 'block';
                allPanes.forEach(pane => {
                    if (pane.id !== 'pane-overview') {
                        pane.style.display = 'none';
                    }
                });
            } else {
                if (overviewPane) overviewPane.style.display = 'none';
                allPanes.forEach(pane => {
                    if (pane.id === 'pane-overview') {
                        pane.style.display = 'none';
                    } else if (pane.getAttribute('data-tab') === tabId) {
                        pane.style.display = 'block';
                    } else {
                        pane.style.display = 'none';
                    }
                });
            }

            // Sync URL hash without triggering recursive hashchange
            if (window.location.hash !== '#' + tabId) {
                history.replaceState(null, '', '#' + tabId);
            }

            // Trigger targeted data reload for active tab
            onTabActivated(tabId);
        }

        function onTabActivated(tabId) {
            switch (tabId) {
                case 'overview':
                    reloadCommandCenter();
                    break;
                case 'daily-practice':
                    if (typeof reloadDailyPractice === 'function') reloadDailyPractice();
                    break;
                case 'skills':
                    if (typeof reloadSkillGaps === 'function') reloadSkillGaps();
                    break;
                case 'adaptive-learning':
                    if (typeof reloadLearningLoop === 'function') reloadLearningLoop();
                    break;
                case 'learning-plan':
                    if (typeof reloadPreparationPlanner === 'function') reloadPreparationPlanner();
                    break;
                case 'coding-performance':
                    if (typeof reloadCodingBehavior === 'function') reloadCodingBehavior();
                    break;
                case 'interviews':
                    if (typeof reloadInterviewAnalytics === 'function') reloadInterviewAnalytics();
                    if (typeof reloadInterviewHistory === 'function') reloadInterviewHistory();
                    break;
                case 'revision':
                    if (typeof reloadRevisionQueue === 'function') reloadRevisionQueue();
                    break;
                case 'reports':
                    if (typeof reloadPortfolioPreview === 'function') reloadPortfolioPreview();
                    break;
                case 'all':
                    reloadCommandCenter();
                    break;
            }
        }

        async function reloadCommandCenter() {
            try {
                const res = await fetch('/api/command-center');
                if (!res.ok) {
                    console.warn('Failed to load command center overview:', res.status);
                    return;
                }
                const data = await res.json();
                renderCommandCenter(data);
            } catch (err) {
                console.error('Error fetching command center data:', err);
            }
        }

        function renderCommandCenter(data) {
            if (!data) return;

            // 1. Unified Action Flow Hero Banner
            if (data.primary_action) {
                currentPrimaryAction = data.primary_action;
                const act = data.primary_action;

                const iconElem = document.getElementById('uafIcon');
                const badgeElem = document.getElementById('uafPriorityBadge');
                const titleElem = document.getElementById('uafTitle');
                const descElem = document.getElementById('uafDescription');
                const evElem = document.getElementById('uafEvidence');
                const ctaBtn = document.getElementById('uafCtaBtn');

                if (titleElem) titleElem.textContent = act.title || 'Recommended Action';
                if (descElem) descElem.textContent = act.description || '';
                if (evElem) evElem.textContent = act.evidence ? `Evidence: ${act.evidence}` : (act.reason ? `Rationale: ${act.reason}` : '');
                if (ctaBtn) ctaBtn.textContent = act.cta_label || 'Take Action';

                const prio = (act.priority || 'P2').toUpperCase();
                if (badgeElem) {
                    badgeElem.textContent = prio;
                    if (prio === 'P0') {
                        badgeElem.style.background = 'rgba(239, 68, 68, 0.25)';
                        badgeElem.style.color = '#fca5a5';
                    } else if (prio === 'P1') {
                        badgeElem.style.background = 'rgba(245, 158, 11, 0.25)';
                        badgeElem.style.color = '#fcd34d';
                    } else {
                        badgeElem.style.background = 'rgba(59, 130, 246, 0.25)';
                        badgeElem.style.color = '#93c5fd';
                    }
                }

                if (iconElem) {
                    const at = act.action_type || '';
                    if (at.includes('continue') || at.includes('resume') || at.includes('start')) {
                        iconElem.textContent = '⚡';
                    } else if (at.includes('proposal')) {
                        iconElem.textContent = '🔄';
                    } else if (at.includes('revision')) {
                        iconElem.textContent = '🔁';
                    } else if (at.includes('unresolved') || at.includes('failing')) {
                        iconElem.textContent = '🐞';
                    } else if (at.includes('skill_gap')) {
                        iconElem.textContent = '🎯';
                    } else {
                        iconElem.textContent = '🚀';
                    }
                }
            }

            // 2. Tab Badges
            const loopBadge = document.getElementById('tabLoopBadge');
            const loopData = data.adaptive_learning || data.adaptive_loop;
            if (loopBadge && loopData) {
                const count = loopData.pending_proposals_count || 0;
                if (count > 0) {
                    loopBadge.textContent = count;
                    loopBadge.style.display = 'inline-block';
                } else {
                    loopBadge.style.display = 'none';
                }
            }
            const revBadge = document.getElementById('tabRevBadge');
            if (revBadge && data.interview_prep) {
                const count = data.interview_prep.overdue_revisions_count || 0;
                if (count > 0) {
                    revBadge.textContent = count;
                    revBadge.style.display = 'inline-block';
                } else {
                    revBadge.style.display = 'none';
                }
            }

            // 3. Overview Widgets
            // Today's Learning
            if (data.today_learning) {
                const tl = data.today_learning;
                const statusBadge = document.getElementById('ovTodayStatusBadge');
                const titleElem = document.getElementById('ovTodayTitle');
                const timeElem = document.getElementById('ovTodayTime');
                const progElem = document.getElementById('ovTodayProgress');
                const progBar = document.getElementById('ovTodayProgressBar');
                const taskElem = document.getElementById('ovTodayCurrentTask');

                const sessStatus = tl.status || tl.session_status || 'none';
                if (statusBadge) statusBadge.textContent = sessStatus.toUpperCase();
                if (titleElem) titleElem.textContent = tl.title || tl.session_title || 'No study session active today.';
                
                const spent = tl.elapsed_minutes !== undefined ? tl.elapsed_minutes : (tl.spent_minutes || 0);
                const budget = tl.budget_minutes || 0;
                if (timeElem) timeElem.textContent = `${spent} / ${budget}m`;
                
                const pct = Math.round(tl.completion_pct !== undefined ? tl.completion_pct : (tl.progress_percentage || 0));
                if (progElem) progElem.textContent = `${pct}%`;
                if (progBar) progBar.style.width = `${pct}%`;

                if (taskElem) {
                    if (tl.current_task) {
                        taskElem.innerHTML = `Current Focus: <strong style="color: #6ee7b7;">${tl.current_task.title}</strong>`;
                    } else if (tl.remaining_tasks_count > 0) {
                        taskElem.innerHTML = `Next up: <strong>${tl.remaining_tasks_count} tasks remaining</strong>`;
                    } else if (sessStatus === 'completed') {
                        taskElem.innerHTML = `<span style="color: #6ee7b7;">✓ Session Completed (${tl.completed_tasks_count || 0} tasks done)</span>`;
                    } else {
                        taskElem.innerHTML = `Current Focus: <strong>None</strong>`;
                    }
                }
            }

            // My Skill Focus
            if (data.skill_focus) {
                const sf = data.skill_focus;
                const topTopic = document.getElementById('ovSkillTopTopic');
                const topDiff = document.getElementById('ovSkillTopDiff');
                const evText = document.getElementById('ovSkillEvidence');
                const suggProb = document.getElementById('ovSkillSuggestedProblem');

                if (topTopic) topTopic.textContent = sf.top_gap_topic || (sf.highest_priority_gaps && sf.highest_priority_gaps[0]?.topic) || 'General';
                if (topDiff) topDiff.textContent = ((sf.top_gap_priority || (sf.highest_priority_gaps && sf.highest_priority_gaps[0]?.priority)) || 'MEDIUM').toUpperCase();
                if (evText) evText.textContent = sf.top_gap_evidence || 'Evidence analyzed across local session history.';
                if (suggProb) suggProb.textContent = sf.recommended_problem_id || sf.suggested_next_problem || 'two-sum';
            }

            // Adaptive Learning Loop
            const al = data.adaptive_learning || data.adaptive_loop;
            if (al) {
                const phaseBadge = document.getElementById('ovLoopPhaseBadge');
                const propCount = document.getElementById('ovLoopProposalsCount');
                const evalElem = document.getElementById('ovLoopLastEval');
                const summText = document.getElementById('ovLoopSummaryText');

                if (phaseBadge) phaseBadge.textContent = (al.phase || al.loop_status || 'DIAGNOSIS').toUpperCase();
                const c = al.pending_proposals_count || 0;
                if (propCount) {
                    propCount.textContent = `${c} awaiting review`;
                    propCount.style.color = c > 0 ? '#fde047' : '#94a3b8';
                }
                if (evalElem && al.latest_evaluation) {
                    evalElem.textContent = `Latest evaluation: ${al.latest_evaluation.replace('T', ' ').substring(0, 16)}`;
                }
                if (summText) {
                    summText.textContent = c > 0 
                        ? `${c} active plan adjustment(s) require explicit acceptance.` 
                        : 'Plan is aligned with current verified coding evidence.';
                }
            }

            // Interview & Preparation
            if (data.interview_prep) {
                const ip = data.interview_prep;
                const planTitle = document.getElementById('ovPlanTitle');
                const planTasks = document.getElementById('ovPlanTasks');
                const overdueRev = document.getElementById('ovOverdueRevisions');
                const progBar = document.getElementById('ovPlanProgressBar');

                if (ip.active_plan) {
                    if (planTitle) planTitle.textContent = ip.active_plan.title || 'Active Preparation Plan';
                    if (planTasks) planTasks.textContent = `${ip.active_plan.completed_tasks || 0} / ${ip.active_plan.total_tasks || 0}`;
                    const pct = Math.round(ip.active_plan.completion_pct || 0);
                    if (progBar) progBar.style.width = `${pct}%`;
                } else {
                    if (planTitle) planTitle.textContent = ip.active_plan_title || 'No active preparation plan.';
                    if (planTasks) planTasks.textContent = `${ip.completed_planner_tasks || 0} / ${ip.total_planner_tasks || 0}`;
                    const totalT = ip.total_planner_tasks || 0;
                    const doneT = ip.completed_planner_tasks || 0;
                    const planPct = totalT > 0 ? Math.round((doneT / totalT) * 100) : 0;
                    if (progBar) progBar.style.width = `${planPct}%`;
                }
                if (overdueRev) overdueRev.textContent = ip.overdue_revisions_count || 0;
            }

            // Coding Performance
            const oa = data.overview_stats || data.coding_performance || data.overall_activity;
            if (oa) {
                const fpass = document.getElementById('ovFirstPassRate');
                const acc = document.getElementById('ovOverallAccuracy');
                const langElem = document.getElementById('ovLanguageBreakdown');

                const fRate = oa.first_attempt_pass_rate_pct !== undefined ? oa.first_attempt_pass_rate_pct : ((oa.first_attempt_pass_rate || 0) * 100);
                if (fpass) fpass.textContent = `${fRate.toFixed(1)}%`;
                
                const accRate = oa.pass_rate_pct !== undefined ? oa.pass_rate_pct : (oa.total_attempts > 0 ? (oa.passed_attempts / oa.total_attempts * 100) : 0);
                if (acc) acc.textContent = `${accRate.toFixed(1)}%`;

                const langs = oa.languages || oa.language_distribution;
                if (langElem && langs) {
                    const lNames = Object.keys(langs);
                    if (lNames.length > 0) {
                        langElem.textContent = `Languages: ${lNames.join(', ')}`;
                    }
                }
            }

            // Recent Activity Stream
            const streamList = document.getElementById('ovRecentActivityList');
            if (streamList && data.recent_activity) {
                if (data.recent_activity.length === 0) {
                    streamList.innerHTML = '<div style="padding: 10px 0; color: var(--text-muted); text-align: center;">No recent activities recorded yet.</div>';
                } else {
                    let html = '';
                    data.recent_activity.slice(0, 8).forEach(item => {
                        const icon = item.type === 'attempt' ? '⚡'
                            : item.activity_type === 'practice_session' ? '📅' 
                            : item.activity_type === 'interview' ? '💼' 
                            : '📋';
                        const timeStr = item.timestamp ? item.timestamp.replace('T', ' ').substring(0, 16) : '';
                        html += `
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.05);">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span>${icon}</span>
                                <span style="color: #cbd5e1;">${item.title || item.activity_type || item.type}</span>
                            </div>
                            <span style="color: var(--text-muted); font-size: 0.7rem;">${timeStr}</span>
                        </div>
                        `;
                    });
                    streamList.innerHTML = html;
                }
            }
        }

        function executePrimaryAction() {
            if (!currentPrimaryAction) {
                switchTab('daily-practice');
                return;
            }
            const act = currentPrimaryAction;
            if (act.action_type === 'resume_session' || act.action_type === 'start_session') {
                switchTab('daily-practice');
            } else if (act.action_type === 'review_proposal') {
                switchTab('adaptive-learning');
            } else if (act.action_type === 'review_spaced_revision') {
                switchTab('revision');
            } else if (act.action_type === 'resolve_failing_problem' || act.action_type === 'practice_skill_gap') {
                if (act.metadata && act.metadata.problem_id) {
                    if (typeof openProblemInWorkspace === 'function') {
                        openProblemInWorkspace(act.metadata.problem_id);
                    }
                } else {
                    switchTab('skills');
                }
            } else {
                switchTab('daily-practice');
            }
        }

        // Initialize Coach, Revision, Goals, Roadmap, Daily Mission, Workspace, Portfolio, Interview, Analytics, and Command Center on window load
        window.addEventListener("DOMContentLoaded", () => {
            // Setup hash listener for URL navigation
            window.addEventListener('hashchange', () => {
                const target = window.location.hash.replace('#', '') || 'overview';
                switchTab(target);
            });

            // Initial view
            const initialTab = window.location.hash.replace('#', '') || 'overview';
            switchTab(initialTab);

            // Resilient background loading of all subsystems with Promise.allSettled
            Promise.allSettled([
                reloadCommandCenter(),
                initCoach(),
                reloadRevisionQueue(),
                reloadGoalsAndMilestones(),
                reloadRoadmapData(),
                reloadDailyMission(),
                openProblemInWorkspace("two-sum"),
                reloadPortfolioPreview(),
                reloadInterviewState(),
                reloadInterviewHistory(),
                reloadInterviewAnalytics(),
                reloadPreparationPlanner(),
                reloadActivePracticeSession(),
                reloadCodingBehavior(),
                reloadSkillGaps(),
                reloadLearningLoop(),
                reloadDailyPractice(),
            ]).then(results => {
                const failed = results.filter(r => r.status === 'rejected');
                if (failed.length > 0) {
                    console.warn(`Command Center background initialization completed with ${failed.length} non-fatal warning(s).`);
                }
            }).catch(e => console.warn("Background load error:", e));
        });

        // =========================================================================
        // Milestone 6.3.21: Adaptive Interview Preparation Planner Client Functions
        // =========================================================================

        let currentActivePlanId = null;

        async function reloadPreparationPlanner() {
            try {
                // Fetch settings
                const setRes = await fetch("/api/preparation-planner/settings");
                if (setRes.ok) {
                    const settings = await setRes.json();
                    document.getElementById("plannerDailyMinutes").value = settings.daily_minutes || 60;
                    document.getElementById("plannerHorizonDays").value = settings.horizon_days || 7;
                    document.getElementById("plannerTargetTrack").value = settings.target_track || "intermediate";
                    document.getElementById("plannerLanguage").value = settings.language || "python";
                    document.getElementById("plannerTargetScore").value = settings.target_score || 80;
                    document.getElementById("plannerIntensity").value = settings.intensity || "moderate";
                }

                // Fetch active plan
                const planRes = await fetch("/api/preparation-planner");
                if (planRes.ok) {
                    const data = await planRes.json();
                    renderPreparationPlan(data.plan);
                }
            } catch (err) {
                console.error("Failed to reload preparation planner:", err);
            }
        }

        async function savePlannerSettings() {
            try {
                const payload = {
                    daily_minutes: parseInt(document.getElementById("plannerDailyMinutes").value, 10),
                    horizon_days: parseInt(document.getElementById("plannerHorizonDays").value, 10),
                    target_track: document.getElementById("plannerTargetTrack").value,
                    language: document.getElementById("plannerLanguage").value,
                    target_score: parseFloat(document.getElementById("plannerTargetScore").value),
                    intensity: document.getElementById("plannerIntensity").value
                };

                const res = await fetch("/api/preparation-planner/settings", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });

                if (res.ok) {
                    showToast("Planner settings saved successfully!", "success");
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to save settings", "error");
                }
            } catch (err) {
                showToast("Error saving planner settings", "error");
            }
        }

        async function generatePreparationPlan() {
            try {
                showToast("Synthesizing evidence-driven preparation schedule...", "info");
                const res = await fetch("/api/preparation-planner/generate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({})
                });

                if (res.ok) {
                    const plan = await res.json();
                    renderPreparationPlan(plan);
                    showToast("New preparation plan generated!", "success");
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to generate plan", "error");
                }
            } catch (err) {
                showToast("Error generating preparation plan", "error");
            }
        }

        async function applyPreparationPlan(planId) {
            try {
                const res = await fetch(`/api/preparation-planner/plan/${planId}/apply`, {
                    method: "POST"
                });

                if (res.ok) {
                    const plan = await res.json();
                    renderPreparationPlan(plan);
                    showToast("Plan activated successfully!", "success");
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to apply plan", "error");
                }
            } catch (err) {
                showToast("Error applying plan", "error");
            }
        }

        async function completePlanTask(taskId) {
            try {
                const res = await fetch(`/api/preparation-planner/task/${taskId}/complete`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({})
                });

                if (res.ok) {
                    showToast("Task completed!", "success");
                    reloadPreparationPlanner();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to complete task", "error");
                }
            } catch (err) {
                showToast("Error completing task", "error");
            }
        }

        async function skipPlanTask(taskId) {
            try {
                const reason = prompt("Optional reason for skipping this task:") || "Skipped by learner";
                const res = await fetch(`/api/preparation-planner/task/${taskId}/skip`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ reason: reason })
                });

                if (res.ok) {
                    showToast("Task marked as skipped.", "warning");
                    reloadPreparationPlanner();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to skip task", "error");
                }
            } catch (err) {
                showToast("Error skipping task", "error");
            }
        }

        async function previewReplan() {
            try {
                const res = await fetch("/api/preparation-planner/replan/preview", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({})
                });

                if (res.ok) {
                    const preview = await res.json();
                    const box = document.getElementById("replanPreviewBox");
                    const exp = document.getElementById("replanExplanation");
                    const list = document.getElementById("replanChangesList");

                    exp.innerText = preview.explanation;
                    if (preview.rescheduled_tasks && preview.rescheduled_tasks.length > 0) {
                        list.innerHTML = `
                            <div style="margin-top: 8px;">
                                <strong>Proposed Task Rescheduling:</strong>
                                <ul style="margin: 4px 0 0 16px; padding: 0;">
                                    ${preview.rescheduled_tasks.map(t => `<li><strong>${t.title}</strong>: moved from ${t.old_date} &rarr; ${t.new_date}</li>`).join("")}
                                </ul>
                            </div>
                        `;
                    } else {
                        list.innerHTML = `<div style="margin-top: 6px; color: var(--text-muted);">Current schedule is fully on track. No tasks need rescheduling.</div>`;
                    }
                    box.style.display = "block";
                } else {
                    const err = await res.json();
                    showToast(err.error || "No active plan found to replan.", "warning");
                }
            } catch (err) {
                showToast("Error previewing replan", "error");
            }
        }

        function dismissReplanPreview() {
            document.getElementById("replanPreviewBox").style.display = "none";
        }

        async function applyReplan() {
            try {
                const res = await fetch("/api/preparation-planner/replan/apply", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({})
                });

                if (res.ok) {
                    dismissReplanPreview();
                    const updatedPlan = await res.json();
                    renderPreparationPlan(updatedPlan);
                    showToast("Adaptive plan changes applied successfully!", "success");
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to apply replan", "error");
                }
            } catch (err) {
                showToast("Error applying replan", "error");
            }
        }

        function renderPreparationPlan(plan) {
            if (!plan) return;
            currentActivePlanId = plan.plan_id;

            // Update badge & title
            const badge = document.getElementById("planStatusBadge");
            if (badge) {
                badge.innerText = plan.status.toUpperCase();
                badge.style.background = plan.status === 'active' ? 'rgba(34, 197, 94, 0.2)' : 'rgba(234, 179, 8, 0.2)';
                badge.style.color = plan.status === 'active' ? 'var(--success)' : '#fde047';
            }

            document.getElementById("activePlanTitle").innerText = plan.title;
            document.getElementById("activePlanDateRange").innerText = `${plan.start_date} to ${plan.end_date} • ${plan.horizon_days} Day Horizon`;

            const btnContainer = document.getElementById("planActionBtnContainer");
            if (btnContainer) {
                if (plan.status === 'draft') {
                    btnContainer.innerHTML = `<button class="btn btn-primary btn-sm" onclick="applyPreparationPlan('${plan.plan_id}')">🚀 Activate This Plan</button>`;
                } else {
                    btnContainer.innerHTML = `<span style="font-size: 0.8rem; color: var(--success); font-weight: 600;">Active Schedule</span>`;
                }
            }

            // Progress stats
            const prog = plan.progress;
            document.getElementById("planTasksCount").innerText = `${prog.tasks_completed} / ${prog.tasks_planned}`;
            document.getElementById("planPctText").innerText = `${prog.completion_ratio_pct}%`;
            document.getElementById("planProgressBar").style.width = `${prog.completion_ratio_pct}%`;

            document.getElementById("statPlannedTime").innerText = `${prog.planned_minutes}m`;
            document.getElementById("statActualTime").innerText = `${prog.actual_recorded_minutes}m`;
            document.getElementById("statStreakDays").innerText = `${prog.current_streak_days} days`;
            document.getElementById("statOverdueTasks").innerText = `${prog.tasks_overdue}`;

            // Render schedule container
            const container = document.getElementById("plannerScheduleContainer");
            if (!container) return;

            let html = "";
            (plan.weeks || []).forEach(w => {
                html += `
                    <div style="background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-bottom: 16px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 8px;">
                            <div>
                                <h3 style="margin: 0; font-size: 0.95rem; color: var(--text);">Week ${w.week_number}: ${w.start_date} &rarr; ${w.end_date}</h3>
                                <p style="margin: 2px 0 0 0; font-size: 0.8rem; color: var(--text-muted);">${w.week_objective}</p>
                            </div>
                            <div style="display: flex; gap: 6px; font-size: 0.75rem;">
                                ${(w.focus_topics || []).map(t => `<span class="badge" style="background: rgba(59, 130, 246, 0.2); color: #93c5fd; padding: 2px 6px; border-radius: 4px;">${t}</span>`).join("")}
                            </div>
                        </div>

                        <!-- Days list -->
                        <div style="display: flex; flex-direction: column; gap: 10px;">
                            ${(w.days || []).map(d => `
                                <div style="background: rgba(30, 41, 59, 0.5); border: 1px solid var(--border); border-radius: 6px; padding: 10px;">
                                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <strong style="color: var(--text); font-size: 0.85rem;">${d.day_name}, ${d.day_date}</strong>
                                            <span style="font-size: 0.75rem; padding: 1px 6px; border-radius: 4px; background: ${d.is_study_day ? 'rgba(59, 130, 246, 0.2)' : 'rgba(100, 116, 139, 0.2)'}; color: ${d.is_study_day ? '#93c5fd' : 'var(--text-muted)'};">
                                                ${d.is_study_day ? `${d.planned_minutes}m Planned` : 'Rest Day'}
                                            </span>
                                        </div>
                                        <span style="font-size: 0.75rem; color: var(--text-muted);">
                                            ${d.tasks.length} task${d.tasks.length !== 1 ? 's' : ''}
                                        </span>
                                    </div>

                                    <!-- Tasks list for day -->
                                    <div style="display: flex; flex-direction: column; gap: 6px;">
                                        ${d.tasks.map(t => {
                                            const isDone = t.status === 'completed';
                                            const isSkip = t.status === 'skipped';
                                            const prioColor = t.priority === 'P0' ? '#ef4444' : (t.priority === 'P1' ? '#3b82f6' : '#10b981');
                                            return `
                                                <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(15, 23, 42, 0.6); padding: 8px 10px; border-radius: 4px; border-left: 3px solid ${prioColor};">
                                                    <div style="flex: 1; margin-right: 12px;">
                                                        <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 2px;">
                                                            <span style="font-size: 0.7rem; font-weight: bold; color: ${prioColor};">[${t.priority}]</span>
                                                            <strong style="font-size: 0.85rem; color: ${isDone ? 'var(--text-muted)' : 'var(--text)'}; text-decoration: ${isDone ? 'line-through' : 'none'};">
                                                                ${t.title}
                                                            </strong>
                                                            <span style="font-size: 0.75rem; color: var(--text-muted);">(${t.estimated_minutes}m)</span>
                                                        </div>
                                                        <div style="font-size: 0.75rem; color: var(--text-muted); line-height: 1.3;">
                                                            ${t.description} &bull; <em style="color: #cbd5e1;">Reason: ${t.reason}</em>
                                                        </div>
                                                    </div>
                                                    <div style="display: flex; gap: 6px; align-items: center;">
                                                        ${isDone ? `<span style="font-size: 0.8rem; color: var(--success); font-weight: 600;">&#10003; Done</span>` :
                                                          isSkip ? `<span style="font-size: 0.8rem; color: var(--text-muted);">Skipped</span>` : `
                                                            <button class="btn btn-sm btn-secondary" style="font-size: 0.75rem; padding: 2px 8px;" onclick="startTaskPracticeSession('${t.task_id}')">▶️ Practice</button>
                                                            <button class="btn btn-sm btn-primary" style="font-size: 0.75rem; padding: 2px 8px;" onclick="completePlanTask('${t.task_id}')">Done</button>
                                                            <button class="btn btn-sm btn-secondary" style="font-size: 0.75rem; padding: 2px 8px;" onclick="skipPlanTask('${t.task_id}')">Skip</button>
                                                        `}
                                                    </div>
                                                </div>
                                            `;
                                        }).join("")}
                                    </div>
                                </div>
                            `).join("")}
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
        }

        // =========================================================================
        // Milestone 6.3.22: Plan-to-Practice Execution Bridge Client Functions
        // =========================================================================

        let activePracticeSessionId = null;
        let practiceSessionTimerInterval = null;
        let practiceSessionBaseElapsed = 0;
        let practiceSessionStartedAt = null;
        let practiceSessionStatus = "pending";

        async function reloadActivePracticeSession() {
            try {
                const res = await fetch("/api/practice-session/active");
                if (!res.ok) return;
                const data = await res.json();
                renderPracticeSession(data);
            } catch (err) {
                console.error("Failed to reload active practice session:", err);
            }
        }

        function renderPracticeSession(session) {
            const cardBadge = document.getElementById("practiceSessionStatusBadge");
            const box = document.getElementById("activePracticeSessionBox");
            const btnPauseResume = document.getElementById("btnPauseResumeSession");

            if (!session) {
                activePracticeSessionId = null;
                practiceSessionStatus = "pending";
                if (practiceSessionTimerInterval) clearInterval(practiceSessionTimerInterval);
                if (cardBadge) {
                    cardBadge.textContent = "NO ACTIVE SESSION";
                    cardBadge.style.background = "var(--surface-light)";
                    cardBadge.style.color = "var(--text-muted)";
                }
                if (box) box.style.display = "none";
                return;
            }

            activePracticeSessionId = session.session_id;
            practiceSessionStatus = session.status;
            practiceSessionBaseElapsed = session.elapsed_seconds || 0;
            practiceSessionStartedAt = session.started_at ? new Date(session.started_at).getTime() : Date.now();

            if (box) box.style.display = "block";

            // Status Badge
            if (cardBadge) {
                cardBadge.textContent = session.status.toUpperCase();
                cardBadge.style.background = session.status === 'active' ? 'rgba(34, 197, 94, 0.2)' : 'rgba(234, 179, 8, 0.2)';
                cardBadge.style.color = session.status === 'active' ? 'var(--success)' : '#fde047';
            }

            // Title & Subtitle
            document.getElementById("activeSessTitle").textContent = session.task_title || (session.problem_id ? `Practice: ${session.problem_id}` : "Standalone Practice");
            document.getElementById("activeSessSubtitle").textContent = `Problem: ${session.problem_id || 'None'} • Language: ${session.language.toUpperCase()}`;
            document.getElementById("activeSessTaskTypeBadge").textContent = (session.task_type || 'standalone').toUpperCase();

            // Evidence metrics
            document.getElementById("sessSubmissionsCount").textContent = session.submissions_count;
            document.getElementById("sessPassedCount").textContent = session.passed_submissions_count;
            document.getElementById("sessFailedCount").textContent = session.failed_submissions_count;
            const finalStatusEl = document.getElementById("sessFinalStatus");
            if (session.submissions_count === 0) {
                finalStatusEl.textContent = "Unattempted";
                finalStatusEl.style.color = "var(--text-muted)";
            } else if (session.final_submission_passed) {
                finalStatusEl.textContent = "PASSED";
                finalStatusEl.style.color = "var(--success)";
            } else {
                finalStatusEl.textContent = "FAILED";
                finalStatusEl.style.color = "var(--danger)";
            }

            // Reflection notes
            if (session.notes) {
                document.getElementById("noteInitialApproach").value = session.notes.initial_approach || "";
                document.getElementById("noteMistakes").value = session.notes.mistakes_encountered || "";
                document.getElementById("noteTimeCplx").value = session.notes.time_complexity || "";
                document.getElementById("noteSpaceCplx").value = session.notes.space_complexity || "";
                document.getElementById("noteKeyLearning").value = session.notes.key_learning || "";
            }

            // Pause/Resume button text
            if (btnPauseResume) {
                if (session.status === 'paused') {
                    btnPauseResume.textContent = "▶️ Resume";
                    btnPauseResume.className = "btn btn-primary btn-sm";
                } else {
                    btnPauseResume.textContent = "⏸️ Pause";
                    btnPauseResume.className = "btn btn-secondary btn-sm";
                }
            }

            // Start or freeze timer
            if (practiceSessionTimerInterval) clearInterval(practiceSessionTimerInterval);
            updatePracticeTimerDisplay();
            if (session.status === 'active') {
                practiceSessionTimerInterval = setInterval(updatePracticeTimerDisplay, 1000);
            }
        }

        function updatePracticeTimerDisplay() {
            const timerEl = document.getElementById("activeSessTimerDisplay");
            if (!timerEl) return;

            let totalSec = practiceSessionBaseElapsed;
            if (practiceSessionStatus === 'active' && practiceSessionStartedAt) {
                const now = Date.now();
                const deltaSec = Math.max(0, Math.floor((now - practiceSessionStartedAt) / 1000));
                totalSec += deltaSec;
            }

            const mins = Math.floor(totalSec / 60);
            const secs = totalSec % 60;
            timerEl.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        }

        async function startTaskPracticeSession(taskId) {
            try {
                const res = await fetch("/api/practice-session/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ task_id: taskId, force_switch: true })
                });

                if (res.ok) {
                    const session = await res.json();
                    renderPracticeSession(session);
                    showToast("Practice session launched for task!", "success");

                    // If problem_id exists, open in workspace editor
                    if (session.problem_id) {
                        openProblemInWorkspace(session.problem_id);
                    }
                    const card = document.getElementById("practiceSessionCard");
                    if (card) card.scrollIntoView({ behavior: 'smooth' });
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to start practice session", "error");
                }
            } catch (err) {
                showToast("Error starting task practice session", "error");
            }
        }

        async function startStandalonePracticeSession() {
            try {
                const pid = document.getElementById("standaloneProblemId").value.trim() || "two-sum";
                const lang = document.getElementById("standaloneLanguage").value || "python";

                const res = await fetch("/api/practice-session/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ problem_id: pid, language: lang, force_switch: true })
                });

                if (res.ok) {
                    const session = await res.json();
                    renderPracticeSession(session);
                    showToast("Standalone practice session started!", "success");
                    openProblemInWorkspace(pid);
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to start standalone session", "error");
                }
            } catch (err) {
                showToast("Error starting standalone session", "error");
            }
        }

        async function togglePauseResumeSession() {
            if (!activePracticeSessionId) return;
            const isPaused = (practiceSessionStatus === 'paused');
            const endpoint = isPaused ? `/api/practice-session/${activePracticeSessionId}/resume` : `/api/practice-session/${activePracticeSessionId}/pause`;

            try {
                const res = await fetch(endpoint, { method: "POST" });
                if (res.ok) {
                    const session = await res.json();
                    renderPracticeSession(session);
                    showToast(isPaused ? "Session resumed!" : "Session paused.", "info");
                } else {
                    const err = await res.json();
                    showToast(err.error || "Error toggling pause/resume", "error");
                }
            } catch (err) {
                showToast("Error toggling pause/resume", "error");
            }
        }

        async function endPracticeSession(status = "completed") {
            if (!activePracticeSessionId) return;
            if (!confirm(`Are you sure you want to ${status === 'abandoned' ? 'abandon' : 'end'} this practice session?`)) return;

            try {
                const res = await fetch(`/api/practice-session/${activePracticeSessionId}/end`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ status: status })
                });

                if (res.ok) {
                    renderPracticeSession(null);
                    showToast(`Practice session ${status}.`, "info");
                    reloadPreparationPlanner();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Error ending practice session", "error");
                }
            } catch (err) {
                showToast("Error ending practice session", "error");
            }
        }

        async function saveActiveSessionNotes() {
            if (!activePracticeSessionId) return;
            const payload = {
                initial_approach: document.getElementById("noteInitialApproach").value,
                mistakes_encountered: document.getElementById("noteMistakes").value,
                time_complexity: document.getElementById("noteTimeCplx").value,
                space_complexity: document.getElementById("noteSpaceCplx").value,
                key_learning: document.getElementById("noteKeyLearning").value,
            };

            try {
                const res = await fetch(`/api/practice-session/${activePracticeSessionId}/notes`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });

                if (res.ok) {
                    showToast("Reflection notes saved!", "success");
                } else {
                    const err = await res.json();
                    showToast(err.error || "Error saving notes", "error");
                }
            } catch (err) {
                showToast("Error saving notes", "error");
            }
        }

        async function confirmTaskCompletion() {
            if (!activePracticeSessionId) return;
            const payload = {
                initial_approach: document.getElementById("noteInitialApproach").value,
                mistakes_encountered: document.getElementById("noteMistakes").value,
                time_complexity: document.getElementById("noteTimeCplx").value,
                space_complexity: document.getElementById("noteSpaceCplx").value,
                key_learning: document.getElementById("noteKeyLearning").value,
            };

            try {
                const res = await fetch(`/api/practice-session/${activePracticeSessionId}/confirm-task`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });

                if (res.ok) {
                    const session = await res.json();
                    renderPracticeSession(null);
                    showToast("Preparation task confirmed completed and recorded!", "success");
                    reloadPreparationPlanner();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Error confirming task completion", "error");
                }
            } catch (err) {
                showToast("Error confirming task completion", "error");
            }
        }

        function openActiveSessionInWorkspace() {
            const sub = document.getElementById("activeSessSubtitle").textContent;
            const match = sub.match(/Problem:\s*([a-zA-Z0-9_\-]+)/);
            if (match && match[1] && match[1] !== 'None') {
                openProblemInWorkspace(match[1]);
                document.getElementById("workspaceCodeCard")?.scrollIntoView({ behavior: 'smooth' });
            }
        }

        async function showPracticeHistoryModal() {
            try {
                const res = await fetch("/api/practice-session/history");
                if (!res.ok) return;
                const items = await res.json();

                const modalBody = document.getElementById("modalSessionBody");
                document.getElementById("modalSessionTitle").textContent = "Practice Session History";

                if (items.length === 0) {
                    modalBody.innerHTML = "<p style='color: var(--text-muted);'>No historical practice sessions recorded yet.</p>";
                } else {
                    modalBody.innerHTML = `
                        <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem;">
                            <thead>
                                <tr style="border-bottom: 1px solid var(--border); color: var(--text-muted); text-align: left;">
                                    <th style="padding: 6px;">Date</th>
                                    <th style="padding: 6px;">Task / Problem</th>
                                    <th style="padding: 6px;">Status</th>
                                    <th style="padding: 6px;">Elapsed</th>
                                    <th style="padding: 6px;">Runs</th>
                                    <th style="padding: 6px;">Confirmed</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${items.map(i => `
                                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                                        <td style="padding: 6px; color: var(--text-muted);">${(i.created_at || '').slice(0, 16)}</td>
                                        <td style="padding: 6px; color: var(--text);"><strong>${i.task_title || i.problem_id || 'Standalone'}</strong></td>
                                        <td style="padding: 6px;"><span class="badge" style="font-size: 0.75rem;">${i.status.toUpperCase()}</span></td>
                                        <td style="padding: 6px; color: var(--text);">${Math.floor((i.elapsed_seconds || 0) / 60)}m ${((i.elapsed_seconds || 0) % 60)}s</td>
                                        <td style="padding: 6px; color: var(--text);">${i.submissions_count} (${i.passed_submissions_count} pass)</td>
                                        <td style="padding: 6px; color: ${i.task_confirmed_completed ? 'var(--success)' : 'var(--text-muted)'};">${i.task_confirmed_completed ? 'YES' : 'NO'}</td>
                                    </tr>
                                `).join("")}
                            </tbody>
                        </table>
                    `;
                }
                document.getElementById("sessionModal").style.display = "block";
            } catch (err) {
                console.error("Failed to show practice history:", err);
            }
        }

        // =========================================================================
        // Milestone 6.3.23: Personal Coding Behavior Intelligence Client Functions
        // =========================================================================

        async function reloadCodingBehavior() {
            try {
                const res = await fetch("/api/coding-behavior");
                if (!res.ok) return;
                const data = await res.json();
                renderCodingBehavior(data);
            } catch (err) {
                console.error("Failed to reload coding behavior data:", err);
            }
        }

        async function runBehaviorAnalysis() {
            try {
                const res = await fetch("/api/coding-behavior/analyze", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({}),
                });
                if (res.ok) {
                    showToast("Behavioral intelligence analysis complete!", "success");
                    await reloadCodingBehavior();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Analysis failed", "error");
                }
            } catch (err) {
                showToast("Error running behavioral analysis", "error");
            }
        }

        function renderCodingBehavior(data) {
            if (!data) return;

            // Update badge and top stats
            const badge = document.getElementById("cbConfidenceBadge");
            if (badge) {
                badge.textContent = (data.confidence || "BASELINE").toUpperCase();
                badge.style.background = data.sample_adequate ? "rgba(16, 185, 129, 0.2)" : "rgba(139, 92, 246, 0.2)";
                badge.style.color = data.sample_adequate ? "#6ee7b7" : "#c4b5fd";
            }

            document.getElementById("cbTotalEvents").textContent = data.total_evidence_events || 0;
            document.getElementById("cbConfidence").textContent = data.confidence || "insufficient_data";

            const attempts = data.attempt_patterns || {};
            document.getElementById("cbFirstPassRate").textContent = (attempts.first_attempt_pass_rate ?? 0) + "%";
            document.getElementById("cbPersistenceRate").textContent = (attempts.persistence_rate ?? 0) + "%";

            const sessions = data.session_behavior || {};
            document.getElementById("cbSessionCompletion").textContent = (sessions.completion_rate ?? 0) + "%";

            const psp = data.problem_solving_progression || {};
            document.getElementById("cbComplexityRate").textContent = (psp.complexity_awareness_rate ?? 0) + "%";

            // Render Patterns
            const patList = document.getElementById("cbPatternsList");
            if (patList) {
                const patterns = data.patterns || [];
                if (patterns.length === 0) {
                    patList.innerHTML = "<p style='margin:0; color:var(--text-muted);'>No distinct recurring patterns identified yet.</p>";
                } else {
                    patList.innerHTML = patterns.map(p => `
                        <div style="margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.05);">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                                <strong style="color: var(--text);">${p.name}</strong>
                                <span class="badge" style="font-size: 0.7rem; background: rgba(59, 130, 246, 0.15); color: #93c5fd;">${p.frequency}%</span>
                            </div>
                            <p style="margin: 0 0 2px 0; color: var(--text-muted); font-size: 0.75rem;">${p.description}</p>
                            <span style="font-size: 0.7rem; color: #64748b;">Evidence: ${p.evidence_summary}</span>
                        </div>
                    `).join("");
                }
            }

            // Render Insights
            const insList = document.getElementById("cbInsightsList");
            if (insList) {
                const insights = data.insights || [];
                if (insights.length === 0) {
                    insList.innerHTML = "<p style='margin:0; color:var(--text-muted);'>No behavioral insights generated yet.</p>";
                } else {
                    insList.innerHTML = insights.map(i => {
                        let color = "#93c5fd";
                        let bg = "rgba(59, 130, 246, 0.15)";
                        if (i.severity === "positive") { color = "#6ee7b7"; bg = "rgba(16, 185, 129, 0.15)"; }
                        else if (i.severity === "attention") { color = "#fcd34d"; bg = "rgba(245, 158, 11, 0.15)"; }
                        else if (i.severity === "recommendation") { color = "#c4b5fd"; bg = "rgba(139, 92, 246, 0.15)"; }

                        return `
                            <div style="margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.05);">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                                    <strong style="color: var(--text);">${i.title}</strong>
                                    <span class="badge" style="font-size: 0.65rem; background: ${bg}; color: ${color};">${(i.severity || 'info').toUpperCase()}</span>
                                </div>
                                <p style="margin: 0 0 2px 0; color: var(--text-muted); font-size: 0.75rem;">${i.description}</p>
                                <span style="font-size: 0.7rem; color: #94a3b8; display: block;">🎯 Action: ${i.recommended_action}</span>
                            </div>
                        `;
                    }).join("");
                }
            }

            // Render Recommendations
            const recList = document.getElementById("cbRecommendationsList");
            if (recList) {
                const recs = data.recommendations || [];
                if (recs.length === 0) {
                    recList.innerHTML = "<p style='margin:0; color:var(--text-muted);'>No practice recommendations at this time.</p>";
                } else {
                    recList.innerHTML = recs.map(r => `
                        <div style="margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.05);">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                                <strong style="color: var(--text);">${r.title}</strong>
                                <span class="badge" style="font-size: 0.65rem; background: rgba(245, 158, 11, 0.2); color: #fcd34d;">${r.priority || 'P1'}</span>
                            </div>
                            <p style="margin: 0 0 2px 0; color: var(--text-muted); font-size: 0.75rem;">${r.rationale}</p>
                            <span style="font-size: 0.7rem; color: #38bdf8; display: block;">👉 Suggested: ${r.suggested_action}</span>
                        </div>
                    `).join("");
                }
            }

            // Render Limitations / Disclaimer
            const limText = document.getElementById("cbLimitationsText");
            if (limText && data.limitations && data.limitations.length > 0) {
                limText.textContent = data.limitations.join(" • ");
            }
        }

        // =========================================================================
        // Milestone 6.3.24: Personal Skill Gap & Focus Prioritization Client Functions
        // =========================================================================

        async function reloadSkillGaps() {
            try {
                const res = await fetch("/api/skill-gaps");
                if (!res.ok) return;
                const data = await res.json();
                renderSkillGaps(data);
            } catch (err) {
                console.error("Failed to reload skill gap intelligence:", err);
            }
        }

        async function runSkillGapAnalysis() {
            try {
                const res = await fetch("/api/skill-gaps/analyze", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({}),
                });
                if (res.ok) {
                    showToast("Skill gap prioritization analysis complete!", "success");
                    await reloadSkillGaps();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Analysis failed", "error");
                }
            } catch (err) {
                showToast("Error running skill gap analysis", "error");
            }
        }

        function renderSkillGaps(data) {
            if (!data) return;

            const cov = data.coverage_summary || {};
            const covPct = cov.coverage_percentage ?? 0;
            const badge = document.getElementById("sgCoverageBadge");
            if (badge) {
                badge.textContent = `${covPct}% COVERAGE`;
                badge.style.background = covPct > 50 ? "rgba(16, 185, 129, 0.2)" : "rgba(236, 72, 153, 0.2)";
                badge.style.color = covPct > 50 ? "#6ee7b7" : "#f472b6";
            }

            document.getElementById("sgTotalTopics").textContent = cov.total_topics || 0;
            document.getElementById("sgPracticedCoverage").textContent = `${covPct}%`;
            document.getElementById("sgCriticalGaps").textContent = cov.critical_gap_count || 0;
            document.getElementById("sgStrengthsCount").textContent = cov.strengths_count || 0;

            // Render Focus Queue Table
            const tbody = document.getElementById("sgFocusQueueBody");
            if (tbody) {
                const queue = data.focus_queue || [];
                if (queue.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="8" style="padding: 12px; text-align: center; color: var(--text-muted);">No focus queue items available. Click 'Analyze Now'.</td></tr>`;
                } else {
                    tbody.innerHTML = queue.map(item => {
                        let prioColor = "#93c5fd";
                        let prioBg = "rgba(59, 130, 246, 0.2)";
                        if (item.priority_tier === "P0") { prioColor = "#ef4444"; prioBg = "rgba(239, 68, 68, 0.2)"; }
                        else if (item.priority_tier === "P1") { prioColor = "#f59e0b"; prioBg = "rgba(245, 158, 11, 0.2)"; }
                        else if (item.priority_tier === "P2") { prioColor = "#38bdf8"; prioBg = "rgba(56, 189, 248, 0.2)"; }

                        const catLabel = (item.gap_type || '').replace(/_/g, ' ').toUpperCase();
                        return `
                            <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                                <td style="padding: 6px 8px; color: var(--text-muted); font-weight: bold;">#${item.rank}</td>
                                <td style="padding: 6px 8px;"><span class="badge" style="background:${prioBg}; color:${prioColor}; font-size:0.7rem;">${item.priority_tier}</span></td>
                                <td style="padding: 6px 8px; color: var(--text); font-weight: 600;">${item.topic}</td>
                                <td style="padding: 6px 8px;"><span style="font-size: 0.7rem; color: #94a3b8;">${catLabel}</span></td>
                                <td style="padding: 6px 8px; color: var(--text); font-weight: 500;">${item.priority_score}</td>
                                <td style="padding: 6px 8px; color: #cbd5e1;">${item.suggested_difficulty}</td>
                                <td style="padding: 6px 8px; color: #38bdf8; font-size: 0.75rem;">${item.suggested_action}</td>
                                <td style="padding: 6px 8px; color: var(--text-muted); font-size: 0.75rem;">${item.reason}</td>
                            </tr>
                        `;
                    }).join("");
                }
            }

            // Render Strengths
            const strList = document.getElementById("sgStrengthsList");
            if (strList) {
                const strengths = data.strengths || [];
                if (strengths.length === 0) {
                    strList.innerHTML = "<p style='margin:0; color:var(--text-muted);'>No confirmed strengths yet (requires >= 2 solves and >= 80% success rate).</p>";
                } else {
                    strList.innerHTML = strengths.map(s => `
                        <div style="margin-bottom: 6px; padding-bottom: 4px; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
                            <strong style="color: var(--success);">${s.topic}</strong>
                            <span style="font-size: 0.75rem; color: #94a3b8;">${s.evidence.solved_problems_count} solved • ${s.evidence.success_rate}% success</span>
                        </div>
                    `).join("");
                }
            }

            // Render Insufficient Practice Topics
            const insList = document.getElementById("sgInsufficientList");
            if (insList) {
                const unpracticed = data.insufficient_evidence_topics || [];
                if (unpracticed.length === 0) {
                    insList.innerHTML = "<p style='margin:0; color:var(--text-muted);'>All evaluated topics currently have practice evidence.</p>";
                } else {
                    insList.innerHTML = unpracticed.map(u => `
                        <div style="margin-bottom: 6px; padding-bottom: 4px; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
                            <strong style="color: var(--text);">${u.topic}</strong>
                            <span style="font-size: 0.75rem; color: #94a3b8;">0 solves • ${u.evidence.total_problems_available} in library</span>
                        </div>
                    `).join("");
                }
            }

            // Render Limitations / Disclaimer
            const limText = document.getElementById("sgLimitationsText");
            if (limText && data.limitations && data.limitations.length > 0) {
                limText.textContent = data.limitations.join(" • ");
            }
        }

        // =========================================================================
        // Milestone 6.3.25: Adaptive Learning Loop Client Functions
        // =========================================================================

        let currentLoopRecommendedAction = null;

        async function reloadLearningLoop() {
            try {
                const res = await fetch("/api/learning-loop");
                if (!res.ok) return;
                const data = await res.json();
                renderLearningLoop(data);
            } catch (err) {
                console.error("Failed to reload learning loop intelligence:", err);
            }
        }

        async function runLearningLoopAnalysis() {
            try {
                const res = await fetch("/api/learning-loop/analyze", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({}),
                });
                if (res.ok) {
                    showToast("Learning cycle evaluated & reconciled!", "success");
                    await reloadLearningLoop();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Loop analysis failed", "error");
                }
            } catch (err) {
                showToast("Error running learning loop analysis", "error");
            }
        }

        async function acceptLearningLoopProposal(proposalId) {
            try {
                const res = await fetch("/api/learning-loop/proposals/accept", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ proposal_id: proposalId, apply_to_plan: true }),
                });
                if (res.ok) {
                    showToast("Proposal accepted and reconciled with plan!", "success");
                    await reloadLearningLoop();
                    reloadPreparationPlanner();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to accept proposal", "error");
                }
            } catch (err) {
                showToast("Error accepting proposal", "error");
            }
        }

        async function rejectLearningLoopProposal(proposalId) {
            try {
                const res = await fetch("/api/learning-loop/proposals/reject", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ proposal_id: proposalId }),
                });
                if (res.ok) {
                    showToast("Proposal rejected.", "info");
                    await reloadLearningLoop();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to reject proposal", "error");
                }
            } catch (err) {
                showToast("Error rejecting proposal", "error");
            }
        }

        function launchLoopPracticeAction() {
            if (!currentLoopRecommendedAction) return;
            const pid = currentLoopRecommendedAction.problem_id;
            if (pid) {
                openProblemInWorkspace(pid);
                showToast(`Loaded recommended problem '${pid}' in Workspace!`, "success");
            }
        }

        function renderLearningLoop(data) {
            if (!data) return;

            const badge = document.getElementById("llPhaseBadge");
            if (badge) {
                badge.textContent = (data.phase || "RE_EVALUATION").toUpperCase();
            }

            document.getElementById("llCurrentPhase").textContent = data.phase || "re_evaluation";
            const topFocus = (data.highest_priority_focus && data.highest_priority_focus.length > 0)
                ? data.highest_priority_focus[0]
                : "None";
            document.getElementById("llTopFocus").textContent = topFocus;

            const pending = data.pending_proposals || [];
            document.getElementById("llPendingProposalsCount").textContent = pending.length;

            // Next recommended practice action
            currentLoopRecommendedAction = data.next_recommended_action;
            const launchBtn = document.getElementById("llActionLaunchBtn");
            if (currentLoopRecommendedAction) {
                document.getElementById("llActionTitle").textContent = `${currentLoopRecommendedAction.topic}: ${currentLoopRecommendedAction.problem_id || 'Problem Practice'} (${currentLoopRecommendedAction.difficulty})`;
                document.getElementById("llActionReason").textContent = currentLoopRecommendedAction.reason || currentLoopRecommendedAction.learning_objective;
                if (launchBtn) launchBtn.style.display = currentLoopRecommendedAction.problem_id ? "inline-block" : "none";
            } else {
                document.getElementById("llActionTitle").textContent = "No immediate practice action needed";
                document.getElementById("llActionReason").textContent = "Active preparation plan and skill gaps are aligned.";
                if (launchBtn) launchBtn.style.display = "none";
            }

            // Render Proposals Table
            const tbody = document.getElementById("llProposalsBody");
            if (tbody) {
                if (pending.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="6" style="padding: 12px; text-align: center; color: var(--text-muted);">No pending plan proposals. Current preparation plan matches diagnosed skill gaps.</td></tr>`;
                } else {
                    tbody.innerHTML = pending.map(prop => {
                        let actionBg = "rgba(59, 130, 246, 0.2)";
                        let actionColor = "#93c5fd";
                        if (prop.action_type === "add_task") { actionBg = "rgba(16, 185, 129, 0.2)"; actionColor = "#6ee7b7"; }
                        else if (prop.action_type === "adjust_difficulty") { actionBg = "rgba(245, 158, 11, 0.2)"; actionColor = "#fcd34d"; }
                        else if (prop.action_type === "revise_task") { actionBg = "rgba(139, 92, 246, 0.2)"; actionColor = "#c4b5fd"; }

                        return `
                            <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                                <td style="padding: 6px 8px;"><span class="badge" style="background:${actionBg}; color:${actionColor}; font-size:0.7rem;">${prop.action_type.toUpperCase()}</span></td>
                                <td style="padding: 6px 8px; font-weight: 600; color: var(--text);">${prop.topic || 'General'}</td>
                                <td style="padding: 6px 8px; color: var(--text); font-size: 0.8rem;">${prop.title}</td>
                                <td style="padding: 6px 8px; color: #cbd5e1;">${prop.target_difficulty}</td>
                                <td style="padding: 6px 8px; color: var(--text-muted); font-size: 0.75rem;">${prop.rationale}</td>
                                <td style="padding: 6px 8px; white-space: nowrap;">
                                    <button class="btn btn-primary btn-sm" style="font-size: 0.7rem; padding: 2px 6px; margin-right: 4px;" onclick="acceptLearningLoopProposal('${prop.proposal_id}')">Accept</button>
                                    <button class="btn btn-secondary btn-sm" style="font-size: 0.7rem; padding: 2px 6px;" onclick="rejectLearningLoopProposal('${prop.proposal_id}')">Reject</button>
                                </td>
                            </tr>
                        `;
                    }).join("");
                }
            }

            // Render Comparison Summary
            const compText = document.getElementById("llComparisonText");
            if (compText) {
                const comp = data.comparison;
                if (comp && comp.summary) {
                    compText.textContent = comp.summary;
                } else {
                    compText.textContent = "Baseline cycle recorded. Future cycles will compare progression automatically.";
                }
            }

            // Render Limitations / Disclaimer
            const limText = document.getElementById("llLimitationsText");
            if (limText && data.limitations && data.limitations.length > 0) {
                limText.textContent = data.limitations.join(" • ");
            }
        }

        // =========================================================================
        // Milestone 6.3.26: Guided Daily Practice & Study Session Client Functions
        // =========================================================================

        let currentDailyPracticeSession = null;

        function onDpBudgetChange() {
            const select = document.getElementById("dpBudgetSelect");
            const customInput = document.getElementById("dpCustomMinutes");
            if (select && customInput) {
                customInput.style.display = select.value === "custom" ? "inline-block" : "none";
            }
        }

        async function reloadDailyPractice() {
            try {
                const res = await fetch("/api/daily-practice");
                if (!res.ok) return;
                const data = await res.json();
                renderDailyPractice(data);
            } catch (err) {
                console.error("Failed to load daily practice overview:", err);
            }
        }

        async function generateDailyPracticeSession() {
            const select = document.getElementById("dpBudgetSelect");
            const customInput = document.getElementById("dpCustomMinutes");
            let budget = 45;
            if (select) {
                if (select.value === "custom" && customInput && customInput.value) {
                    budget = parseInt(customInput.value, 10);
                } else {
                    budget = parseInt(select.value, 10);
                }
            }
            if (isNaN(budget) || budget < 15 || budget > 360) {
                showToast("Budget must be between 15 and 360 minutes", "error");
                return;
            }

            try {
                const res = await fetch("/api/daily-practice/generate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ budget_minutes: budget }),
                });
                if (res.ok) {
                    showToast("New daily study session generated!", "success");
                    await reloadDailyPractice();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to generate session", "error");
                }
            } catch (err) {
                console.error("Generate daily practice error:", err);
                showToast("Failed to generate session", "error");
            }
        }

        async function startDailyPracticeSession() {
            if (!currentDailyPracticeSession) return;
            try {
                const res = await fetch("/api/daily-practice/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: currentDailyPracticeSession.session_id }),
                });
                if (res.ok) {
                    showToast("Study session started!", "success");
                    await reloadDailyPractice();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to start session", "error");
                }
            } catch (err) {
                showToast("Failed to start session", "error");
            }
        }

        async function startDailyPracticeTask(taskId) {
            if (!currentDailyPracticeSession) return;
            try {
                const res = await fetch("/api/daily-practice/task/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: currentDailyPracticeSession.session_id, task_id: taskId }),
                });
                if (res.ok) {
                    showToast("Task started!", "info");
                    await reloadDailyPractice();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to start task", "error");
                }
            } catch (err) {
                showToast("Failed to start task", "error");
            }
        }

        async function completeDailyPracticeTask(taskId) {
            if (!currentDailyPracticeSession) return;
            try {
                const res = await fetch("/api/daily-practice/task/complete", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        session_id: currentDailyPracticeSession.session_id,
                        task_id: taskId,
                        verified_pass: true,
                        notes: "Completed via dashboard",
                    }),
                });
                if (res.ok) {
                    showToast("Task completed!", "success");
                    await reloadDailyPractice();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to complete task", "error");
                }
            } catch (err) {
                showToast("Failed to complete task", "error");
            }
        }

        async function skipDailyPracticeTask(taskId) {
            if (!currentDailyPracticeSession) return;
            try {
                const res = await fetch("/api/daily-practice/task/skip", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        session_id: currentDailyPracticeSession.session_id,
                        task_id: taskId,
                        reason: "Skipped via dashboard",
                    }),
                });
                if (res.ok) {
                    showToast("Task skipped", "info");
                    await reloadDailyPractice();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to skip task", "error");
                }
            } catch (err) {
                showToast("Failed to skip task", "error");
            }
        }

        async function pauseDailyPracticeSession() {
            if (!currentDailyPracticeSession) return;
            try {
                const res = await fetch("/api/daily-practice/pause", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: currentDailyPracticeSession.session_id, reason: "Paused via dashboard" }),
                });
                if (res.ok) {
                    showToast("Session paused", "info");
                    await reloadDailyPractice();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to pause session", "error");
                }
            } catch (err) {
                showToast("Failed to pause session", "error");
            }
        }

        async function resumeDailyPracticeSession() {
            if (!currentDailyPracticeSession) return;
            try {
                const res = await fetch("/api/daily-practice/resume", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: currentDailyPracticeSession.session_id }),
                });
                if (res.ok) {
                    showToast("Session resumed!", "success");
                    await reloadDailyPractice();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to resume session", "error");
                }
            } catch (err) {
                showToast("Failed to resume session", "error");
            }
        }

        async function abandonDailyPracticeSession() {
            if (!currentDailyPracticeSession) return;
            if (!confirm("Are you sure you want to abandon this practice session?")) return;
            try {
                const res = await fetch("/api/daily-practice/abandon", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: currentDailyPracticeSession.session_id, reason: "Abandoned by user" }),
                });
                if (res.ok) {
                    showToast("Session abandoned", "info");
                    await reloadDailyPractice();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to abandon session", "error");
                }
            } catch (err) {
                showToast("Failed to abandon session", "error");
            }
        }

        async function completeDailyPracticeSession() {
            if (!currentDailyPracticeSession) return;
            try {
                const res = await fetch("/api/daily-practice/complete", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: currentDailyPracticeSession.session_id, notes: "Completed via dashboard" }),
                });
                if (res.ok) {
                    showToast("Session completed! Report generated.", "success");
                    await reloadDailyPractice();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to complete session", "error");
                }
            } catch (err) {
                showToast("Failed to complete session", "error");
            }
        }

        async function reevaluateDailyPracticeLoop() {
            if (!currentDailyPracticeSession) return;
            try {
                const res = await fetch("/api/daily-practice/re-evaluate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: currentDailyPracticeSession.session_id }),
                });
                if (res.ok) {
                    showToast("Session evidence fed back to Learning Loop!", "success");
                    await reloadDailyPractice();
                    reloadLearningLoop();
                } else {
                    const err = await res.json();
                    showToast(err.error || "Failed to re-evaluate learning loop", "error");
                }
            } catch (err) {
                showToast("Failed to re-evaluate learning loop", "error");
            }
        }

        function renderDailyPractice(data) {
            const session = data.active_session || data.latest_session;
            currentDailyPracticeSession = session;

            const badge = document.getElementById("dpStatusBadge");
            const titleEl = document.getElementById("dpSessionTitle");
            const timeEl = document.getElementById("dpTimeDisplay");
            const progressEl = document.getElementById("dpProgressDisplay");
            const verifiedEl = document.getElementById("dpVerifiedDisplay");
            const currentTaskEl = document.getElementById("dpCurrentTaskLabel");

            const startBtn = document.getElementById("dpStartBtn");
            const pauseBtn = document.getElementById("dpPauseBtn");
            const resumeBtn = document.getElementById("dpResumeBtn");
            const completeBtn = document.getElementById("dpCompleteBtn");
            const abandonBtn = document.getElementById("dpAbandonBtn");
            const reevaluateBtn = document.getElementById("dpReevaluateBtn");

            // Hide all action buttons by default
            [startBtn, pauseBtn, resumeBtn, completeBtn, abandonBtn, reevaluateBtn].forEach(b => {
                if (b) b.style.display = "none";
            });

            if (!session) {
                if (badge) {
                    badge.textContent = "NO SESSION";
                    badge.style.background = "rgba(100, 116, 139, 0.2)";
                    badge.style.color = "#94a3b8";
                }
                if (titleEl) titleEl.textContent = "No session generated";
                if (timeEl) timeEl.textContent = `0 / ${data.default_budget_minutes || 45}m`;
                if (progressEl) progressEl.textContent = "0% (0/0)";
                if (verifiedEl) verifiedEl.textContent = "0";
                if (currentTaskEl) currentTaskEl.innerHTML = "Current focus: <strong>None</strong>";
                const tbody = document.getElementById("dpTasksTableBody");
                if (tbody) {
                    tbody.innerHTML = `<tr><td colspan="7" style="padding: 12px; text-align: center; color: var(--text-muted);">No study session active. Click "Generate Today's Session" to schedule tasks based on learning evidence.</td></tr>`;
                }
                return;
            }

            const status = (session.status || "ready").toUpperCase();
            if (badge) {
                badge.textContent = status;
                if (status === "ACTIVE") {
                    badge.style.background = "rgba(16, 185, 129, 0.2)";
                    badge.style.color = "#6ee7b7";
                } else if (status === "PAUSED") {
                    badge.style.background = "rgba(245, 158, 11, 0.2)";
                    badge.style.color = "#fcd34d";
                } else if (status === "COMPLETED") {
                    badge.style.background = "rgba(59, 130, 246, 0.2)";
                    badge.style.color = "#93c5fd";
                } else if (status === "ABANDONED") {
                    badge.style.background = "rgba(239, 68, 68, 0.2)";
                    badge.style.color = "#fca5a5";
                } else {
                    badge.style.background = "rgba(147, 51, 234, 0.2)";
                    badge.style.color = "#d8b4fe";
                }
            }

            if (titleEl) titleEl.textContent = session.title || "Daily Study Session";
            const elapsedMins = Math.round((session.elapsed_seconds || 0) / 60);
            if (timeEl) timeEl.textContent = `${elapsedMins} / ${session.budget_minutes}m`;

            const prog = session.progress || {};
            const pct = prog.completion_percentage || 0;
            const completedCount = prog.completed_tasks || 0;
            const totalCount = prog.total_tasks || (session.tasks ? session.tasks.length : 0);
            if (progressEl) progressEl.textContent = `${Math.round(pct)}% (${completedCount}/${totalCount})`;

            const verifiedCount = prog.verified_passes || 0;
            if (verifiedEl) verifiedEl.textContent = `${verifiedCount}`;

            // Button visibility based on status
            if (status === "READY") {
                if (startBtn) startBtn.style.display = "inline-block";
                if (abandonBtn) abandonBtn.style.display = "inline-block";
            } else if (status === "ACTIVE") {
                if (pauseBtn) pauseBtn.style.display = "inline-block";
                if (completeBtn) completeBtn.style.display = "inline-block";
                if (abandonBtn) abandonBtn.style.display = "inline-block";
            } else if (status === "PAUSED") {
                if (resumeBtn) resumeBtn.style.display = "inline-block";
                if (completeBtn) completeBtn.style.display = "inline-block";
                if (abandonBtn) abandonBtn.style.display = "inline-block";
            } else if (status === "COMPLETED") {
                if (reevaluateBtn) reevaluateBtn.style.display = "inline-block";
            }

            // Current task focus label
            const activeTask = (session.tasks || []).find(t => t.status === "in_progress")
                || (session.tasks || []).find(t => t.status === "pending");
            if (currentTaskEl) {
                if (activeTask) {
                    currentTaskEl.innerHTML = `Current focus: <strong>${activeTask.title}</strong> (${activeTask.target_duration_minutes}m • ${activeTask.topic || 'General'})`;
                } else {
                    currentTaskEl.innerHTML = `Current focus: <strong>Session Finished</strong>`;
                }
            }

            // Render tasks table
            const tbody = document.getElementById("dpTasksTableBody");
            if (tbody && session.tasks) {
                tbody.innerHTML = session.tasks.map(t => {
                    let typeBg = "rgba(59, 130, 246, 0.2)";
                    let typeColor = "#93c5fd";
                    if (t.task_type === "unresolved_review") { typeBg = "rgba(239, 68, 68, 0.2)"; typeColor = "#fca5a5"; }
                    else if (t.task_type === "spaced_revision") { typeBg = "rgba(245, 158, 11, 0.2)"; typeColor = "#fcd34d"; }
                    else if (t.task_type === "skill_gap_drill") { typeBg = "rgba(168, 85, 247, 0.2)"; typeColor = "#d8b4fe"; }
                    else if (t.task_type === "break_checkpoint") { typeBg = "rgba(100, 116, 139, 0.2)"; typeColor = "#94a3b8"; }
                    else if (t.task_type === "session_reflection") { typeBg = "rgba(16, 185, 129, 0.2)"; typeColor = "#6ee7b7"; }

                    let statusBg = "rgba(100, 116, 139, 0.2)";
                    let statusColor = "#94a3b8";
                    if (t.status === "completed") { statusBg = "rgba(16, 185, 129, 0.2)"; statusColor = "#6ee7b7"; }
                    else if (t.status === "in_progress") { statusBg = "rgba(6, 182, 212, 0.2)"; statusColor = "#67e8f9"; }
                    else if (t.status === "skipped") { statusBg = "rgba(245, 158, 11, 0.2)"; statusColor = "#fcd34d"; }

                    let actionsHtml = "";
                    if (status === "ACTIVE" || status === "READY") {
                        if (t.status === "pending") {
                            actionsHtml += `<button class="btn btn-primary btn-sm" style="font-size: 0.7rem; padding: 2px 6px; margin-right: 4px;" onclick="startDailyPracticeTask('${t.task_id}')">Start</button>`;
                            actionsHtml += `<button class="btn btn-secondary btn-sm" style="font-size: 0.7rem; padding: 2px 6px;" onclick="skipDailyPracticeTask('${t.task_id}')">Skip</button>`;
                        } else if (t.status === "in_progress") {
                            if (t.problem_id) {
                                actionsHtml += `<button class="btn btn-secondary btn-sm" style="font-size: 0.7rem; padding: 2px 6px; margin-right: 4px;" onclick="launchWorkspace('${t.problem_id}')">🚀 Solve</button>`;
                            }
                            actionsHtml += `<button class="btn btn-primary btn-sm" style="font-size: 0.7rem; padding: 2px 6px; margin-right: 4px; background:#059669;" onclick="completeDailyPracticeTask('${t.task_id}')">Done</button>`;
                            actionsHtml += `<button class="btn btn-secondary btn-sm" style="font-size: 0.7rem; padding: 2px 6px;" onclick="skipDailyPracticeTask('${t.task_id}')">Skip</button>`;
                        } else {
                            actionsHtml = `<span style="font-size: 0.75rem; color: var(--text-muted);">${t.verified_pass ? '✅ Verified' : 'Finished'}</span>`;
                        }
                    } else {
                        actionsHtml = `<span style="font-size: 0.75rem; color: var(--text-muted);">${t.verified_pass ? '✅ Verified' : (t.status)}</span>`;
                    }

                    return `
                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                            <td style="padding: 6px 8px; color: var(--text-muted); font-size: 0.75rem;">${t.order_index}</td>
                            <td style="padding: 6px 8px;"><span class="badge" style="background:${typeBg}; color:${typeColor}; font-size:0.7rem;">${t.task_type}</span></td>
                            <td style="padding: 6px 8px; font-weight: 600; color: var(--text);">
                                ${t.title}
                                ${t.problem_id ? '<span style="font-size:0.75rem; color: var(--text-muted); font-weight: normal;"> (#' + t.problem_id + ')</span>' : ''}
                            </td>
                            <td style="padding: 6px 8px; color: #cbd5e1;">${t.target_duration_minutes}m</td>
                            <td style="padding: 6px 8px; color: #cbd5e1;">${t.actual_duration_minutes || 0}m</td>
                            <td style="padding: 6px 8px;"><span class="badge" style="background:${statusBg}; color:${statusColor}; font-size:0.7rem;">${t.status}</span></td>
                            <td style="padding: 6px 8px; white-space: nowrap;">${actionsHtml}</td>
                        </tr>
                    `;
                }).join("");
            }
        }

        // Close modal on outside click
        window.onclick = function(event) {
            const modal = document.getElementById("sessionModal");
            if (event.target == modal) {
                modal.style.display = "none";
            }
        }
    </script>
</body>
</html>
"""


def create_app(
    db_path: Optional[str | Path] = None,
    tracking_db_path: Optional[str | Path] = None,
) -> Flask:
    """Create and configure the Flask interactive learning command center app."""
    app = Flask(__name__)
    tracker_path = tracking_db_path if tracking_db_path is not None else DEFAULT_TRACKING_DB_PATH

    @app.route("/")
    def index():
        data = get_dashboard_data(db_path=db_path)
        # Ensure learning intelligence connects to the specific tracking db
        data["learning_intelligence"] = _get_learning_intelligence_data(
            db_path=db_path,
            tracking_db_path=tracker_path,
            language="python",
        )
        return render_template_string(HTML_TEMPLATE, data=data)

    @app.route("/api/dashboard")
    def api_dashboard():
        data = get_dashboard_data(db_path=db_path)
        data["learning_intelligence"] = _get_learning_intelligence_data(
            db_path=db_path,
            tracking_db_path=tracker_path,
            language="python",
        )
        return jsonify(data)

    @app.route("/api/preview-plan")
    def api_preview_plan():
        """Generate a preview session plan based on query parameters."""
        try:
            session_size = int(request.args.get("session_size", 3))
        except ValueError:
            return jsonify({"error": "Invalid session_size"}), 400

        if session_size < 1 or session_size > 10:
            return jsonify({"error": "session_size must be between 1 and 10"}), 400

        diff = request.args.get("difficulty")
        if diff:
            diff = diff.strip().lower()
            if diff not in ("easy", "medium", "hard"):
                return jsonify({"error": "Invalid difficulty"}), 400

        skip_solved = request.args.get("skip_solved", "true").lower() == "true"

        candidates = load_problems()
        planner = SessionPlanner(
            db_path=db_path,
            language="python",
            preferred_difficulty=diff,
        )
        session_plan = planner.plan_session(
            candidates=candidates,
            session_size=session_size,
            skip_solved=skip_solved,
        )

        problems_list = []
        for p in session_plan.planned_problems:
            problems_list.append({
                "rank": p.rank,
                "role": p.role.value,
                "problem_id": p.problem_id,
                "title": p.title,
                "difficulty": p.difficulty,
                "priority_score": p.priority_score,
                "topics": p.topics,
                "reason": p.reason,
            })

        return jsonify({
            "target_size": session_plan.target_size,
            "total_planned": session_plan.total_problems,
            "summary": session_plan.session_summary,
            "problems": problems_list,
        })

    @app.route("/api/save-session", methods=["POST"])
    def api_save_session():
        """Save a generated session plan to the tracking database."""
        req_data = request.get_json(silent=True) or {}
        session_size = req_data.get("session_size", 3)
        diff = req_data.get("difficulty")
        skip_solved = req_data.get("skip_solved", True)

        try:
            session_size = int(session_size)
            if session_size < 1 or session_size > 10:
                return jsonify({"error": "session_size must be between 1 and 10"}), 400
        except ValueError:
            return jsonify({"error": "Invalid session_size"}), 400

        if diff and diff.lower() not in ("easy", "medium", "hard"):
            return jsonify({"error": "Invalid difficulty"}), 400

        candidates = load_problems()
        planner = SessionPlanner(
            db_path=db_path,
            language="python",
            preferred_difficulty=diff.lower() if diff else None,
        )
        plan = planner.plan_session(
            candidates=candidates,
            session_size=session_size,
            skip_solved=bool(skip_solved),
        )

        if not plan.planned_problems:
            return jsonify({"error": "No problems available to plan session"}), 400

        tracker = SessionTracker(db_path=tracker_path)
        record = tracker.record_session(plan)
        return jsonify({
            "message": "Session saved successfully",
            "session_id": record.session_id,
            "status": record.status.value,
            "total_problems": record.total_problems,
        }), 201

    @app.route("/api/sessions")
    def api_sessions():
        """Retrieve list of tracked sessions."""
        tracker = SessionTracker(db_path=tracker_path)
        sessions = tracker.list_sessions(limit=50)
        return jsonify([
            {
                "session_id": s.session_id,
                "status": s.status.value,
                "target_language": s.target_language,
                "total_problems": s.total_problems,
                "completed_count": s.completed_count,
                "skipped_count": s.skipped_count,
                "created_at": s.created_at,
                "summary": s.session_summary,
            }
            for s in sessions
        ])

    @app.route("/api/session/<session_id>")
    def api_session_detail(session_id: str):
        """Retrieve details and item list of a specific session."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid session ID format"}), 400

        tracker = SessionTracker(db_path=tracker_path)
        s = tracker.get_session(session_id)
        if not s:
            return jsonify({"error": f"Session '{session_id}' not found"}), 404

        return jsonify({
            "session_id": s.session_id,
            "target_language": s.target_language,
            "status": s.status.value,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "completed_at": s.completed_at,
            "session_summary": s.session_summary,
            "problems": [
                {
                    "rank": p.rank,
                    "problem_id": p.problem_id,
                    "role": p.role,
                    "difficulty": p.difficulty,
                    "topics": p.topics,
                    "status": p.status.value,
                    "priority_score": p.priority_score,
                    "reason": p.reason,
                    "completed_at": p.completed_at,
                }
                for p in s.problems
            ],
        })

    @app.route("/api/session/<session_id>/status", methods=["POST"])
    def api_session_update_status(session_id: str):
        """Update session lifecycle status (start, completed, cancel)."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid session ID format"}), 400

        req_data = request.get_json(silent=True) or {}
        action = req_data.get("action")
        if action not in ("start", "completed", "cancel"):
            return jsonify({"error": "Action must be 'start', 'completed', or 'cancel'"}), 400

        tracker = SessionTracker(db_path=tracker_path)
        try:
            if action == "start":
                updated = tracker.start_session(session_id)
            elif action == "completed":
                updated = tracker.complete_session(session_id)
            elif action == "cancel":
                updated = tracker.cancel_session(session_id, reason="Cancelled via interactive command center")
            return jsonify({
                "message": f"Session status updated to {updated.status.value}",
                "session_id": updated.session_id,
                "status": updated.status.value,
            })
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/session/<session_id>/problem/<problem_id>", methods=["POST"])
    def api_update_problem_progress(session_id: str, problem_id: str):
        """Mark a problem completed or skipped within a session."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id) or not re.match(r"^[a-zA-Z0-9_\-]+$", problem_id):
            return jsonify({"error": "Invalid identifier format"}), 400

        req_data = request.get_json(silent=True) or {}
        status_str = req_data.get("status")
        if status_str not in ("completed", "skipped"):
            return jsonify({"error": "Status must be 'completed' or 'skipped'"}), 400

        tracker = SessionTracker(db_path=tracker_path)
        try:
            target_status = ProblemProgressStatus.COMPLETED if status_str == "completed" else ProblemProgressStatus.SKIPPED
            updated = tracker.update_problem_progress(session_id, problem_id, target_status)

            # Auto-complete session if all problems finished
            if updated.pending_count == 0:
                tracker.complete_session(session_id)
                updated.status = SessionStatus.COMPLETED

            return jsonify({
                "message": f"Problem '{problem_id}' marked as {status_str}",
                "session_id": updated.session_id,
                "session_status": updated.status.value,
                "completed_count": updated.completed_count,
                "skipped_count": updated.skipped_count,
                "pending_count": updated.pending_count,
            })
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/insights")
    def api_insights():
        """Retrieve complete learning performance insights report."""
        engine = LearningInsightsEngine(
            progress_db_path=db_path,
            tracking_db_path=tracker_path,
        )
        report = engine.generate_report()
        from dataclasses import asdict
        return jsonify(asdict(report))

    @app.route("/api/export/json")
    def api_export_json():
        """Safe export of learning analytics as sanitized JSON."""
        engine = LearningInsightsEngine(
            progress_db_path=db_path,
            tracking_db_path=tracker_path,
        )
        json_str = engine.export_json()
        return Response(
            json_str,
            mimetype="application/json",
            headers={"Content-Disposition": "attachment;filename=learning_analytics.json"},
        )

    @app.route("/api/export/csv")
    def api_export_csv():
        """Safe export of learning analytics as sanitized CSV."""
        engine = LearningInsightsEngine(
            progress_db_path=db_path,
            tracking_db_path=tracker_path,
        )
        csv_str = engine.export_csv()
        return Response(
            csv_str,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=learning_analytics.csv"},
        )

    @app.route("/api/coach/overview")
    def api_coach_overview():
        """Retrieve personalized coaching summary, recommended problem, and observations."""
        coach = OfflineCodingCoach(
            progress_db_path=db_path,
            tracking_db_path=tracker_path,
            language="python",
        )
        overview = coach.get_coach_overview()
        from dataclasses import asdict
        return jsonify(asdict(overview))

    @app.route("/api/coach/problem/<problem_id>")
    def api_coach_problem_guide(problem_id: str):
        """Retrieve 8-point pedagogical problem-solving guide."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", problem_id):
            return jsonify({"error": "Invalid problem identifier format"}), 400

        coach = OfflineCodingCoach(
            progress_db_path=db_path,
            tracking_db_path=tracker_path,
            language="python",
        )
        guide = coach.get_problem_guidance(problem_id)
        if not guide:
            return jsonify({"error": f"Problem '{problem_id}' not found"}), 404

        from dataclasses import asdict
        return jsonify(asdict(guide))

    @app.route("/api/coach/problem/<problem_id>/hint")
    def api_coach_problem_hint(problem_id: str):
        """Retrieve progressive hint tier (1 to 4) for a problem."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", problem_id):
            return jsonify({"error": "Invalid problem identifier format"}), 400

        try:
            tier = int(request.args.get("tier", 1))
        except ValueError:
            return jsonify({"error": "Invalid tier parameter"}), 400

        if tier < 1 or tier > 4:
            return jsonify({"error": "Tier must be an integer between 1 and 4"}), 400

        coach = OfflineCodingCoach(
            progress_db_path=db_path,
            tracking_db_path=tracker_path,
            language="python",
        )
        hint = coach.get_progressive_hint(problem_id, tier=tier)
        if not hint:
            return jsonify({"error": f"Hint not available for problem '{problem_id}'"}), 404

        from dataclasses import asdict
        return jsonify(asdict(hint))

    @app.route("/api/revision/queue")
    def api_revision_queue():
        """Retrieve the prioritized spaced revision queue."""
        rev_engine = SpacedRevisionEngine(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        status_filter = request.args.get("status")
        items = rev_engine.list_queue(status_filter=status_filter)
        from dataclasses import asdict
        return jsonify([asdict(i) for i in items])

    @app.route("/api/revision/analytics")
    def api_revision_analytics():
        """Retrieve aggregated spaced repetition metrics and retention proxies."""
        rev_engine = SpacedRevisionEngine(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        analytics = rev_engine.get_analytics()
        from dataclasses import asdict
        return jsonify(asdict(analytics))

    @app.route("/api/revision/schedule", methods=["POST"])
    def api_revision_schedule():
        """Schedule a problem into the spaced repetition queue."""
        req_data = request.get_json(silent=True) or {}
        problem_id = req_data.get("problem_id")
        if not problem_id or not re.match(r"^[a-zA-Z0-9_\-]+$", str(problem_id)):
            return jsonify({"error": "Invalid problem identifier"}), 400

        # Check problem existence
        all_problems = load_problems()
        p = next((prob for prob in all_problems if prob["id"] == problem_id), None)
        if not p:
            cp = store.get_custom_problem(problem_id, db_path=db_path)
            if cp:
                p = cp
            else:
                return jsonify({"error": f"Problem '{problem_id}' not found"}), 404

        rev_engine = SpacedRevisionEngine(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        item = rev_engine.schedule_problem(p)
        from dataclasses import asdict
        return jsonify({
            "message": f"Problem '{problem_id}' scheduled for revision",
            "item": asdict(item),
        }), 201

    @app.route("/api/revision/<problem_id>/outcome", methods=["POST"])
    def api_revision_outcome(problem_id: str):
        """Log a recall outcome for a problem (easy_recall, effort_recall, needed_hints, failed_to_solve)."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", problem_id):
            return jsonify({"error": "Invalid problem identifier"}), 400

        req_data = request.get_json(silent=True) or {}
        outcome_str = req_data.get("outcome")
        valid_outcomes = {o.value: o for o in RevisionOutcome}
        if outcome_str not in valid_outcomes:
            return jsonify({"error": f"Outcome must be one of {list(valid_outcomes.keys())}"}), 400

        rev_engine = SpacedRevisionEngine(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            updated = rev_engine.record_revision_outcome(problem_id, valid_outcomes[outcome_str])
            return jsonify({
                "message": f"Outcome recorded: {outcome_str}",
                "problem_id": updated.problem_id,
                "interval_days": updated.interval_days,
                "next_review_at": updated.next_review_at,
                "status": updated.status.value,
            })
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/revision/<problem_id>/pause", methods=["POST"])
    def api_revision_pause(problem_id: str):
        """Pause or resume a problem in the revision queue."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", problem_id):
            return jsonify({"error": "Invalid problem identifier"}), 400

        req_data = request.get_json(silent=True) or {}
        paused = bool(req_data.get("paused", True))

        rev_engine = SpacedRevisionEngine(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            updated = rev_engine.set_paused(problem_id, paused)
            return jsonify({
                "message": f"Problem '{problem_id}' is now {updated.status.value}",
                "problem_id": updated.problem_id,
                "status": updated.status.value,
            })
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    # =========================================================================
    # Goals & Milestones Management Endpoints (Milestone 6.3.13)
    # =========================================================================

    @app.route("/api/goals")
    def api_list_goals():
        """Retrieve all active/tracked learning goals."""
        status_filter = request.args.get("status")
        mgr = GoalsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        filter_status = None
        if status_filter:
            try:
                filter_status = GoalStatus(status_filter)
            except ValueError:
                pass
        goals = mgr.list_goals(status_filter=filter_status)
        from dataclasses import asdict
        return jsonify([asdict(g) for g in goals])

    @app.route("/api/goals/create", methods=["POST"])
    def api_create_goal():
        """Create a new learning goal with validated target metrics."""
        req_data = request.get_json(silent=True) or {}
        title = req_data.get("title", "").strip()
        goal_type_str = req_data.get("goal_type", "")
        target_value = req_data.get("target_value", 1)
        target_difficulty = req_data.get("target_difficulty")
        target_topic = req_data.get("target_topic")
        description = req_data.get("description", "")
        days_to_complete = req_data.get("days_to_complete")

        try:
            goal_type = GoalType(goal_type_str)
        except ValueError:
            return jsonify({"error": f"Invalid goal_type. Must be one of {[t.value for t in GoalType]}"}), 400

        mgr = GoalsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            goal = mgr.create_goal(
                title=title,
                goal_type=goal_type,
                target_value=int(target_value),
                target_difficulty=target_difficulty,
                target_topic=target_topic,
                description=description,
                days_to_complete=int(days_to_complete) if days_to_complete else None,
            )
            from dataclasses import asdict
            return jsonify({
                "message": f"Goal '{goal.title}' created successfully",
                "goal": asdict(goal),
            }), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/goals/<goal_id>")
    def api_get_goal(goal_id: str):
        """Retrieve a specific learning goal by ID."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", goal_id):
            return jsonify({"error": "Invalid goal_id format"}), 400

        mgr = GoalsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        goal = mgr.get_goal(goal_id)
        if not goal:
            return jsonify({"error": f"Goal '{goal_id}' not found"}), 404

        from dataclasses import asdict
        return jsonify(asdict(goal))

    @app.route("/api/goals/<goal_id>/update", methods=["POST"])
    def api_update_goal(goal_id: str):
        """Update goal parameters (title, description, target_value, deadline_at)."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", goal_id):
            return jsonify({"error": "Invalid goal_id format"}), 400

        req_data = request.get_json(silent=True) or {}
        mgr = GoalsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            updated = mgr.update_goal(
                goal_id=goal_id,
                title=req_data.get("title"),
                description=req_data.get("description"),
                target_value=req_data.get("target_value"),
                deadline_at=req_data.get("deadline_at"),
            )
            from dataclasses import asdict
            return jsonify({
                "message": f"Goal '{goal_id}' updated successfully",
                "goal": asdict(updated),
            })
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/goals/<goal_id>/status", methods=["POST"])
    def api_set_goal_status(goal_id: str):
        """Set goal status to active, paused, or archived."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", goal_id):
            return jsonify({"error": "Invalid goal_id format"}), 400

        req_data = request.get_json(silent=True) or {}
        status_str = req_data.get("status", "")
        try:
            status = GoalStatus(status_str)
        except ValueError:
            return jsonify({"error": f"Invalid status. Must be one of {[s.value for s in GoalStatus]}"}), 400

        mgr = GoalsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            updated = mgr.set_goal_status(goal_id, status)
            from dataclasses import asdict
            return jsonify({
                "message": f"Goal '{goal_id}' status set to {status.value}",
                "goal": asdict(updated),
            })
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/goals/<goal_id>/complete", methods=["POST"])
    def api_complete_goal(goal_id: str):
        """Explicitly complete a goal."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", goal_id):
            return jsonify({"error": "Invalid goal_id format"}), 400

        mgr = GoalsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            updated = mgr.complete_goal(goal_id)
            from dataclasses import asdict
            return jsonify({
                "message": f"Goal '{goal_id}' marked as completed",
                "goal": asdict(updated),
            })
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/milestones")
    def api_list_milestones():
        """Retrieve all milestone badges and their unlock status."""
        mgr = GoalsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        milestones = mgr.check_and_unlock_milestones()
        from dataclasses import asdict
        return jsonify([asdict(m) for m in milestones])

    @app.route("/api/goals/analytics")
    def api_goals_analytics():
        """Retrieve aggregated goals analytics report."""
        mgr = GoalsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        analytics = mgr.get_goals_analytics()
        from dataclasses import asdict
        d = asdict(analytics)
        d["total_goals"] = analytics.total_goals
        d["active_goals"] = analytics.active_goals_count
        d["completed_goals"] = analytics.completed_goals_count
        d["completion_rate_pct"] = analytics.completion_rate_pct
        d["milestones_unlocked"] = analytics.milestones_unlocked
        d["total_milestones"] = analytics.total_milestones
        return jsonify(d)

    # =========================================================================
    # DSA Skill Roadmap & Mastery Map Endpoints (Milestone 6.3.14)
    # =========================================================================

    @app.route("/api/roadmap")
    @app.route("/api/roadmap/analytics")
    def api_roadmap_overview():
        """Retrieve complete DSA skill roadmap overview and stage analytics."""
        engine = DsaRoadmapEngine(
            progress_db_path=db_path,
            tracking_db_path=tracker_path,
            language="python",
        )
        overview = engine.get_roadmap_overview()
        from dataclasses import asdict
        return jsonify(asdict(overview))

    @app.route("/api/roadmap/stages")
    def api_roadmap_stages():
        """Retrieve stage summaries and topic lists."""
        engine = DsaRoadmapEngine(
            progress_db_path=db_path,
            tracking_db_path=tracker_path,
            language="python",
        )
        stages = engine.get_stage_summaries()
        from dataclasses import asdict
        return jsonify([asdict(s) for s in stages])

    @app.route("/api/roadmap/topics")
    def api_roadmap_topics():
        """Retrieve all roadmap topics with computed mastery."""
        engine = DsaRoadmapEngine(
            progress_db_path=db_path,
            tracking_db_path=tracker_path,
            language="python",
        )
        summaries = engine.get_stage_summaries()
        from dataclasses import asdict
        all_topics = []
        for s in summaries:
            for t in s.topics:
                all_topics.append(asdict(t))
        return jsonify(all_topics)

    @app.route("/api/roadmap/topics/<topic_id>")
    def api_roadmap_topic_detail(topic_id: str):
        """Retrieve mastery detail for a specific roadmap topic."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", topic_id):
            return jsonify({"error": "Invalid topic identifier format"}), 400

        engine = DsaRoadmapEngine(
            progress_db_path=db_path,
            tracking_db_path=tracker_path,
            language="python",
        )
        detail = engine.get_topic_detail(topic_id)
        if not detail:
            return jsonify({"error": f"Topic '{topic_id}' not found in roadmap"}), 404

        from dataclasses import asdict
        return jsonify(asdict(detail))

    @app.route("/api/roadmap/recommendations")
    def api_roadmap_recommendations():
        """Retrieve personalized next topic and practice recommendations."""
        try:
            limit = int(request.args.get("limit", 5))
        except ValueError:
            limit = 5

        engine = DsaRoadmapEngine(
            progress_db_path=db_path,
            tracking_db_path=tracker_path,
            language="python",
        )
        recs = engine.generate_recommendations(limit=limit)
        from dataclasses import asdict
        return jsonify([asdict(r) for r in recs])

    # =========================================================================
    # Daily Learning Mission & Focus Mode Endpoints (Milestone 6.3.15)
    # =========================================================================

    @app.route("/api/daily-mission")
    @app.route("/api/daily-mission/current")
    def api_get_daily_mission():
        """Retrieve the current daily mission and active focus task."""
        mgr = DailyMissionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
            language="python",
        )
        mission = mgr.get_today_mission()
        if not mission:
            # Auto-generate if none exists
            mission = mgr.generate_mission()
        from dataclasses import asdict
        d = asdict(mission)
        d["completion_percentage"] = mission.completion_percentage
        d["current_task"] = asdict(mission.current_task) if mission.current_task else None
        return jsonify(d)

    @app.route("/api/daily-mission/generate", methods=["POST"])
    def api_generate_daily_mission():
        """Generate a personalized daily mission."""
        req_data = request.get_json(silent=True) or {}
        force_new = bool(req_data.get("force_new", False))
        duration = int(req_data.get("target_duration_min", 45))
        max_tasks = int(req_data.get("max_tasks", 3))

        mgr = DailyMissionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
            language="python",
        )
        mission = mgr.generate_mission(
            target_duration_min=duration,
            max_tasks=max_tasks,
            force_new=force_new,
        )
        from dataclasses import asdict
        d = asdict(mission)
        d["completion_percentage"] = mission.completion_percentage
        d["current_task"] = asdict(mission.current_task) if mission.current_task else None
        return jsonify(d), 201

    @app.route("/api/daily-mission/start", methods=["POST"])
    def api_start_daily_mission():
        """Start the daily mission and its first task."""
        req_data = request.get_json(silent=True) or {}
        mission_id = req_data.get("mission_id")

        mgr = DailyMissionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
            language="python",
        )
        try:
            mission = mgr.start_mission(mission_id)
            from dataclasses import asdict
            d = asdict(mission)
            d["completion_percentage"] = mission.completion_percentage
            d["current_task"] = asdict(mission.current_task) if mission.current_task else None
            return jsonify(d)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-mission/task/<task_id>/start", methods=["POST"])
    def api_start_daily_mission_task(task_id: str):
        """Set task to in_progress."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", task_id):
            return jsonify({"error": "Invalid task identifier format"}), 400

        mgr = DailyMissionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
            language="python",
        )
        try:
            task = mgr.start_task(task_id)
            from dataclasses import asdict
            return jsonify(asdict(task))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-mission/task/<task_id>/complete", methods=["POST"])
    def api_complete_daily_mission_task(task_id: str):
        """Mark task completed and advance focus mode."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", task_id):
            return jsonify({"error": "Invalid task identifier format"}), 400

        mgr = DailyMissionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
            language="python",
        )
        try:
            task, mission = mgr.complete_task(task_id)
            from dataclasses import asdict
            d_mission = asdict(mission)
            d_mission["completion_percentage"] = mission.completion_percentage
            d_mission["current_task"] = asdict(mission.current_task) if mission.current_task else None
            return jsonify({
                "task": asdict(task),
                "mission": d_mission,
            })
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-mission/task/<task_id>/skip", methods=["POST"])
    def api_skip_daily_mission_task(task_id: str):
        """Skip task with reason and advance focus mode."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", task_id):
            return jsonify({"error": "Invalid task identifier format"}), 400

        req_data = request.get_json(silent=True) or {}
        reason = req_data.get("reason", "Skipped by user")

        mgr = DailyMissionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
            language="python",
        )
        try:
            task, mission = mgr.skip_task(task_id, reason=reason)
            from dataclasses import asdict
            d_mission = asdict(mission)
            d_mission["completion_percentage"] = mission.completion_percentage
            d_mission["current_task"] = asdict(mission.current_task) if mission.current_task else None
            return jsonify({
                "task": asdict(task),
                "mission": d_mission,
            })
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-mission/pause", methods=["POST"])
    def api_pause_daily_mission():
        """Pause currently running mission."""
        mgr = DailyMissionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
            language="python",
        )
        try:
            mission = mgr.pause_mission()
            from dataclasses import asdict
            d = asdict(mission)
            d["completion_percentage"] = mission.completion_percentage
            d["current_task"] = asdict(mission.current_task) if mission.current_task else None
            return jsonify(d)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-mission/resume", methods=["POST"])
    def api_resume_daily_mission():
        """Resume paused mission."""
        mgr = DailyMissionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
            language="python",
        )
        try:
            mission = mgr.resume_mission()
            from dataclasses import asdict
            d = asdict(mission)
            d["completion_percentage"] = mission.completion_percentage
            d["current_task"] = asdict(mission.current_task) if mission.current_task else None
            return jsonify(d)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-mission/cancel", methods=["POST"])
    def api_cancel_daily_mission():
        """Cancel daily mission."""
        mgr = DailyMissionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
            language="python",
        )
        try:
            mission = mgr.cancel_mission()
            from dataclasses import asdict
            d = asdict(mission)
            d["completion_percentage"] = mission.completion_percentage
            d["current_task"] = asdict(mission.current_task) if mission.current_task else None
            return jsonify(d)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-mission/history")
    def api_daily_mission_history():
        """Fetch mission history."""
        try:
            limit = int(request.args.get("limit", 10))
        except ValueError:
            limit = 10

        mgr = DailyMissionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
            language="python",
        )
        history = mgr.list_mission_history(limit=limit)
        from dataclasses import asdict
        return jsonify([asdict(m) for m in history])

    @app.route("/api/daily-mission/analytics")
    def api_daily_mission_analytics():
        """Fetch daily mission aggregated analytics."""
        mgr = DailyMissionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
            language="python",
        )
        analytics = mgr.get_analytics()
        from dataclasses import asdict
        return jsonify(asdict(analytics))

    # =========================================================================
    # Mission-Integrated Coding Workspace Endpoints (Milestone 6.3.16)
    # =========================================================================

    @app.route("/api/workspace")
    def api_workspace_status():
        """Retrieve workspace capabilities and active defaults."""
        return jsonify({
            "status": "ready",
            "supported_languages": ["python", "c", "cpp", "java"],
            "default_language": "python",
        })

    @app.route("/api/workspace/problem/<problem_id>")
    def api_workspace_problem_context(problem_id: str):
        """Fetch problem context, metadata, examples, and active mission links."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", problem_id):
            return jsonify({"error": "Invalid problem identifier format"}), 400

        mission_id = request.args.get("mission_id")
        task_id = request.args.get("task_id")

        ws_mgr = WorkspaceManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        ctx = ws_mgr.get_problem_context(
            problem_id=problem_id,
            mission_id=mission_id,
            task_id=task_id,
        )
        if not ctx:
            return jsonify({"error": f"Problem '{problem_id}' not found"}), 404

        from dataclasses import asdict
        return jsonify(asdict(ctx))

    @app.route("/api/workspace/draft/<problem_id>")
    def api_workspace_get_draft(problem_id: str):
        """Fetch saved draft code for a problem in specified language."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", problem_id):
            return jsonify({"error": "Invalid problem identifier format"}), 400

        language = request.args.get("language", "python")
        ws_mgr = WorkspaceManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        draft = ws_mgr.get_draft(problem_id, language=language)
        if not draft:
            return jsonify({"problem_id": problem_id, "language": language, "code": ""})

        from dataclasses import asdict
        return jsonify(asdict(draft))

    @app.route("/api/workspace/draft/save", methods=["POST"])
    def api_workspace_save_draft():
        """Save solution draft locally."""
        req_data = request.get_json(silent=True) or {}
        problem_id = req_data.get("problem_id", "").strip()
        language = req_data.get("language", "python")
        code = req_data.get("code", "")

        if not problem_id or not re.match(r"^[a-zA-Z0-9_\-]+$", problem_id):
            return jsonify({"error": "Invalid problem identifier"}), 400

        ws_mgr = WorkspaceManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        draft = ws_mgr.save_draft(problem_id=problem_id, language=language, code=code)
        from dataclasses import asdict
        return jsonify(asdict(draft))

    @app.route("/api/workspace/run", methods=["POST"])
    def api_workspace_run_code():
        """Run solution code against local test cases using UnifiedJudge."""
        req_data = request.get_json(silent=True) or {}
        problem_id = req_data.get("problem_id", "").strip()
        language = req_data.get("language", "python")
        code = req_data.get("code", "")
        timeout = int(req_data.get("timeout", 10))

        if not problem_id or not re.match(r"^[a-zA-Z0-9_\-]+$", problem_id):
            return jsonify({"error": "Invalid problem identifier"}), 400

        ws_mgr = WorkspaceManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            result = ws_mgr.run_code(
                problem_id=problem_id,
                code=code,
                language=language,
                timeout=timeout,
            )

            # Record submission in active practice session if matching problem or session
            try:
                ps_mgr = PracticeSessionManager(
                    tracking_db_path=tracker_path,
                    progress_db_path=db_path,
                )
                active_sess = ps_mgr.get_active_session()
                if active_sess and (not active_sess.problem_id or active_sess.problem_id == problem_id):
                    err_msg = result.compiler_error or result.execution_error
                    ps_mgr.record_submission(
                        session_id=active_sess.session_id,
                        status=result.status,
                        passed_count=result.passed_count,
                        total_tests=result.total_tests,
                        runtime_ms=result.runtime_ms,
                        error=err_msg,
                    )
            except Exception:
                pass

            from dataclasses import asdict
            return jsonify(asdict(result))
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": f"Execution failed: {str(e)}"}), 500

    @app.route("/api/workspace/history")
    def api_workspace_history():
        """Fetch recent run results."""
        problem_id = request.args.get("problem_id")
        try:
            limit = int(request.args.get("limit", 10))
        except ValueError:
            limit = 10

        ws_mgr = WorkspaceManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        runs = ws_mgr.list_run_history(problem_id=problem_id, limit=limit)
        from dataclasses import asdict
        return jsonify([asdict(r) for r in runs])

    @app.route("/api/workspace/result/<run_id>")
    def api_workspace_run_result(run_id: str):
        """Fetch specific run result by run_id."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", run_id):
            return jsonify({"error": "Invalid run_id format"}), 400

        ws_mgr = WorkspaceManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        run_res = ws_mgr.get_run_result(run_id)
        if not run_res:
            return jsonify({"error": f"Run result '{run_id}' not found"}), 404

        from dataclasses import asdict
        return jsonify(asdict(run_res))

    # =========================================================================
    # Solution Quality Analyzer & Complexity Review Endpoints (Milestone 6.3.17)
    # =========================================================================

    @app.route("/api/workspace/review", methods=["POST"])
    def api_workspace_review_solution():
        """Perform static analysis, complexity review, and checklist synthesis."""
        req_data = request.get_json(silent=True) or {}
        problem_id = req_data.get("problem_id", "").strip()
        code = req_data.get("code", "")
        language = req_data.get("language", "python")
        linked_run_id = req_data.get("linked_run_id")
        learner_time = req_data.get("learner_time")
        learner_space = req_data.get("learner_space")
        checklist_overrides = req_data.get("checklist")

        if not problem_id or not re.match(r"^[a-zA-Z0-9_\-]+$", problem_id):
            return jsonify({"error": "Invalid problem identifier"}), 400

        engine = SolutionReviewEngine(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        report = engine.review_solution(
            problem_id=problem_id,
            code=code,
            language=language,
            linked_run_id=linked_run_id,
            learner_time=learner_time,
            learner_space=learner_space,
            checklist_overrides=checklist_overrides,
        )
        from dataclasses import asdict
        return jsonify(asdict(report))

    @app.route("/api/workspace/review/<review_id>")
    def api_workspace_get_review(review_id: str):
        """Fetch previously stored solution review by review_id."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", review_id):
            return jsonify({"error": "Invalid review_id format"}), 400

        engine = SolutionReviewEngine(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        review = engine.get_review(review_id)
        if not review:
            return jsonify({"error": f"Review '{review_id}' not found"}), 404

        from dataclasses import asdict
        return jsonify(asdict(review))

    @app.route("/api/workspace/reviews/history")
    def api_workspace_review_history():
        """Fetch historical reviews."""
        problem_id = request.args.get("problem_id")
        try:
            limit = int(request.args.get("limit", 10))
        except ValueError:
            limit = 10

        engine = SolutionReviewEngine(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        history = engine.list_review_history(problem_id=problem_id, limit=limit)
        from dataclasses import asdict
        return jsonify([asdict(h) for h in history])

    @app.route("/api/workspace/review/checklist", methods=["POST"])
    def api_workspace_review_checklist():
        """Update or validate checklist items for a problem."""
        req_data = request.get_json(silent=True) or {}
        problem_id = req_data.get("problem_id", "").strip()
        code = req_data.get("code", "")
        language = req_data.get("language", "python")
        checklist_overrides = req_data.get("checklist") or {}

        if not problem_id or not re.match(r"^[a-zA-Z0-9_\-]+$", problem_id):
            return jsonify({"error": "Invalid problem identifier"}), 400

        engine = SolutionReviewEngine(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        report = engine.review_solution(
            problem_id=problem_id,
            code=code,
            language=language,
            checklist_overrides=checklist_overrides,
        )
        from dataclasses import asdict
        return jsonify({
            "review_id": report.review_id,
            "checklist": asdict(report.checklist),
            "completed_count": report.checklist.completed_count,
            "total_count": report.checklist.total_count,
        })

    @app.route("/api/workspace/review/complexity", methods=["POST"])
    def api_workspace_review_complexity():
        """Analyze complexity and compare learner estimates."""
        req_data = request.get_json(silent=True) or {}
        code = req_data.get("code", "")
        language = req_data.get("language", "python")
        learner_time = req_data.get("learner_time")
        learner_space = req_data.get("learner_space")

        engine = SolutionReviewEngine(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        cr = engine.review_complexity(
            code=code,
            language=language,
            learner_time=learner_time,
            learner_space=learner_space,
        )
        from dataclasses import asdict
        return jsonify(asdict(cr))

    # =========================================================================
    # Personal Learning Portfolio & Progress Report Generator Endpoints (Milestone 6.3.18)
    # =========================================================================

    @app.route("/api/portfolio")
    def api_portfolio_root():
        """Retrieve default portfolio configuration and aggregated summary."""
        mgr = PortfolioManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        report = mgr.aggregate_evidence()
        from dataclasses import asdict
        return jsonify({
            "status": "ready",
            "report": asdict(report),
        })

    @app.route("/api/portfolio/preview")
    def api_portfolio_preview():
        """Generate dynamic portfolio preview with applied style and date filters."""
        style = request.args.get("report_style", "developer_portfolio")
        preset = request.args.get("date_preset", "all_time")
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")

        mgr = PortfolioManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        saved_cfg = mgr.get_saved_config()
        cfg = PortfolioConfig(
            learner_name=saved_cfg.learner_name,
            portfolio_title=saved_cfg.portfolio_title,
            introduction=saved_cfg.introduction,
            primary_language=saved_cfg.primary_language,
            learning_objectives=saved_cfg.learning_objectives,
            skills_to_highlight=saved_cfg.skills_to_highlight,
            report_style=style,
            date_range_preset=preset,
            start_date=start_date,
            end_date=end_date,
        )
        report = mgr.aggregate_evidence(config=cfg)
        from dataclasses import asdict
        return jsonify({
            "config": asdict(cfg),
            "report": asdict(report),
        })

    @app.route("/api/portfolio/config", methods=["POST"])
    def api_portfolio_save_config():
        """Update and persist learner profile and portfolio generation settings."""
        req_data = request.get_json(silent=True) or {}
        mgr = PortfolioManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        existing = mgr.get_saved_config()
        cfg = PortfolioConfig(
            learner_name=req_data.get("learner_name", existing.learner_name),
            portfolio_title=req_data.get("portfolio_title", existing.portfolio_title),
            introduction=req_data.get("introduction", existing.introduction),
            primary_language=req_data.get("primary_language", existing.primary_language),
            learning_objectives=req_data.get("learning_objectives", existing.learning_objectives),
            skills_to_highlight=req_data.get("skills_to_highlight", existing.skills_to_highlight),
            report_style=req_data.get("report_style", existing.report_style),
            date_range_preset=req_data.get("date_range_preset", existing.date_range_preset),
            start_date=req_data.get("start_date", existing.start_date),
            end_date=req_data.get("end_date", existing.end_date),
        )
        saved = mgr.save_config(cfg)
        from dataclasses import asdict
        return jsonify({
            "message": "Portfolio configuration saved successfully",
            "config": asdict(saved),
        })

    @app.route("/api/portfolio/generate", methods=["POST"])
    def api_portfolio_generate():
        """Generate and export a report in Markdown, JSON, or HTML."""
        req_data = request.get_json(silent=True) or {}
        format_type = req_data.get("format", "markdown")
        style = req_data.get("report_style", "developer_portfolio")
        preset = req_data.get("date_range_preset", "all_time")
        start_date = req_data.get("start_date")
        end_date = req_data.get("end_date")
        learner_name = req_data.get("learner_name")
        portfolio_title = req_data.get("portfolio_title")
        custom_filename = req_data.get("filename")

        mgr = PortfolioManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        saved_cfg = mgr.get_saved_config()
        cfg = PortfolioConfig(
            learner_name=learner_name or saved_cfg.learner_name,
            portfolio_title=portfolio_title or saved_cfg.portfolio_title,
            introduction=saved_cfg.introduction,
            primary_language=saved_cfg.primary_language,
            learning_objectives=saved_cfg.learning_objectives,
            skills_to_highlight=saved_cfg.skills_to_highlight,
            report_style=style,
            date_range_preset=preset,
            start_date=start_date,
            end_date=end_date,
        )
        try:
            report = mgr.aggregate_evidence(config=cfg)
            export_record = mgr.export_portfolio(
                report=report,
                format_type=format_type,
                custom_filename=custom_filename,
            )
            export_record["download_url"] = f"/api/portfolio/export/{export_record['export_id']}"
            return jsonify(export_record), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/portfolio/history")
    def api_portfolio_history():
        """Fetch previously generated portfolio exports."""
        try:
            limit = int(request.args.get("limit", 10))
        except ValueError:
            limit = 10

        mgr = PortfolioManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        history = mgr.list_exports(limit=limit)
        return jsonify(history)

    @app.route("/api/portfolio/export/<export_id>")
    def api_portfolio_download_export(export_id: str):
        """Safely download an exported report file."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", export_id):
            return jsonify({"error": "Invalid export_id format"}), 400

        mgr = PortfolioManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        result = mgr.get_export_file(export_id)
        if not result:
            return jsonify({"error": f"Export '{export_id}' not found"}), 404

        filename, filepath_str, fmt = result
        filepath = Path(filepath_str).resolve()
        exports_dir = mgr.exports_dir.resolve()

        # Path traversal guard
        if not str(filepath).startswith(str(exports_dir)):
            return jsonify({"error": "Unauthorized file access"}), 403

        if not filepath.is_file():
            return jsonify({"error": "File not found on disk"}), 404

        mimetype_map = {
            "markdown": "text/markdown; charset=utf-8",
            "md": "text/markdown; charset=utf-8",
            "json": "application/json; charset=utf-8",
            "html": "text/html; charset=utf-8",
        }
        mime = mimetype_map.get(fmt, "text/plain; charset=utf-8")
        return send_file(
            filepath,
            mimetype=mime,
            as_attachment=True,
            download_name=filename,
        )

    # =========================================================================
    # Mock Interview & Technical Assessment Endpoints (Milestone 6.3.19)
    # =========================================================================

    @app.route("/api/interview")
    def api_interview_active():
        """Retrieve active mock interview session or default state."""
        mgr = InterviewManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        active = mgr.get_active_interview()
        if not active:
            return jsonify({
                "status": "none",
                "message": "No active mock interview session.",
                "available_tracks": [t.value for t in InterviewTrack],
                "available_durations": [30, 45, 60],
            })
        from dataclasses import asdict
        return jsonify(asdict(active))

    @app.route("/api/interview/start", methods=["POST"])
    def api_interview_start():
        """Configure, select problems, and start a new timed mock interview session."""
        req_data = request.get_json(silent=True) or {}
        track = req_data.get("track", "intermediate")
        duration = int(req_data.get("duration_minutes", 45))
        language = req_data.get("language", "python")
        problem_count = int(req_data.get("problem_count", 2))
        title = req_data.get("title")

        mgr = InterviewManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = mgr.create_interview(
                track=track,
                duration_minutes=duration,
                language=language,
                problem_count=problem_count,
                title=title,
                auto_start=True,
            )
            from dataclasses import asdict
            return jsonify(asdict(session)), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/interview/<interview_id>")
    def api_interview_get(interview_id: str):
        """Retrieve interview state, remaining time, and problem overview."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", interview_id):
            return jsonify({"error": "Invalid interview_id format"}), 400

        mgr = InterviewManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        interview = mgr.get_interview(interview_id)
        if not interview:
            return jsonify({"error": f"Interview '{interview_id}' not found"}), 404

        from dataclasses import asdict
        return jsonify(asdict(interview))

    @app.route("/api/interview/<interview_id>/problem")
    def api_interview_get_problem(interview_id: str):
        """Retrieve problem context, metadata, and constraints for interview problem."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", interview_id):
            return jsonify({"error": "Invalid interview_id format"}), 400

        idx_str = request.args.get("index")
        idx = int(idx_str) if idx_str is not None and idx_str.isdigit() else None

        mgr = InterviewManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            ctx = mgr.get_current_problem(interview_id, problem_index=idx)
            from dataclasses import asdict
            return jsonify(asdict(ctx))
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/interview/<interview_id>/draft", methods=["POST"])
    def api_interview_save_draft(interview_id: str):
        """Save draft code for an interview problem."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", interview_id):
            return jsonify({"error": "Invalid interview_id format"}), 400

        req_data = request.get_json(silent=True) or {}
        code = req_data.get("code", "")
        problem_id = req_data.get("problem_id")

        mgr = InterviewManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            draft = mgr.save_draft(interview_id=interview_id, code=code, problem_id=problem_id)
            return jsonify(draft)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/interview/<interview_id>/submit", methods=["POST"])
    def api_interview_submit(interview_id: str):
        """Run candidate solution against local judge and record submission."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", interview_id):
            return jsonify({"error": "Invalid interview_id format"}), 400

        req_data = request.get_json(silent=True) or {}
        code = req_data.get("code")
        problem_id = req_data.get("problem_id")
        timeout = int(req_data.get("timeout", 10))

        mgr = InterviewManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            sub = mgr.submit_solution(
                interview_id=interview_id,
                code=code,
                problem_id=problem_id,
                timeout=timeout,
            )
            from dataclasses import asdict
            return jsonify(asdict(sub))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/interview/<interview_id>/advance", methods=["POST"])
    def api_interview_advance(interview_id: str):
        """Advance candidate to the next assigned problem."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", interview_id):
            return jsonify({"error": "Invalid interview_id format"}), 400

        mgr = InterviewManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = mgr.advance_problem(interview_id)
            from dataclasses import asdict
            return jsonify(asdict(session))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/interview/<interview_id>/finish", methods=["POST"])
    def api_interview_finish(interview_id: str):
        """Finish interview session, evaluate performance, and generate final report."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", interview_id):
            return jsonify({"error": "Invalid interview_id format"}), 400

        mgr = InterviewManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            report = mgr.finish_interview(interview_id)
            from dataclasses import asdict
            return jsonify(asdict(report))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/interview/<interview_id>/report")
    def api_interview_report(interview_id: str):
        """Retrieve evaluation report for an interview session."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", interview_id):
            return jsonify({"error": "Invalid interview_id format"}), 400

        mgr = InterviewManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        interview = mgr.get_interview(interview_id)
        if not interview:
            return jsonify({"error": f"Interview '{interview_id}' not found"}), 404

        if interview.assessment:
            from dataclasses import asdict
            return jsonify(asdict(interview.assessment))

        try:
            report = mgr.finish_interview(interview_id)
            from dataclasses import asdict
            return jsonify(asdict(report))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/interview/history")
    def api_interview_history():
        """Retrieve historical interview sessions."""
        try:
            limit = int(request.args.get("limit", 10))
        except ValueError:
            limit = 10

        mgr = InterviewManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        history = mgr.list_interview_history(limit=limit)
        return jsonify(history)

    @app.route("/api/interview/history/<interview_id>")
    def api_interview_history_detail(interview_id: str):
        """Retrieve detailed past interview session with submissions and evaluation."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", interview_id):
            return jsonify({"error": "Invalid interview_id format"}), 400

        mgr = InterviewManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        interview = mgr.get_interview(interview_id)
        if not interview:
            return jsonify({"error": f"Interview '{interview_id}' not found"}), 404

        from dataclasses import asdict
        return jsonify(asdict(interview))

    # -------------------------------------------------------------------------
    # Milestone 6.3.20: Interview Performance Trends & Benchmark Analytics APIs
    # -------------------------------------------------------------------------

    @app.route("/api/interview-analytics")
    def api_interview_analytics():
        """Retrieve full aggregated interview performance trends, benchmarks, and goals."""
        timeframe = request.args.get("timeframe", "all_time")
        custom_start = request.args.get("custom_start")
        custom_end = request.args.get("custom_end")

        mgr = InterviewAnalyticsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        overview = mgr.get_analytics_overview(
            date_preset=timeframe,
            start_date=custom_start,
            end_date=custom_end,
        )
        from dataclasses import asdict
        return jsonify(asdict(overview))

    @app.route("/api/interview-analytics/trends")
    def api_interview_analytics_trends():
        """Retrieve multi-category rubric performance trends."""
        timeframe = request.args.get("timeframe", "all_time")
        custom_start = request.args.get("custom_start")
        custom_end = request.args.get("custom_end")

        mgr = InterviewAnalyticsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        interviews = mgr.get_completed_interviews(
            date_preset=timeframe,
            start_date=custom_start,
            end_date=custom_end,
        )
        trends = mgr.calculate_score_trends(interviews)
        from dataclasses import asdict
        return jsonify({k: asdict(v) for k, v in trends.items()})

    @app.route("/api/interview-analytics/tracks")
    def api_interview_analytics_tracks():
        """Retrieve track benchmarks (Beginner, Intermediate, Advanced, Mixed)."""
        timeframe = request.args.get("timeframe", "all_time")
        custom_start = request.args.get("custom_start")
        custom_end = request.args.get("custom_end")

        mgr = InterviewAnalyticsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        interviews = mgr.get_completed_interviews(
            date_preset=timeframe,
            start_date=custom_start,
            end_date=custom_end,
        )
        tracks = mgr.analyze_tracks(interviews)
        from dataclasses import asdict
        return jsonify([asdict(t) for t in tracks])

    @app.route("/api/interview-analytics/languages")
    def api_interview_analytics_languages():
        """Retrieve programming language benchmarks (Python, C, C++, Java)."""
        timeframe = request.args.get("timeframe", "all_time")
        custom_start = request.args.get("custom_start")
        custom_end = request.args.get("custom_end")

        mgr = InterviewAnalyticsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        interviews = mgr.get_completed_interviews(
            date_preset=timeframe,
            start_date=custom_start,
            end_date=custom_end,
        )
        languages = mgr.analyze_languages(interviews)
        from dataclasses import asdict
        return jsonify([asdict(l) for l in languages])

    @app.route("/api/interview-analytics/insights")
    def api_interview_analytics_insights():
        """Retrieve evidence-based recurring weaknesses and performance patterns."""
        timeframe = request.args.get("timeframe", "all_time")
        custom_start = request.args.get("custom_start")
        custom_end = request.args.get("custom_end")

        mgr = InterviewAnalyticsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        interviews = mgr.get_completed_interviews(
            date_preset=timeframe,
            start_date=custom_start,
            end_date=custom_end,
        )
        trends = mgr.calculate_score_trends(interviews)
        insights = mgr.analyze_performance_patterns(interviews, trends)
        from dataclasses import asdict
        return jsonify([asdict(i) for i in insights])

    @app.route("/api/interview-analytics/topics")
    def api_interview_analytics_topics():
        """Retrieve topic-level interview metrics and roadmap recommendations."""
        timeframe = request.args.get("timeframe", "all_time")
        custom_start = request.args.get("custom_start")
        custom_end = request.args.get("custom_end")

        mgr = InterviewAnalyticsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        interviews = mgr.get_completed_interviews(
            date_preset=timeframe,
            start_date=custom_start,
            end_date=custom_end,
        )
        topic_metrics, rec_topics, rec_revisions = mgr.analyze_topics(interviews)
        from dataclasses import asdict
        return jsonify({
            "topics": [asdict(t) for t in topic_metrics],
            "recommended_roadmap_topics": rec_topics,
            "recommended_revisions": rec_revisions,
        })

    @app.route("/api/interview-analytics/goals", methods=["GET", "POST"])
    def api_interview_analytics_goals():
        """Retrieve list of interview practice goals or create a new goal."""
        mgr = InterviewAnalyticsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        from dataclasses import asdict

        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            goal_type = data.get("goal_type")
            target_value = data.get("target_value")
            period = data.get("period", "all_time")

            if not goal_type or target_value is None:
                return jsonify({"error": "Missing required fields: 'goal_type' and 'target_value'"}), 400

            try:
                target_val_float = float(target_value)
                new_goal = mgr.create_goal(
                    goal_type=goal_type,
                    target_value=target_val_float,
                    period=period,
                )
                return jsonify(asdict(new_goal)), 201
            except ValueError as e:
                return jsonify({"error": str(e)}), 400

        # GET request
        status_filter = request.args.get("status")
        goals = mgr.list_goals(status_filter=status_filter)
        return jsonify([asdict(g) for g in goals])

    @app.route("/api/interview-analytics/goals/<goal_id>", methods=["PUT"])
    def api_interview_analytics_goal_update(goal_id: str):
        """Update status or target value of an interview practice goal."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", goal_id):
            return jsonify({"error": "Invalid goal_id format"}), 400

        data = request.get_json(silent=True) or {}
        target_value = data.get("target_value")
        status = data.get("status")
        period = data.get("period")

        mgr = InterviewAnalyticsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            target_val_float = float(target_value) if target_value is not None else None
            updated = mgr.update_goal(
                goal_id=goal_id,
                target_value=target_val_float,
                status=status,
                period=period,
            )
            from dataclasses import asdict
            return jsonify(asdict(updated)), 200
        except ValueError as e:
            err_msg = str(e)
            status_code = 404 if "not found" in err_msg.lower() else 400
            return jsonify({"error": err_msg}), status_code

    @app.route("/api/interview-analytics/history")
    def api_interview_analytics_history():
        """Retrieve completed interview summaries included in analytics."""
        timeframe = request.args.get("timeframe", "all_time")
        custom_start = request.args.get("custom_start")
        custom_end = request.args.get("custom_end")
        try:
            limit = int(request.args.get("limit", 50))
        except ValueError:
            limit = 50

        mgr = InterviewAnalyticsManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        interviews = mgr.get_completed_interviews(
            date_preset=timeframe,
            start_date=custom_start,
            end_date=custom_end,
        )
        return jsonify(interviews[:limit])

    # -------------------------------------------------------------------------
    # Milestone 6.3.21: Adaptive Interview Preparation Planner APIs
    # -------------------------------------------------------------------------

    @app.route("/api/preparation-planner")
    def api_preparation_planner_active():
        """Retrieve active preparation plan and current settings."""
        planner = PreparationPlanner(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        settings = planner.get_settings()
        plan = planner.get_active_plan()
        from dataclasses import asdict
        return jsonify({
            "settings": asdict(settings),
            "plan": asdict(plan) if plan else None,
        })

    @app.route("/api/preparation-planner/settings", methods=["GET", "POST"])
    def api_preparation_planner_settings():
        """Get or save planner settings."""
        planner = PreparationPlanner(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        from dataclasses import asdict

        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            try:
                current_settings = planner.get_settings()
                daily_min = data.get("daily_minutes", current_settings.daily_minutes)
                horizon = data.get("horizon_days", current_settings.horizon_days)
                pref_days = data.get("preferred_days", current_settings.preferred_days)
                sessions = data.get("sessions_per_day", current_settings.sessions_per_day)
                track = data.get("target_track", current_settings.target_track)
                lang = data.get("language", current_settings.language)
                score = data.get("target_score", current_settings.target_score)
                intensity = data.get("intensity", current_settings.intensity)

                new_settings = PlannerSettings(
                    daily_minutes=int(daily_min),
                    horizon_days=int(horizon),
                    preferred_days=pref_days,
                    sessions_per_day=int(sessions),
                    target_track=str(track),
                    language=str(lang),
                    target_score=float(score),
                    intensity=str(intensity),
                )
                saved = planner.save_settings(new_settings)
                return jsonify(asdict(saved)), 200
            except ValueError as e:
                return jsonify({"error": str(e)}), 400

        # GET request
        settings = planner.get_settings()
        return jsonify(asdict(settings))

    @app.route("/api/preparation-planner/generate", methods=["POST"])
    def api_preparation_planner_generate():
        """Generate a new evidence-driven interview preparation plan."""
        data = request.get_json(silent=True) or {}
        planner = PreparationPlanner(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        from dataclasses import asdict

        try:
            settings = None
            if "settings" in data and isinstance(data["settings"], dict):
                s_dict = data["settings"]
                settings = PlannerSettings(
                    daily_minutes=int(s_dict.get("daily_minutes", 60)),
                    horizon_days=int(s_dict.get("horizon_days", 7)),
                    preferred_days=s_dict.get("preferred_days", list(ALL_WEEKDAYS)),
                    sessions_per_day=int(s_dict.get("sessions_per_day", 2)),
                    target_track=s_dict.get("target_track", "intermediate"),
                    language=s_dict.get("language", "python"),
                    target_score=float(s_dict.get("target_score", 80.0)),
                    intensity=s_dict.get("intensity", "moderate"),
                )

            start_date = data.get("start_date")
            title = data.get("title")

            plan = planner.generate_plan(
                settings=settings,
                start_date=start_date,
                title=title,
            )
            saved_plan = planner.save_plan(plan)
            return jsonify(asdict(saved_plan)), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/preparation-planner/plans")
    def api_preparation_planner_list_plans():
        """List summary of historical and active preparation plans."""
        planner = PreparationPlanner(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        plans = planner.list_plans()
        return jsonify(plans)

    @app.route("/api/preparation-planner/plan/<plan_id>")
    def api_preparation_planner_get_plan(plan_id: str):
        """Retrieve full details of a specific preparation plan."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", plan_id):
            return jsonify({"error": "Invalid plan_id format"}), 400

        planner = PreparationPlanner(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        plan = planner.get_plan(plan_id)
        if not plan:
            return jsonify({"error": f"Plan '{plan_id}' not found."}), 404

        from dataclasses import asdict
        return jsonify(asdict(plan))

    @app.route("/api/preparation-planner/plan/<plan_id>/preview")
    def api_preparation_planner_preview_plan(plan_id: str):
        """Preview structured daily and weekly schedule for a plan."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", plan_id):
            return jsonify({"error": "Invalid plan_id format"}), 400

        planner = PreparationPlanner(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        plan = planner.get_plan(plan_id)
        if not plan:
            return jsonify({"error": f"Plan '{plan_id}' not found."}), 404

        from dataclasses import asdict
        return jsonify(asdict(plan))

    @app.route("/api/preparation-planner/plan/<plan_id>/apply", methods=["POST"])
    def api_preparation_planner_apply_plan(plan_id: str):
        """Explicitly activate a generated preparation plan."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", plan_id):
            return jsonify({"error": "Invalid plan_id format"}), 400

        planner = PreparationPlanner(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            active_plan = planner.apply_plan(plan_id)
            from dataclasses import asdict
            return jsonify(asdict(active_plan)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/preparation-planner/plan/<plan_id>/progress")
    def api_preparation_planner_plan_progress(plan_id: str):
        """Retrieve progress metrics and streaks for a plan."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", plan_id):
            return jsonify({"error": "Invalid plan_id format"}), 400

        planner = PreparationPlanner(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        plan = planner.get_plan(plan_id)
        if not plan:
            return jsonify({"error": f"Plan '{plan_id}' not found."}), 404

        from dataclasses import asdict
        return jsonify(asdict(plan.progress))

    @app.route("/api/preparation-planner/task/<task_id>/complete", methods=["POST"])
    def api_preparation_planner_complete_task(task_id: str):
        """Mark a preparation task as completed with optional actual minutes."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", task_id):
            return jsonify({"error": "Invalid task_id format"}), 400

        data = request.get_json(silent=True) or {}
        actual_min = data.get("actual_minutes")

        planner = PreparationPlanner(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            act_int = int(actual_min) if actual_min is not None else None
            task = planner.complete_task(task_id, actual_minutes=act_int)
            from dataclasses import asdict
            return jsonify(asdict(task)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/preparation-planner/task/<task_id>/skip", methods=["POST"])
    def api_preparation_planner_skip_task(task_id: str):
        """Mark a preparation task as skipped."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", task_id):
            return jsonify({"error": "Invalid task_id format"}), 400

        data = request.get_json(silent=True) or {}
        reason = data.get("reason")

        planner = PreparationPlanner(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            task = planner.skip_task(task_id, reason=reason)
            from dataclasses import asdict
            return jsonify(asdict(task)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/preparation-planner/replan/preview", methods=["POST"])
    def api_preparation_planner_replan_preview():
        """Preview adaptive schedule adjustments without modifying active schedule."""
        data = request.get_json(silent=True) or {}
        plan_id = data.get("plan_id")
        if plan_id and not re.match(r"^[a-zA-Z0-9_\-]+$", plan_id):
            return jsonify({"error": "Invalid plan_id format"}), 400

        planner = PreparationPlanner(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            preview = planner.preview_replan(plan_id=plan_id)
            return jsonify(preview), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/preparation-planner/replan/apply", methods=["POST"])
    def api_preparation_planner_replan_apply():
        """Apply adaptive schedule adjustments to the active preparation plan."""
        data = request.get_json(silent=True) or {}
        plan_id = data.get("plan_id")
        if plan_id and not re.match(r"^[a-zA-Z0-9_\-]+$", plan_id):
            return jsonify({"error": "Invalid plan_id format"}), 400

        planner = PreparationPlanner(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            updated_plan = planner.apply_replan(plan_id=plan_id)
            from dataclasses import asdict
            return jsonify(asdict(updated_plan)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    # -------------------------------------------------------------------------
    # Milestone 6.3.22: Plan-to-Practice Execution Bridge APIs
    # -------------------------------------------------------------------------

    @app.route("/api/practice-session/active")
    def api_practice_session_active():
        """Retrieve current active or paused practice session."""
        mgr = PracticeSessionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        session = mgr.get_active_session()
        from dataclasses import asdict
        return jsonify(asdict(session) if session else None)

    @app.route("/api/practice-session/history")
    def api_practice_session_history():
        """Retrieve historical practice sessions."""
        try:
            limit = int(request.args.get("limit", 50))
        except ValueError:
            limit = 50

        mgr = PracticeSessionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        history = mgr.list_history(limit=limit)
        return jsonify(history)

    @app.route("/api/practice-session/<session_id>")
    def api_practice_session_detail(session_id: str):
        """Retrieve details of a specific practice session."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid session_id format"}), 400

        mgr = PracticeSessionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        session = mgr.get_session(session_id)
        if not session:
            return jsonify({"error": f"Practice session '{session_id}' not found."}), 404

        from dataclasses import asdict
        return jsonify(asdict(session))

    @app.route("/api/practice-session/start", methods=["POST"])
    def api_practice_session_start():
        """Start a new practice session from a planner task or standalone."""
        data = request.get_json(silent=True) or {}
        task_id = data.get("task_id")
        plan_id = data.get("plan_id")
        problem_id = data.get("problem_id")
        language = data.get("language", "python")
        force_switch = bool(data.get("force_switch", False))

        if task_id and not re.match(r"^[a-zA-Z0-9_\-]+$", task_id):
            return jsonify({"error": "Invalid task_id format"}), 400
        if plan_id and not re.match(r"^[a-zA-Z0-9_\-]+$", plan_id):
            return jsonify({"error": "Invalid plan_id format"}), 400
        if problem_id and not re.match(r"^[a-zA-Z0-9_\-]+$", problem_id):
            return jsonify({"error": "Invalid problem_id format"}), 400

        mgr = PracticeSessionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = mgr.start_session(
                task_id=task_id,
                plan_id=plan_id,
                problem_id=problem_id,
                language=language,
                force_switch=force_switch,
            )
            from dataclasses import asdict
            return jsonify(asdict(session)), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/practice-session/<session_id>/pause", methods=["POST"])
    def api_practice_session_pause(session_id: str):
        """Pause active practice session and freeze elapsed time."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid session_id format"}), 400

        mgr = PracticeSessionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = mgr.pause_session(session_id)
            from dataclasses import asdict
            return jsonify(asdict(session)), 200
        except ValueError as e:
            err_msg = str(e)
            code = 404 if "not found" in err_msg.lower() else 400
            return jsonify({"error": err_msg}), code

    @app.route("/api/practice-session/<session_id>/resume", methods=["POST"])
    def api_practice_session_resume(session_id: str):
        """Resume paused practice session."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid session_id format"}), 400

        mgr = PracticeSessionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = mgr.resume_session(session_id)
            from dataclasses import asdict
            return jsonify(asdict(session)), 200
        except ValueError as e:
            err_msg = str(e)
            code = 404 if "not found" in err_msg.lower() else 400
            return jsonify({"error": err_msg}), code

    @app.route("/api/practice-session/<session_id>/end", methods=["POST"])
    def api_practice_session_end(session_id: str):
        """End a session as completed or abandoned."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid session_id format"}), 400

        data = request.get_json(silent=True) or {}
        status = data.get("status", PracticeSessionStatus.COMPLETED.value)

        mgr = PracticeSessionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = mgr.end_session(session_id, status=status)
            from dataclasses import asdict
            return jsonify(asdict(session)), 200
        except ValueError as e:
            err_msg = str(e)
            code = 404 if "not found" in err_msg.lower() else 400
            return jsonify({"error": err_msg}), code

    @app.route("/api/practice-session/<session_id>/notes", methods=["POST"])
    def api_practice_session_notes(session_id: str):
        """Save learner reflection and complexity notes."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid session_id format"}), 400

        notes_data = request.get_json(silent=True) or {}

        mgr = PracticeSessionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            notes = mgr.save_notes(session_id, notes=notes_data)
            from dataclasses import asdict
            return jsonify(asdict(notes)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/practice-session/<session_id>/summary")
    def api_practice_session_summary(session_id: str):
        """Retrieve high-level evidence summary of a practice session."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid session_id format"}), 400

        mgr = PracticeSessionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            summary = mgr.get_session_summary(session_id)
            from dataclasses import asdict
            return jsonify(asdict(summary)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/practice-session/<session_id>/confirm-task", methods=["POST"])
    def api_practice_session_confirm_task(session_id: str):
        """Explicitly confirm task completion and bridge evidence to preparation planner."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid session_id format"}), 400

        notes = request.get_json(silent=True)

        mgr = PracticeSessionManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = mgr.confirm_task_completion(session_id, notes=notes)
            from dataclasses import asdict
            return jsonify(asdict(session)), 200
        except ValueError as e:
            err_msg = str(e)
            code = 404 if "not found" in err_msg.lower() else 400
            return jsonify({"error": err_msg}), code

    # =========================================================================
    # Milestone 6.3.23: Personal Coding Behavior Intelligence REST Endpoints
    # =========================================================================

    @app.route("/api/coding-behavior")
    def api_coding_behavior_overview():
        """Retrieve overview summary of personal coding behavior intelligence."""
        analyzer = CodingBehaviorAnalyzer(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        return jsonify(analyzer.get_overview())

    @app.route("/api/coding-behavior/profile")
    def api_coding_behavior_profile():
        """Retrieve latest personal coding behavior profile."""
        analyzer = CodingBehaviorAnalyzer(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        prof = analyzer.get_latest_profile()
        from dataclasses import asdict
        if not prof:
            report = analyzer.analyze(save=False)
            return jsonify(asdict(report.profile))
        return jsonify(asdict(prof))

    @app.route("/api/coding-behavior/insights")
    def api_coding_behavior_insights():
        """Retrieve list of behavioral insights with optional category/severity filters."""
        category = request.args.get("category")
        severity = request.args.get("severity")
        try:
            limit = int(request.args.get("limit", 20))
        except ValueError:
            limit = 20

        if category and not re.match(r"^[a-zA-Z0-9_\-]+$", category):
            return jsonify({"error": "Invalid category format"}), 400
        if severity and not re.match(r"^[a-zA-Z0-9_\-]+$", severity):
            return jsonify({"error": "Invalid severity format"}), 400

        analyzer = CodingBehaviorAnalyzer(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        insights = analyzer.get_insights(category=category, severity=severity, limit=limit)
        from dataclasses import asdict
        return jsonify([asdict(ins) for ins in insights])

    @app.route("/api/coding-behavior/history")
    def api_coding_behavior_history():
        """Retrieve list of historical behavioral analysis reports."""
        try:
            limit = int(request.args.get("limit", 10))
        except ValueError:
            limit = 10

        analyzer = CodingBehaviorAnalyzer(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        return jsonify(analyzer.list_reports(limit=limit))

    @app.route("/api/coding-behavior/analyze", methods=["POST"])
    def api_coding_behavior_analyze():
        """Run an on-demand behavioral intelligence analysis."""
        analyzer = CodingBehaviorAnalyzer(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        report = analyzer.analyze(save=True)
        from dataclasses import asdict
        return jsonify(asdict(report)), 201

    @app.route("/api/coding-behavior/report/<report_id>")
    def api_coding_behavior_report(report_id: str):
        """Retrieve a specific behavioral analysis report by report ID."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", report_id):
            return jsonify({"error": "Invalid report_id format"}), 400

        analyzer = CodingBehaviorAnalyzer(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        report = analyzer.get_report(report_id)
        if not report:
            return jsonify({"error": f"Behavior report '{report_id}' not found."}), 404

        from dataclasses import asdict
        return jsonify(asdict(report))

    # =========================================================================
    # Milestone 6.3.24: Personal Skill Gap & Focus Prioritization REST Endpoints
    # =========================================================================

    @app.route("/api/skill-gaps")
    def api_skill_gaps_overview():
        """Retrieve overview summary of personal skill gaps and focus priorities."""
        analyzer = SkillGapAnalyzer(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        return jsonify(analyzer.get_overview())

    @app.route("/api/skill-gaps/report")
    def api_skill_gaps_report_latest():
        """Retrieve the latest skill gap report."""
        analyzer = SkillGapAnalyzer(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        report = analyzer.get_latest_report()
        from dataclasses import asdict
        if not report:
            report = analyzer.analyze(save=False)
        return jsonify(asdict(report))

    @app.route("/api/skill-gaps/queue")
    def api_skill_gaps_queue():
        """Retrieve prioritized algorithmic focus queue."""
        try:
            limit = int(request.args.get("limit", 20))
        except ValueError:
            limit = 20

        analyzer = SkillGapAnalyzer(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        queue = analyzer.get_focus_queue(limit=limit)
        from dataclasses import asdict
        return jsonify([asdict(item) for item in queue])

    @app.route("/api/skill-gaps/history")
    def api_skill_gaps_history():
        """Retrieve list of historical skill gap reports."""
        try:
            limit = int(request.args.get("limit", 10))
        except ValueError:
            limit = 10

        analyzer = SkillGapAnalyzer(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        return jsonify(analyzer.list_reports(limit=limit))

    @app.route("/api/skill-gaps/analyze", methods=["POST"])
    def api_skill_gaps_analyze():
        """Run an on-demand personal skill gap and focus prioritization analysis."""
        analyzer = SkillGapAnalyzer(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        report = analyzer.analyze(save=True)
        from dataclasses import asdict
        return jsonify(asdict(report)), 201

    @app.route("/api/skill-gaps/report/<report_id>")
    def api_skill_gaps_report_by_id(report_id: str):
        """Retrieve a specific skill gap report by its report ID."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", report_id):
            return jsonify({"error": "Invalid report_id format"}), 400

        analyzer = SkillGapAnalyzer(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        report = analyzer.get_report(report_id)
        if not report:
            return jsonify({"error": f"Skill gap report '{report_id}' not found."}), 404

        from dataclasses import asdict
        return jsonify(asdict(report))

    # =========================================================================
    # Milestone 6.3.25: Adaptive Learning Loop & Plan Reconciliation Endpoints
    # =========================================================================

    @app.route("/api/learning-loop")
    def api_learning_loop_overview():
        """Retrieve overview summary of the adaptive learning loop."""
        loop = AdaptiveLearningLoop(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        return jsonify(loop.get_overview())

    @app.route("/api/learning-loop/latest")
    def api_learning_loop_latest():
        """Retrieve the latest learning loop report and snapshot."""
        loop = AdaptiveLearningLoop(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        report = loop.get_latest_report()
        from dataclasses import asdict
        if not report:
            report = loop.run_learning_cycle(save=False)
        return jsonify(asdict(report))

    @app.route("/api/learning-loop/history")
    def api_learning_loop_history():
        """Retrieve list of historical learning loop evaluations."""
        try:
            limit = int(request.args.get("limit", 10))
        except ValueError:
            limit = 10

        loop = AdaptiveLearningLoop(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        return jsonify(loop.list_history(limit=limit))

    @app.route("/api/learning-loop/analyze", methods=["POST"])
    def api_learning_loop_analyze():
        """Run an on-demand adaptive learning cycle and plan reconciliation."""
        loop = AdaptiveLearningLoop(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        report = loop.run_learning_cycle(save=True)
        from dataclasses import asdict
        return jsonify(asdict(report)), 201

    @app.route("/api/learning-loop/snapshot/<snapshot_id>")
    def api_learning_loop_snapshot(snapshot_id: str):
        """Retrieve a specific learning loop snapshot by ID."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", snapshot_id):
            return jsonify({"error": "Invalid snapshot_id format"}), 400

        loop = AdaptiveLearningLoop(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        snap = loop.get_snapshot(snapshot_id)
        if not snap:
            return jsonify({"error": f"Snapshot '{snapshot_id}' not found."}), 404

        from dataclasses import asdict
        return jsonify(asdict(snap))

    @app.route("/api/learning-loop/compare")
    def api_learning_loop_compare():
        """Compare two learning loop snapshots (defaults to latest two)."""
        s1_id = request.args.get("s1")
        s2_id = request.args.get("s2")

        if s1_id and not re.match(r"^[a-zA-Z0-9_\-]+$", s1_id):
            return jsonify({"error": "Invalid s1 format"}), 400
        if s2_id and not re.match(r"^[a-zA-Z0-9_\-]+$", s2_id):
            return jsonify({"error": "Invalid s2 format"}), 400

        loop = AdaptiveLearningLoop(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        s1 = loop.get_snapshot(s1_id) if s1_id else loop.get_latest_snapshot()
        if not s1:
            return jsonify({"error": "No snapshots available for comparison."}), 404

        s2 = loop.get_snapshot(s2_id) if s2_id else None
        if not s2:
            # Try to fetch previous from history
            history = loop.list_history(limit=2)
            if len(history) >= 2:
                s2 = loop.get_snapshot(history[1]["snapshot_id"])

        comparison = loop.compare_snapshots(s1, s2)
        return jsonify(comparison)

    @app.route("/api/learning-loop/proposals")
    def api_learning_loop_proposals():
        """Retrieve list of plan change proposals."""
        snapshot_id = request.args.get("snapshot_id")
        status = request.args.get("status")
        try:
            limit = int(request.args.get("limit", 20))
        except ValueError:
            limit = 20

        if snapshot_id and not re.match(r"^[a-zA-Z0-9_\-]+$", snapshot_id):
            return jsonify({"error": "Invalid snapshot_id format"}), 400
        if status and not re.match(r"^[a-zA-Z0-9_\-]+$", status):
            return jsonify({"error": "Invalid status format"}), 400

        loop = AdaptiveLearningLoop(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        proposals = loop.get_proposals(snapshot_id=snapshot_id, status=status, limit=limit)
        from dataclasses import asdict
        return jsonify([asdict(p) for p in proposals])

    @app.route("/api/learning-loop/proposals/preview", methods=["POST"])
    def api_learning_loop_proposals_preview():
        """Preview impact of pending proposals without modifying the active plan."""
        data = request.get_json(silent=True) or {}
        snapshot_id = data.get("snapshot_id")

        if snapshot_id and not re.match(r"^[a-zA-Z0-9_\-]+$", snapshot_id):
            return jsonify({"error": "Invalid snapshot_id format"}), 400

        loop = AdaptiveLearningLoop(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        pending = loop.get_proposals(snapshot_id=snapshot_id, status=ProposalStatus.PENDING.value)
        from dataclasses import asdict
        return jsonify({
            "pending_proposals_count": len(pending),
            "proposals": [asdict(p) for p in pending],
            "impact_summary": f"Applying these {len(pending)} proposal(s) will align your active plan with verified skill gaps.",
        })

    @app.route("/api/learning-loop/proposals/accept", methods=["POST"])
    def api_learning_loop_proposals_accept():
        """Explicitly accept and apply a plan change proposal."""
        data = request.get_json(silent=True) or {}
        proposal_id = data.get("proposal_id")
        apply_to_plan = bool(data.get("apply_to_plan", True))

        if not proposal_id or not re.match(r"^[a-zA-Z0-9_\-]+$", proposal_id):
            return jsonify({"error": "Invalid or missing proposal_id format"}), 400

        loop = AdaptiveLearningLoop(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            prop = loop.accept_proposal(proposal_id=proposal_id, apply_to_plan=apply_to_plan)
            from dataclasses import asdict
            return jsonify(asdict(prop)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/learning-loop/proposals/reject", methods=["POST"])
    def api_learning_loop_proposals_reject():
        """Explicitly reject a plan change proposal."""
        data = request.get_json(silent=True) or {}
        proposal_id = data.get("proposal_id")
        reason = data.get("reason", "")

        if not proposal_id or not re.match(r"^[a-zA-Z0-9_\-]+$", proposal_id):
            return jsonify({"error": "Invalid or missing proposal_id format"}), 400

        loop = AdaptiveLearningLoop(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            prop = loop.reject_proposal(proposal_id=proposal_id, reason=reason)
            from dataclasses import asdict
            return jsonify(asdict(prop)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

    # =========================================================================
    # Milestone 6.3.26: Guided Daily Practice & Study Session Endpoints
    # =========================================================================

    @app.route("/api/daily-practice")
    def api_daily_practice_overview():
        """Retrieve overview summary of the daily practice orchestrator."""
        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        return jsonify(orchestrator.get_overview())

    @app.route("/api/daily-practice/latest")
    def api_daily_practice_latest():
        """Retrieve the latest daily practice session."""
        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        session = orchestrator.get_latest_session()
        if not session:
            return jsonify({"session": None}), 200
        from dataclasses import asdict
        return jsonify(asdict(session)), 200

    @app.route("/api/daily-practice/history")
    def api_daily_practice_history():
        """Retrieve list of historical daily practice sessions."""
        limit_str = request.args.get("limit", "20")
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 20
        limit = max(1, min(100, limit))
        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        return jsonify({"sessions": orchestrator.list_sessions(limit=limit)}), 200

    @app.route("/api/daily-practice/generate", methods=["POST"])
    def api_daily_practice_generate():
        """Generate or preview a daily study session based on real evidence."""
        data = request.get_json(silent=True) or {}
        budget_minutes = data.get("budget_minutes", 45)
        preview_only = data.get("preview_only", False)
        title = data.get("title")
        focus_topics = data.get("focus_topics")

        try:
            budget_minutes = int(budget_minutes)
        except (ValueError, TypeError):
            return jsonify({"error": "budget_minutes must be an integer"}), 400

        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        from dataclasses import asdict
        try:
            if preview_only:
                preview = orchestrator.preview_session(
                    budget_minutes=budget_minutes,
                    title=title,
                    focus_topics=focus_topics,
                )
                return jsonify(asdict(preview)), 200
            else:
                session = orchestrator.generate_session(
                    budget_minutes=budget_minutes,
                    title=title,
                    focus_topics=focus_topics,
                )
                return jsonify(asdict(session)), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-practice/start", methods=["POST"])
    def api_daily_practice_start():
        """Start a generated daily practice session."""
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        if not session_id or not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid or missing session_id"}), 400

        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = orchestrator.start_session(session_id)
            from dataclasses import asdict
            return jsonify(asdict(session)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-practice/task/start", methods=["POST"])
    def api_daily_practice_task_start():
        """Mark a specific task within an active session as in progress."""
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        task_id = data.get("task_id")
        if not session_id or not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid or missing session_id"}), 400
        if not task_id or not re.match(r"^[a-zA-Z0-9_\-]+$", task_id):
            return jsonify({"error": "Invalid or missing task_id"}), 400

        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = orchestrator.start_task(session_id, task_id)
            from dataclasses import asdict
            return jsonify(asdict(session)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-practice/task/complete", methods=["POST"])
    def api_daily_practice_task_complete():
        """Mark a specific task within an active session as completed."""
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        task_id = data.get("task_id")
        verified_pass = bool(data.get("verified_pass", False))
        notes = data.get("notes", "")
        test_run_id = data.get("test_run_id")

        if not session_id or not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid or missing session_id"}), 400
        if not task_id or not re.match(r"^[a-zA-Z0-9_\-]+$", task_id):
            return jsonify({"error": "Invalid or missing task_id"}), 400

        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = orchestrator.complete_task(
                session_id=session_id,
                task_id=task_id,
                verified_pass=verified_pass,
                notes=notes,
                test_run_id=test_run_id,
            )
            from dataclasses import asdict
            return jsonify(asdict(session)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-practice/task/skip", methods=["POST"])
    def api_daily_practice_task_skip():
        """Skip a specific task within an active session."""
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        task_id = data.get("task_id")
        reason = data.get("reason", "")

        if not session_id or not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid or missing session_id"}), 400
        if not task_id or not re.match(r"^[a-zA-Z0-9_\-]+$", task_id):
            return jsonify({"error": "Invalid or missing task_id"}), 400

        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = orchestrator.skip_task(session_id=session_id, task_id=task_id, reason=reason)
            from dataclasses import asdict
            return jsonify(asdict(session)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-practice/pause", methods=["POST"])
    def api_daily_practice_pause():
        """Pause an active daily practice session."""
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        reason = data.get("reason", "")

        if not session_id or not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid or missing session_id"}), 400

        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = orchestrator.pause_session(session_id=session_id, reason=reason)
            from dataclasses import asdict
            return jsonify(asdict(session)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-practice/resume", methods=["POST"])
    def api_daily_practice_resume():
        """Resume a paused daily practice session."""
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")

        if not session_id or not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid or missing session_id"}), 400

        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = orchestrator.resume_session(session_id=session_id)
            from dataclasses import asdict
            return jsonify(asdict(session)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-practice/abandon", methods=["POST"])
    def api_daily_practice_abandon():
        """Abandon a session safely without data corruption."""
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        reason = data.get("reason", "")

        if not session_id or not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid or missing session_id"}), 400

        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session = orchestrator.abandon_session(session_id=session_id, reason=reason)
            from dataclasses import asdict
            return jsonify(asdict(session)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-practice/complete", methods=["POST"])
    def api_daily_practice_complete():
        """Complete an active or paused daily practice session."""
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        notes = data.get("notes", "")

        if not session_id or not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid or missing session_id"}), 400

        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            session, report = orchestrator.complete_session(session_id=session_id, notes=notes)
            from dataclasses import asdict
            return jsonify({
                "session": asdict(session),
                "report": asdict(report),
            }), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/daily-practice/report/<session_id>")
    def api_daily_practice_report(session_id: str):
        """Retrieve verified retrospective report for a session."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid session_id format"}), 400

        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            report = orchestrator.get_report(session_id)
            from dataclasses import asdict
            return jsonify(asdict(report)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/daily-practice/re-evaluate", methods=["POST"])
    def api_daily_practice_reevaluate():
        """Feed completed session evidence back into the Adaptive Learning Loop."""
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")

        if not session_id or not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            return jsonify({"error": "Invalid or missing session_id"}), 400

        orchestrator = DailyPracticeOrchestrator(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            loop_report = orchestrator.reevaluate_learning_loop(session_id)
            from dataclasses import asdict
            return jsonify(asdict(loop_report)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    # =========================================================================
    # Milestone 6.3.27: Unified Learning Command Center Endpoints
    # =========================================================================

    @app.route("/api/command-center")
    def api_command_center():
        """Get unified command center overview aggregating all learning subsystems."""
        mgr = CommandCenterManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            overview = mgr.get_overview()
            from dataclasses import asdict
            return jsonify(asdict(overview)), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/command-center/action")
    def api_command_center_action():
        """Derive the deterministic primary action based strictly on evidence."""
        mgr = CommandCenterManager(
            tracking_db_path=tracker_path,
            progress_db_path=db_path,
        )
        try:
            action = mgr.derive_primary_action()
            from dataclasses import asdict
            return jsonify(asdict(action)), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return app


def run_dashboard_server(
    host: str = "127.0.0.1",
    port: int = 5050,
    db_path: Optional[str | Path] = None,
    tracking_db_path: Optional[str | Path] = None,
) -> None:
    """Launch local Flask web server. Strictly binds to 127.0.0.1."""
    # Enforce safe local binding
    safe_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    app = create_app(db_path=db_path, tracking_db_path=tracking_db_path)
    print(f"\n=======================================================")
    print(f"  LEETCODE AGENT - INTERACTIVE LEARNING COMMAND CENTER")
    print(f"  Local Web Workspace: http://{safe_host}:{port}/")
    print(f"  Binding: Localhost Only ({safe_host})")
    print(f"  (Press Ctrl+C to stop)")
    print(f"=======================================================\n")
    app.run(host=safe_host, port=port, debug=False)


if __name__ == "__main__":
    run_dashboard_server()
