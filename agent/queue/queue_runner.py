"""Autonomous Problem Queue Runner (Stage 18).

Orchestrates continuous, autonomous multi-problem solving:
SELECT NEXT -> LOAD -> SOLVE -> EXECUTE -> TEST -> DIAGNOSE -> REPAIR -> VERIFY -> PERSIST -> NEXT.

Preserves all Stage 1-17 verification gates, isolated error handling, bounded repairs,
idempotency, resumability, and structured aggregation.
"""

import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from agent.benchmarking.benchmark_registry import (
    BENCHMARK_REGISTRY,
    BenchmarkProblem,
    to_problem_spec,
)
from agent.benchmarking.multi_language_runner import (
    MULTI_LANG_CODE,
    INTENTIONAL_FLAWS,
)
from agent.core.models import (
    AgentState,
    AlgorithmPlan,
    ExecutionStatus,
    ProblemSpec,
    SupportedLanguage,
    VerificationStatus,
)
from agent.core.orchestrator import SelfCorrectionOrchestrator
from agent.planning.pattern_classifier import PatternClassifier
from agent.planning.planner import AlgorithmPlanner
from agent.queue.models import QueueItem, QueueItemStatus, QueueRunSummary
from agent.queue.store import SQLiteQueueStore
from agent.testing.engine import TestingEngine
from agent.verification.verifier import SolutionVerifier


from agent.config import Config
from agent.llm.base import BaseLLMProvider
from agent.llm.factory import get_llm_provider


class AutonomousQueueRunner:
    """Orchestrates autonomous, continuous problem solving across a queue of DSA problems."""

    def __init__(
        self,
        store: Optional[SQLiteQueueStore] = None,
        testing_engine: Optional[TestingEngine] = None,
        orchestrator: Optional[SelfCorrectionOrchestrator] = None,
        max_attempts_per_item: int = 3,
        allow_duplicates: bool = True,
        memory_service: Optional[Any] = None,
        llm_provider: Optional[BaseLLMProvider] = None,
    ):
        self.store = store or SQLiteQueueStore()
        self.testing_engine = testing_engine or TestingEngine()

        # Initialize LLM provider if configured or passed
        if llm_provider is not None:
            self.llm = llm_provider
        elif Config.is_api_key_configured():
            try:
                self.llm = get_llm_provider()
            except Exception:
                self.llm = None
        else:
            self.llm = None

        self.planner = AlgorithmPlanner(llm_provider=self.llm)
        self.verifier = SolutionVerifier(testing_engine=self.testing_engine)
        self.memory_service = memory_service
        self.orchestrator = orchestrator or SelfCorrectionOrchestrator(
            planner=self.planner,
            testing_engine=self.testing_engine,
            memory_service=self.memory_service,
            max_attempts=max_attempts_per_item,
            llm_provider=self.llm,
        )
        self.max_attempts_per_item = max_attempts_per_item
        self.allow_duplicates = allow_duplicates


    # --- QUEUE MANAGEMENT ---
    def enqueue(
        self,
        problem_id: str,
        preferred_language: SupportedLanguage = SupportedLanguage.PYTHON,
        priority: int = 0,
        max_attempts: Optional[int] = None,
        initial_flawed_code: Optional[str] = None,
        custom_statement: Optional[str] = None,
        custom_title: Optional[str] = None,
        spec_json: Optional[str] = None,
        raw_problem: Optional[str] = None,
        problem_hash: Optional[str] = None,
    ) -> QueueItem:
        """Enqueues a new problem job. Honors deduplication policy."""
        # Deduplication check
        if not self.allow_duplicates:
            existing = self.store.list_items()
            for ex in existing:
                # Check either problem_id + language OR problem_hash
                if problem_hash and ex.problem_hash and ex.problem_hash == problem_hash:
                    if ex.status in (QueueItemStatus.PENDING, QueueItemStatus.RUNNING, QueueItemStatus.VERIFIED):
                        raise ValueError(f"Duplicate queue entry rejected for problem_hash: {problem_hash}")
                if ex.problem_id == problem_id and ex.preferred_language == preferred_language:
                    if ex.status in (QueueItemStatus.PENDING, QueueItemStatus.RUNNING, QueueItemStatus.VERIFIED):
                        raise ValueError(f"Duplicate queue entry rejected for problem_id: {problem_id}, language: {preferred_language.value}")

        title = custom_title or problem_id
        statement = custom_statement or ""
        category_name = None

        if problem_id in BENCHMARK_REGISTRY:
            bp = BENCHMARK_REGISTRY[problem_id]
            title = custom_title or bp.title
            statement = custom_statement or bp.statement
            category_name = bp.category.value

        item = QueueItem(
            queue_item_id=f"job_{uuid.uuid4().hex[:10]}",
            problem_id=problem_id,
            title=title,
            problem_statement=statement,
            preferred_language=preferred_language,
            priority=priority,
            status=QueueItemStatus.PENDING,
            max_attempts=max_attempts or self.max_attempts_per_item,
            initial_flawed_code=initial_flawed_code,
            category=category_name,
            spec_json=spec_json,
            raw_problem=raw_problem,
            problem_hash=problem_hash,
        )
        self.store.save_item(item)
        return item

    def run_queue(
        self,
        max_items_to_process: Optional[int] = None,
        use_priority: bool = True,
        stop_on_global_infrastructure_error: bool = True,
    ) -> QueueRunSummary:
        """Continuously processes pending items in the queue until completion or limit."""
        run_id = f"qrun_{uuid.uuid4().hex[:8]}"
        start_time = time.time()
        processed_count = 0
        summary = QueueRunSummary(queue_run_id=run_id)

        # Recover any previously interrupted items from a crash
        self.store.reset_in_progress_to_pending()

        while True:
            if max_items_to_process is not None and processed_count >= max_items_to_process:
                break

            item = self.store.get_next_pending(use_priority=use_priority)
            if not item:
                # No more pending items in queue
                break

            processed_count += 1
            old_status = item.status

            # Idempotency safety: if item was already terminal VERIFIED, skip re-solving
            if item.status == QueueItemStatus.VERIFIED:
                continue

            # 1. Transition PENDING -> RUNNING
            item.transition_to(QueueItemStatus.RUNNING)
            self.store.save_item(item)
            self.store.record_transition(item.queue_item_id, old_status, QueueItemStatus.RUNNING, item.started_at)

            # 2. Execute Autonomous Solver
            try:
                res_status, is_verified, attempts, passed_tests, total_tests, err_msg = self._process_item(item)

                item.attempt_count = attempts
                item.tests_passed = passed_tests
                item.tests_total = total_tests
                item.error_message = err_msg

                # 3. Transition to terminal or verifying status
                if res_status == QueueItemStatus.VERIFIED:
                    item.transition_to(QueueItemStatus.VERIFIED)
                    item.final_status = "VERIFIED"
                    item.verification_status = "VERIFIED"
                elif res_status == QueueItemStatus.MAX_ATTEMPTS_REACHED:
                    item.transition_to(QueueItemStatus.MAX_ATTEMPTS_REACHED)
                    item.final_status = "FAILED"
                    item.verification_status = "MAX_ATTEMPTS_REACHED"
                elif res_status == QueueItemStatus.INFRASTRUCTURE_ERROR:
                    item.transition_to(QueueItemStatus.INFRASTRUCTURE_ERROR)
                    item.final_status = "INFRASTRUCTURE_ERROR"
                    item.verification_status = "INFRASTRUCTURE_ERROR"
                else:
                    item.transition_to(QueueItemStatus.FAILED)
                    item.final_status = "FAILED"
                    item.verification_status = "FAILED"

            except Exception as e:
                item.transition_to(QueueItemStatus.INFRASTRUCTURE_ERROR)
                item.final_status = "INFRASTRUCTURE_ERROR"
                item.verification_status = "INFRASTRUCTURE_ERROR"
                item.error_message = str(e)

            # Persist terminal state
            self.store.save_item(item)
            self.store.record_transition(item.queue_item_id, QueueItemStatus.RUNNING, item.status, item.completed_at)

            # Check fatal infrastructure halt condition
            if item.status == QueueItemStatus.INFRASTRUCTURE_ERROR and stop_on_global_infrastructure_error:
                # If infrastructure is completely unavailable (e.g. fatal host failure), stop queue
                pass

        # Aggregate summary across all items in store
        all_items = self.store.list_items()
        summary.total_items = len(all_items)
        languages_set: Set[str] = set()
        categories_set: Set[str] = set()

        for it in all_items:
            languages_set.add(it.preferred_language.value)
            if it.category:
                categories_set.add(it.category)

            summary.total_attempts += it.attempt_count
            summary.total_tests += it.tests_total
            summary.total_tests_passed += it.tests_passed
            summary.total_tests_failed += max(0, it.tests_total - it.tests_passed)

            if it.status == QueueItemStatus.VERIFIED:
                summary.verified += 1
            elif it.status == QueueItemStatus.FAILED:
                summary.failed += 1
            elif it.status == QueueItemStatus.MAX_ATTEMPTS_REACHED:
                summary.max_attempts_reached += 1
            elif it.status == QueueItemStatus.INFRASTRUCTURE_ERROR:
                summary.infrastructure_errors += 1
            elif it.status == QueueItemStatus.PENDING:
                summary.pending += 1
            elif it.status == QueueItemStatus.RUNNING:
                summary.running += 1
            elif it.status == QueueItemStatus.CANCELLED:
                summary.cancelled += 1
            elif it.status == QueueItemStatus.SKIPPED:
                summary.skipped += 1

            summary.item_results.append({
                "queue_item_id": it.queue_item_id,
                "problem_id": it.problem_id,
                "title": it.title,
                "language": it.preferred_language.value,
                "status": it.status.value,
                "attempts": it.attempt_count,
                "tests_passed": it.tests_passed,
                "tests_total": it.tests_total,
                "error_message": it.error_message,
            })

        summary.languages_used = sorted(list(languages_set))
        summary.categories_used = sorted(list(categories_set))
        summary.execution_time_ms = (time.time() - start_time) * 1000.0
        return summary

    def _process_item(self, item: QueueItem) -> Tuple[QueueItemStatus, bool, int, int, int, Optional[str]]:
        """Invokes the autonomous solver for a single queue item without duplicating solver logic."""
        spec: Optional[ProblemSpec] = None

        if item.spec_json:
            try:
                spec = ProblemSpec.model_validate_json(item.spec_json)
            except Exception as e:
                return QueueItemStatus.FAILED, False, 1, 0, 0, f"Malformed spec_json: {e}"
        elif item.problem_id in BENCHMARK_REGISTRY:
            problem = BENCHMARK_REGISTRY[item.problem_id]
            spec = to_problem_spec(problem)
        else:
            return QueueItemStatus.FAILED, False, 1, 0, 0, f"Problem ID {item.problem_id} not registered and no spec_json provided."

        lang = item.preferred_language
        initial_code = item.initial_flawed_code
        if not initial_code:
            initial_code = MULTI_LANG_CODE.get(item.problem_id, {}).get(lang)
        if not initial_code and lang == SupportedLanguage.CPP and item.problem_id in BENCHMARK_REGISTRY:
            initial_code = BENCHMARK_REGISTRY[item.problem_id].canonical_cpp_code

        # If still no initial code, generate it adhering to the planned approach
        if not initial_code:
            try:
                plan = self.planner.plan(spec)
                gen_code = self.orchestrator.generator.generate(spec, plan, lang)
                initial_code = gen_code.source_code
            except Exception as e:
                return QueueItemStatus.FAILED, False, 1, 0, 0, f"Code generation failed: {e}"

        if not initial_code:
            return QueueItemStatus.FAILED, False, 1, 0, 0, f"No code implementation for {item.problem_id} in {lang.value}"

        # Solve via orchestrator (Stage 20: Store -> Retrieve -> Use -> Verify -> Learn)
        session = self.orchestrator.solve(
            problem=spec,
            language=lang,
            override_initial_code=initial_code,
            max_attempts=item.max_attempts,
        )
        attempts = session.total_attempts if session.total_attempts > 0 else 1
        if session.is_verified:
            item.result_reference = session.verified_code
            tests_passed = session.verification_report.tests_passed if session.verification_report else 0
            tests_total = session.verification_report.total_tests_run if session.verification_report else 0
            return QueueItemStatus.VERIFIED, True, attempts, tests_passed, tests_total, None
        elif session.final_state == AgentState.MAX_ATTEMPTS_REACHED:
            last_rep = session.attempt_history[-1] if session.attempt_history else None
            tests_passed = last_rep.tests_passed if last_rep else 0
            tests_total = (last_rep.tests_passed + last_rep.tests_failed) if last_rep else 0
            return QueueItemStatus.MAX_ATTEMPTS_REACHED, False, attempts, tests_passed, tests_total, session.error_summary
        elif session.final_state == AgentState.INFRASTRUCTURE_ERROR:
            return QueueItemStatus.INFRASTRUCTURE_ERROR, False, attempts, 0, 0, session.error_summary
        else:
            return QueueItemStatus.FAILED, False, attempts, 0, 0, session.error_summary




def create_stage18_benchmark_queue(runner: AutonomousQueueRunner) -> List[QueueItem]:
    """Populates the 10-problem Stage 18 benchmark queue covering all 4 languages and >= 9 DSA categories."""
    runner.store.clear()

    # 10 canonical problems:
    # 1. two-sum -> C++
    # 2. valid-palindrome -> C
    # 3. binary-search -> Python
    # 4. valid-parentheses -> Java
    # 5. max-subarray -> C++
    # 6. reverse-linked-list -> Python
    # 7. maximum-depth-of-binary-tree -> Java (flawed start -> MAX_ATTEMPTS_REACHED test scenario)
    # 8. best-time-to-buy-and-sell-stock -> C
    # 9. climbing-stairs -> Python
    # 10. valid-anagram -> C

    # Items with intentional initial flaws:
    # - binary-search in C: boundary failure repaired
    # - valid-parentheses in C++: syntax failure repaired
    # - two-sum in Python: wrong answer repaired
    # - maximum-depth-of-binary-tree in Java: unfixable flaw -> MAX_ATTEMPTS_REACHED

    bs_flaw, _ = INTENTIONAL_FLAWS[("binary-search", SupportedLanguage.C)]
    vp_flaw, _ = INTENTIONAL_FLAWS[("valid-parentheses", SupportedLanguage.CPP)]
    ts_flaw, _ = INTENTIONAL_FLAWS[("two-sum", SupportedLanguage.PYTHON)]

    unfixable_java_flaw = """class Solution {
    public int maxDepth(int[] nodes) {
        // Unfixable dummy loop that always returns -999 and cannot be repaired
        return -999;
    }
}
"""

    items = [
        runner.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.CPP, priority=10),
        runner.enqueue(problem_id="valid-palindrome", preferred_language=SupportedLanguage.C, priority=9),
        runner.enqueue(problem_id="binary-search", preferred_language=SupportedLanguage.C, priority=8, initial_flawed_code=bs_flaw),
        runner.enqueue(problem_id="valid-parentheses", preferred_language=SupportedLanguage.CPP, priority=7, initial_flawed_code=vp_flaw),
        runner.enqueue(problem_id="max-subarray", preferred_language=SupportedLanguage.CPP, priority=6),
        runner.enqueue(problem_id="two-sum", preferred_language=SupportedLanguage.PYTHON, priority=5, initial_flawed_code=ts_flaw),
        runner.enqueue(problem_id="reverse-linked-list", preferred_language=SupportedLanguage.PYTHON, priority=4),
        runner.enqueue(problem_id="climbing-stairs", preferred_language=SupportedLanguage.JAVA, priority=3),
        runner.enqueue(problem_id="best-time-to-buy-and-sell-stock", preferred_language=SupportedLanguage.C, priority=2),
        runner.enqueue(problem_id="valid-anagram", preferred_language=SupportedLanguage.C, priority=1),
        # 11th item: Deterministic MAX_ATTEMPTS_REACHED benchmark scenario
        runner.enqueue(problem_id="maximum-depth-of-binary-tree", preferred_language=SupportedLanguage.JAVA, priority=0, initial_flawed_code=unfixable_java_flaw),
    ]
    return items


if __name__ == "__main__":
    runner = AutonomousQueueRunner()
    print("=" * 100)
    print("STAGE 18: AUTONOMOUS PROBLEM QUEUE / CONTINUOUS MULTI-PROBLEM SOLVING")
    print("Populating 10+ Problem Benchmark Queue across C, C++, Java, and Python...")
    create_stage18_benchmark_queue(runner)

    print(f"Total Enqueued Items: {len(runner.store.list_items())}")
    print("Starting Autonomous Continuous Queue Execution...")
    print("=" * 100)

    summary = runner.run_queue(use_priority=True)

    print("\nQUEUE RUN COMPLETE")
    print("=" * 115)
    print(f"{'Job ID':<16} | {'Problem':<26} | {'Lang':<7} | {'Prio':<5} | {'Tests':<8} | {'Attempts':<9} | {'Final Status'}")
    print("=" * 115)
    for res in summary.item_results:
        test_str = f"{res['tests_passed']}/{res['tests_total']}"
        print(f"{res['queue_item_id']:<16} | {res['problem_id']:<26} | {res['language']:<7} | {'-':<5} | {test_str:<8} | {res['attempts']:<9} | {res['status']}")

    print("=" * 115)
    print(f"SUMMARY:")
    print(f"  Total Items:              {summary.total_items}")
    print(f"  Verified:                 {summary.verified}")
    print(f"  Failed:                   {summary.failed}")
    print(f"  Max Attempts Reached:     {summary.max_attempts_reached}")
    print(f"  Infrastructure Errors:    {summary.infrastructure_errors}")
    print(f"  Total Attempts:           {summary.total_attempts}")
    print(f"  Total Tests Passed/Total: {summary.total_tests_passed}/{summary.total_tests}")
    print(f"  Languages Used:           {', '.join(summary.languages_used)}")
    print(f"  Categories Covered:       {', '.join(summary.categories_used)}")
    print(f"  Execution Time:           {summary.execution_time_ms / 1000.0:.2f}s")
    print("=" * 115)
