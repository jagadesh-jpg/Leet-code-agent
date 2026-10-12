"""Normalizer for LeetCode data structures into Canonical ProblemSpec (Stage 31).

Converts rich LeetCode problem payloads (HTML/text, code snippets, metadata)
into the agent's strongly-typed ProblemSpec without losing context or inventing facts.
"""

import html
import json
import re
from typing import Any, Dict, List, Optional

from agent.core.models import (
    ConfidenceLevel,
    ConstraintItem,
    Difficulty,
    EdgeCaseItem,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCategory,
    TypedField,
)
from agent.core.normalizer import ProblemNormalizer
from agent.leetcode.models import LeetCodeProblemDetail


class LeetCodeProblemAdapter:
    """Normalizes LeetCode problem responses into the agent's ProblemSpec."""

    @staticmethod
    def html_to_markdown_or_text(html_content: str) -> str:
        """Converts basic HTML formatting from LeetCode problem statements into plain text/markdown."""
        if not html_content:
            return ""

        text = html_content
        # Replace <p> and </p>
        text = re.sub(r"<\s*p\s*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<\s*/p\s*>", "\n\n", text, flags=re.IGNORECASE)

        # Replace <br> and <br/>
        text = re.sub(r"<\s*br\s*/?>", "\n", text, flags=re.IGNORECASE)

        # Replace strong, b
        text = re.sub(r"<\s*(?:strong|b)\s*>", "**", text, flags=re.IGNORECASE)
        text = re.sub(r"<\s*/(?:strong|b)\s*>", "**", text, flags=re.IGNORECASE)

        # Replace em, i
        text = re.sub(r"<\s*(?:em|i)\s*>", "*", text, flags=re.IGNORECASE)
        text = re.sub(r"<\s*/(?:em|i)\s*>", "*", text, flags=re.IGNORECASE)

        # Replace code tags
        text = re.sub(r"<\s*code\s*>", "`", text, flags=re.IGNORECASE)
        text = re.sub(r"<\s*/code\s*>", "`", text, flags=re.IGNORECASE)

        # Replace pre tags
        text = re.sub(r"<\s*pre\s*>", "\n```\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<\s*/pre\s*>", "\n```\n", text, flags=re.IGNORECASE)

        # Replace li tags
        text = re.sub(r"<\s*li\s*>", "- ", text, flags=re.IGNORECASE)
        text = re.sub(r"<\s*/li\s*>", "\n", text, flags=re.IGNORECASE)

        # Strip remaining tags
        text = re.sub(r"<[^>]+>", "", text)

        # Unescape HTML entities
        text = html.unescape(text)

        # Clean multiple blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def to_problem_spec(
        cls,
        detail: LeetCodeProblemDetail,
        preferred_lang: Optional[SupportedLanguage] = None,
    ) -> ProblemSpec:
        """Normalizes LeetCodeProblemDetail into canonical ProblemSpec using existing ProblemNormalizer."""
        # 1. Obtain clean text
        content_text = detail.content_text or cls.html_to_markdown_or_text(detail.content_html)

        # 2. Extract starter code for method signature inference
        starter_code = ""
        lang_key = "python3"
        if preferred_lang == SupportedLanguage.CPP:
            lang_key = "cpp"
        elif preferred_lang == SupportedLanguage.JAVA:
            lang_key = "java"
        elif preferred_lang == SupportedLanguage.C:
            lang_key = "c"

        for snippet in detail.code_snippets:
            if snippet.lang_slug == lang_key:
                starter_code = snippet.code
                break

        # Fallback to python3 snippet if preferred not found
        if not starter_code:
            for snippet in detail.code_snippets:
                if snippet.lang_slug == "python3" or snippet.lang_slug == "python":
                    starter_code = snippet.code
                    break

        full_raw_text = f"# {detail.title} [{detail.difficulty}]\n\n{content_text}"
        if starter_code:
            full_raw_text += f"\n\n```\n{starter_code}\n```\n"

        # 3. Parse with ProblemNormalizer
        normalizer = ProblemNormalizer()
        spec = normalizer.parse(full_raw_text, problem_id=detail.title_slug)

        # 4. Enrich spec with verified LeetCode metadata
        spec.title = detail.title
        spec.id = detail.title_slug

        # Set difficulty
        diff_str = detail.difficulty.capitalize()
        if diff_str in ("Easy", "Medium", "Hard"):
            spec.difficulty = Difficulty(diff_str)

        # Incorporate example test cases from GraphQL if test_cases in spec is sparse
        if detail.example_test_cases and len(spec.test_cases) == 0:
            for i, etc in enumerate(detail.example_test_cases):
                # Try to map line-by-line inputs
                spec.test_cases.append(
                    TestCase(
                        id=f"lc_sample_{i+1}",
                        inputs={"raw_input": etc},
                        expected_output=None,
                        category=TestCategory.EXAMPLE,
                        is_sample=True,
                    )
                )

        return spec
