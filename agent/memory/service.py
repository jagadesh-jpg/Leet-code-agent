"""
Memory Service.
Orchestrates high-level persistent memory interactions for the autonomous DSA agent.
Enforces:
1. Memory is contextual guidance, NEVER a substitute for execution or verification.
2. Verified solutions are ONLY saved when actually certified as VERIFIED.
3. Historical failures and repairs are indexed for learning.
4. Bounded, structured retrieval that does not overflow context.
"""

import hashlib
import uuid
from typing import List, Optional

from agent.core.models import (
    AlgorithmPlan,
    DSAPattern,
    FailureCategory,
    FailureReport,
    FinalVerificationReport,
    ProblemSpec,
    RepairAttempt,
    SelfCorrectionSession,
    SupportedLanguage,
    VerificationStatus,
)
from agent.memory.models import (
    ExperienceRecord,
    ExperienceRecommendation,
    FailureMemoryRecord,
    MemoryRetrievalReport,
    PatternKnowledgeRecord,
    ProblemMemoryRecord,
    RepairMemoryRecord,
    RetrievedProblemContext,
    SolutionMemoryRecord,
)
from agent.memory.repository import BaseMemoryStore
from agent.memory.sqlite_store import SQLiteMemoryStore


class MemoryService:
    """
    High-level memory operations service consumed by the Orchestrator and Planning layers.
    """

    def __init__(self, store: Optional[BaseMemoryStore] = None):
        self.store = store or SQLiteMemoryStore()

    @staticmethod
    def compute_source_hash(source_code: str) -> str:
        """Computes deterministic SHA-256 hex digest for candidate source code."""
        return hashlib.sha256(source_code.encode("utf-8")).hexdigest()[:16]

    # --- PROBLEM CONTEXT RETRIEVAL ---
    def retrieve_context_for_problem(
        self,
        problem: ProblemSpec,
        limit_solutions: int = 3,
        limit_failures: int = 5,
        limit_repairs: int = 5,
    ) -> RetrievedProblemContext:
        """
        Retrieves bounded historical context prior to problem-solving.
        Includes previous verified solutions, recent failure causes, and successful repairs.
        """
        prob_rec = self.store.get_problem(problem.id)
        verified_sols = self.store.get_solutions_for_problem(
            problem_id=problem.id,
            only_verified=True,
            limit=limit_solutions,
        )
        recent_failures = self.store.get_failures_for_problem(
            problem_id=problem.id,
            limit=limit_failures,
        )
        repairs = self.store.get_repairs_for_problem(
            problem_id=problem.id,
            limit=limit_repairs,
        )

        pattern_notes: List[PatternKnowledgeRecord] = []
        for p in getattr(prob_rec, "detected_patterns", []):
            pk = self.store.get_pattern_knowledge(p)
            if pk:
                pattern_notes.append(pk)

        return RetrievedProblemContext(
            problem=prob_rec,
            verified_solutions=verified_sols,
            recent_failures=recent_failures,
            successful_repairs=repairs,
            pattern_notes=pattern_notes,
        )

    # --- PROBLEM PERSISTENCE ---
    def record_problem(
        self,
        problem: ProblemSpec,
        detected_patterns: Optional[List[DSAPattern]] = None,
    ) -> ProblemMemoryRecord:
        """Persists or updates normalized problem specification."""
        patterns = detected_patterns or []
        record = ProblemMemoryRecord(
            problem_id=problem.id,
            title=problem.title,
            description=problem.description,
            difficulty=problem.difficulty,
            function_name=problem.function_name,
            param_names=problem.param_names,
            return_type=problem.return_type,
            constraints=problem.constraints,
            detected_patterns=patterns,
            raw_statement=problem.raw_statement,
        )
        self.store.save_problem(record)
        return record

    # --- SOLUTION PERSISTENCE ---
    def record_solution(
        self,
        problem: ProblemSpec,
        source_code: str,
        language: SupportedLanguage,
        verification_report: FinalVerificationReport,
        plan: Optional[AlgorithmPlan] = None,
    ) -> SolutionMemoryRecord:
        """
        Persists a candidate solution alongside its complete verification audit evidence.
        Enforces: ONLY records is_verified=True if verification_report.final_verification_status == VERIFIED.
        """
        # Ensure parent problem is persisted
        self.record_problem(problem, detected_patterns=plan.identified_patterns if plan else None)

        source_hash = self.compute_source_hash(source_code)
        solution_id = f"sol_{problem.id}_{source_hash}"

        is_verified = (verification_report.final_verification_status == VerificationStatus.VERIFIED)

        claimed_time = plan.selected_approach.time_complexity if plan else None
        claimed_space = plan.selected_approach.space_complexity if plan else None
        inferred_time = verification_report.complexity_audit.inferred_time_complexity
        inferred_space = verification_report.complexity_audit.inferred_space_complexity

        record = SolutionMemoryRecord(
            solution_id=solution_id,
            problem_id=problem.id,
            language=language,
            source_code=source_code,
            source_hash=source_hash,
            algorithm_name=plan.selected_approach.name if plan else None,
            data_structures_used=plan.selected_approach.data_structures if plan else [],
            claimed_time_complexity=claimed_time,
            claimed_space_complexity=claimed_space,
            inferred_time_complexity=inferred_time,
            inferred_space_complexity=inferred_space,
            verification_status=verification_report.final_verification_status,
            verification_report=verification_report,
            is_verified=is_verified,
        )
        self.store.save_solution(record)
        return record

    # --- FAILURE & REPAIR PERSISTENCE ---
    def record_failure(
        self,
        problem: ProblemSpec,
        attempt_number: int,
        language: SupportedLanguage,
        source_code: str,
        failure_report: FailureReport,
        repair_performed: Optional[str] = None,
        repair_succeeded: bool = False,
    ) -> FailureMemoryRecord:
        """Persists a failed attempt with structured root-cause diagnostic evidence."""
        self.record_problem(problem)

        source_hash = self.compute_source_hash(source_code)
        failure_id = f"fail_{problem.id}_{source_hash}_{attempt_number}"

        likely_cause = None
        if failure_report.ranked_hypotheses:
            likely_cause = failure_report.ranked_hypotheses[0].hypothesis

        record = FailureMemoryRecord(
            failure_id=failure_id,
            problem_id=problem.id,
            attempt_number=attempt_number,
            language=language,
            source_code=source_code,
            source_hash=source_hash,
            failure_category=failure_report.failure_category,
            likely_root_cause=likely_cause,
            error_message=failure_report.error_message,
            affected_test_ids=failure_report.affected_test_ids,
            raw_failure_report=failure_report,
            repair_performed=repair_performed,
            repair_succeeded=repair_succeeded,
        )
        self.store.save_failure(record)
        return record

    def record_repair(
        self,
        problem: ProblemSpec,
        language: SupportedLanguage,
        attempt: RepairAttempt,
        verification_status_after: VerificationStatus,
    ) -> RepairMemoryRecord:
        """Persists a successful repair cycle linking original failure to patch."""
        self.record_problem(problem)

        repair_id = f"rep_{uuid.uuid4().hex[:8]}"
        root_cause = "Unknown root cause"
        if attempt.failure_addressed.ranked_hypotheses:
            root_cause = attempt.failure_addressed.ranked_hypotheses[0].hypothesis
        elif attempt.failure_addressed.error_message:
            root_cause = attempt.failure_addressed.error_message

        record = RepairMemoryRecord(
            repair_id=repair_id,
            problem_id=problem.id,
            language=language,
            original_failure_category=attempt.failure_addressed.failure_category,
            root_cause=root_cause,
            source_hash_before=attempt.source_hash_before,
            source_code_before=attempt.source_code_before,
            source_hash_after=attempt.source_hash_after,
            source_code_after=attempt.source_code_after,
            patch_summary=attempt.patch_summary,
            tests_passed_after=attempt.tests_passed,
            tests_failed_after=attempt.tests_failed,
            verification_status_after=verification_status_after,
            regression_passed=(attempt.tests_failed == 0),
        )
        self.store.save_repair(record)
        return record

    # --- SESSION RECORDING ---
    def record_session_results(
        self,
        problem: ProblemSpec,
        session: SelfCorrectionSession,
    ) -> None:
        """
        Persists all artifacts produced during an autonomous self-correction session:
        - Problem record
        - Failure attempts
        - Successful repairs
        - Verified solution (if achieved)
        """
        self.record_problem(problem, detected_patterns=session.plan.identified_patterns if session.plan else None)

        # 1. Record each repair attempt
        for attempt in session.attempt_history:
            # Record failure
            repair_succeeded = (attempt.tests_failed == 0 and attempt.tests_passed > 0)
            self.record_failure(
                problem=problem,
                attempt_number=attempt.attempt_number,
                language=session.language,
                source_code=attempt.source_code_before,
                failure_report=attempt.failure_addressed,
                repair_performed=attempt.patch_summary,
                repair_succeeded=repair_succeeded,
            )

            if repair_succeeded:
                self.record_repair(
                    problem=problem,
                    language=session.language,
                    attempt=attempt,
                    verification_status_after=VerificationStatus.VERIFIED if session.is_verified else VerificationStatus.VERIFIED_WITH_WARNINGS,
                )

        # 2. Record solution with verification report
        if session.verified_code and session.verification_report:
            self.record_solution(
                problem=problem,
                source_code=session.verified_code,
                language=session.language,
                verification_report=session.verification_report,
                plan=session.plan,
            )

        # 3. Record Stage 20 structured experience
        self.learn_from_session(problem, session)

    # =================================================================
    # STAGE 20: PROBLEM FINGERPRINTING, RETRIEVAL, AND LEARNING METHODS
    # =================================================================

    @staticmethod
    def compute_problem_fingerprint(problem: ProblemSpec) -> str:
        """
        Creates a deterministic problem fingerprint based on structural features:
        - normalized tokens (sorted keywords)
        - parameter count and signature types
        - return type
        - constraint magnitude signatures
        Enforces: "Two Sum" and "Find two numbers whose sum equals target" have matching or close structural profiles.
        """
        import re
        # Tokenize statement into normalized keywords
        clean_text = re.sub(r"[^a-zA-Z0-9\s]", " ", (problem.description or problem.raw_statement or problem.title).lower())
        tokens = set(clean_text.split())
        # Filter stop words
        stop_words = {"the", "a", "an", "is", "in", "to", "of", "and", "or", "for", "with", "that", "this", "by", "from", "at"}
        meaningful_tokens = sorted(list(tokens - stop_words))
        token_sample = "_".join(meaningful_tokens[:12])

        # Signature features
        param_count = len(problem.param_names)
        ret_type = problem.return_type.strip().lower()

        # Constraint signature
        constraint_str = "_".join(sorted(problem.constraints))
        raw_key = f"params:{param_count}|ret:{ret_type}|tokens:{token_sample}|cons:{constraint_str}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]

    def store_experience(self, experience: ExperienceRecord) -> ExperienceRecord:
        """Saves a structured experience record to the persistent store."""
        self.store.save_experience(experience)
        return experience

    def get_experience(self, experience_id: str) -> Optional[ExperienceRecord]:
        """Retrieves an experience record by ID."""
        return self.store.get_experience(experience_id)

    def retrieve_relevant_experiences(
        self,
        problem: ProblemSpec,
        dsa_pattern: Optional[DSAPattern] = None,
        top_k: int = 5,
    ) -> MemoryRetrievalReport:
        """
        Multi-signal bounded experience retrieval and deterministic ranking (Stage 20).
        Signals:
        - Pattern Match: (Weight 0.40)
        - Structure / I/O Match: (Weight 0.25)
        - Constraint Match: (Weight 0.20)
        - Problem Fingerprint / Token Match: (Weight 0.15)
        
        Safeguards:
        - Rejects records without verified facts unless they provide verified failure/repair warnings.
        - Strict top-K bounding (default 5).
        - Returns explainable 'useful_reason' string.
        - Gracefully handles empty memory or retrieval anomalies (returns NO_RELEVANT_EXPERIENCE).
        """
        fingerprint = self.compute_problem_fingerprint(problem)
        report = MemoryRetrievalReport(
            query_problem_id=problem.id,
            query_fingerprint=fingerprint,
            query_pattern=dsa_pattern,
            retrieval_status="SUCCESS",
            top_k_limit=top_k,
        )

        try:
            all_records = self.store.list_all_experiences(only_verified=False, limit=200)
            report.total_candidates_inspected = len(all_records)

            if not all_records:
                report.retrieval_status = "NO_RELEVANT_EXPERIENCE"
                report.notes.append("Persistent memory store is empty (cold start).")
                return report

            scored_candidates = []

            for rec in all_records:
                score = 0.0
                reasons = []

                # 1. Pattern signal
                if dsa_pattern and rec.dsa_pattern == dsa_pattern:
                    score += 0.40
                    reasons.append(f"Matching DSA pattern ({dsa_pattern.value})")

                # 2. Structural I/O / Problem ID signal
                if rec.problem_id == problem.id:
                    score += 0.25
                    reasons.append("Exact problem identity match")
                elif rec.problem_fingerprint == fingerprint:
                    score += 0.25
                    reasons.append("Identical structural fingerprint")
                else:
                    # Partial structural overlap
                    score += 0.05

                # 3. Constraint profile overlap
                shared_constraints = set(problem.constraints).intersection(set(rec.constraints_summary))
                if shared_constraints:
                    score += 0.20
                    reasons.append(f"Matching constraint profile ({len(shared_constraints)} shared constraints)")

                # 4. Verified solution bonus vs failure warning
                if rec.is_verified:
                    score += 0.15
                    reasons.append("Historically certified and verified")
                elif rec.status == "MAX_ATTEMPTS_REACHED" or rec.failure_categories:
                    # Useful as an actionable warning if pattern matches
                    if dsa_pattern and rec.dsa_pattern == dsa_pattern:
                        score += 0.10
                        reasons.append("Contains verified failure/repair warning pattern")
                    else:
                        # Irrelevant unverified failure
                        report.rejected_count += 1
                        report.rejection_reasons.append(f"Rejected unverified record {rec.experience_id} with no pattern match")
                        continue
                elif rec.status == "INFRASTRUCTURE_ERROR":
                    # Infrastructure errors must NEVER advise algorithm choices
                    report.rejected_count += 1
                    report.rejection_reasons.append(f"Rejected infrastructure failure record {rec.experience_id}")
                    continue
                else:
                    # Unverified non-failure
                    report.rejected_count += 1
                    report.rejection_reasons.append(f"Rejected unverified record {rec.experience_id}")
                    continue

                # Relevance filter: Must have at least DSA pattern alignment OR exact/structural match
                has_substantive_match = (dsa_pattern and rec.dsa_pattern == dsa_pattern) or (rec.problem_id == problem.id) or (rec.problem_fingerprint == fingerprint)
                if score >= 0.35 and has_substantive_match:
                    reason_str = "; ".join(reasons) if reasons else "General algorithmic similarity"
                    scored_candidates.append((score, rec, reason_str))
                else:
                    report.rejected_count += 1
                    report.rejection_reasons.append(f"Record {rec.experience_id} lacked substantive pattern/structural match or scored below threshold ({score:.2f})")


            # Deterministic Sort: primary key = -score (descending), secondary key = rec.created_at (descending), tertiary = rec.experience_id
            scored_candidates.sort(key=lambda item: (-item[0], item[1].created_at, item[1].experience_id), reverse=False)

            # Apply Top-K Limit
            bounded = scored_candidates[:top_k]
            report.retrieved_count = len(bounded)

            if not bounded:
                report.retrieval_status = "NO_RELEVANT_EXPERIENCE"
                report.notes.append("No experiences met the minimum relevance threshold.")
                return report

            for sc, rec, reason_text in bounded:
                warning_notes = []
                for cat in rec.failure_categories:
                    warning_notes.append(f"Historical risk: observed {cat}")
                for hyp in rec.failure_hypotheses:
                    warning_notes.append(f"Diagnostic hypothesis note: {hyp}")

                rec_dto = ExperienceRecommendation(
                    experience_id=rec.experience_id,
                    problem_id=rec.problem_id,
                    relevance_score=round(sc, 4),
                    pattern=rec.dsa_pattern,
                    algorithm=rec.algorithm_name,
                    language=rec.language,
                    verified=rec.is_verified,
                    status=rec.status,
                    useful_reason=reason_text,
                    complexity_time=rec.complexity_expected_time or rec.complexity_observed_time,
                    complexity_space=rec.complexity_expected_space or rec.complexity_observed_space,
                    warning_notes=warning_notes,
                    repair_insights=rec.repair_actions,
                )
                report.recommendations.append(rec_dto)

            return report

        except Exception as e:
            report.retrieval_status = "MEMORY_RETRIEVAL_ERROR"
            report.notes.append(f"Exception during retrieval: {str(e)}")
            return report

    def learn_from_session(
        self,
        problem: ProblemSpec,
        session: SelfCorrectionSession,
    ) -> Optional[ExperienceRecord]:
        """
        Distills verified facts, observed complexity, diagnostic hypotheses, and repairs
        into a structured ExperienceRecord without storing private chain-of-thought.
        """
        fingerprint = self.compute_problem_fingerprint(problem)
        status_str = session.final_state.value
        is_verified = session.is_verified

        # Pattern
        dsa_pattern = DSAPattern.UNKNOWN
        if session.plan and session.plan.identified_patterns:
            dsa_pattern = session.plan.identified_patterns[0]

        # Algorithm name & candidates
        algo_name = "Unknown"
        candidates = []
        comp_exp_time = None
        comp_exp_space = None
        if session.plan:
            algo_name = session.plan.selected_approach.name
            candidates = [c.name for c in session.plan.candidate_approaches]
            comp_exp_time = session.plan.selected_approach.time_complexity
            comp_exp_space = session.plan.selected_approach.space_complexity

        # Observed complexity from Stage 10 audit
        comp_obs_time = None
        comp_obs_space = None
        tests_passed = 0
        tests_total = 0
        source_hash = None
        if session.verification_report:
            vr = session.verification_report
            comp_obs_time = vr.complexity_audit.inferred_time_complexity
            comp_obs_space = vr.complexity_audit.inferred_space_complexity
            tests_passed = vr.tests_passed
            tests_total = vr.total_tests_run
            source_hash = vr.source_version_hash

        # Failures & repairs from session attempts
        failure_cats = []
        failure_hyps = []
        repairs = []
        for att in session.attempt_history:
            cat = att.failure_addressed.failure_category.value
            if cat not in failure_cats:
                failure_cats.append(cat)
            for rh in att.failure_addressed.ranked_hypotheses:
                if rh.hypothesis not in failure_hyps:
                    failure_hyps.append(rh.hypothesis)
            if att.patch_summary and att.patch_summary not in repairs:
                repairs.append(att.patch_summary)

        # Source hash fallback
        if not source_hash and session.verified_code:
            source_hash = self.compute_source_hash(session.verified_code)
        elif not source_hash and session.initial_code:
            source_hash = self.compute_source_hash(session.initial_code)

        exp_id = f"exp_{problem.id}_{session.language.value}_{uuid.uuid4().hex[:6]}"

        record = ExperienceRecord(
            experience_id=exp_id,
            problem_id=problem.id,
            problem_fingerprint=fingerprint,
            normalized_title=problem.title,
            dsa_pattern=dsa_pattern,
            algorithm_name=algo_name,
            candidate_algorithms=candidates,
            language=session.language,
            complexity_expected_time=comp_exp_time,
            complexity_expected_space=comp_exp_space,
            complexity_observed_time=comp_obs_time,
            complexity_observed_space=comp_obs_space,
            constraints_summary=problem.constraints,
            status=status_str,
            is_verified=is_verified,
            failure_categories=failure_cats,
            failure_hypotheses=failure_hyps,
            repair_actions=repairs,
            attempt_count=session.total_attempts if session.total_attempts > 0 else 1,
            tests_passed=tests_passed,
            tests_total=tests_total,
            source_hash=source_hash,
        )
        self.store_experience(record)
        return record

    def close(self) -> None:
        """Closes store."""
        self.store.close()

