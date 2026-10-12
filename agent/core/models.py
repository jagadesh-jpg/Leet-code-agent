"""
Core Data Models for Autonomous DSA Coding Agent.
Defines strongly typed schemas for problems, test cases, execution results,
failure classifications, and agent state transitions.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SupportedLanguage(str, Enum):
    PYTHON = "python"
    CPP = "cpp"
    C = "c"
    JAVA = "java"


class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    COMPILE_ERROR = "compile_error"
    RUNTIME_ERROR = "runtime_error"
    TIMEOUT = "timeout"
    WRONG_ANSWER = "wrong_answer"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


class FailureCategory(str, Enum):
    COMPILE_ERROR = "COMPILE_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    TIME_LIMIT_EXCEEDED = "TIME_LIMIT_EXCEEDED"
    MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"
    WRONG_ANSWER = "WRONG_ANSWER"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    EMPTY_OUTPUT = "EMPTY_OUTPUT"
    SEGMENTATION_FAULT = "SEGMENTATION_FAULT"
    INFINITE_LOOP = "INFINITE_LOOP"
    LOGICAL_ERROR = "LOGICAL_ERROR"
    ALGORITHM_TOO_SLOW = "ALGORITHM_TOO_SLOW"
    EDGE_CASE_FAILURE = "EDGE_CASE_FAILURE"
    FORMAT_ERROR = "FORMAT_ERROR"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    ORACLE_ERROR = "ORACLE_ERROR"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class AgentState(str, Enum):
    IDLE = "IDLE"
    NORMALIZING_PROBLEM = "NORMALIZING_PROBLEM"
    ANALYZING_PROBLEM = "ANALYZING_PROBLEM"
    PLANNING_ALGORITHM = "PLANNING_ALGORITHM"
    GENERATING_CODE = "GENERATING_CODE"
    COMPILING = "COMPILING"
    EXECUTING_TESTS = "EXECUTING_TESTS"
    ANALYZING_FAILURE = "ANALYZING_FAILURE"
    REPAIRING = "REPAIRING"
    RETESTING = "RETESTING"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    MAX_ATTEMPTS_REACHED = "MAX_ATTEMPTS_REACHED"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"


class TestCategory(str, Enum):
    __test__ = False
    EXAMPLE = "example"
    BASIC = "basic"
    EDGE_CASE = "edge_case"
    BOUNDARY = "boundary"
    DUPLICATE = "duplicate"
    SINGLE_ELEMENT = "single_element"
    ALL_EQUAL = "all_equal"
    NEGATIVE_ZERO = "negative_zero"
    LARGE_VALUE = "large_value"
    ADVERSARIAL = "adversarial"
    RANDOMIZED = "randomized"
    STRESS = "stress"


class OracleType(str, Enum):
    PROBLEM_SPEC = "problem_spec"            # Stated directly in problem statement / examples
    DERIVED = "derived"                      # Deterministically derived expected output
    TRUSTED_REFERENCE = "trusted_reference"  # Computed by simple trusted baseline / brute force
    REFERENCE_ALGO = "reference_algo"        # Alias / legacy for trusted reference
    MATHEMATICAL = "mathematical"            # Mathematical property / closed-form formula
    METAMORPHIC = "metamorphic"              # Metamorphic / property invariance
    GENERATED = "generated"                  # AI-generated oracle
    UNAVAILABLE = "unavailable"              # No oracle / expected output available


class TestCase(BaseModel):
    """A single input/output test case."""
    __test__ = False  # Prevent pytest from treating this Pydantic model as a test suite
    id: str = Field(description="Unique identifier for the test case")
    inputs: Dict[str, Any] = Field(description="Parameter name to input value mapping")
    expected_output: Any = Field(description="Expected return value or output")
    category: TestCategory = Field(default=TestCategory.BASIC, description="Category of this test case")
    oracle_type: OracleType = Field(default=OracleType.PROBLEM_SPEC, description="Source of truth for expected output")
    rationale: Optional[str] = Field(default=None, description="Why this test case is included")
    random_seed: Optional[int] = Field(default=None, description="Deterministic seed if randomly generated")
    description: Optional[str] = Field(default=None, description="Optional explanation or category")
    is_sample: bool = Field(default=False, description="Whether this is a problem statement example")
    is_edge_case: bool = Field(default=False, description="Whether this targets boundary/edge conditions")


class Difficulty(str, Enum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"
    UNKNOWN = "Unknown"


class ConfidenceLevel(str, Enum):
    EXPLICIT = "explicit"      # Directly stated verbatim in problem text
    INFERRED = "inferred"      # Derived logically from constraints/statement
    UNKNOWN = "unknown"        # Ambiguous, cannot be reliably confirmed


class TypedField(BaseModel):
    name: str = Field(description="Variable or parameter name")
    type_str: str = Field(default="Any", description="Detected or inferred type string")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.EXPLICIT)
    description: Optional[str] = None


class ConstraintItem(BaseModel):
    statement: str = Field(description="Constraint text")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.EXPLICIT)
    variable: Optional[str] = Field(default=None, description="Affected variable if identified")
    min_val: Optional[str] = Field(default=None, description="Lower bound if numeric")
    max_val: Optional[str] = Field(default=None, description="Upper bound if numeric")


class EdgeCaseItem(BaseModel):
    description: str = Field(description="Description of boundary or edge situation")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.INFERRED)
    example_input: Optional[Dict[str, Any]] = None


class ProblemSpec(BaseModel):
    """Canonical representation of a DSA problem."""
    id: str = Field(description="Unique problem identifier (e.g., 'two-sum')")
    title: str = Field(description="Problem title")
    description: str = Field(description="Cleaned, normalized problem statement")
    raw_statement: str = Field(default="", description="Original, unadulterated source statement")
    difficulty: Difficulty = Field(default=Difficulty.UNKNOWN, description="Difficulty if available")
    function_name: str = Field(description="Target function/method name to solve")
    param_names: List[str] = Field(description="Ordered list of argument names")
    params_schema: List[TypedField] = Field(default_factory=list, description="Typed parameter details")
    return_type: str = Field(default="Any", description="Target return type description (e.g., 'List[int]')")
    constraints: List[str] = Field(default_factory=list, description="Raw constraint strings")
    structured_constraints: List[ConstraintItem] = Field(default_factory=list, description="Detailed constraint objects")
    edge_cases: List[EdgeCaseItem] = Field(default_factory=list, description="Explicit or inferred edge cases")
    test_cases: List[TestCase] = Field(default_factory=list, description="Test suite for verification")
    is_ambiguous: bool = Field(default=False, description="True if critical problem attributes are missing/uncertain")
    ambiguity_notes: List[str] = Field(default_factory=list, description="Identified ambiguities or missing specs")


class TestCaseResult(BaseModel):
    """Result of running code against a single test case."""
    __test__ = False
    test_case_id: str
    passed: bool
    input_data: Dict[str, Any]
    expected_output: Any
    actual_output: Optional[Any] = None
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0
    category: Optional[TestCategory] = None
    oracle_type: Optional[OracleType] = None
    random_seed: Optional[int] = None


class ExecutionResult(BaseModel):
    """Deterministic, structured output from running or compiling code."""
    status: ExecutionStatus
    failure_category: Optional[FailureCategory] = None
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    execution_time_ms: float = 0.0
    memory_bytes: Optional[int] = None
    test_results: List[TestCaseResult] = Field(default_factory=list)
    compile_output: Optional[str] = None
    error_detail: Optional[str] = None


class TestSuiteReport(BaseModel):
    """Aggregated report of test suite execution and differential validation."""
    __test__ = False
    all_passed: bool
    total_tests: int
    passed_count: int
    failed_count: int
    execution_status: ExecutionStatus
    failure_category: Optional[FailureCategory] = None
    failed_test_results: List[TestCaseResult] = Field(default_factory=list)
    all_test_results: List[TestCaseResult] = Field(default_factory=list)
    raw_execution_result: Optional[ExecutionResult] = None
    oracle_failure_detected: bool = False
    notes: List[str] = Field(default_factory=list)
    # Stage 21 Adaptive Testing Metadata
    adaptive_rounds_executed: int = 0
    targeted_tests_generated: int = 0
    deduplicated_tests_count: int = 0
    risk_signals_evaluated: List[str] = Field(default_factory=list)



class FailureSeverity(str, Enum):
    CRITICAL = "CRITICAL"  # Blocker: Infrastructure or Compilation error
    HIGH = "HIGH"          # Runtime exception, TLE, or Security violation
    MEDIUM = "MEDIUM"      # Algorithmic Wrong Answer or Edge Case failure
    LOW = "LOW"            # Formatting or performance warning


class RootCauseHypothesis(BaseModel):
    """A ranked hypothesis explaining the root cause."""
    hypothesis: str = Field(description="Descriptive root cause (e.g. 'Off-by-one boundary condition')")
    confidence: ConfidenceLevel = Field(description="Confidence in this hypothesis based on evidence")
    supporting_evidence: List[str] = Field(default_factory=list, description="Concrete observations supporting this cause")


class FailureReport(BaseModel):
    """Structured, machine-readable diagnostic report produced by FailureAnalyzer."""
    failure_id: str = Field(description="Unique identifier for this diagnostic failure report")
    failure_category: FailureCategory = Field(description="Normalized failure classification")
    severity: FailureSeverity = Field(default=FailureSeverity.MEDIUM, description="Impact severity of failure")
    affected_test_ids: List[str] = Field(default_factory=list, description="IDs of test cases failing with this issue")
    sample_failing_input: Optional[Dict[str, Any]] = None
    expected_output: Optional[Any] = None
    actual_output: Optional[Any] = None
    error_message: Optional[str] = None
    exit_code: Optional[int] = None
    source_line: Optional[int] = Field(default=None, description="Mapped source code line number where failure occurred")
    source_excerpt: Optional[str] = Field(default=None, description="Source lines surrounding the failure point")
    ranked_hypotheses: List[RootCauseHypothesis] = Field(default_factory=list, description="Ranked probable causes")
    is_infrastructure_failure: bool = Field(default=False, description="True if host/compiler/oracle failed rather than solution")
    uncertainty_notes: List[str] = Field(default_factory=list, description="Unresolved ambiguities or lack of evidence")
    recommended_diagnostic_direction: Optional[str] = Field(default=None, description="Actionable hint for debugging/repair layer")


class DSAPattern(str, Enum):
    ARRAYS_STRINGS = "Arrays & Strings"
    HASH_TABLE = "Hash Table / Set"
    TWO_POINTERS = "Two Pointers"
    SLIDING_WINDOW = "Sliding Window"
    PREFIX_SUM = "Prefix Sum / Difference Array"
    BINARY_SEARCH = "Binary Search"
    SORTING_SEARCHING = "Sorting & Searching"
    LINKED_LIST = "Linked List"
    STACK = "Stack / Monotonic Stack"
    QUEUE_DEQUE = "Queue / Monotonic Queue"
    BINARY_TREE = "Binary Tree / BST"
    HEAP_PRIORITY_QUEUE = "Heap / Priority Queue"
    GRAPH_BFS_DFS = "Graph Traversal (BFS/DFS)"
    SHORTEST_PATH = "Shortest Path (Dijkstra/Bellman-Ford/Floyd-Warshall)"
    MINIMUM_SPANNING_TREE = "Minimum Spanning Tree (Kruskal/Prim)"
    TOPOLOGICAL_SORT = "Topological Sort"
    UNION_FIND = "Union-Find / DSU"
    TRIE = "Trie"
    BACKTRACKING_RECURSION = "Backtracking & Recursion"
    DYNAMIC_PROGRAMMING = "Dynamic Programming (1D/2D/State-Machine)"
    GREEDY = "Greedy Algorithm"
    INTERVALS = "Intervals / Sweep-Line"
    BIT_MANIPULATION = "Bit Manipulation"
    MATH_NUMBER_THEORY = "Math & Number Theory"
    DIVIDE_AND_CONQUER = "Divide and Conquer"
    UNKNOWN = "Unknown / Ad-hoc"


class CandidateApproach(BaseModel):
    """A candidate algorithmic solution evaluated during planning."""
    name: str = Field(description="Descriptive name (e.g. 'Brute Force Nested Loop', 'Hash Map Lookup')")
    data_structures: List[str] = Field(description="Primary data structures employed")
    time_complexity: str = Field(description="Big-O asymptotic time complexity (e.g., 'O(N^2)', 'O(N)')")
    space_complexity: str = Field(description="Big-O auxiliary space complexity (e.g., 'O(1)', 'O(N)')")
    description: str = Field(description="Step-by-step summary of this approach")
    satisfies_constraints: bool = Field(description="True if time/space bounds meet problem limits")
    rejection_reason: Optional[str] = Field(default=None, description="Explicit reason if rejected")


class AlgorithmPlan(BaseModel):
    """Structured plan produced by the Algorithm Planning layer."""
    problem_id: str
    identified_patterns: List[DSAPattern] = Field(description="Detected DSA patterns")
    candidate_approaches: List[CandidateApproach] = Field(description="Evaluated candidates")
    selected_approach: CandidateApproach = Field(description="The chosen approach for code generation")
    justification: str = Field(description="Why the selected approach is correct and optimal")
    constraints_validated: bool = Field(description="Whether explicit constraint limits were verified")
    constraints_uncertain: bool = Field(default=False, description="True if constraints were missing/ambiguous")
    edge_cases_considered: List[str] = Field(default_factory=list, description="Specific edge cases handled")
    assumptions_and_notes: List[str] = Field(default_factory=list, description="Assumptions or uncertainties")


class StaticValidationResult(BaseModel):
    """Result of deterministic static AST analysis / security linting."""
    is_valid: bool = Field(description="True if syntactically valid and compliant with sandbox policy")
    has_syntax_error: bool = Field(default=False, description="True if source failed syntactic parsing")
    has_security_violation: bool = Field(default=False, description="True if source attempted prohibited operations")
    violation_details: List[str] = Field(default_factory=list, description="Descriptions of any syntax or policy violations")
    ast_tree_verified: bool = Field(default=False, description="True if AST was successfully constructed and inspected")


class GeneratedCode(BaseModel):
    """Structured output from the Code Generation layer."""
    problem_id: str = Field(description="Identifier of the solved problem")
    target_language: SupportedLanguage = Field(description="Target programming language")
    source_code: str = Field(description="Raw generated source code")
    algorithm_name: str = Field(description="Name of the algorithm selected from the plan")
    expected_time_complexity: str = Field(description="Target time complexity from plan")
    expected_space_complexity: str = Field(description="Target space complexity from plan")
    validation_result: Optional[StaticValidationResult] = Field(default=None, description="Deterministic static check results")
    generation_metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata such as generator model, timestamps, etc.")


class RepairAttempt(BaseModel):
    """Structured record of a single repair cycle within the self-correction loop."""
    attempt_number: int = Field(description="1-indexed cycle sequence number")
    state_at_start: AgentState = Field(description="Agent state prior to repair")
    source_hash_before: str = Field(description="SHA256 hex digest of source code before patch")
    source_code_before: str = Field(description="Source code prior to repair")
    source_hash_after: str = Field(description="SHA256 hex digest of source code after patch")
    source_code_after: str = Field(description="Patched source code")
    failure_addressed: FailureReport = Field(description="The diagnostic failure report being resolved")
    patch_summary: str = Field(description="Brief explanation of the applied correction")
    tests_passed: int = Field(default=0, description="Passing regression tests in this cycle")
    tests_failed: int = Field(default=0, description="Failing regression tests in this cycle")
    ast_valid: bool = Field(default=True, description="True if repaired code passed AST & security check")
    resulting_state: AgentState = Field(description="Final state reached after this attempt")


class SelfCorrectionSession(BaseModel):
    """Observability record of the complete autonomous problem-solving run."""
    session_id: str = Field(description="Unique run identifier")
    problem_id: str = Field(description="Problem ID")
    language: SupportedLanguage = Field(description="Target programming language")
    max_attempts: int = Field(default=5, description="Configured upper limit for repairs")
    total_attempts: int = Field(default=0, description="Number of attempts performed")
    final_state: AgentState = Field(description="Terminal state reached by the loop")
    is_verified: bool = Field(default=False, description="True if all tests passed and verified")
    initial_code: Optional[str] = None
    verified_code: Optional[str] = None
    plan: Optional[AlgorithmPlan] = None
    attempt_history: List[RepairAttempt] = Field(default_factory=list, description="Audit trail of all cycles")
    verification_report: Optional[Any] = Field(default=None, description="Final verification report from Stage 10")
    final_test_report: Optional[TestSuiteReport] = Field(default=None, description="Final test execution report")
    error_summary: Optional[str] = None
    strategy_bundle: Optional[Any] = Field(default=None, description="Stage 23 Strategy decisions bundle")


# --- STAGE 10: SOLUTION VERIFICATION & ASYMPTOTIC COMPLEXITY AUDIT SCHEMAS ---

class VerificationStatus(str, Enum):
    """Explicit certification statuses for solution verification."""
    VERIFIED = "VERIFIED"
    VERIFIED_WITH_WARNINGS = "VERIFIED_WITH_WARNINGS"
    CORRECTNESS_VERIFIED_COMPLEXITY_UNCERTAIN = "CORRECTNESS_VERIFIED_COMPLEXITY_UNCERTAIN"
    FAILED_CORRECTNESS = "FAILED_CORRECTNESS"
    FAILED_COMPLEXITY = "FAILED_COMPLEXITY"
    CONSTRAINT_INCOMPATIBLE = "CONSTRAINT_INCOMPATIBLE"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
    ORACLE_ERROR = "ORACLE_ERROR"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    VERIFICATION_INCOMPLETE = "VERIFICATION_INCOMPLETE"



class ComplexityConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNCERTAIN = "UNCERTAIN"


class StructuralComplexityObservation(BaseModel):
    """Observed AST and structural elements of the implementation."""
    max_loop_depth: int = Field(default=0, description="Maximum loop nesting depth detected in AST")
    has_nested_loops: bool = Field(default=False, description="True if depth >= 2")
    dominant_loops: List[str] = Field(default_factory=list, description="Descriptions/locations of dominant iteration constructs")
    sorting_calls: List[str] = Field(default_factory=list, description="Sorting calls observed (e.g. sorted, .sort)")
    recursion_detected: bool = Field(default=False, description="True if self-referential recursive calls detected")
    recursion_depth_estimate: Optional[str] = Field(default=None, description="Estimated recursion depth (e.g. O(N), O(log N))")
    hash_operations_in_loop: bool = Field(default=False, description="True if map/set lookups/inserts occur within loops")
    string_concatenation_in_loop: bool = Field(default=False, description="True if quadratic string building pattern detected")
    data_structures_observed: List[str] = Field(default_factory=list, description="Data structures instantiated or utilized")
    auxiliary_allocations: List[str] = Field(default_factory=list, description="Auxiliary memory buffers observed")


class ComplexityAuditResult(BaseModel):
    """Audit comparing AlgorithmPlan's expected complexity with actual implementation."""
    expected_time_complexity: str = Field(description="Plan's stated time complexity (e.g. O(N))")
    expected_space_complexity: str = Field(description="Plan's stated space complexity (e.g. O(1))")
    inferred_time_complexity: str = Field(description="Complexity derived from code structure (e.g. O(N^2))")
    inferred_space_complexity: str = Field(description="Auxiliary space derived from allocations")
    confidence: ComplexityConfidence = Field(default=ComplexityConfidence.HIGH)
    observed_structure: StructuralComplexityObservation = Field(default_factory=StructuralComplexityObservation)
    plan_implementation_consistent: bool = Field(description="True if actual structure matches or improves upon plan")
    detected_anomalies: List[str] = Field(default_factory=list, description="Structural inefficiencies or anti-patterns detected")
    worst_case_analysis: str = Field(default="", description="Detailed reasoning distinguishing worst-case vs average/amortized")


class ConstraintCompatibilityResult(BaseModel):
    """Evaluation of algorithmic complexity against extracted ProblemSpec constraints."""
    compatible: bool = Field(description="True if operations are within time/memory limits for max N")
    max_input_bound: Optional[int] = Field(default=None, description="Parsed upper bound N from constraints")
    estimated_operations: Optional[float] = Field(default=None, description="Estimated worst-case operations for max N")
    operations_threshold: float = Field(default=10**8, description="Standard competitive programming limit")
    constraints_uncertain: bool = Field(default=False, description="True if constraints were missing or ambiguous")
    details: str = Field(default="", description="Reasoning and compatibility statement")


class FinalVerificationReport(BaseModel):
    """Structured, machine-readable final verification report."""
    __test__ = False
    problem_id: str = Field(description="Identifier of the problem")
    source_version_hash: str = Field(description="SHA256 hash of the candidate source code")
    language: SupportedLanguage = Field(description="Programming language of candidate solution")
    test_suite_status: str = Field(description="Summary of execution test suite (e.g. ALL_PASSED, FAILED)")
    total_tests_run: int = Field(default=0)
    tests_passed: int = Field(default=0)
    tests_failed: int = Field(default=0)
    has_stress_evidence: bool = Field(default=False)
    has_edge_case_evidence: bool = Field(default=False)
    has_boundary_evidence: bool = Field(default=False)
    has_randomized_evidence: bool = Field(default=False)
    has_differential_evidence: bool = Field(default=False)
    complexity_audit: ComplexityAuditResult = Field(description="Detailed asymptotic complexity audit")
    constraint_compatibility: ConstraintCompatibilityResult = Field(description="Compatibility check vs input constraints")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings or performance notes")
    unresolved_uncertainty: List[str] = Field(default_factory=list, description="Ambiguities or uncertainties in analysis")
    final_verification_status: VerificationStatus = Field(description="Final certification status")
    is_fully_certified: bool = Field(default=False, description="True ONLY when status == VERIFIED")




