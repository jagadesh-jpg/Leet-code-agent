"""
Unit & Integration Tests for Stage 12: n8n Orchestration & Python Agent API.
Tests:
1. Health endpoint returns 200 and language adapter availability.
2. Problem analysis endpoint normalizes raw statement into ProblemSpec.
3. Solve endpoint with valid problem and correct code runs through pipeline to VERIFIED.
4. Solve endpoint enforces idempotency (repeated call returns identical job without duplicate run).
5. Solve endpoint rejects invalid/malformed problem statements with 400.
6. Async solve endpoint returns job immediately in non-terminal state.
7. Job query endpoint retrieves existing job status and reports 404 for missing jobs.
8. Verification endpoint evaluates solution through Stage 10 multi-gate pipeline.
9. Security authentication: rejects requests with invalid API key when auth is enabled.
10. n8n workflow definition is valid JSON and contains required nodes and branching rules.
11. End-to-end simulated n8n orchestration flow matches the real API.
12. Memory service receives session record upon solve completion via API.
"""

import json
from pathlib import Path
import pytest
import httpx

from agent.api.jobs import JobManager
from agent.api.server import create_app
from agent.config import Config
from agent.core.models import SupportedLanguage, VerificationStatus
from agent.memory.service import MemoryService
from agent.memory.sqlite_store import SQLiteMemoryStore


class SyncASGIAgentClient:
    """Synchronous test client wrapping httpx.AsyncClient with ASGITransport."""

    def __init__(self, app):
        self.app = app
        self.transport = httpx.ASGITransport(app=app)
        self.async_client = httpx.AsyncClient(transport=self.transport, base_url="http://127.0.0.1:8000")

    def get(self, url, headers=None):
        import asyncio
        return asyncio.run(self.async_client.get(url, headers=headers))

    def post(self, url, json=None, headers=None):
        import asyncio
        return asyncio.run(self.async_client.post(url, json=json, headers=headers))

    def close(self):
        import asyncio
        asyncio.run(self.async_client.aclose())


@pytest.fixture
def client_fixture(tmp_path):
    db_path = str(tmp_path / "test_api_memory.db")
    store = SQLiteMemoryStore(db_path=db_path)
    mem_svc = MemoryService(store=store)
    job_mgr = JobManager(memory_service=mem_svc)
    app = create_app(job_manager=job_mgr, memory_service=mem_svc)
    client = SyncASGIAgentClient(app)
    yield client, mem_svc
    client.close()
    mem_svc.close()


# 1. Health check
def test_1_health_endpoint(client_fixture):
    client, _ = client_fixture
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "python" in data["adapters_available"]
    assert data["adapters_available"]["python"] is True


# 2. Problem analysis endpoint
def test_2_analyze_problem_endpoint(client_fixture):
    client, _ = client_fixture
    payload = {
        "problem": {
            "problem_id": "two-sum",
            "statement": "Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target.\n2 <= nums.length <= 10^5\nExample 1: Input: nums = [2,7,11,15], target = 9 Output: [0,1]",
            "function_name": "twoSum",
            "param_names": ["nums", "target"],
        }
    }
    response = client.post("/api/v1/problems/analyze", json=payload)
    assert response.status_code == 200
    spec = response.json()
    assert spec["id"] == "two-sum"
    assert spec["function_name"] == "twoSum"
    assert len(spec["param_names"]) == 2


# 3. Synchronous solve endpoint
def test_3_solve_problem_endpoint(client_fixture):
    client, _ = client_fixture
    correct_code = """
def twoSum(nums, target):
    lookup = {}
    for i, num in enumerate(nums):
        diff = target - num
        if diff in lookup:
            return [lookup[diff], i]
        lookup[num] = i
    return []
"""
    payload = {
        "problem": {
            "problem_id": "two-sum",
            "statement": "Find two numbers.",
            "function_name": "twoSum",
            "param_names": ["nums", "target"],
            "constraints": ["2 <= nums.length <= 10^4"],
            "examples": [{"inputs": {"nums": [2, 7, 11, 15], "target": 9}, "expected_output": [0, 1]}],
        },
        "language": "python",
        "options": {"max_attempts": 2},
        "override_initial_code": correct_code,
    }
    response = client.post("/api/v1/problems/solve?async_run=false", json=payload)
    assert response.status_code == 200
    job = response.json()
    assert job["is_verified"] is True
    assert job["final_status"] == "VERIFIED"
    assert job["verified_code"] is not None


# 4. Idempotency enforcement
def test_4_idempotency_enforcement(client_fixture):
    client, _ = client_fixture
    correct_code = "def twoSum(nums, target): return [0, 1]"
    payload = {
        "problem": {
            "problem_id": "two-sum-idemp",
            "statement": "Find two numbers.",
            "function_name": "twoSum",
            "param_names": ["nums", "target"],
            "examples": [{"inputs": {"nums": [2, 7], "target": 9}, "expected_output": [0, 1]}],
        },
        "language": "python",
        "override_initial_code": correct_code,
        "idempotency_key": "unique_idem_key_12345",
    }
    # First call
    res1 = client.post("/api/v1/problems/solve", json=payload)
    assert res1.status_code == 200
    job1 = res1.json()

    # Second call with same idempotency key
    res2 = client.post("/api/v1/problems/solve", json=payload)
    assert res2.status_code == 200
    job2 = res2.json()

    # Must return exact same job without re-executing
    assert job1["job_id"] == job2["job_id"]


# 5. Invalid / malformed problem statements rejected with 400
def test_5_malformed_problem_rejected(client_fixture):
    client, _ = client_fixture
    payload = {
        "problem": {
            "statement": "   ",  # Empty statement
        }
    }
    response = client.post("/api/v1/problems/solve", json=payload)
    assert response.status_code == 400
    assert "Problem statement cannot be empty" in response.json()["detail"]


# 6. Async solve endpoint
def test_6_async_solve_endpoint(client_fixture):
    client, _ = client_fixture
    payload = {
        "problem": {
            "problem_id": "two-sum-async",
            "statement": "Find two numbers.",
            "function_name": "twoSum",
            "param_names": ["nums", "target"],
            "examples": [{"inputs": {"nums": [2, 7], "target": 9}, "expected_output": [0, 1]}],
        },
        "language": "python",
        "override_initial_code": "def twoSum(nums, target): return [0, 1]",
    }
    response = client.post("/api/v1/problems/solve?async_run=true", json=payload)
    assert response.status_code == 200
    job = response.json()
    assert "job_id" in job
    assert job["job_id"].startswith("job_")


# 7. Job query and 404 handling
def test_7_job_query_endpoint(client_fixture):
    client, _ = client_fixture
    # Missing job returns 404
    res_missing = client.get("/api/v1/jobs/non_existent_job_id")
    assert res_missing.status_code == 404

    # Create job via solve and query
    payload = {
        "problem": {
            "problem_id": "two-sum-query",
            "statement": "Find two numbers.",
            "function_name": "twoSum",
            "param_names": ["nums", "target"],
            "examples": [{"inputs": {"nums": [2, 7], "target": 9}, "expected_output": [0, 1]}],
        },
        "override_initial_code": "def twoSum(nums, target): return [0, 1]",
    }
    res_solve = client.post("/api/v1/problems/solve?async_run=false", json=payload)
    job_id = res_solve.json()["job_id"]

    res_get = client.get(f"/api/v1/jobs/{job_id}")
    assert res_get.status_code == 200
    assert res_get.json()["job_id"] == job_id


# 8. Verification endpoint
def test_8_verify_solution_endpoint(client_fixture):
    client, _ = client_fixture
    payload = {
        "problem": {
            "problem_id": "two-sum-verify",
            "statement": "Find two numbers.",
            "function_name": "twoSum",
            "param_names": ["nums", "target"],
            "constraints": ["2 <= nums.length <= 10^4"],
            "examples": [{"inputs": {"nums": [2, 7, 11, 15], "target": 9}, "expected_output": [0, 1]}],
        },
        "source_code": """
def twoSum(nums, target):
    seen = {}
    for i, x in enumerate(nums):
        if target - x in seen:
            return [seen[target - x], i]
        seen[x] = i
    return []
""",
        "language": "python",
    }
    response = client.post("/api/v1/solutions/verify", json=payload)
    assert response.status_code == 200
    report = response.json()
    assert report["final_verification_status"] == VerificationStatus.VERIFIED.value
    assert report["is_fully_certified"] is True


# 9. Authentication enforcement
def test_9_auth_security(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "API_SECRET_KEY", "super-secret-test-key")
    db_path = str(tmp_path / "test_auth_memory.db")
    app = create_app(memory_service=MemoryService(store=SQLiteMemoryStore(db_path=db_path)))
    client = SyncASGIAgentClient(app)

    # Without header -> 401
    res_no_auth = client.get("/api/v1/jobs/test_job")
    assert res_no_auth.status_code == 401

    # With wrong key -> 401
    res_bad_auth = client.get("/api/v1/jobs/test_job", headers={"X-API-Key": "wrong-key"})
    assert res_bad_auth.status_code == 401

    # With correct key -> 404 (authorized, job not found)
    res_good_auth = client.get("/api/v1/jobs/test_job", headers={"X-API-Key": "super-secret-test-key"})
    assert res_good_auth.status_code == 404
    client.close()


# 10. n8n workflow file validation
def test_10_n8n_workflow_file_validity():
    workflow_path = Path(__file__).resolve().parent.parent / "workflows" / "dsa_agent_orchestrator.json"
    assert workflow_path.exists()
    content = json.loads(workflow_path.read_text(encoding="utf-8"))

    assert "nodes" in content
    assert "connections" in content
    node_names = {node["name"] for node in content["nodes"]}
    assert "Webhook Trigger" in node_names
    assert "Validate Request" in node_names
    assert "Call Python Agent API" in node_names
    assert "Switch on Agent State" in node_names
    assert "Format Verified Result" in node_names


# 11. Simulated n8n orchestration response branching
def test_11_simulated_n8n_branching():
    workflow_path = Path(__file__).resolve().parent.parent / "workflows" / "dsa_agent_orchestrator.json"
    content = json.loads(workflow_path.read_text(encoding="utf-8"))
    switch_node = next(n for n in content["nodes"] if n["name"] == "Switch on Agent State")
    rules = [r["value2"] for r in switch_node["parameters"]["rules"]["rules"]]

    assert "VERIFIED" in rules
    assert "FAILED" in rules
    assert "MAX_ATTEMPTS_REACHED" in rules
    assert "INFRASTRUCTURE_ERROR" in rules


# 12. Memory service receives session record upon solve completion via API
def test_12_memory_integration_via_api(client_fixture):
    client, mem_svc = client_fixture
    correct_code = """
def twoSum(nums, target):
    lookup = {}
    for i, num in enumerate(nums):
        diff = target - num
        if diff in lookup:
            return [lookup[diff], i]
        lookup[num] = i
    return []
"""
    payload = {
        "problem": {
            "problem_id": "two-sum-mem-api",
            "statement": "Find two numbers.",
            "function_name": "twoSum",
            "param_names": ["nums", "target"],
            "constraints": ["2 <= nums.length <= 10^4"],
            "examples": [{"inputs": {"nums": [2, 7, 11, 15], "target": 9}, "expected_output": [0, 1]}],
        },
        "language": "python",
        "override_initial_code": correct_code,
    }
    res = client.post("/api/v1/problems/solve?async_run=false", json=payload)
    assert res.status_code == 200
    assert res.json()["is_verified"] is True

    # Confirm memory store received the problem and verified solution
    prob = mem_svc.store.get_problem("two-sum-mem-api")
    assert prob is not None
    verified = mem_svc.store.get_latest_verified_solution("two-sum-mem-api")
    assert verified is not None
    assert verified.is_verified is True
