"""
Structured Schemas for Model-Backed DSA Solving, Planning, and Repair.
Ensures machine-checkable, validated JSON outputs from model providers.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class ModelCandidateApproach(BaseModel):
    """Candidate algorithm approach proposed by the model."""
    name: str = Field(description="Name of the algorithmic approach, e.g. 'Two-Pointer Sliding Window'")
    data_structures: List[str] = Field(description="Primary data structures, e.g. ['Hash Map', 'Two Pointers']")
    time_complexity: str = Field(description="Big-O time complexity, e.g. 'O(N)'")
    space_complexity: str = Field(description="Big-O space complexity, e.g. 'O(1)'")
    description: str = Field(description="Brief explanation of how the approach solves the problem")
    correctness_argument: str = Field(description="Correctness argument justifying why this approach produces valid results")


class ModelAlgorithmPlan(BaseModel):
    """Structured algorithm planning response from model."""
    candidate_approaches: List[ModelCandidateApproach] = Field(description="Alternative candidate algorithms considered")
    selected_approach_index: int = Field(default=0, description="0-based index of the chosen candidate approach")
    selection_justification: str = Field(description="Why this approach was selected given problem bounds and constraints")
    time_complexity: str = Field(description="Formal Big-O time complexity of selected approach")
    space_complexity: str = Field(description="Formal Big-O space complexity of selected approach")
    edge_cases: List[str] = Field(default_factory=list, description="Critical edge cases and boundary conditions identified")


class ModelCodeGeneration(BaseModel):
    """Structured code generation response from model."""
    language: str = Field(description="Target programming language (c, cpp, java, python)")
    source_code: str = Field(description="Complete, executable implementation adhering strictly to problem signature")
    algorithmic_invariants: List[str] = Field(default_factory=list, description="Key invariants maintained by the code")
    complexity_explanation: str = Field(description="Explanation of why this implementation achieves planned complexity")


class ModelRepairResponse(BaseModel):
    """Structured code repair response from model."""
    root_cause_analysis: str = Field(description="Analysis of why the failure occurred based on the diagnostic report")
    faulty_component: str = Field(description="Specific logic, boundary, or condition that was defective")
    repaired_source_code: str = Field(description="Complete, corrected source code with the bug resolved")
    patch_summary: str = Field(description="Concise description of the specific fix applied")
