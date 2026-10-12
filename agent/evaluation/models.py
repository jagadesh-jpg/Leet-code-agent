"""
Stage 24: Dataset Partitioning, Metadata Schemas & Leakage Prevention Models.
Strict separation of Development (train/tuning), Validation, and Held-Out Test sets.
Tracks split membership, source attribution, fingerprints, and leakage audits.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agent.core.models import (
    ProblemSpec,
    SupportedLanguage,
)


class DatasetSplit(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"    # Tuning, prompt engineering, strategy baseline calibration
    VALIDATION = "VALIDATION"      # Hyperparameter selection, checkpoint evaluation
    HELD_OUT_TEST = "HELD_OUT_TEST"  # Strictly isolated, unseen test set for final evaluation


class ProblemSourceType(str, Enum):
    EXTERNAL_CANONICAL = "EXTERNAL_CANONICAL"  # Sourced from standard competitive programming
    USER_PROVIDED = "USER_PROVIDED"            # Provided via JSON / Markdown intake
    SYNTHETIC_BENCHMARK = "SYNTHETIC_BENCHMARK"  # Generated / synthetic benchmark variants


class ProblemMetadata(BaseModel):
    """
    Metadata annotating dataset split membership, origin, and fingerprints.
    """
    problem_id: str
    split: DatasetSplit
    dataset_version: str = "v1.0"
    source_type: ProblemSourceType = ProblemSourceType.EXTERNAL_CANONICAL
    source_attribution: Optional[str] = None
    exact_fingerprint: str
    token_fingerprint: str
    created_at: Optional[str] = None
    is_held_out: bool = False


class LeakageAuditRecord(BaseModel):
    """
    Audit record reporting potential contamination or leakage for a problem.
    """
    problem_id: str
    target_split: DatasetSplit
    has_exact_leakage: bool = False
    has_near_duplicate_leakage: bool = False
    has_memory_leakage: bool = False
    has_registry_leakage: bool = False
    leakage_details: List[str] = Field(default_factory=list)
    is_contaminated: bool = False
    status: str = Field(default="CLEAN", description="'CLEAN', 'CONTAMINATED', or 'INCONCLUSIVE'")
