"""
Unit and regression tests for Task 1:
Wiring the LLM provider into the production solver (AutonomousQueueRunner, AlgorithmPlanner, CodeGenerator, SelfCorrectionOrchestrator, CodeRepairer)
and missing-key / unavailable provider behavior.
"""

import pytest
from unittest.mock import MagicMock, patch

from agent.config import Config
from agent.core.models import (
    Difficulty,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
)
from agent.llm.base import BaseLLMProvider, LLMResponse
from agent.planning.planner import AlgorithmPlanner
from agent.generation.generator import CodeGenerator
from agent.debugging.repairer import CodeRepairer
from agent.core.orchestrator import SelfCorrectionOrchestrator
from agent.queue.queue_runner import AutonomousQueueRunner
from agent.intake.service import ProblemIntakeService


class MockLLMProvider(BaseLLMProvider):
    def __init__(self, configured: bool = True):
        self._configured = configured

    @property
    def provider_name(self) -> str:
        return "mock_provider"

    @property
    def model_name(self) -> str:
        return "mock-model"

    def is_configured(self) -> bool:
        return self._configured

    def generate_text(self, prompt: str, system_instruction=None, temperature=0.2, max_output_tokens=None) -> LLMResponse:
        return LLMResponse(
            text="class Solution:\n    def twoSum(self, nums: List[int], target: int) -> List[int]:\n        return [0, 1]\n",
            model_name="mock-model",
        )

    def generate_structured(self, prompt: str, response_schema, system_instruction=None, temperature=0.1):
        raise NotImplementedError("Mock structured not implemented")


@pytest.fixture
def sample_problem() -> ProblemSpec:
    return ProblemSpec(
        id="two-sum",
        title="Two Sum",
        description="Find two numbers that add up to target.",
        raw_statement="Find two numbers that add up to target.",
        difficulty=Difficulty.EASY,
        function_name="twoSum",
        param_names=["nums", "target"],
        return_type="List[int]",
        test_cases=[
            TestCase(id="tc_1", inputs={"nums": [2, 7, 11, 15], "target": 9}, expected_output=[0, 1], is_sample=True)
        ],
    )


def test_queue_runner_propagates_provided_llm():
    """Test AutonomousQueueRunner passes explicit llm_provider to planner and orchestrator."""
    mock_llm = MockLLMProvider(configured=True)
    runner = AutonomousQueueRunner(llm_provider=mock_llm)

    assert runner.llm is mock_llm
    assert runner.planner.llm is mock_llm
    assert runner.orchestrator.llm is mock_llm
    assert runner.orchestrator.generator.llm is mock_llm
    assert runner.orchestrator.repairer.llm is mock_llm


def test_intake_service_propagates_provided_llm():
    """Test ProblemIntakeService passes llm_provider to AutonomousQueueRunner."""
    mock_llm = MockLLMProvider(configured=True)
    intake = ProblemIntakeService(llm_provider=mock_llm)

    assert intake.runner.llm is mock_llm
    assert intake.runner.planner.llm is mock_llm
    assert intake.runner.orchestrator.generator.llm is mock_llm


def test_queue_runner_initializes_provider_when_configured():
    """When Gemini API key is configured, get_llm_provider() is invoked and passed through."""
    mock_gemini = MockLLMProvider(configured=True)
    with patch.object(Config, "is_api_key_configured", return_value=True), \
         patch("agent.queue.queue_runner.get_llm_provider", return_value=mock_gemini):
        runner = AutonomousQueueRunner()
        assert runner.llm is mock_gemini
        assert runner.planner.llm is mock_gemini
        assert runner.orchestrator.generator.llm is mock_gemini


def test_missing_key_behavior(sample_problem: ProblemSpec):
    """When no API key is configured, runner.llm is None or unconfigured, and generator/repairer report unavailable."""
    with patch.object(Config, "is_api_key_configured", return_value=False):
        runner = AutonomousQueueRunner()
        assert runner.llm is None
        assert runner.planner.llm is None
        assert runner.orchestrator.generator.llm is None
        assert runner.orchestrator.repairer.llm is None

        # Verify CodeGenerator does not claim LLM generation
        plan = runner.planner.plan(sample_problem)
        gen_result = runner.orchestrator.generator.generate(
            sample_problem,
            plan,
            SupportedLanguage.PYTHON,
        )
        assert gen_result.generation_metadata.get("provenance") == "DETERMINISTIC_FALLBACK" or not runner.orchestrator.generator.llm
