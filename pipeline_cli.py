"""Dedicated CLI Entrypoint & Offline Demonstration for AutonomousPipeline.

Milestone 6.3.2: CLI Integration & Offline End-to-End Demonstration.
Provides a clear command-line interface to run the modular AutonomousPipeline
either in full offline demonstration mode or against custom problem queues
using an isolated database by default to guarantee zero production data impact
and zero external API / network requests.
"""

import argparse
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

# Ensure project root is available
ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import memory
from pipeline import AutonomousPipeline, MockSolutionGenerator, PipelineStage, ProblemExecutionResult
from problems import load_problems
import store


def run_offline_demo(
    db_path: Optional[str | Path] = None,
    language: str = "python",
    max_attempts: int = 3,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Execute a reproducible, deterministic 2-problem offline demonstration.

    Problem 1: Simulated wrong answer on Attempt 1 followed by passing correction on Attempt 2.
    Problem 2: Immediate passing solution on Attempt 1.

    Guarantees:
    - Zero live API calls (deterministic scripted mock solutions clearly labeled as demonstrations).
    - Isolated database (production progress.db is never touched).
    - Uses existing local UnifiedJudge subprocess execution.
    """
    is_temp_db = False
    temp_dir = None
    if db_path is None:
        temp_dir = tempfile.mkdtemp(prefix="pipeline_demo_")
        db_file = Path(temp_dir) / "demo_pipeline.db"
        is_temp_db = True
    else:
        db_file = Path(db_path)

    if verbose:
        print("=" * 72)
        print("  AUTONOMOUS PIPELINE - OFFLINE END-TO-END DEMONSTRATION")
        print("=" * 72)
        print(f"  Mode:               100% Offline (Scripted Demonstration)")
        print(f"  Language:           {language}")
        print(f"  Database:           {db_file} {'(Isolated Temporary)' if is_temp_db else ''}")
        print(f"  Live API Calls:     0 (Guaranteed Offline)")
        print(f"  Max Attempts:       {max_attempts}")
        print("=" * 72)

    # 1. Initialize isolated demo database and DSA pattern memory
    store.init(db_path=db_file)
    memory.seed_default_learning(db_path=db_file)

    # 2. Define demonstration problems
    # Problem 1: Two Sum (demonstrating correction cycle)
    demo_p1 = {
        "id": "demo-two-sum",
        "title": "Two Sum (Correction Cycle Demo)",
        "difficulty": "Easy",
        "description": "Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target.",
        "function_name": "twoSum",
        "signature": "def twoSum(nums: List[int], target: int) -> List[int]:",
        "tests": [
            {"input": [[2, 7, 11, 15], 9], "expected": [0, 1]},
            {"input": [[3, 2, 4], 6], "expected": [1, 2]},
            {"input": [[3, 3], 6], "expected": [0, 1]},
        ],
    }

    # Problem 2: Valid Palindrome (demonstrating immediate passing solution)
    demo_p2 = {
        "id": "demo-valid-palindrome",
        "title": "Valid Palindrome (Immediate Success Demo)",
        "difficulty": "Easy",
        "description": "Given a string s, return true if it is a palindrome, or false otherwise.",
        "function_name": "isPalindrome",
        "signature": "def isPalindrome(s: str) -> bool:",
        "tests": [
            {"input": ["A man, a plan, a canal: Panama"], "expected": True},
            {"input": ["race a car"], "expected": False},
            {"input": [" "], "expected": True},
        ],
    }

    # Register demonstration problems in the demo database
    for p in [demo_p1, demo_p2]:
        store.save_custom_problem(
            problem_id=p["id"],
            url="offline://demo/" + p["id"],
            title=p["title"],
            difficulty=p["difficulty"],
            description=p["description"],
            function_name=p["function_name"],
            signature=p["signature"],
            tests=p["tests"],
            db_path=db_file,
        )

    # 3. Configure deterministic scripted mock responses
    # Explicitly labeled as scripted demonstration code
    scripts = {
        "demo-two-sum": [
            # Attempt 1: Deliberately flawed implementation returning incorrect indices
            (
                "# [DEMO SCRIPTED CANDIDATE - ATTEMPT 1: INTENTIONAL WRONG ANSWER]\n"
                "def twoSum(nums, target):\n"
                "    return [0, 0]  # Flawed: repeats index\n"
            ),
            # Attempt 2: Correct hash map solution demonstrating post-failure repair
            (
                "# [DEMO SCRIPTED CANDIDATE - ATTEMPT 2: CORRECTED PASSING SOLUTION]\n"
                "def twoSum(nums, target):\n"
                "    seen = {}\n"
                "    for idx, num in enumerate(nums):\n"
                "        diff = target - num\n"
                "        if diff in seen:\n"
                "            return [seen[diff], idx]\n"
                "        seen[num] = idx\n"
                "    return []\n"
            ),
        ],
        "demo-valid-palindrome": [
            # Attempt 1: Immediate clean, passing solution
            (
                "# [DEMO SCRIPTED CANDIDATE - ATTEMPT 1: IMMEDIATE PASSING SOLUTION]\n"
                "def isPalindrome(s):\n"
                "    filtered = [ch.lower() for ch in str(s) if ch.isalnum()]\n"
                "    return filtered == filtered[::-1]\n"
            )
        ],
    }

    mock_generator = MockSolutionGenerator(scripts=scripts)

    # Stage change reporter for clean CLI output
    def on_stage_change(stage: PipelineStage, data: Dict[str, Any]):
        if not verbose:
            return
        stage_name = stage.value.upper()
        if stage == PipelineStage.GENERATING:
            print(f"    -> [Attempt {data.get('attempt')}] Generating candidate solution...")
        elif stage == PipelineStage.EXECUTING:
            print(f"    -> [Attempt {data.get('attempt')}] Executing candidate in local judge...")
        elif stage == PipelineStage.DIAGNOSING:
            fail_cat = data.get("failure_category")
            cat_name = fail_cat.value if hasattr(fail_cat, "value") else str(fail_cat)
            print(f"    -> [Diagnose] Judge verdict: {data.get('status')} | Category: {cat_name}")
        elif stage == PipelineStage.CORRECTING:
            print(f"    -> [Attempt {data.get('attempt')}] Assembling repair prompt with failure trace...")
        elif stage == PipelineStage.COMPLETED:
            print(f"    -> [Verified] All tests passed! Problem marked solved locally.")

    pipeline = AutonomousPipeline(
        generator=mock_generator,
        db_path=db_file,
        language=language,
        max_attempts=max_attempts,
        on_stage_change=on_stage_change,
    )

    start_wall = time.time()
    results = pipeline.run_queue(problem_ids=[demo_p1["id"], demo_p2["id"]], skip_solved=False)
    elapsed_total = time.time() - start_wall

    if verbose:
        print("\n" + "=" * 72)
        print("  DEMONSTRATION RESULTS & PIPELINE SUMMARY")
        print("=" * 72)
        for r in results:
            status_tag = "[PASSED]" if r.passed else "[FAILED]"
            print(f"  {status_tag:<9} {r.problem_id:<24} Attempts: {r.attempts_used}/{r.max_attempts}  "
                  f"Verdict: {r.final_verdict}  Tests: {r.tests_passed}/{r.total_tests} ({r.elapsed_seconds:.2f}s)")
            for h in r.history:
                cat = h.get("failure_category", "none")
                print(f"            Attempt {h['attempt_no']}: status={h['status']}, category={cat}")

        print("-" * 72)
        total_p = len(results)
        solved_p = sum(1 for r in results if r.passed)
        print(f"  Summary:            {solved_p}/{total_p} problems solved locally ({solved_p/total_p*100:.0f}%)")
        print(f"  Total Attempts:     {sum(r.attempts_used for r in results)}")
        print(f"  Network Requests:   0 (Offline deterministic execution)")
        print(f"  API Cost / Budget:  $0.00 / 0 calls")
        print(f"  Total Elapsed Time: {elapsed_total:.2f}s")
        print("=" * 72 + "\n")

    return {
        "success": all(r.passed for r in results),
        "total_problems": len(results),
        "solved_problems": sum(1 for r in results if r.passed),
        "total_attempts": sum(r.attempts_used for r in results),
        "network_requests": 0,
        "api_calls_count": 0,
        "db_path": str(db_file),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="AutonomousPipeline CLI & Offline Demonstration (Milestone 6.3.2)"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run deterministic offline end-to-end demonstration (2 problems, correction cycle + immediate success)",
    )
    parser.add_argument(
        "--select",
        action="store_true",
        help="Display deterministic problem prioritization ranking using ProblemSelector",
    )
    parser.add_argument(
        "--topics",
        action="store_true",
        help="Display offline algorithm topic coverage, performance metrics, and learning opportunities",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include already solved problems in selection ranking (default: False)",
    )
    parser.add_argument(
        "--difficulty",
        choices=["easy", "medium", "hard"],
        default=None,
        help="Filter or prefer specific difficulty (default: None)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Custom SQLite database path for isolated demo/testing. Defaults to a temporary DB.",
    )
    parser.add_argument(
        "--language",
        choices=["python", "c", "cpp", "java"],
        default="python",
        help="Target programming language (default: python)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum correction attempts per problem (default: 3)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose pipeline progression logs",
    )

    args = parser.parse_args()

    if args.topics:
        from intelligence.topics import TopicAnalyzer
        from problems import load_problems
        analyzer = TopicAnalyzer(db_path=args.db_path, language=args.language)
        candidates = load_problems()
        metrics = analyzer.analyze_topics(candidates)

        print("=" * 80)
        print("  TOPIC-AWARE LEARNING INTELLIGENCE - OFFLINE PERFORMANCE ANALYSIS")
        print("=" * 80)
        print(f"  Target Language: {args.language}")
        print(f"  Database Path:   {args.db_path or 'Default progress.db'}")
        print("-" * 80)
        print(f"{'TOPIC':<22} {'TOTAL':<7} {'SOLVED':<8} {'ATTEMPTS':<10} {'MASTERY STATUS':<16} {'SUMMARY'}")
        print("-" * 80)
        for topic, m in sorted(metrics.items(), key=lambda x: (-x[1].unsolved_problems, x[0])):
            print(f"{m.topic:<22} {m.total_problems:<7} {m.solved_problems:<8} {m.total_attempts:<10} {m.mastery_status:<16} {m.summary}")

        print("=" * 80)
        # Recommendation insight
        weak_topics = [t for t, m in metrics.items() if m.mastery_status == "needs_practice"]
        untouched = [t for t, m in metrics.items() if m.mastery_status == "no_history"]
        if weak_topics:
            print(f"  Recommendations: Prioritize weak topics: {', '.join(weak_topics)}")
        elif untouched:
            print(f"  Recommendations: Expand topic coverage by practicing: {', '.join(untouched[:3])}")
        else:
            print("  Recommendations: All covered topics are proficient or mastered.")
        print("=" * 80 + "\n")
        sys.exit(0)

    if args.select:
        from intelligence.selector import ProblemSelector
        from problems import load_problems
        selector = ProblemSelector(
            db_path=args.db_path,
            language=args.language,
            preferred_difficulty=args.difficulty,
        )
        candidates = load_problems()
        prioritized = selector.prioritize_candidates(candidates, skip_solved=not args.all)
        print("=" * 80)
        print("  INTELLIGENT PROBLEM SELECTION ENGINE - DETERMINISTIC RANKING")
        print("=" * 80)
        print(f"{'RANK':<5} {'ID':<30} {'DIFF':<8} {'SCORE':<7} {'RATIONALE'}")
        print("-" * 80)
        if not prioritized:
            print("  (No eligible uncompleted problems found. Use --all to view ranking of all problems.)")
        for idx, (p, b) in enumerate(prioritized, 1):
            print(f"{idx:<5} {b.problem_id:<30} {b.difficulty:<8} {b.total_score:<7.1f} {b.rationale}")
        print("=" * 80)
        sys.exit(0)

    if args.demo or len(sys.argv) == 1:
        # Default behavior: run deterministic offline demonstration
        res = run_offline_demo(
            db_path=args.db_path,
            language=args.language,
            max_attempts=args.max_attempts,
            verbose=not args.quiet,
        )
        sys.exit(0 if res["success"] else 1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
