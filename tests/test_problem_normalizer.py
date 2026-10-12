"""
Tests for Problem Analysis & Schema Normalization Layer (Stage 3).
Verifies:
1. Simple problem with clear input/output.
2. Problem with explicit numeric constraints.
3. Problem with multiple examples.
4. Problem containing edge cases (min/max bounds, empty structures).
5. Incomplete/ambiguous problem statement (analyzer records ambiguities without guessing).
6. Malformed or unexpected input handling (empty strings, syntax errors).
"""

import pytest
from agent.core.models import (
    ConfidenceLevel,
    Difficulty,
    ProblemSpec,
)
from agent.core.normalizer import ProblemNormalizer


@pytest.fixture
def normalizer() -> ProblemNormalizer:
    return ProblemNormalizer()


def test_1_simple_problem_clear_io(normalizer: ProblemNormalizer):
    """Verifies standard clean problem parsing with title, inputs, output, and types."""
    text = """
# Two Sum [Easy]

Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target.

Example 1:
Input: nums = [2,7,11,15], target = 9
Output: [0,1]
Explanation: Because nums[0] + nums[1] == 9, we return [0, 1].

Constraints:
- 2 <= nums.length <= 10^4
- -10^9 <= nums[i] <= 10^9
- -10^9 <= target <= 10^9
    """
    spec = normalizer.parse(text)

    assert spec.id == "two-sum"
    assert spec.title == "Two Sum"
    assert spec.difficulty == Difficulty.EASY
    assert len(spec.test_cases) == 1
    assert spec.test_cases[0].inputs == {"nums": [2, 7, 11, 15], "target": 9}
    assert spec.test_cases[0].expected_output == [0, 1]
    assert spec.param_names == ["nums", "target"]
    assert not spec.is_ambiguous


def test_2_explicit_numeric_constraints(normalizer: ProblemNormalizer):
    """Verifies extraction of structured bounds (min_val, max_val, target variable)."""
    text = """
### Search in Rotated Sorted Array [Medium]

There is an integer array nums sorted in ascending order.

Constraints:
- 1 <= nums.length <= 5000
- -10^4 <= nums[i] <= 10^4
- -10^4 <= target <= 10^4

Example 1:
Input: nums = [4,5,6,7,0,1,2], target = 0
Output: 4
    """
    spec = normalizer.parse(text)

    assert spec.difficulty == Difficulty.MEDIUM
    assert len(spec.structured_constraints) == 3

    # Check bounded constraint item
    length_constraint = spec.structured_constraints[0]
    assert length_constraint.variable == "nums.length"
    assert length_constraint.min_val == "1"
    assert length_constraint.max_val == "5000"
    assert length_constraint.confidence == ConfidenceLevel.EXPLICIT


def test_3_multiple_examples_and_explanations(normalizer: ProblemNormalizer):
    """Verifies parsing of multiple example test cases with descriptions."""
    text = """
# Valid Parentheses (Easy)

Given a string s containing just the characters '(', ')', '{', '}', '[' and ']', determine if the input string is valid.

Example 1:
Input: s = "()"
Output: true

Example 2:
Input: s = "()[]{}"
Output: true

Example 3:
Input: s = "(]"
Output: false

Constraints:
- 1 <= s.length <= 10^4
    """
    spec = normalizer.parse(text)

    assert spec.title == "Valid Parentheses"
    assert spec.difficulty == Difficulty.EASY
    assert len(spec.test_cases) == 3

    assert spec.test_cases[0].inputs == {"s": "()"}
    assert spec.test_cases[0].expected_output is True

    assert spec.test_cases[1].inputs == {"s": "()[]{}"}
    assert spec.test_cases[1].expected_output is True

    assert spec.test_cases[2].inputs == {"s": "(]"}
    assert spec.test_cases[2].expected_output is False


def test_4_edge_cases_derivation(normalizer: ProblemNormalizer):
    """Verifies edge cases are derived strictly from boundary conditions."""
    text = """
# Maximum Subarray

Given an integer array nums, find the subarray with the largest sum.

Constraints:
- 1 <= nums.length <= 10^5
- -10^4 <= nums[i] <= 10^4

Example 1:
Input: nums = [-2,1,-3,4,-1,2,1,-5,4]
Output: 6
    """
    spec = normalizer.parse(text)

    assert len(spec.edge_cases) >= 2
    edge_descriptions = [ec.description for ec in spec.edge_cases]
    # Inferred minimum and maximum boundary conditions
    assert any("nums.length = 1" in desc for desc in edge_descriptions)
    assert any("nums.length = 10^5" in desc for desc in edge_descriptions)
    assert all(ec.confidence == ConfidenceLevel.INFERRED for ec in spec.edge_cases)


def test_5_incomplete_or_ambiguous_problem(normalizer: ProblemNormalizer):
    """Verifies that missing parameters and examples are marked as ambiguous rather than guessed."""
    text = """
# Vague Problem

Solve this puzzle without any further explanation or parameters.
    """
    spec = normalizer.parse(text)

    assert spec.is_ambiguous is True
    assert len(spec.ambiguity_notes) > 0
    # Must flag missing examples and uncertain parameters
    assert spec.function_name in ("vagueProblem", "solve")
    assert len(spec.test_cases) == 0


def test_6_malformed_input_handling(normalizer: ProblemNormalizer):
    """Verifies empty or whitespace inputs raise clear ValueErrors."""
    with pytest.raises(ValueError) as exc_info:
        normalizer.parse("")
    assert "empty" in str(exc_info.value).lower()

    with pytest.raises(ValueError) as exc_info:
        normalizer.parse("   \n\t  ")
    assert "empty" in str(exc_info.value).lower()


def test_7_structured_json_input(normalizer: ProblemNormalizer):
    """Verifies that problem definitions provided as JSON load into ProblemSpec directly."""
    json_str = """{
        "id": "merge-intervals",
        "title": "Merge Intervals",
        "difficulty": "Medium",
        "function_name": "merge",
        "param_names": ["intervals"],
        "return_type": "List[List[int]]",
        "constraints": ["1 <= intervals.length <= 10^4"],
        "test_cases": [
            {
                "id": "tc1",
                "inputs": {"intervals": [[1,3],[2,6],[8,10],[15,18]]},
                "expected_output": [[1,6],[8,10],[15,18]],
                "is_sample": true
            }
        ]
    }"""
    spec = normalizer.parse(json_str)

    assert spec.id == "merge-intervals"
    assert spec.title == "Merge Intervals"
    assert spec.difficulty == Difficulty.MEDIUM
    assert spec.function_name == "merge"
    assert spec.param_names == ["intervals"]
    assert len(spec.test_cases) == 1
    assert spec.test_cases[0].expected_output == [[1, 6], [8, 10], [15, 18]]
    assert not spec.is_ambiguous
