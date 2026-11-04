import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from assistant import solve_problem_flow
from llm import LLMClient, LLMError, MockLLM
from memory import retrieve_relevant_learning, seed_default_learning
from problems import get_problems, load_problems
import store

# Global worker lock & control signals for in-process thread
_WORKER_LOCK = threading.Lock()
_ACTIVE_WORKER_THREAD: Optional[threading.Thread] = None
_PAUSE_REQUESTED = threading.Event()
_STOP_REQUESTED = threading.Event()
_CURRENT_RUN_ID: Optional[str] = None


def get_active_run_id() -> Optional[str]:
    global _CURRENT_RUN_ID
    return _CURRENT_RUN_ID


def is_worker_running() -> bool:
    global _ACTIVE_WORKER_THREAD
    return _ACTIVE_WORKER_THREAD is not None and _ACTIVE_WORKER_THREAD.is_alive()


def get_pending_queue(
    difficulty: Optional[str] = None,
    max_problems: int = 5,
    skip_locally_verified: bool = True,
    db_path: Optional[str | Path] = None,
) -> List[Dict[str, Any]]:
    """Assemble pending eligible problems from custom imported and curated datasets."""
    store.init(db_path=db_path)
    custom_list = store.list_custom_problems(db_path=db_path)
    built_in = load_problems()

    # Map all candidates
    candidates = []
    seen_ids = set()

    # 1. Custom imported problems first
    for cp in custom_list:
        pid = cp["id"]
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        c_prob = store.get_custom_problem(pid, db_path=db_path)
        if c_prob:
            candidates.append(c_prob)

    # 2. Built-in curated problems
    for bp in built_in:
        pid = bp["id"]
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        candidates.append(bp)

    # Filter difficulty
    if difficulty:
        diff_norm = difficulty.strip().lower()
        candidates = [p for p in candidates if p.get("difficulty", "").strip().lower() == diff_norm]

    # Filter locally verified if requested
    filtered = []
    for p in candidates:
        pid = p["id"]
        if skip_locally_verified and store.is_solved(pid, db_path=db_path):
            continue
        filtered.append(p)

    return filtered[:max_problems]


def run_autonomous_queue(
    max_problems: int = 5,
    max_attempts_per_problem: int = 5,
    difficulty: Optional[str] = None,
    api_request_budget: int = 100,
    api_delay_seconds: float = 0.0,
    llm_client: Any = None,
    db_path: Optional[str | Path] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Autonomous batch worker executing solve-test-fix loop sequentially."""
    global _CURRENT_RUN_ID, _PAUSE_REQUESTED, _STOP_REQUESTED

    store.init(db_path=db_path)
    seed_default_learning(db_path=db_path)

    # Recover existing run or create new
    if not run_id:
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        pending = get_pending_queue(
            difficulty=difficulty,
            max_problems=max_problems,
            skip_locally_verified=True,
            db_path=db_path,
        )
        problem_ids = [p["id"] for p in pending]
        run_data = store.create_autonomous_run(
            run_id=run_id,
            total_problems=len(problem_ids),
            difficulty_filter=difficulty,
            max_attempts=max_attempts_per_problem,
            db_path=db_path,
        )
        store.save_autonomous_queue(run_id, problem_ids, db_path=db_path)
    else:
        run_data = store.get_autonomous_run(run_id, db_path=db_path)
        if not run_data:
            return {"error": f"Run '{run_id}' not found."}

    _CURRENT_RUN_ID = run_id
    _PAUSE_REQUESTED.clear()
    _STOP_REQUESTED.clear()

    # Determine LLM client
    if llm_client is None:
        try:
            client = LLMClient()
        except Exception:
            all_probs = load_problems()
            client = MockLLM(problems=all_probs)
    else:
        client = llm_client

    queue_items = store.get_autonomous_queue_items(run_id, db_path=db_path)
    total = len(queue_items)
    completed_count = run_data.get("completed_count", 0)
    verified_count = run_data.get("verified_count", 0)
    failed_count = run_data.get("failed_count", 0)
    api_calls = run_data.get("api_calls_count", 0)
    api_errors = run_data.get("api_errors_count", 0)

    store.update_autonomous_run(
        run_id,
        {"status": "running"},
        db_path=db_path,
    )

    all_custom = store.list_custom_problems(db_path=db_path)
    all_builtin = load_problems()

    for item in queue_items:
        # Check external signals
        if _STOP_REQUESTED.is_set():
            store.update_autonomous_run(
                run_id,
                {"status": "stopped"},
                db_path=db_path,
            )
            break

        if _PAUSE_REQUESTED.is_set():
            store.update_autonomous_run(
                run_id,
                {"status": "paused"},
                db_path=db_path,
            )
            break

        # Check API budget limit
        if api_calls >= api_request_budget:
            store.update_autonomous_run(
                run_id,
                {
                    "status": "stopped",
                    "error_message": f"API request budget of {api_request_budget} calls reached.",
                },
                db_path=db_path,
            )
            break

        pid = item["problem_id"]
        # Skip if already processed in this run
        if item["status"] in ["locally_verified", "failed", "skipped"]:
            continue

        # Find problem definition
        prob_def = store.get_custom_problem(pid, db_path=db_path)
        if not prob_def:
            prob_def = next((b for b in all_builtin if b["id"] == pid), None)

        if not prob_def:
            store.update_autonomous_queue_item(
                run_id, pid, "failed", error="Problem definition not found", db_path=db_path
            )
            completed_count += 1
            failed_count += 1
            continue

        store.update_autonomous_run(
            run_id,
            {
                "current_problem_id": pid,
                "current_attempt": 1,
            },
            db_path=db_path,
        )
        store.update_autonomous_queue_item(
            run_id, pid, "running", db_path=db_path
        )

        try:
            res = solve_problem_flow(
                problem=prob_def,
                llm_client=client,
                max_attempts=max_attempts_per_problem,
                db_path=db_path,
            )
            attempts = res.get("attempts", 1)
            api_calls += attempts

            if res.get("passed", False):
                verified_count += 1
                q_status = "locally_verified"
            else:
                failed_count += 1
                q_status = "failed"

            completed_count += 1
            remaining = total - completed_count

            store.update_autonomous_queue_item(
                run_id=run_id,
                problem_id=pid,
                status=q_status,
                attempts_used=attempts,
                result_status=res.get("local_status", q_status),
                db_path=db_path,
            )

            store.update_autonomous_run(
                run_id,
                {
                    "completed_count": completed_count,
                    "remaining_count": max(0, remaining),
                    "verified_count": verified_count,
                    "failed_count": failed_count,
                    "api_calls_count": api_calls,
                    "api_errors_count": api_errors,
                },
                db_path=db_path,
            )

            if api_delay_seconds > 0:
                time.sleep(api_delay_seconds)

        except Exception as e:
            api_errors += 1
            completed_count += 1
            failed_count += 1
            remaining = total - completed_count

            store.update_autonomous_queue_item(
                run_id=run_id,
                problem_id=pid,
                status="failed",
                error=str(e),
                db_path=db_path,
            )
            store.update_autonomous_run(
                run_id,
                {
                    "completed_count": completed_count,
                    "remaining_count": max(0, remaining),
                    "failed_count": failed_count,
                    "api_errors_count": api_errors,
                    "error_message": f"Error solving {pid}: {e}",
                },
                db_path=db_path,
            )

    # Final run completion status check
    final_run = store.get_autonomous_run(run_id, db_path=db_path) or {}
    cur_status = final_run.get("status", "running")
    if cur_status == "running":
        rem = final_run.get("remaining_count", 0)
        final_status = "completed" if rem == 0 else "running"
        store.update_autonomous_run(
            run_id,
            {"status": final_status, "current_problem_id": ""},
            db_path=db_path,
        )

    return store.get_autonomous_run(run_id, db_path=db_path) or {}


# ============================================================================
# Run Controls (Start, Pause, Resume, Stop, Status)
# ============================================================================

def start_autonomous_run(
    max_problems: int = 5,
    max_attempts_per_problem: int = 5,
    difficulty: Optional[str] = None,
    api_request_budget: int = 100,
    api_delay_seconds: float = 0.0,
    llm_client: Any = None,
    db_path: Optional[str | Path] = None,
    run_in_background: bool = True,
) -> Dict[str, Any]:
    global _ACTIVE_WORKER_THREAD, _CURRENT_RUN_ID

    with _WORKER_LOCK:
        if is_worker_running():
            return {
                "error": "An autonomous run is already currently executing.",
                "run_id": _CURRENT_RUN_ID,
            }

        # Check if an interrupted or paused run exists to recover or start clean
        latest = store.get_latest_autonomous_run(db_path=db_path)
        if latest and latest.get("status") in ["running", "interrupted"]:
            # Mark previous interrupted run as interrupted
            store.update_autonomous_run(latest["run_id"], {"status": "interrupted"}, db_path=db_path)

        def worker_target():
            global _CURRENT_RUN_ID
            try:
                run_autonomous_queue(
                    max_problems=max_problems,
                    max_attempts_per_problem=max_attempts_per_problem,
                    difficulty=difficulty,
                    api_request_budget=api_request_budget,
                    api_delay_seconds=api_delay_seconds,
                    llm_client=llm_client,
                    db_path=db_path,
                )
            finally:
                pass

        if run_in_background:
            _ACTIVE_WORKER_THREAD = threading.Thread(target=worker_target, daemon=True)
            _ACTIVE_WORKER_THREAD.start()
            # Give short moment for run entry creation
            time.sleep(0.15)
            latest = store.get_latest_autonomous_run(db_path=db_path) or {}
            return {
                "status": "started",
                "run_id": latest.get("run_id", "active_run"),
                "total_problems": latest.get("total_problems", max_problems),
                "message": "Autonomous batch solver started in background.",
            }
        else:
            return run_autonomous_queue(
                max_problems=max_problems,
                max_attempts_per_problem=max_attempts_per_problem,
                difficulty=difficulty,
                api_request_budget=api_request_budget,
                api_delay_seconds=api_delay_seconds,
                llm_client=llm_client,
                db_path=db_path,
            )


def get_run_status(
    run_id: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    store.init(db_path=db_path)
    if not run_id:
        target = store.get_latest_autonomous_run(db_path=db_path)
    else:
        target = store.get_autonomous_run(run_id, db_path=db_path)

    if not target:
        return {"status": "idle", "message": "No autonomous runs recorded yet."}

    target_id = target["run_id"]
    queue = store.get_autonomous_queue_items(target_id, db_path=db_path)

    # Check live thread state
    is_live = is_worker_running() and (_CURRENT_RUN_ID == target_id)
    reported_status = target.get("status", "unknown")
    if not is_live and reported_status == "running":
        # System restarted or process terminated: marked interrupted
        reported_status = "interrupted"

    return {
        "run_id": target_id,
        "status": reported_status,
        "is_active_thread": is_live,
        "current_problem": target.get("current_problem_id", ""),
        "current_attempt": target.get("current_attempt", 0),
        "completed_count": target.get("completed_count", 0),
        "remaining_count": target.get("remaining_count", 0),
        "total_problems": target.get("total_problems", 0),
        "locally_verified": target.get("verified_count", 0),
        "failed": target.get("failed_count", 0),
        "api_calls": target.get("api_calls_count", 0),
        "api_errors": target.get("api_errors_count", 0),
        "started_at": target.get("started_at", ""),
        "updated_at": target.get("updated_at", ""),
        "queue": queue,
    }


def pause_autonomous_run(
    run_id: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    global _PAUSE_REQUESTED
    with _WORKER_LOCK:
        latest = store.get_autonomous_run(run_id, db_path=db_path) if run_id else store.get_latest_autonomous_run(db_path=db_path)
        if not latest:
            return {"error": "No active or recorded run found to pause."}

        target_id = latest["run_id"]
        _PAUSE_REQUESTED.set()
        store.update_autonomous_run(target_id, {"status": "paused"}, db_path=db_path)

        return {
            "status": "pause_requested",
            "run_id": target_id,
            "message": "Pause signal sent. The worker will safely pause after completing or finishing the current problem attempt.",
        }


def resume_autonomous_run(
    run_id: Optional[str] = None,
    llm_client: Any = None,
    db_path: Optional[str | Path] = None,
    run_in_background: bool = True,
) -> Dict[str, Any]:
    global _ACTIVE_WORKER_THREAD, _CURRENT_RUN_ID, _PAUSE_REQUESTED

    with _WORKER_LOCK:
        if is_worker_running():
            return {
                "error": "An autonomous run is already currently executing.",
                "run_id": _CURRENT_RUN_ID,
            }

        target = store.get_autonomous_run(run_id, db_path=db_path) if run_id else store.get_latest_autonomous_run(db_path=db_path)
        if not target:
            return {"error": "No recorded run found to resume."}

        target_id = target["run_id"]
        # Allow resuming if status is paused, interrupted, or running (e.g. recovering process restart)
        _PAUSE_REQUESTED.clear()
        _STOP_REQUESTED.clear()

        def resume_worker():
            run_autonomous_queue(
                max_problems=target.get("total_problems", 5),
                max_attempts_per_problem=target.get("max_attempts", 5),
                llm_client=llm_client,
                db_path=db_path,
                run_id=target_id,
            )

        if run_in_background:
            _ACTIVE_WORKER_THREAD = threading.Thread(target=resume_worker, daemon=True)
            _ACTIVE_WORKER_THREAD.start()
            return {
                "status": "resumed",
                "run_id": target_id,
                "message": f"Autonomous run '{target_id}' resumed in background from saved checkpoint.",
            }
        else:
            return run_autonomous_queue(
                max_problems=target.get("total_problems", 5),
                max_attempts_per_problem=target.get("max_attempts", 5),
                llm_client=llm_client,
                db_path=db_path,
                run_id=target_id,
            )


def stop_autonomous_run(
    run_id: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    global _STOP_REQUESTED
    with _WORKER_LOCK:
        latest = store.get_autonomous_run(run_id, db_path=db_path) if run_id else store.get_latest_autonomous_run(db_path=db_path)
        if not latest:
            return {"error": "No active or recorded run found to stop."}

        target_id = latest["run_id"]
        _STOP_REQUESTED.set()
        store.update_autonomous_run(target_id, {"status": "stopped"}, db_path=db_path)

        return {
            "status": "stop_requested",
            "run_id": target_id,
            "message": "Stop signal sent. Worker will terminate cleanly after the current step.",
        }
