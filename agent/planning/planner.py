"""
Algorithm Planner.
Takes a validated ProblemSpec, classifies patterns, generates multiple candidate
approaches, evaluates constraint viability, and selects the optimal approach.
"""

from typing import Any, List, Optional
from agent.core.models import (
    AlgorithmPlan,
    CandidateApproach,
    DSAPattern,
    ProblemSpec,
)
from agent.llm.base import BaseLLMProvider
from agent.planning.constraint_evaluator import ConstraintEvaluator
from agent.planning.pattern_classifier import PatternClassifier


class AlgorithmPlanner:
    """
    Algorithm Planning & DSA Pattern Classification engine.
    Works either deterministically or collaboratively with an LLMProvider when available.
    """

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        self.llm = llm_provider

    def plan(
        self,
        problem: ProblemSpec,
        retrieved_experiences: Optional[List[Any]] = None,
    ) -> AlgorithmPlan:
        """
        Generates a structured AlgorithmPlan for the problem.
        1. Classifies applicable DSA patterns.
        2. Generates candidate algorithmic approaches.
        3. Evaluates constraint viability for each candidate.
        4. Consults retrieved historical experiences (Stage 20):
           - Uses verified experiences as recommendations/guidance.
           - Current problem constraints ALWAYS override memory.
           - Incorporates historical failure warnings and repair insights.
        5. Selects optimal approach and records rejection reasons.
        """
        # 1. Classify DSA Patterns
        patterns = PatternClassifier.classify(problem)

        # 2. Extract upper bound N from constraints
        max_n = ConstraintEvaluator.extract_max_n(problem.constraints)
        constraints_uncertain = (max_n is None) or problem.is_ambiguous

        # 3. Generate Candidate Approaches (Collaborative Model Planning when available)
        candidates = []
        if self.llm and self.llm.is_configured():
            try:
                candidates = self._generate_candidates_with_llm(problem, patterns, max_n)
            except Exception:
                # Untrusted model fallback: fallback cleanly to deterministic generator
                candidates = []

        if not candidates:
            candidates = self._generate_candidates(problem, patterns, max_n)

        # 4. Perform Constraint Satisfaction Check on all candidates (Deterministic Grounding)
        for cand in candidates:
            satisfies, reason = ConstraintEvaluator.evaluate_complexity(cand.time_complexity, max_n)
            cand.satisfies_constraints = satisfies
            if not satisfies and not cand.rejection_reason:
                cand.rejection_reason = reason

        # 5. Process Retrieved Memory Experience (Stage 20)
        memory_notes = []
        memory_warnings = []
        memory_recommended_algo = None

        if retrieved_experiences:
            for exp in retrieved_experiences:
                # Exp can be ExperienceRecommendation or dict
                rec_algo = getattr(exp, "algorithm", None) or (exp.get("algorithm") if isinstance(exp, dict) else None)
                rec_verified = getattr(exp, "verified", False) or (exp.get("verified", False) if isinstance(exp, dict) else False)
                rec_pattern = getattr(exp, "pattern", None) or (exp.get("pattern") if isinstance(exp, dict) else None)
                rec_reason = getattr(exp, "useful_reason", "") or (exp.get("useful_reason", "") if isinstance(exp, dict) else "")
                rec_warnings = getattr(exp, "warning_notes", []) or (exp.get("warning_notes", []) if isinstance(exp, dict) else [])
                rec_repairs = getattr(exp, "repair_insights", []) or (exp.get("repair_insights", []) if isinstance(exp, dict) else [])

                # Verify if memory pattern matches current problem pattern
                pattern_match = False
                if rec_pattern:
                    rec_p_val = rec_pattern.value if hasattr(rec_pattern, "value") else str(rec_pattern)
                    for p in patterns:
                        if p.value == rec_p_val:
                            pattern_match = True
                            break

                if pattern_match and rec_verified and not memory_recommended_algo:
                    memory_recommended_algo = rec_algo
                    memory_notes.append(f"Memory recommendation: Prioritizing '{rec_algo}' based on verified prior experience ({rec_reason}).")

                # Accumulate historical warnings and repair insights
                for w in rec_warnings:
                    if w not in memory_warnings:
                        memory_warnings.append(w)
                for r in rec_repairs:
                    insight_str = f"Historical repair insight: {r}"
                    if insight_str not in memory_notes:
                        memory_notes.append(insight_str)

        # 6. Select Recommended Approach
        # Filter for candidates that satisfy constraints
        viable_candidates = [c for c in candidates if c.satisfies_constraints]
        selected = None

        if viable_candidates:
            # If memory suggested a viable algorithm matching current problem constraints, prioritize it
            if memory_recommended_algo:
                for vc in viable_candidates:
                    if memory_recommended_algo.lower() in vc.name.lower() or vc.name.lower() in memory_recommended_algo.lower():
                        selected = vc
                        break

            # If no memory match, or memory approach was rejected due to constraint violation:
            if not selected:
                # Pick the most efficient viable candidate (e.g. O(N) or O(N log N) before O(N^2))
                selected = min(
                    viable_candidates,
                    key=lambda c: ConstraintEvaluator.estimate_operations(c.time_complexity, max_n or 1000) or float("inf"),
                )
        else:
            # Fallback to the first candidate if none or all rejected
            selected = candidates[0]

        # 7. Formulate Justification & Notes
        notes = []
        if constraints_uncertain:
            notes.append("Input constraints (e.g. max N) were not explicitly bounded; complexity is estimated.")
        for note in problem.ambiguity_notes:
            notes.append(f"Problem ambiguity noted: {note}")

        # Add memory notes and warnings
        notes.extend(memory_notes)
        notes.extend(memory_warnings)

        justification = (
            f"Selected '{selected.name}' with time complexity {selected.time_complexity} and space "
            f"complexity {selected.space_complexity}. "
        )
        if max_n:
            justification += f"For max N = {max_n}, this operates well within the 10^8 operations limit."
        else:
            justification += "Meets general asymptotic requirements without unbounded resource growth."

        if memory_recommended_algo and selected.name.lower() in memory_recommended_algo.lower():
            justification += f" Approach aligns with verified prior engineering experience."

        edge_cases = [ec.description for ec in problem.edge_cases]

        return AlgorithmPlan(
            problem_id=problem.id,
            identified_patterns=patterns,
            candidate_approaches=candidates,
            selected_approach=selected,
            justification=justification,
            constraints_validated=not constraints_uncertain,
            constraints_uncertain=constraints_uncertain,
            edge_cases_considered=edge_cases,
            assumptions_and_notes=notes,
        )


    def _generate_candidates(
        self,
        problem: ProblemSpec,
        patterns: List[DSAPattern],
        max_n: Optional[int],
    ) -> List[CandidateApproach]:
        """
        Synthesizes candidate approaches based on problem characteristics and patterns.
        """
        candidates: List[CandidateApproach] = []

        # If problem involves Two Sum or Hash Map search
        if DSAPattern.HASH_TABLE in patterns:
            # Candidate 1: Brute Force O(N^2)
            candidates.append(CandidateApproach(
                name="Brute Force Nested Loop",
                data_structures=["Array / List"],
                time_complexity="O(N^2)",
                space_complexity="O(1)",
                description="Iterate through all pairs (i, j) to test condition.",
                satisfies_constraints=True,  # Will be evaluated by ConstraintEvaluator
            ))
            # Candidate 2: Hash Map Lookup O(N)
            candidates.append(CandidateApproach(
                name="Single-Pass Hash Map",
                data_structures=["Hash Map / Dict"],
                time_complexity="O(N)",
                space_complexity="O(N)",
                description="Maintain lookup map of seen values to indices for instant O(1) checks.",
                satisfies_constraints=True,
            ))

        # If problem involves Binary Search
        elif DSAPattern.BINARY_SEARCH in patterns:
            candidates.append(CandidateApproach(
                name="Linear Scan",
                data_structures=["Array / List"],
                time_complexity="O(N)",
                space_complexity="O(1)",
                description="Linearly examine every element sequentially.",
                satisfies_constraints=True,
            ))
            candidates.append(CandidateApproach(
                name="Binary Search on Monotonic Space",
                data_structures=["Array / Pointers"],
                time_complexity="O(log N)",
                space_complexity="O(1)",
                description="Halve the search boundary at each step using left and right pointers.",
                satisfies_constraints=True,
            ))

        # If problem involves Stack / Parentheses
        elif DSAPattern.STACK in patterns:
            candidates.append(CandidateApproach(
                name="Explicit LIFO Stack",
                data_structures=["Stack / List"],
                time_complexity="O(N)",
                space_complexity="O(N)",
                description="Push opening elements onto stack; pop and validate matching closers.",
                satisfies_constraints=True,
            ))

        # If problem involves Sliding Window
        elif DSAPattern.SLIDING_WINDOW in patterns:
            candidates.append(CandidateApproach(
                name="Brute Force All Subarrays",
                data_structures=["Array"],
                time_complexity="O(N^2)",
                space_complexity="O(1)",
                description="Generate and inspect every possible contiguous window.",
                satisfies_constraints=True,
            ))
            candidates.append(CandidateApproach(
                name="Two-Pointer Sliding Window",
                data_structures=["Two Pointers", "Hash Map / Set"],
                time_complexity="O(N)",
                space_complexity="O(N)",
                description="Expand right pointer and contract left pointer dynamically maintaining window invariant.",
                satisfies_constraints=True,
            ))

        # If problem involves Two Pointers (e.g. Valid Palindrome)
        elif DSAPattern.TWO_POINTERS in patterns:
            candidates.append(CandidateApproach(
                name="Two-Pointer Convergence",
                data_structures=["Two Pointers"],
                time_complexity="O(N)",
                space_complexity="O(1)",
                description="Traverse from both ends towards the center checking equality.",
                satisfies_constraints=True,
            ))

        # If problem involves Dynamic Programming (e.g. Climbing Stairs)
        elif DSAPattern.DYNAMIC_PROGRAMMING in patterns:
            candidates.append(CandidateApproach(
                name="Bottom-Up DP",
                data_structures=["State Variables"],
                time_complexity="O(N)",
                space_complexity="O(1)",
                description="Iterative recurrence tracking the last two transition states.",
                satisfies_constraints=True,
            ))

        # If problem involves Greedy (e.g. Best Time to Buy and Sell Stock, Assign Cookies)
        elif DSAPattern.GREEDY in patterns:
            # Check if problem involves matching or multiple arrays requiring sorting
            param_names_lower = [p.lower() for p in problem.param_names]
            text = f"{problem.id} {problem.title} {problem.description}".lower()
            if len(problem.param_names) >= 2 or "cookie" in text or "interval" in text or "content" in text or "assign" in text:
                candidates.append(CandidateApproach(
                    name="Sorted Greedy Matching",
                    data_structures=["Sorted Arrays / Two Pointers"],
                    time_complexity="O(N log N)",
                    space_complexity="O(1)",
                    description="Sort input arrays and use greedy two-pointer scanning to match elements.",
                    satisfies_constraints=True,
                ))
            else:
                candidates.append(CandidateApproach(
                    name="Single-Pass Greedy Scan",
                    data_structures=["Variables"],
                    time_complexity="O(N)",
                    space_complexity="O(1)",
                    description="Track minimum element seen so far and update maximum profit greedily.",
                    satisfies_constraints=True,
                ))

        # If problem involves Heap / Priority Queue (e.g. Kth Largest Element)
        elif DSAPattern.HEAP_PRIORITY_QUEUE in patterns:
            candidates.append(CandidateApproach(
                name="Min-Heap Top-K Tracking",
                data_structures=["priority_queue"],
                time_complexity="O(N log K)",
                space_complexity="O(K)",
                description="Maintain a min-heap of size K containing the largest elements seen so far.",
                satisfies_constraints=True,
            ))

        # If problem involves Graph / BFS / DFS / Matrix
        elif DSAPattern.GRAPH_BFS_DFS in patterns:
            candidates.append(CandidateApproach(
                name="Breadth-First / Depth-First Traversal",
                data_structures=["Queue / Recursion stack"],
                time_complexity="O(V + E)",
                space_complexity="O(V)",
                description="Explore reachable components systematically marking visited states.",
                satisfies_constraints=True,
            ))

        # If problem involves Binary Tree
        elif DSAPattern.BINARY_TREE in patterns:
            candidates.append(CandidateApproach(
                name="Recursive Tree Traversal",
                data_structures=["Call Stack"],
                time_complexity="O(N)",
                space_complexity="O(H)",
                description="Recursively compute subtree properties and combine at each node.",
                satisfies_constraints=True,
            ))

        # If problem involves Linked List
        elif DSAPattern.LINKED_LIST in patterns:
            candidates.append(CandidateApproach(
                name="Iterative Pointer Reversal",
                data_structures=["Pointers"],
                time_complexity="O(N)",
                space_complexity="O(1)",
                description="Iteratively redirect next pointers using prev, curr, and next tracking pointers.",
                satisfies_constraints=True,
            ))

        # If problem involves Backtracking
        elif DSAPattern.BACKTRACKING_RECURSION in patterns:
            candidates.append(CandidateApproach(
                name="Exhaustive Backtracking",
                data_structures=["Recursion stack"],
                time_complexity="O(2^N)",
                space_complexity="O(N)",
                description="Depth-first state search exploring decisions and pruning invalid paths.",
                satisfies_constraints=True,
            ))

        # Default / Fallback Candidates
        else:
            candidates.append(CandidateApproach(
                name="Direct Iterative Pass",
                data_structures=["Array / List"],
                time_complexity="O(N)",
                space_complexity="O(1)",
                description="Iterate linearly over the input collection.",
                satisfies_constraints=True,
            ))

        return candidates

    def _generate_candidates_with_llm(
        self,
        problem: ProblemSpec,
        patterns: List[DSAPattern],
        max_n: Optional[int],
    ) -> List[CandidateApproach]:
        """Queries model for structured candidate algorithm comparison with strict schema validation."""
        from agent.llm.schemas import ModelAlgorithmPlan
        prompt = f"""You are planning an optimal algorithm for the following competitive programming DSA problem:
Title: {problem.title}
Statement: {problem.description}
Function: {problem.function_name}({', '.join(problem.param_names)}) -> {problem.return_type}
Constraints: {'; '.join(problem.constraints)}
Classified Patterns: {', '.join(p.value for p in patterns)}
Max Input Bound N: {max_n or 'Unknown'}

Instructions:
1. Propose 2 or 3 distinct candidate approaches (e.g. Brute Force vs Optimal).
2. Detail time and space complexity with formal Big-O notation (e.g. 'O(N)', 'O(N log N)').
3. Provide correctness arguments for each candidate.
"""
        plan_response: ModelAlgorithmPlan = self.llm.generate_structured(
            prompt=prompt,
            response_schema=ModelAlgorithmPlan,
            system_instruction="You are an expert competitive programmer and algorithmic complexity auditor. Provide precise Big-O bounds and data structure analysis.",
        )

        candidates: List[CandidateApproach] = []
        for cand in plan_response.candidate_approaches:
            candidates.append(CandidateApproach(
                name=cand.name,
                data_structures=cand.data_structures,
                time_complexity=cand.time_complexity,
                space_complexity=cand.space_complexity,
                description=f"{cand.description} | Correctness: {cand.correctness_argument}",
                satisfies_constraints=True,
            ))
        return candidates
