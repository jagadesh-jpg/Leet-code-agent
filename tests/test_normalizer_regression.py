"""
Regression tests for Task 2:
Problem title normalization with markdown headers, trailing newlines, descriptions, and punctuation.
"""

import pytest
from agent.core.normalizer import ProblemNormalizer
from agent.core.models import Difficulty


def test_markdown_title_followed_by_newline_and_description():
    normalizer = ProblemNormalizer()
    raw_markdown = "# 1. Two Sum\\n\\nGiven an array of integers nums and an integer target, return indices of the two numbers such that they add up to target.\\nYou may assume that each input would have exactly one solution."
    spec = normalizer.parse(
        raw_markdown,
        problem_id="1",
    )
    assert spec.title == "1. Two Sum"
    assert "Two Sum" in spec.title
    assert "Given an array" not in spec.title
    assert "Two Sum" not in spec.description or len(spec.description) > len(spec.title)


def test_markdown_title_with_real_newlines_and_description():
    normalizer = ProblemNormalizer()
    raw_markdown = "# Reverse Linked List\n\nGiven the head of a singly linked list, reverse the list, and return the reversed list."
    spec = normalizer.parse(
        raw_markdown,
        problem_id="206",
    )
    assert spec.title == "Reverse Linked List"
    assert "Given" not in spec.title


def test_markdown_title_with_difficulty_label():
    normalizer = ProblemNormalizer()
    raw_markdown = "## 121. Best Time to Buy and Sell Stock (Easy)\n\nYou are given an array prices where prices[i] is the price of a given stock on the ith day."
    spec = normalizer.parse(
        raw_markdown,
        problem_id="121",
    )
    assert spec.title == "121. Best Time to Buy and Sell Stock"
    assert spec.difficulty == Difficulty.EASY


def test_title_with_punctuation_and_symbols():
    normalizer = ProblemNormalizer()
    raw_markdown = "# 3Sum Closest\nGiven an integer array nums of length n..."
    spec = normalizer.parse(
        raw_markdown,
        problem_id="16",
    )
    assert spec.title == "3Sum Closest"

    raw_markdown2 = "# Valid Parentheses\nGiven a string s containing just the characters..."
    spec2 = normalizer.parse(
        raw_markdown2,
        problem_id="20",
    )
    assert spec2.title == "Valid Parentheses"


def test_standalone_title_in_json():
    normalizer = ProblemNormalizer()
    raw_json = '{"id": "70", "title": "Climbing Stairs", "description": "You are climbing a staircase. It takes n steps to reach the top.", "param_names": ["n"]}'
    spec = normalizer.parse(raw_json)
    assert spec.title == "Climbing Stairs"
    assert spec.function_name == "climbingStairs" or spec.function_name == "climbStairs"
