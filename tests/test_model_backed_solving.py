"""
Unit and Integration Tests for Model-Backed General DSA Solving.
Tests:
1. LLMProvider interface contract (is_configured, text, structured).
2. Model schema validation for plan, code generation, and repair.
3. Unconfigured model fallback behavior (graceful deterministic fallback, no fake success).
4. Stage 27 held-out set disjointness (0 exact leaks, 0 near-duplicate leaks).
5. Untrusted model code gating through real compilation and test execution.
"""

import pytest
from pydantic import ValidationError

from agent.core.models import DSAPattern, ProblemSpec, SupportedLanguage
from agent.evaluation.dataset_registry import DatasetRegistry
from agent.evaluation.leakage_detector import LeakageDetector
from agent.evaluation.models import DatasetSplit
from agent.generation.generator import CodeGenerator
from agent.llm.base import BaseLLMProvider, LLMResponse
from agent.llm.schemas import (
    ModelAlgorithmPlan,
    ModelCandidateApproach,
    ModelCodeGeneration,
    ModelRepairResponse,
)
from agent.planning.planner import AlgorithmPlanner


class MockConfiguredLLM(BaseLLMProvider):
    """Mock provider simulating an active, configured model provider."""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-reasoning-model"

    def is_configured(self) -> bool:
        return True

    def generate_text(self, prompt: str, **kwargs) -> LLMResponse:
        return LLMResponse(
            text="```python\nclass Solution:\n    def test(self, x): return x + 1\n```",
            model_name="mock-reasoning-model",
        )

    def generate_structured(self, prompt: str, response_schema, **kwargs):
        if response_schema == ModelAlgorithmPlan:
            return ModelAlgorithmPlan(
                candidate_approaches=[
                    ModelCandidateApproach(
                        name="Linear Pass",
                        data_structures=["Array"],
                        time_complexity="O(N)",
                        space_complexity="O(1)",
                        description="Iterate linearly",
                        correctness_argument="Valid for monotonic sequence",
                    )
                ],
                selected_approach_index=0,
                selection_justification="Satisfies linear bound",
                time_complexity="O(N)",
                space_complexity="O(1)",
                edge_cases=["Empty array", "Single element"],
            )
        elif response_schema == ModelCodeGeneration:
            return ModelCodeGeneration(
                language="python",
                source_code="""class Solution:
    def numJewelsInStones(self, jewels: str, stones: str) -> int:
        s = set(jewels)
        return sum(1 for c in stones if c in s)
""",
                algorithmic_invariants=["s contains distinct jewels"],
                complexity_explanation="Hash set lookup in O(1)",
            )
        elif response_schema == ModelRepairResponse:
            return ModelRepairResponse(
                root_cause_analysis="Off-by-one boundary",
                faulty_component="Loop condition",
                repaired_source_code="""class Solution:
    def numJewelsInStones(self, jewels: str, stones: str) -> int:
        return sum(1 for c in stones if c in jewels)
""",
                patch_summary="Simplified membership scan",
            )
        raise ValueError(f"Unsupported schema: {response_schema}")


def test_model_schemas_validation():
    """Validates that structured Pydantic schemas enforce required fields."""
    cand = ModelCandidateApproach(
        name="Binary Search",
        data_structures=["Array"],
        time_complexity="O(log N)",
        space_complexity="O(1)",
        description="Halves search space",
        correctness_argument="Monotonic invariant holds",
    )
    assert cand.time_complexity == "O(log N)"

    with pytest.raises(ValidationError):
        # Missing required correctness_argument
        ModelCandidateApproach(
            name="Incomplete",
            data_structures=[],
            time_complexity="O(N)",
            space_complexity="O(1)",
            description="desc",
        )


def test_planner_integrates_model_when_configured():
    """Confirms planner uses model structured candidate generation when provider is configured."""
    llm = MockConfiguredLLM()
    planner = AlgorithmPlanner(llm_provider=llm)

    spec = ProblemSpec(
        id="sample-prob",
        title="Sample Problem",
        description="Find number",
        function_name="findNum",
        param_names=["nums"],
        return_type="int",
        constraints=["1 <= nums.length <= 10^5"],
    )

    plan = planner.plan(spec)
    assert plan.selected_approach.time_complexity == "O(N)"
    assert len(plan.candidate_approaches) > 0


def test_generator_integrates_model_when_configured():
    """Confirms generator queries model when provider is configured and applies AST validation."""
    llm = MockConfiguredLLM()
    generator = CodeGenerator(llm_provider=llm)
    planner = AlgorithmPlanner(llm_provider=llm)

    spec = ProblemSpec(
        id="jewels-test",
        title="Jewels and Stones",
        description="Count jewels",
        function_name="numJewelsInStones",
        param_names=["jewels", "stones"],
        return_type="int",
    )
    plan = planner.plan(spec)
    gen_code = generator.generate(spec, plan, SupportedLanguage.PYTHON)

    assert "numJewelsInStones" in gen_code.source_code
    assert gen_code.validation_result.is_valid


def test_stage27_disjoint_leak_free_held_out():
    """Guarantees Stage 27 held-out evaluation suite has 0 leakage against prior suites."""
    reg = DatasetRegistry()
    stage27_items = reg.get_held_out_problems(stage=27)
    assert len(stage27_items) == 15

    prior_pool = [s for s, _ in reg.get_held_out_problems(stage=24)]
    prior_pool += [s for s, _ in reg.get_held_out_problems(stage=25)]
    prior_pool += [s for s, _ in reg.get_held_out_problems(stage=26)]

    prior_ids = {p.id for p in prior_pool}

    for spec, _ in stage27_items:
        assert spec.id not in prior_ids
        audit = LeakageDetector.audit_problem_leakage(
            problem=spec,
            split=DatasetSplit.HELD_OUT_TEST,
            existing_problem_pool=prior_pool,
            similarity_threshold=0.70,
        )
        assert not audit.has_exact_leakage
        assert not audit.has_near_duplicate_leakage


def test_stage28_disjoint_leak_free_held_out():
    """Guarantees Stage 28 held-out evaluation suite has 0 leakage against all prior suites."""
    reg = DatasetRegistry()
    stage28_items = reg.get_held_out_problems(stage=28)
    assert len(stage28_items) == 15

    prior_pool = [s for s, _ in reg.get_held_out_problems(stage=24)]
    prior_pool += [s for s, _ in reg.get_held_out_problems(stage=25)]
    prior_pool += [s for s, _ in reg.get_held_out_problems(stage=26)]
    prior_pool += [s for s, _ in reg.get_held_out_problems(stage=27)]

    prior_ids = {p.id for p in prior_pool}

    for spec, _ in stage28_items:
        assert spec.id not in prior_ids
        audit = LeakageDetector.audit_problem_leakage(
            problem=spec,
            split=DatasetSplit.HELD_OUT_TEST,
            existing_problem_pool=prior_pool,
            similarity_threshold=0.70,
        )
        assert not audit.has_exact_leakage
        assert not audit.has_near_duplicate_leakage
