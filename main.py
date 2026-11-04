import argparse
import sys
from typing import Optional

import autonomous
from judge import run_solution
from llm import LLMClient, LLMError, MockLLM
import memory
from problems import get_problems, load_problems
from prompts import SYSTEM_PROMPT, build_initial_prompt, build_retry_prompt, extract_code
import store


def print_summary(problems_list):
    stats = store.summary(problems=problems_list)
    print("\n" + "=" * 50)
    print("PROGRESS SUMMARY")
    print("=" * 50)
    print(f"Solved: {stats['solved']}")
    print(f"Failed: {stats['failed']}")
    print(f"Total Processed: {stats['total_attempted']}")
    print(f"Average Attempts for Solved: {stats['avg_attempts_solved']}")
    print("\nBy Difficulty:")
    for diff, data in stats["by_difficulty"].items():
        print(f"  {diff.capitalize()}: {data['solved']} solved / {data['failed']} failed (out of {data['total']} total)")
    print("=" * 50 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Autonomous LeetCode-Solving Agent")
    parser.add_argument("--autonomous", action="store_true", help="Launch autonomous batch queue solver")
    parser.add_argument("--max-problems", type=int, default=5, help="Maximum problems to process in autonomous queue (default: 5)")
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard"], help="Filter problems by difficulty")
    parser.add_argument("--max-attempts", type=int, default=5, help="Maximum attempts per problem (default: 5)")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of problems to process (legacy single run)")
    parser.add_argument("--budget", type=int, default=100, help="Maximum API request budget (default: 100)")
    parser.add_argument("--mock", action="store_true", help="Use MockLLM instead of real LLM API")
    parser.add_argument("--reset", action="store_true", help="Reset saved progress database before starting")

    args = parser.parse_args()

    # 1. Initialize SQLite database
    store.init()
    memory.seed_default_learning()
    if args.reset:
        store.reset()
        print("Progress database reset successfully.")

    # 2. Autonomous batch solver mode
    if args.autonomous:
        print(f"=== Starting Autonomous Batch Solver 4.0 ===")
        print(f"Max Problems: {args.max_problems} | Max Attempts: {args.max_attempts} | Difficulty Filter: {args.difficulty or 'all'}")

        # Choose LLM Client
        if args.mock:
            all_probs = load_problems()
            custom_probs = store.list_custom_problems()
            combined = list(all_probs)
            for cp in custom_probs:
                if not any(x["id"] == cp["id"] for x in combined):
                    combined.append(cp)
            client = MockLLM(problems=combined)
        else:
            try:
                client = LLMClient()
            except LLMError as e:
                print(f"LLM Configuration Error: {e}", file=sys.stderr)
                sys.exit(1)

        result = autonomous.run_autonomous_queue(
            max_problems=args.max_problems,
            max_attempts_per_problem=args.max_attempts,
            difficulty=args.difficulty,
            api_request_budget=args.budget,
            llm_client=client,
        )
        print(f"\nAutonomous Batch Run Finished: {result.get('status')}")
        print(f"Run ID: {result.get('run_id')}")
        print(f"Completed: {result.get('completed_count')} / {result.get('total_problems')}")
        print(f"Locally Verified: {result.get('verified_count')} | Failed: {result.get('failed_count')}")
        return

    # 2. Load all problems for reference & summary
    try:
        all_problems = load_problems()
    except Exception as e:
        print(f"Error loading problems: {e}", file=sys.stderr)
        sys.exit(1)

    # 3. Apply difficulty and limit filters
    try:
        problems_to_run = get_problems(difficulty=args.difficulty)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.limit is not None and args.limit > 0:
        problems_to_run = problems_to_run[:args.limit]

    # Instantiate LLM
    if args.mock:
        client = MockLLM(problems=all_problems)
    else:
        try:
            client = LLMClient()
        except LLMError as e:
            print(f"LLM Configuration Error: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"Loaded {len(problems_to_run)} problems to evaluate. Max attempts per problem: {args.max_attempts}")

    try:
        for idx, problem in enumerate(problems_to_run, 1):
            prob_id = problem["id"]
            title = problem["title"]
            diff = problem["difficulty"].capitalize()

            # 4. Skip already-solved problems
            if store.is_solved(prob_id):
                print(f"[{idx}/{len(problems_to_run)}] Skipping {title} ({diff}) - Already solved.")
                continue

            print(f"\n[{idx}/{len(problems_to_run)}] Problem: {title} ({diff})")

            passed = False
            last_code = ""
            last_judge_res = {}

            for attempt_no in range(1, args.max_attempts + 1):
                # 5. Build prompt and ask LLM
                if attempt_no == 1:
                    user_prompt = build_initial_prompt(problem)
                else:
                    user_prompt = build_retry_prompt(
                        problem=problem,
                        previous_code=last_code,
                        judge_status=last_judge_res.get("status", "error"),
                        failure_details=last_judge_res.get("failure"),
                        error_trace=last_judge_res.get("error"),
                    )

                response_text = client.ask(SYSTEM_PROMPT, user_prompt)

                # 6. Extract code
                code = extract_code(response_text)
                last_code = code

                # 7. Run code through judge
                judge_res = run_solution(code, problem)
                last_judge_res = judge_res
                status = judge_res["status"]
                passed_tests = judge_res["passed_count"]
                total_tests = judge_res["total"]
                err_text = judge_res.get("error")

                # 8. Log attempt
                store.log_attempt(
                    problem_id=prob_id,
                    attempt_no=attempt_no,
                    code=code,
                    status=status,
                    error=err_text,
                )

                # 9. Print one readable line per attempt
                details = f"tests passed: {passed_tests}/{total_tests}"
                if status != "passed" and err_text:
                    preview = err_text.strip().split("\n")[-1]
                    details += f" | {preview[:60]}"
                print(f"  Attempt {attempt_no}/{args.max_attempts}: {status.upper()} ({details})")

                # 10. Check if passed
                if status == "passed":
                    passed = True
                    store.mark_result(prob_id, "solved", attempt_no)
                    print(f"  >>> Solved '{title}' in {attempt_no} attempt(s)!")
                    break

            # 11. Check if exhausted
            if not passed:
                store.mark_result(prob_id, "failed", args.max_attempts)
                print(f"  >>> Failed '{title}' after {args.max_attempts} attempt(s).")

    except LLMError as e:
        # 12. If LLMError occurs, stop cleanly and preserve saved progress
        print(f"\n[Error] LLM request failed: {e}", file=sys.stderr)
        print("Progress preserved.")
    except KeyboardInterrupt:
        # 13. Handle Ctrl+C gracefully
        print("\n\nExecution interrupted by user.")
    finally:
        # 14. Display final summary
        print_summary(all_problems)


if __name__ == "__main__":
    main()
