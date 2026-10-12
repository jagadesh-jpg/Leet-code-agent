"""Single-Problem Autonomous Solving CLI (Stage 19 / Stage 31 / Stage 32).

Usage:
  python -m agent.solve <file_path> [--language <c|cpp|java|python>]
  python -m agent.solve --text "<raw_problem_statement>" [--language <c|cpp|java|python>]
  python -m agent.solve --input <json_or_md_file> [--language <c|cpp|java|python>]
  python -m agent.solve --leetcode <title_slug> [--language <c|cpp|java|python>] [--dry-run]
  python -m agent.solve --leetcode <title_slug> --live-submission --confirm-live-submission
"""

import argparse
import json
import sys
from pathlib import Path

from agent.intake.service import ProblemIntakeService
from agent.leetcode.service import LeetCodeWorkflowService


def main():
    parser = argparse.ArgumentParser(description="Autonomous DSA Dynamic Intake & LeetCode Solver")
    parser.add_argument("file", nargs="?", default=None, help="Path to Markdown or JSON problem file")
    parser.add_argument("--input", dest="input_file", default=None, help="Path to problem file")
    parser.add_argument("--text", dest="raw_text", default=None, help="Raw problem statement text or Markdown")
    parser.add_argument("--leetcode", dest="leetcode_slug", default=None, help="LeetCode problem title slug (e.g. two-sum)")
    parser.add_argument("--language", "-l", dest="language", default=None, help="Target language (c, cpp, java, python)")
    parser.add_argument("--max-attempts", type=int, default=3, help="Maximum repair attempts")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True, help="Validate submission payload locally without sending network requests (default: True)")
    parser.add_argument("--live-submission", dest="live_submission", action="store_true", default=False, help="Perform external submission to LeetCode (requires --confirm-live-submission)")
    parser.add_argument("--confirm-live-submission", dest="confirm_live_submission", action="store_true", default=False, help="Explicit confirmation required to send live submission to LeetCode")

    args = parser.parse_args()

    if args.leetcode_slug:
        lc_service = LeetCodeWorkflowService()
        is_live = bool(args.live_submission)
        is_confirmed = bool(args.confirm_live_submission)

        result = lc_service.solve_leetcode_problem(
            title_slug=args.leetcode_slug,
            preferred_language=args.language,
            max_attempts=args.max_attempts,
            prepare_submission=True,
            live_submission=is_live,
            confirmed=is_confirmed,
        )

        # Print structured summary report
        print("=" * 60)
        print("STAGE 32 LEETCODE EXECUTION REPORT")
        print("=" * 60)
        print(f"Problem Slug:          {result.leetcode_title_slug or result.problem_id}")
        print(f"Language:              {result.language}")
        print(f"Code Hash:             {result.code_hash or 'None'}")
        print(f"Local Verified:        {result.is_verified} (status: {result.status})")
        print(f"Request Sent:          {result.request_sent}")
        print(f"Submission ID:         {result.submission_id or 'None'}")
        print(f"Judge Verdict:         {result.judge_verdict or 'N/A'}")
        if result.judge_runtime:
            print(f"Judge Runtime:         {result.judge_runtime}")
        if result.judge_memory:
            print(f"Judge Memory:          {result.judge_memory}")
        print(f"Status Note:           {result.submission_prep_status or 'N/A'}")
        print("=" * 60)
        print(json.dumps(result.model_dump(), indent=2))
    else:
        content = None
        target_file = args.input_file or args.file
        if target_file:
            p = Path(target_file)
            if not p.exists():
                print(f"Error: Problem file '{target_file}' not found.", file=sys.stderr)
                sys.exit(1)
            content = p.read_text(encoding="utf-8")
        elif args.raw_text:
            content = args.raw_text
        else:
            parser.print_help()
            sys.exit(1)

        intake_svc = ProblemIntakeService()
        result = intake_svc.solve_dynamically(
            raw_input=content,
            preferred_language=args.language,
            max_attempts=args.max_attempts,
        )
        print(json.dumps(result.model_dump(), indent=2))

    if result.status == "VERIFIED":
        sys.exit(0)
    elif result.status == "MAX_ATTEMPTS_REACHED":
        sys.exit(2)
    elif result.status == "INFRASTRUCTURE_ERROR":
        sys.exit(3)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
