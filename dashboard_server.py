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
from intelligence.mock_interview import (
    AssessmentReport,
    InterviewManager,
    InterviewStatus,
    InterviewTrack,
    MockInterviewSession,
)
from intelligence.planner import SessionPlanner
from intelligence.portfolio import (
    DEFAULT_PORTFOLIO_EXPORTS_DIR,
    PortfolioConfig,
    PortfolioManager,
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

        <!-- Top Stat Cards -->
        <div class="grid-stats">
            <div class="stat-card">
                <div class="label">Problems Solved</div>
                <div class="value" id="statSolved">{{ data.summary.unique_problems_solved }}</div>
                <div class="subtext">{{ data.summary.by_difficulty_solved.Easy }} Easy, {{ data.summary.by_difficulty_solved.Medium }} Med, {{ data.summary.by_difficulty_solved.Hard }} Hard</div>
            </div>
            <div class="stat-card">
                <div class="label">Total Attempts</div>
                <div class="value" id="statAttempts">{{ data.summary.attempts_summary.total_attempts }}</div>
                <div class="subtext">{{ data.summary.attempts_summary.passed_attempts }} Passed / {{ data.summary.attempts_summary.failed_attempts }} Failed</div>
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

        <!-- Adaptive Learning Recommendation -->
        <div class="card">
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
        <div class="card">
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
        <div class="card">
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
        <div class="card">
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
        <div class="card">
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
        <div class="card">
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
        <div class="card">
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
        <div class="card">
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
        <div class="card">
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
        <div class="card">
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
        <div class="card" id="codingWorkspaceCard">
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
        <div class="card" id="portfolioSection">
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
        <div class="card" id="interviewSection">
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

        // Initialize Coach, Revision, Goals, Roadmap, Daily Mission, Workspace, Portfolio, and Interview on window load
        window.addEventListener("DOMContentLoaded", () => {
            initCoach();
            reloadRevisionQueue();
            reloadGoalsAndMilestones();
            reloadRoadmapData();
            reloadDailyMission();
            openProblemInWorkspace("two-sum");
            reloadPortfolioPreview();
            reloadInterviewState();
            reloadInterviewHistory();
        });

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
