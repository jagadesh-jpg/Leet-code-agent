"""
Stage 24: Benchmark Leakage Detector & Duplicate Problem Identifier.
Implements:
1. Exact fingerprint matching (SHA-256 of canonical tokens + I/O schema).
2. Near-duplicate similarity detection (Jaccard similarity on semantic keyword shingles + constraint profiles).
3. Cross-split contamination auditing (detecting held-out problems in DEV, MEMORY, or REGISTRY).
"""

import hashlib
import re
from typing import Dict, List, Optional, Set, Tuple

from agent.core.models import ProblemSpec
from agent.evaluation.models import DatasetSplit, LeakageAuditRecord, ProblemMetadata


class LeakageDetector:
    """
    Detects benchmark leakage, duplicate problems, and cross-split contamination.
    """

    @classmethod
    def compute_exact_fingerprint(cls, problem: ProblemSpec) -> str:
        """
        Computes deterministic fingerprint from function signature, parameters, and return type.
        """
        params_str = ",".join(sorted(problem.param_names))
        ret_type = (problem.return_type or "").strip().lower()
        func_name = (problem.function_name or "").strip().lower()
        raw = f"{func_name}|{params_str}|{ret_type}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def extract_semantic_tokens(cls, text: str) -> Set[str]:
        """
        Extracts normalized semantic keyword tokens, filtering common English stop words.
        """
        clean = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
        words = clean.split()
        stop_words = {
            "the", "a", "an", "is", "in", "to", "of", "and", "or", "for",
            "with", "that", "this", "by", "from", "at", "as", "be", "on",
            "it", "are", "you", "given", "return", "an", "integer", "array",
            "string", "find", "determine",
        }
        return set(w for w in words if len(w) > 2 and w not in stop_words)

    @classmethod
    def compute_semantic_fingerprint(cls, problem: ProblemSpec) -> str:
        """
        Computes hash of sorted top semantic keyword tokens.
        """
        text = f"{problem.title} {problem.description} {' '.join(problem.constraints)}"
        tokens = sorted(list(cls.extract_semantic_tokens(text)))
        token_str = "_".join(tokens[:15])
        return hashlib.sha256(token_str.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def calculate_near_duplicate_similarity(
        cls, prob_a: ProblemSpec, prob_b: ProblemSpec
    ) -> Tuple[float, str]:
        """
        Calculates Jaccard similarity between semantic token sets of prob_a and prob_b.
        Returns (similarity_score, explanation).
        Similarity >= 0.70 indicates a likely near-duplicate or problem mutation.
        """
        # Exact function signature match
        fp_a = cls.compute_exact_fingerprint(prob_a)
        fp_b = cls.compute_exact_fingerprint(prob_b)
        if fp_a == fp_b:
            return 1.0, "Identical function name, parameter names, and return type"

        text_a = f"{prob_a.title} {prob_a.description}"
        text_b = f"{prob_b.title} {prob_b.description}"
        tokens_a = cls.extract_semantic_tokens(text_a)
        tokens_b = cls.extract_semantic_tokens(text_b)

        if not tokens_a or not tokens_b:
            return 0.0, "Insufficient semantic tokens for comparison"

        intersection = tokens_a.intersection(tokens_b)
        union = tokens_a.union(tokens_b)
        jaccard = len(intersection) / len(union) if union else 0.0

        explanation = f"Jaccard similarity: {jaccard:.2f} ({len(intersection)} shared keywords out of {len(union)})"
        return round(jaccard, 3), explanation

    @classmethod
    def audit_problem_leakage(
        cls,
        problem: ProblemSpec,
        split: DatasetSplit,
        existing_problem_pool: List[ProblemSpec],
        persistent_memory_problem_ids: Optional[Set[str]] = None,
        registry_problem_ids: Optional[Set[str]] = None,
        similarity_threshold: float = 0.70,
    ) -> LeakageAuditRecord:
        """
        Audits whether a problem from a given split has leaked into or contaminated other sets.
        - Exact duplicate check
        - Near-duplicate similarity check
        - Persistent memory presence check
        - Canonical registry overlap check
        """
        leak_details: List[str] = []
        has_exact = False
        has_near_dup = False
        has_mem_leak = False
        has_reg_leak = False

        my_fp = cls.compute_exact_fingerprint(problem)

        # 1. Compare against existing pool (e.g. DEV set problems)
        for other in existing_problem_pool:
            if other.id == problem.id:
                has_exact = True
                leak_details.append(f"Exact problem ID collision: '{problem.id}' exists in reference pool")
                continue

            other_fp = cls.compute_exact_fingerprint(other)
            if my_fp == other_fp:
                has_exact = True
                leak_details.append(f"Exact signature match with '{other.id}' in reference pool")
                continue

            sim, expl = cls.calculate_near_duplicate_similarity(problem, other)
            if sim >= similarity_threshold:
                has_near_dup = True
                leak_details.append(f"Likely near-duplicate of '{other.id}' ({expl})")

        # 2. Check persistent memory
        if persistent_memory_problem_ids and problem.id in persistent_memory_problem_ids:
            has_mem_leak = True
            leak_details.append(f"Problem ID '{problem.id}' already exists in persistent memory store prior to evaluation")

        # 3. Check canonical benchmark registry
        if registry_problem_ids and problem.id in registry_problem_ids:
            has_reg_leak = True
            leak_details.append(f"Problem ID '{problem.id}' is present in canonical benchmark registry")

        is_contaminated = has_exact or has_near_dup or has_mem_leak or has_reg_leak
        status = "CONTAMINATED" if is_contaminated else "CLEAN"

        return LeakageAuditRecord(
            problem_id=problem.id,
            target_split=split,
            has_exact_leakage=has_exact,
            has_near_duplicate_leakage=has_near_dup,
            has_memory_leakage=has_mem_leak,
            has_registry_leakage=has_reg_leak,
            leakage_details=leak_details,
            is_contaminated=is_contaminated,
            status=status,
        )
