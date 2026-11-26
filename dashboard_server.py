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

from flask import Flask, jsonify, render_template_string, request

from dashboard import get_dashboard_data, _get_learning_intelligence_data
from intelligence.adaptive import AdaptiveLearningEngine
from intelligence.planner import SessionPlanner
from intelligence.tracker import (
    DEFAULT_TRACKING_DB_PATH,
    ProblemProgressStatus,
    SessionStatus,
    SessionTracker,
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
