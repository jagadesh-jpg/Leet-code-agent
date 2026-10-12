"""Deterministic Problem Validator and Normalizer for Dynamic Intake (Stage 19).

Validates:
- Title, statement, input/output description, constraints, examples.
- Supported languages (c, cpp, java, python).
- Distinguishes VALID, INVALID_PROBLEM, and INCOMPLETE_PROBLEM.
- Preserves explicit/inferred/unknown semantics without inventing facts.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from agent.core.models import (
    ProblemSpec,
    SupportedLanguage,
)
from agent.core.normalizer import ProblemNormalizer
from agent.intake.models import (
    IntakeValidationStatus,
    ProblemValidationReport,
)


class ProblemValidator:
    """
    Validates dynamic problem submissions.
    Ensures input is non-empty, well-formed, distinguishes valid from incomplete or malformed problems.
    """

    SUPPORTED_LANGUAGES = {
        "c": SupportedLanguage.C,
        "cpp": SupportedLanguage.CPP,
        "c++": SupportedLanguage.CPP,
        "java": SupportedLanguage.JAVA,
        "python": SupportedLanguage.PYTHON,
        "py": SupportedLanguage.PYTHON,
    }

    @classmethod
    def validate(
        cls,
        raw_input: Union[str, Dict[str, Any], ProblemSpec],
        preferred_language: Optional[Union[str, SupportedLanguage]] = None,
    ) -> Tuple[ProblemValidationReport, Optional[ProblemSpec]]:
        """
        Validates problem input and returns (Report, Optional[ProblemSpec]).
        Distinguishes:
        - VALID
        - INVALID_PROBLEM
        - INCOMPLETE_PROBLEM
        """
        report = ProblemValidationReport(status=IntakeValidationStatus.INVALID_PROBLEM)

        # 1. Language validation
        selected_lang: Optional[SupportedLanguage] = None
        if preferred_language is not None:
            if isinstance(preferred_language, SupportedLanguage):
                selected_lang = preferred_language
            elif isinstance(preferred_language, str):
                normalized_lang = preferred_language.strip().lower()
                if normalized_lang in cls.SUPPORTED_LANGUAGES:
                    selected_lang = cls.SUPPORTED_LANGUAGES[normalized_lang]
                else:
                    report.status = IntakeValidationStatus.INVALID_PROBLEM
                    report.language_valid = False
                    report.issues.append(f"Unsupported language requested: '{preferred_language}'. Supported: C, C++, Java, Python.")
                    return report, None
        else:
            # Deterministic default policy: Default to SupportedLanguage.PYTHON
            selected_lang = SupportedLanguage.PYTHON

        report.selected_language = selected_lang

        # 2. Check input types
        if raw_input is None:
            report.status = IntakeValidationStatus.INVALID_PROBLEM
            report.issues.append("Problem input cannot be null.")
            return report, None

        # Case A: Already a canonical ProblemSpec
        if isinstance(raw_input, ProblemSpec):
            return cls._validate_problem_spec(raw_input, report)

        # Case B: Dictionary / Structured JSON
        if isinstance(raw_input, dict):
            return cls._validate_dict(raw_input, report)

        # Case C: String (JSON string or Markdown/Text)
        if isinstance(raw_input, str):
            clean_str = raw_input.strip()
            if not clean_str:
                report.status = IntakeValidationStatus.INVALID_PROBLEM
                report.issues.append("Problem input string is empty or contains only whitespace.")
                return report, None

            # Try parsing JSON string first
            if clean_str.startswith("{") or clean_str.startswith("["):
                try:
                    parsed_json = json.loads(clean_str)
                    if isinstance(parsed_json, dict):
                        return cls._validate_dict(parsed_json, report)
                    else:
                        report.status = IntakeValidationStatus.INVALID_PROBLEM
                        report.issues.append("JSON input must be an object representing a problem, not an array or primitive.")
                        return report, None
                except json.JSONDecodeError as jde:
                    report.status = IntakeValidationStatus.INVALID_PROBLEM
                    report.issues.append(f"Malformed JSON syntax: {jde.msg} at line {jde.lineno} col {jde.colno}.")
                    return report, None

            # Parse Markdown / Plain Text
            return cls._validate_text(clean_str, report)

        report.status = IntakeValidationStatus.INVALID_PROBLEM
        report.issues.append(f"Unsupported problem input type: {type(raw_input).__name__}")
        return report, None

    @classmethod
    def _validate_problem_spec(
        cls,
        spec: ProblemSpec,
        report: ProblemValidationReport,
    ) -> Tuple[ProblemValidationReport, Optional[ProblemSpec]]:
        report.title = spec.title
        report.has_statement = bool(spec.description or spec.raw_statement)
        report.has_constraints = bool(spec.constraints or spec.structured_constraints)
        report.has_examples = bool(spec.test_cases)
        report.has_input_format = bool(spec.param_names)
        report.has_output_format = bool(spec.return_type and spec.return_type != "Any")

        if not spec.title or spec.title == "Untitled Problem":
            report.missing_fields.append("title")
        if not report.has_statement:
            report.missing_fields.append("statement")
        if not report.has_examples:
            report.missing_fields.append("examples")

        if report.missing_fields:
            # If critical statement or examples missing
            if not report.has_statement:
                report.status = IntakeValidationStatus.INVALID_PROBLEM
                report.issues.append("ProblemSpec missing description and raw_statement.")
                return report, None
            else:
                report.status = IntakeValidationStatus.INCOMPLETE_PROBLEM
                report.issues.append(f"ProblemSpec incomplete; missing: {', '.join(report.missing_fields)}")
                report.is_acceptable = True
                return report, spec

        report.status = IntakeValidationStatus.VALID
        report.is_acceptable = True
        return report, spec

    @classmethod
    def _validate_dict(
        cls,
        data: Dict[str, Any],
        report: ProblemValidationReport,
    ) -> Tuple[ProblemValidationReport, Optional[ProblemSpec]]:
        title = data.get("title") or data.get("name") or ""
        statement = data.get("statement") or data.get("description") or data.get("problem") or ""
        input_desc = data.get("input_format") or data.get("input_info") or data.get("param_names") or ""
        output_desc = data.get("output_format") or data.get("output_info") or data.get("return_type") or ""
        constraints = data.get("constraints") or []
        examples = data.get("examples") or data.get("test_cases") or []

        # Check explicit preferred language in dict
        if "preferred_language" in data and data["preferred_language"]:
            lang_str = str(data["preferred_language"]).strip().lower()
            if lang_str in cls.SUPPORTED_LANGUAGES:
                report.selected_language = cls.SUPPORTED_LANGUAGES[lang_str]
            else:
                report.status = IntakeValidationStatus.INVALID_PROBLEM
                report.language_valid = False
                report.issues.append(f"Unsupported language in problem payload: '{lang_str}'")
                return report, None

        report.title = str(title).strip()
        report.has_statement = bool(str(statement).strip())
        report.has_input_format = bool(input_desc)
        report.has_output_format = bool(output_desc)
        report.has_constraints = bool(constraints)
        report.has_examples = bool(examples)

        if not report.has_statement:
            report.status = IntakeValidationStatus.INVALID_PROBLEM
            report.issues.append("Problem statement/description cannot be empty.")
            return report, None

        if not report.title:
            report.missing_fields.append("title")
        if not report.has_examples:
            report.missing_fields.append("examples")
        if not report.has_constraints:
            report.missing_fields.append("constraints")

        # Convert to canonical ProblemSpec using ProblemNormalizer
        normalizer = ProblemNormalizer()
        try:
            norm_data = dict(data)
            if "examples" in norm_data and "test_cases" not in norm_data:
                norm_data["test_cases"] = norm_data["examples"]
            raw_text = json.dumps(norm_data)
            spec = normalizer.parse(raw_text, problem_id=data.get("id"))
        except Exception as e:
            report.status = IntakeValidationStatus.INVALID_PROBLEM
            report.issues.append(f"Failed to normalize structured dictionary: {e}")
            return report, None

        if report.missing_fields and ("title" in report.missing_fields or "examples" in report.missing_fields):
            report.status = IntakeValidationStatus.INCOMPLETE_PROBLEM
            report.issues.append(f"Incomplete problem specification; missing: {', '.join(report.missing_fields)}")
            report.is_acceptable = True
            return report, spec

        report.status = IntakeValidationStatus.VALID
        report.is_acceptable = True
        return report, spec

    @classmethod
    def _validate_text(
        cls,
        text: str,
        report: ProblemValidationReport,
    ) -> Tuple[ProblemValidationReport, Optional[ProblemSpec]]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            report.status = IntakeValidationStatus.INVALID_PROBLEM
            report.issues.append("Problem text contains no readable lines.")
            return report, None

        # Check for title
        normalizer = ProblemNormalizer()
        try:
            spec = normalizer.parse(text)
        except Exception as e:
            report.status = IntakeValidationStatus.INVALID_PROBLEM
            report.issues.append(f"Normalizer rejected text input: {e}")
            return report, None

        report.title = spec.title
        report.has_statement = bool(spec.description)
        report.has_constraints = bool(spec.constraints)
        report.has_examples = bool(spec.test_cases)
        report.has_input_format = bool(spec.param_names and spec.param_names != ["arg1"])
        report.has_output_format = bool(spec.return_type and spec.return_type != "Any")

        if not report.has_statement or report.title == "Untitled Problem":
            if not report.has_statement:
                report.status = IntakeValidationStatus.INVALID_PROBLEM
                report.issues.append("Missing core problem statement.")
                return report, None
            else:
                report.missing_fields.append("title")

        if not report.has_examples:
            report.missing_fields.append("examples")
        if not report.has_constraints:
            report.missing_fields.append("constraints")

        if report.missing_fields:
            report.status = IntakeValidationStatus.INCOMPLETE_PROBLEM
            report.issues.append(f"Problem text lacks: {', '.join(report.missing_fields)}")
            report.is_acceptable = True
            return report, spec

        report.status = IntakeValidationStatus.VALID
        report.is_acceptable = True
        return report, spec
