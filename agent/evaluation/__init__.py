"""Evaluation package for Stage 24 Unseen Generalization & Leakage Prevention."""
from agent.evaluation.models import (
    DatasetSplit,
    ProblemSourceType,
    ProblemMetadata,
    LeakageAuditRecord,
)
from agent.evaluation.leakage_detector import LeakageDetector
from agent.evaluation.dataset_registry import DatasetRegistry, HELD_OUT_PROBLEMS_DEFS

__all__ = [
    "DatasetSplit",
    "ProblemSourceType",
    "ProblemMetadata",
    "LeakageAuditRecord",
    "LeakageDetector",
    "DatasetRegistry",
    "HELD_OUT_PROBLEMS_DEFS",
]
