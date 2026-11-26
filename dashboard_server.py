"""Local Unified Learning Dashboard & Command Center Web Server.

Milestone 6.3.8: Unified Learning Dashboard & Command Center.
Provides a local, zero-external-network Flask web dashboard serving progress,
topic mastery, session history, and adaptive recommendations.
"""

from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template_string, request

from dashboard import get_dashboard_data
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
import store

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LeetCode Agent - Unified Learning Command Center</title>
    <style>
        :root {
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-hover: #334155;
            --primary: #38bdf8;
            --primary-dark: #0284c7;
            --accent: #a855f7;
            --success: #22c55e;
            --warning: #eab308;
            --danger: #ef4444;
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
        .container { max-width: 1200px; margin: 0 auto; }
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
        .badge-completed { background: #064e3b; color: #6ee7b7; }
        .badge-in_progress { background: #1e3a8a; color: #93c5fd; }
        .badge-cancelled { background: #7c2d12; color: #fdba74; }
        .badge-easy { color: #86efac; }
        .badge-medium { color: #fde047; }
        .badge-hard { color: #fca5a5; }
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
                <span>●</span> Local-First / Zero External APIs
            </div>
        </header>

        <!-- Top Stat Cards -->
        <div class="grid-stats">
            <div class="stat-card">
                <div class="label">Problems Solved</div>
                <div class="value">{{ data.summary.unique_problems_solved }}</div>
                <div class="subtext">{{ data.summary.by_difficulty_solved.Easy }} Easy, {{ data.summary.by_difficulty_solved.Medium }} Med, {{ data.summary.by_difficulty_solved.Hard }} Hard</div>
            </div>
            <div class="stat-card">
                <div class="label">Total Attempts</div>
                <div class="value">{{ data.summary.attempts_summary.total_attempts }}</div>
                <div class="subtext">{{ data.summary.attempts_summary.passed_attempts }} Passed / {{ data.summary.attempts_summary.failed_attempts }} Failed</div>
            </div>
            <div class="stat-card">
                <div class="label">Tracked Sessions</div>
                <div class="value">{{ data.learning_intelligence.session_analytics.total_sessions_planned }}</div>
                <div class="subtext">{{ (data.learning_intelligence.session_analytics.session_completion_rate * 100)|round(0) }}% Completion Rate</div>
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

        <!-- Topic Mastery Section -->
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

        <!-- Preview Recommended Session -->
        {% if data.learning_intelligence.preview_session.problems %}
        <div class="card">
            <div class="card-header">
                <h2>Recommended Session Plan (Preview-Only)</h2>
                <span style="color: var(--primary); font-size: 0.9rem;">{{ data.learning_intelligence.preview_session.total_planned }} Problems Planned</span>
            </div>
            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 16px;">{{ data.learning_intelligence.preview_session.summary }}</p>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Role</th>
                        <th>Problem ID</th>
                        <th>Difficulty</th>
                        <th>Topics</th>
                        <th>Score</th>
                        <th>Rationale</th>
                    </tr>
                </thead>
                <tbody>
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
        {% endif %}

        <!-- Recent Tracked Sessions -->
        {% if data.learning_intelligence.recent_sessions %}
        <div class="card">
            <div class="card-header">
                <h2>Recent Learning Sessions</h2>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Session ID</th>
                        <th>Status</th>
                        <th>Progress</th>
                        <th>Created</th>
                        <th>Summary</th>
                    </tr>
                </thead>
                <tbody>
                    {% for s in data.learning_intelligence.recent_sessions %}
                    <tr>
                        <td style="font-family: monospace;">{{ s.session_id }}</td>
                        <td><span class="status-badge badge-{{ s.status }}">{{ s.status|title }}</span></td>
                        <td>{{ s.completed_count }} done, {{ s.skipped_count }} skipped / {{ s.total_problems }} total</td>
                        <td style="color: var(--text-muted);">{{ s.created_at[:10] }}</td>
                        <td style="color: var(--text-muted);">{{ s.summary[:70] }}...</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}

        <footer>
            LeetCode Agent • Local Offline Architecture • No Live Account Modification
        </footer>
    </div>
</body>
</html>
"""


def create_app(
    db_path: Optional[str | Path] = None,
    tracking_db_path: Optional[str | Path] = None,
) -> Flask:
    """Create and configure the Flask dashboard app."""
    app = Flask(__name__)

    @app.route("/")
    def index():
        data = get_dashboard_data(db_path=db_path)
        return render_template_string(HTML_TEMPLATE, data=data)

    @app.route("/api/dashboard")
    def api_dashboard():
        data = get_dashboard_data(db_path=db_path)
        return jsonify(data)

    return app


def run_dashboard_server(
    host: str = "127.0.0.1",
    port: int = 5050,
    db_path: Optional[str | Path] = None,
    tracking_db_path: Optional[str | Path] = None,
) -> None:
    """Launch local Flask web server."""
    app = create_app(db_path=db_path, tracking_db_path=tracking_db_path)
    print(f"\n=======================================================")
    print(f"  LEETCODE AGENT - UNIFIED LEARNING COMMAND CENTER")
    print(f"  Local Web Dashboard: http://{host}:{port}/")
    print(f"  (Press Ctrl+C to stop)")
    print(f"=======================================================\n")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    run_dashboard_server()
