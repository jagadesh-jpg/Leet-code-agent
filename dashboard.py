import csv
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from problems import load_problems
import store


def derive_problem_id(url: str, title: str) -> str:
    """Derive a clean problem identifier from a LeetCode URL or title."""
    if url:
        parsed = urlparse(url.strip())
        parts = [p for p in parsed.path.strip("/").split("/") if p and p != "description"]
        if parts:
            slug = parts[-1].lower()
            if slug != "problems":
                return slug
    cleaned_title = re.sub(r"[^a-zA-Z0-9_\-]+", "-", title.strip().lower()).strip("-")
    return cleaned_title or "unknown-problem"


def import_submissions_from_csv(
    csv_content_or_path: str,
    db_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Import user's manually prepared LeetCode submission CSV into SQLite.
    Accepts either a file path or direct CSV text.
    """
    store.init(db_path=db_path)

    # Check if input is a valid file path
    p = Path(csv_content_or_path)
    if p.is_file():
        with open(p, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
    else:
        lines = csv_content_or_path.splitlines()

    reader = csv.DictReader(lines)
    imported = []
    skipped = []

    for row_idx, row in enumerate(reader, start=1):
        # Normalize header keys (case-insensitive & stripped)
        norm_row = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items() if k}
        title = norm_row.get("title", "")
        url = norm_row.get("url", "")
        if not title and not url:
            skipped.append({"row": row_idx, "reason": "Missing title and URL"})
            continue

        problem_id = derive_problem_id(url, title)
        diff = norm_row.get("difficulty", "Medium").capitalize()
        verdict = norm_row.get("verdict", "Accepted").title()
        date_str = norm_row.get("submission_date", "")
        lang = norm_row.get("language", "Python3") or "Python3"

        # Safe float conversion
        try:
            runtime_ms = float(norm_row.get("runtime_ms")) if norm_row.get("runtime_ms") else None
        except (ValueError, TypeError):
            runtime_ms = None

        try:
            memory_mb = float(norm_row.get("memory_mb")) if norm_row.get("memory_mb") else None
        except (ValueError, TypeError):
            memory_mb = None

        notes = norm_row.get("notes", "")

        record = store.save_imported_submission(
            problem_id=problem_id,
            title=title or problem_id,
            url=url,
            difficulty=diff,
            verdict=verdict,
            submission_date=date_str,
            language=lang,
            runtime_ms=runtime_ms,
            memory_mb=memory_mb,
            notes=notes,
            db_path=db_path,
        )
        imported.append(record)

    return {
        "status": "success",
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "records": imported,
        "skipped": skipped,
    }


def get_dashboard_data(
    username: str = "jagadesh-02",
    db_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Calculate aggregated stats, attempted but not accepted problems, and solve-next recommendations."""
    store.init(db_path=db_path)

    csv_submissions = store.get_imported_submissions(db_path=db_path)
    official_verdicts = store.get_official_verdicts(db_path=db_path)
    custom_problems = store.list_custom_problems(db_path=db_path)
    built_in_problems = load_problems()

    # Build unified tracked submission records with explicit sources & avoid double counting
    unified_submissions = []
    seen_keys = set()

    # 1. Official verdicts (highest fidelity manual submissions)
    for ov in official_verdicts:
        pid = ov["problem_id"]
        # Find matching custom problem or built-in problem for title/difficulty/url
        c_prob = store.get_custom_problem(pid, db_path=db_path)
        b_prob = next((b for b in built_in_problems if b["id"] == pid), None)
        title = (c_prob.get("title") if c_prob else None) or (b_prob.get("title") if b_prob else None) or pid
        diff = (c_prob.get("difficulty") if c_prob else None) or (b_prob.get("difficulty") if b_prob else None) or "Medium"
        url = (c_prob.get("url") if c_prob else None) or f"https://leetcode.com/problems/{pid}/"

        norm_verdict = ov["verdict"].strip().title()
        timestamp = ov.get("submitted_at", "")
        # Dedup key
        dedup_key = (pid, norm_verdict, ov.get("runtime_ms"), ov.get("memory_mb"))
        seen_keys.add(dedup_key)

        unified_submissions.append({
            "id": f"official_{ov['id']}",
            "source": "official_verdict",
            "problem_id": pid,
            "title": title,
            "url": url,
            "difficulty": diff.capitalize(),
            "verdict": norm_verdict,
            "submission_date": timestamp,
            "language": "Python3",
            "runtime_ms": ov.get("runtime_ms"),
            "memory_mb": ov.get("memory_mb"),
            "notes": ov.get("notes", ""),
        })

    # 2. Imported CSV submissions
    for sub in csv_submissions:
        pid = sub["problem_id"]
        v = sub["verdict"].strip().title()
        dedup_key = (pid, v, sub.get("runtime_ms"), sub.get("memory_mb"))
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        unified_submissions.append({
            "id": f"csv_{sub['id']}",
            "source": "csv_import",
            "problem_id": pid,
            "title": sub["title"],
            "url": sub["url"],
            "difficulty": sub["difficulty"].capitalize(),
            "verdict": v,
            "submission_date": sub.get("submission_date") or sub.get("imported_at", ""),
            "language": sub.get("language", "Python3"),
            "runtime_ms": sub.get("runtime_ms"),
            "memory_mb": sub.get("memory_mb"),
            "notes": sub.get("notes", ""),
        })

    # 3. Submission breakdown & status mapping per problem
    problem_verdicts: Dict[str, set] = {}
    problem_info: Dict[str, Dict[str, Any]] = {}
    verdict_counts: Dict[str, int] = {}
    difficulty_solved = {"Easy": 0, "Medium": 0, "Hard": 0}

    for sub in unified_submissions:
        pid = sub["problem_id"]
        v = sub["verdict"]
        diff = sub["difficulty"]
        if diff not in difficulty_solved:
            diff = "Medium"

        verdict_counts[v] = verdict_counts.get(v, 0) + 1

        if pid not in problem_verdicts:
            problem_verdicts[pid] = set()
            problem_info[pid] = {
                "id": pid,
                "title": sub["title"],
                "url": sub["url"],
                "difficulty": diff,
            }
        problem_verdicts[pid].add(v)

    # Count distinct solved problems by difficulty
    for pid, v_set in problem_verdicts.items():
        if "Accepted" in v_set:
            diff = problem_info[pid]["difficulty"]
            difficulty_solved[diff] = difficulty_solved.get(diff, 0) + 1

    total_unique_solved = sum(
        1 for pid, v_set in problem_verdicts.items() if "Accepted" in v_set
    )

    # 4. Identify problems attempted but not accepted
    attempted_not_accepted = []
    for pid, v_set in problem_verdicts.items():
        if "Accepted" not in v_set:
            info = problem_info.get(pid, {"id": pid, "title": pid, "url": "", "difficulty": "Medium"})
            attempted_not_accepted.append({
                "problem_id": pid,
                "title": info["title"],
                "url": info["url"],
                "difficulty": info["difficulty"],
                "attempts_count": sum(1 for s in unified_submissions if s["problem_id"] == pid),
                "last_verdict": next((s["verdict"] for s in unified_submissions if s["problem_id"] == pid), "Unsolved"),
            })

    # 5. Recommendations: which problems to solve next
    recommendations = []

    # Priority A: Attempted but not accepted
    for item in attempted_not_accepted:
        recommendations.append({
            "problem_id": item["problem_id"],
            "title": item["title"],
            "difficulty": item["difficulty"],
            "url": item["url"],
            "reason": f"Previously attempted on LeetCode with '{item['last_verdict']}'. Ready to crack with Gemini assistant!",
            "priority": "High (Unresolved Attempt)",
            "can_solve_with_agent": bool(store.get_custom_problem(item["problem_id"], db_path=db_path) or any(b["id"] == item["problem_id"] for b in built_in_problems)),
        })

    # Priority B: Custom problems not yet officially accepted
    solved_pids = {pid for pid, v_set in problem_verdicts.items() if "Accepted" in v_set}
    for cust in custom_problems:
        c_id = cust["id"]
        if c_id not in solved_pids and not any(r["problem_id"] == c_id for r in recommendations):
            recommendations.append({
                "problem_id": c_id,
                "title": cust["title"],
                "difficulty": cust["difficulty"].capitalize(),
                "url": cust["url"],
                "reason": "Imported into your local agent and ready for Gemini autonomous solving.",
                "priority": "Medium (Imported Problem)",
                "can_solve_with_agent": True,
            })

    # Priority C: Curated problems
    for bip in built_in_problems:
        b_id = bip["id"]
        if b_id not in solved_pids and not any(r["problem_id"] == b_id for r in recommendations):
            is_loc_solved = store.is_solved(b_id, db_path=db_path)
            rec_prio = "Low (Practice Problem)" if is_loc_solved else "Medium (Curated Problem)"
            rec_reason = (
                "Locally verified by judge; ready to test and submit on your official LeetCode account."
                if is_loc_solved
                else f"Curated {bip['difficulty'].capitalize()} problem in local repository."
            )
            recommendations.append({
                "problem_id": b_id,
                "title": bip["title"],
                "difficulty": bip["difficulty"].capitalize(),
                "url": f"https://leetcode.com/problems/{b_id}/",
                "reason": rec_reason,
                "priority": rec_prio,
                "can_solve_with_agent": True,
            })

    # Check for active or latest autonomous run
    latest_run = store.get_latest_autonomous_run(db_path=db_path)
    autonomous_stats = {
        "status": latest_run.get("status", "idle") if latest_run else "idle",
        "current_problem": latest_run.get("current_problem_id", "") if latest_run else "",
        "current_attempt": latest_run.get("current_attempt", 0) if latest_run else 0,
        "completed_count": latest_run.get("completed_count", 0) if latest_run else 0,
        "remaining_count": latest_run.get("remaining_count", 0) if latest_run else 0,
        "verified_count": latest_run.get("verified_count", 0) if latest_run else 0,
        "failed_count": latest_run.get("failed_count", 0) if latest_run else 0,
        "api_errors": latest_run.get("api_errors_count", 0) if latest_run else 0,
        "estimated_api_usage": latest_run.get("api_calls_count", 0) if latest_run else 0,
        "last_error": latest_run.get("error_message", "") if latest_run else "",
    }

    # Language progress breakdown
    lang_progress = store.get_language_progress_summary(db_path=db_path)

    # Run history & status counts
    all_runs = store.list_autonomous_runs(db_path=db_path, limit=20)
    run_status_counts: Dict[str, int] = {}
    for r in all_runs:
        s = r.get("status", "unknown")
        run_status_counts[s] = run_status_counts.get(s, 0) + 1

    # Attempt statistics
    attempts_summary = store.get_all_attempts_summary(db_path=db_path)

    # 6. Unified Learning Intelligence & Command Center Integration (Milestone 6.3.8)
    learning_intelligence = _get_learning_intelligence_data(db_path=db_path, language="python")

    return {
        "username": username,
        "profile_url": f"https://leetcode.com/u/{username}/",
        "summary": {
            "total_submissions_tracked": len(unified_submissions),
            "unique_problems_solved": total_unique_solved,
            "unique_problems_attempted": len(problem_verdicts),
            "by_difficulty_solved": difficulty_solved,
            "verdicts_breakdown": verdict_counts,
            "language_progress": lang_progress,
            "attempts_summary": attempts_summary,
            "run_status_counts": run_status_counts,
        },
        "language_progress": lang_progress,
        "autonomous_worker": autonomous_stats,
        "autonomous_runs_history": all_runs[:10],
        "attempted_not_accepted": attempted_not_accepted,
        "recommendations": recommendations[:6],
        "recent_submissions": unified_submissions[:10],
        "learning_intelligence": learning_intelligence,
    }


def _get_learning_intelligence_data(
    db_path: Optional[str | Path] = None,
    tracking_db_path: Optional[str | Path] = None,
    language: str = "python",
) -> Dict[str, Any]:
    """Extract topic mastery, session history, and adaptive recommendations without side effects."""
    from intelligence.adaptive import AdaptiveLearningEngine
    from intelligence.planner import SessionPlanner
    from intelligence.topics import TopicAnalyzer
    from intelligence.tracker import SessionTracker

    built_in = load_problems()

    # Topic Mastery
    topic_analyzer = TopicAnalyzer(db_path=db_path, language=language)
    topic_metrics = topic_analyzer.analyze_topics(built_in, include_curated=True)
    topics_list = []
    for t_name, m in sorted(topic_metrics.items(), key=lambda x: (-x[1].unsolved_problems, x[0])):
        topics_list.append({
            "topic": m.topic,
            "total_problems": m.total_problems,
            "solved_problems": m.solved_problems,
            "unsolved_problems": m.unsolved_problems,
            "total_attempts": m.total_attempts,
            "failed_attempts": m.failed_attempts,
            "success_rate": round(m.success_rate, 2),
            "mastery_status": m.mastery_status,
            "summary": m.summary,
        })

    # Tracked Sessions & Analytics
    tracker = SessionTracker(db_path=tracking_db_path)
    analytics = tracker.get_analytics()
    recent_sess = tracker.list_sessions(limit=5)
    sessions_list = []
    for s in recent_sess:
        sessions_list.append({
            "session_id": s.session_id,
            "status": s.status.value,
            "target_language": s.target_language,
            "total_problems": s.total_problems,
            "completed_count": s.completed_count,
            "skipped_count": s.skipped_count,
            "created_at": s.created_at,
            "summary": s.session_summary,
        })

    # Adaptive Recommendation
    adaptive_engine = AdaptiveLearningEngine(
        progress_db_path=db_path,
        tracking_db_path=tracking_db_path,
        language=language,
    )
    report = adaptive_engine.analyze_and_recommend(candidate_problems=built_in)

    # Preview Planned Session (using recommended sizing)
    rec_size = report.session_sizing.recommended_size if report.session_sizing else 3
    planner = SessionPlanner(db_path=db_path, language=language)
    planned_session = planner.plan_session(built_in, session_size=rec_size, skip_solved=True)
    planned_problems_list = []
    for p in planned_session.planned_problems:
        planned_problems_list.append({
            "rank": p.rank,
            "role": p.role.value,
            "problem_id": p.problem_id,
            "title": p.title,
            "difficulty": p.difficulty,
            "priority_score": p.priority_score,
            "topics": p.topics,
            "reason": p.reason,
        })

    return {
        "overall_status": report.overall_status,
        "topics_needing_practice": report.topics_needing_practice,
        "proficient_topics": report.proficient_topics,
        "topics_mastery": topics_list,
        "session_analytics": {
            "total_sessions_planned": analytics.total_sessions_planned,
            "total_sessions_completed": analytics.total_sessions_completed,
            "total_sessions_in_progress": analytics.total_sessions_in_progress,
            "total_sessions_cancelled": analytics.total_sessions_cancelled,
            "session_completion_rate": round(analytics.session_completion_rate, 2),
            "total_problems_planned": analytics.total_problems_planned,
            "total_problems_completed": analytics.total_problems_completed,
            "total_problems_skipped": analytics.total_problems_skipped,
            "problem_completion_rate": round(analytics.problem_completion_rate, 2),
        },
        "recent_sessions": sessions_list,
        "primary_recommendation": {
            "action_type": report.primary_recommendation.action_type.value,
            "title": report.primary_recommendation.title,
            "target": report.primary_recommendation.target_identifier,
            "confidence": report.primary_recommendation.confidence,
            "rationale": report.primary_recommendation.rationale,
            "evidence": report.primary_recommendation.evidence,
        },
        "secondary_recommendations": [
            {
                "action_type": r.action_type.value,
                "title": r.title,
                "target": r.target_identifier,
                "rationale": r.rationale,
            }
            for r in report.secondary_recommendations
        ],
        "suggested_session_sizing": {
            "recommended_size": report.session_sizing.recommended_size if report.session_sizing else 3,
            "default_size": report.session_sizing.default_size if report.session_sizing else 3,
            "rationale": report.session_sizing.rationale if report.session_sizing else "Standard baseline.",
            "has_sufficient_evidence": report.session_sizing.has_sufficient_evidence if report.session_sizing else False,
        },
        "preview_session": {
            "target_size": planned_session.target_size,
            "total_planned": planned_session.total_problems,
            "summary": planned_session.session_summary,
            "problems": planned_problems_list,
        },
    }
