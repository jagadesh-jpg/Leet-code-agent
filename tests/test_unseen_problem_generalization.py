"""
Unit & Integration Tests for Stage 24: Unseen-Problem Generalization & Benchmark Leakage Prevention.
Tests:
- dataset separation (DEV vs HELD_OUT)
- exact duplicate detection
- near-duplicate Jaccard similarity detection
- memory leakage audit
- canonical benchmark registry leakage audit
- contamination flagging and clean audit verification
- all four languages (C, C++, Java, Python)
- independent verification gates (complexity & correctness)
- infrastructure error isolation
- bounded repair on unseen problems
- end-to-end solving of unseen problems
"""

import pytest

from agent.core.models import (
    AgentState,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
    TestCategory,
)
from agent.evaluation.dataset_registry import DatasetRegistry
from agent.evaluation.leakage_detector import LeakageDetector
from agent.evaluation.models import DatasetSplit, LeakageAuditRecord, ProblemMetadata
from agent.core.orchestrator import SelfCorrectionOrchestrator


@pytest.fixture
def dataset_registry():
    return DatasetRegistry()


@pytest.fixture
def sample_problem_a():
    return ProblemSpec(
        id="problem-alpha",
        title="Find Missing Number in Array",
        description="Given an array nums of n integers from 0 to n, find the missing number.",
        function_name="missingNumber",
        param_names=["nums"],
        return_type="int",
        constraints=["1 <= nums.length <= 10^4"],
    )


@pytest.fixture
def sample_problem_near_duplicate():
    return ProblemSpec(
        id="problem-alpha-variant",
        title="Find Missing Number in Array Sequence",
        description="Given an array nums of n integers from 0 to n, find the missing number in array.",
        function_name="findMissing",
        param_names=["nums"],
        return_type="int",
        constraints=["1 <= nums.length <= 10^4"],
    )


# 1. Dataset separation
def test_dataset_split_separation(dataset_registry):
    held_out = dataset_registry.get_held_out_problems()
    assert len(held_out) == 15
    for spec, raw_dict in held_out:
        meta = dataset_registry.get_problem_metadata(spec.id)
        assert meta is not None
        assert meta.split == DatasetSplit.HELD_OUT_TEST
        assert meta.is_held_out is True


# 2. Exact duplicate detection
def test_exact_duplicate_detection(sample_problem_a):
    detector = LeakageDetector()
    fp1 = detector.compute_exact_fingerprint(sample_problem_a)
    # Identical signature
    prob_clone = sample_problem_a.model_copy(update={"id": "problem-clone"})
    fp2 = detector.compute_exact_fingerprint(prob_clone)
    assert fp1 == fp2

    audit = detector.audit_problem_leakage(
        problem=prob_clone,
        split=DatasetSplit.HELD_OUT_TEST,
        existing_problem_pool=[sample_problem_a],
    )
    assert audit.has_exact_leakage is True
    assert audit.is_contaminated is True
    assert audit.status == "CONTAMINATED"


# 3. Near-duplicate similarity detection
def test_near_duplicate_similarity_detection(sample_problem_a, sample_problem_near_duplicate):
    detector = LeakageDetector()
    sim, expl = detector.calculate_near_duplicate_similarity(
        sample_problem_a, sample_problem_near_duplicate
    )
    assert sim >= 0.70
    assert "Jaccard similarity" in expl

    audit = detector.audit_problem_leakage(
        problem=sample_problem_near_duplicate,
        split=DatasetSplit.HELD_OUT_TEST,
        existing_problem_pool=[sample_problem_a],
        similarity_threshold=0.65,
    )
    assert audit.has_near_duplicate_leakage is True
    assert audit.is_contaminated is True


# 4. Memory leakage detection
def test_memory_leakage_audit(sample_problem_a):
    detector = LeakageDetector()
    # Problem ID exists in prior memory
    audit = detector.audit_problem_leakage(
        problem=sample_problem_a,
        split=DatasetSplit.HELD_OUT_TEST,
        existing_problem_pool=[],
        persistent_memory_problem_ids={"problem-alpha", "other-p"},
    )
    assert audit.has_memory_leakage is True
    assert audit.is_contaminated is True


# 5. Registry leakage detection
def test_registry_leakage_audit(sample_problem_a):
    detector = LeakageDetector()
    audit = detector.audit_problem_leakage(
        problem=sample_problem_a,
        split=DatasetSplit.HELD_OUT_TEST,
        existing_problem_pool=[],
        registry_problem_ids={"problem-alpha"},
    )
    assert audit.has_registry_leakage is True
    assert audit.is_contaminated is True


# 6. Clean audit on uncontaminated problem
def test_clean_leakage_audit(sample_problem_a):
    detector = LeakageDetector()
    other_prob = ProblemSpec(
        id="different-graph-dijkstra",
        title="Dijkstra Shortest Path",
        description="Compute shortest path between vertices in directed graph.",
        function_name="shortestPath",
        param_names=["n", "edges", "src"],
        return_type="int",
    )
    audit = detector.audit_problem_leakage(
        problem=sample_problem_a,
        split=DatasetSplit.HELD_OUT_TEST,
        existing_problem_pool=[other_prob],
        persistent_memory_problem_ids={"some-unrelated-id"},
        registry_problem_ids={"two-sum"},
    )
    assert audit.has_exact_leakage is False
    assert audit.has_near_duplicate_leakage is False
    assert audit.has_memory_leakage is False
    assert audit.has_registry_leakage is False
    assert audit.is_contaminated is False
    assert audit.status == "CLEAN"


# 7. Multi-language compatibility on held-out suite
def test_held_out_multilanguage_coverage(dataset_registry):
    held_out = dataset_registry.get_held_out_problems()
    languages_seen = set(raw["language"].value for _, raw in held_out)
    assert "c" in languages_seen
    assert "cpp" in languages_seen
    assert "java" in languages_seen
    assert "python" in languages_seen


# 8. DSA category coverage (>= 10 genuine categories)
def test_held_out_dsa_category_coverage(dataset_registry):
    held_out = dataset_registry.get_held_out_problems()
    categories_seen = set(raw["category"] for _, raw in held_out)
    assert len(categories_seen) >= 10


# 9. End-to-end solving on unseen Python problem (Missing Number)
def test_end_to_end_unseen_python_solve():
    prob = ProblemSpec(
        id="unseen-missing-number-test",
        title="Missing Number",
        description="Find missing number in range 0 to n.",
        function_name="missingNumber",
        param_names=["nums"],
        return_type="int",
        test_cases=[
            TestCase(id="t1", inputs={"nums": [3, 0, 1]}, expected_output=2, category=TestCategory.BASIC),
            TestCase(id="t2", inputs={"nums": [0, 1]}, expected_output=2, category=TestCategory.BASIC),
        ],
    )
    flawed_code = "class Solution:\n    def missingNumber(self, nums):\n        return len(nums) - 1\n"
    orchestrator = SelfCorrectionOrchestrator(max_attempts=2)
    session = orchestrator.solve(
        problem=prob,
        language=SupportedLanguage.PYTHON,
        override_initial_code=flawed_code,
        max_attempts=2,
    )
    assert session.is_verified is True
    assert session.total_attempts == 2


# 10. End-to-end solving on unseen C++ problem (First Unique Character)
def test_end_to_end_unseen_cpp_solve():
    prob = ProblemSpec(
        id="unseen-first-uniq-char-test",
        title="First Unique Character",
        description="Find index of first non-repeating character.",
        function_name="firstUniqChar",
        param_names=["s"],
        return_type="int",
        test_cases=[
            TestCase(id="t1", inputs={"s": "leetcode"}, expected_output=0, category=TestCategory.BASIC),
            TestCase(id="t2", inputs={"s": "aabb"}, expected_output=-1, category=TestCategory.BASIC),
        ],
    )
    flawed_code = "#include <string>\nusing namespace std;\nclass Solution {\npublic:\n    int firstUniqChar(string s) {\n        return 0;\n    }\n};\n"
    orchestrator = SelfCorrectionOrchestrator(max_attempts=2)
    session = orchestrator.solve(
        problem=prob,
        language=SupportedLanguage.CPP,
        override_initial_code=flawed_code,
        max_attempts=2,
    )
    assert session.is_verified is True
    assert session.total_attempts == 2


# 11. Bounded failure handling on unseen problem
def test_bounded_unfixable_unseen_problem():
    prob = ProblemSpec(
        id="unseen-unfixable-test",
        title="Unfixable Infinite Loop",
        description="Test watchdog on infinite loop.",
        function_name="circularLoop",
        param_names=["nums"],
        return_type="bool",
        test_cases=[
            TestCase(id="t1", inputs={"nums": [1, 2]}, expected_output=True, category=TestCategory.BASIC),
        ],
    )
    runaway_code = "class Solution {\n    public boolean circularLoop(int[] nums) {\n        while (true) {}\n    }\n}\n"
    orchestrator = SelfCorrectionOrchestrator(max_attempts=2)
    session = orchestrator.solve(
        problem=prob,
        language=SupportedLanguage.JAVA,
        override_initial_code=runaway_code,
        max_attempts=2,
    )
    assert session.final_state == AgentState.MAX_ATTEMPTS_REACHED
    assert session.is_verified is False


# 12. Infrastructure error isolation on unseen problem
def test_infrastructure_isolation_unseen():
    prob = ProblemSpec(
        id="unseen-infra-test",
        title="Unseen Infra Case",
        description="Test toolchain absence.",
        function_name="dummyFunc",
        param_names=["n"],
        return_type="int",
        test_cases=[],
    )
    orchestrator = SelfCorrectionOrchestrator(max_attempts=2)
    from agent.core.models import ExecutionResult, ExecutionStatus, FailureCategory
    mock_infra_report = ExecutionResult(
        status=ExecutionStatus.INFRASTRUCTURE_ERROR,
        failure_category=FailureCategory.ENVIRONMENT_ERROR,
        error_detail="Compiler not found in PATH",
    )
    # Localizer isolates error
    diag = orchestrator.localizer.diagnose(prob, "pass", SupportedLanguage.JAVA, exec_result=mock_infra_report)
    assert diag.is_infrastructure_failure is True
    assert diag.failure_category == FailureCategory.ENVIRONMENT_ERROR
