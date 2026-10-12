"""
FastAPI Server for Python Agent Orchestration API.
Exposes clean endpoints for n8n workflows and external HTTP clients:
- POST /api/v1/problems/solve
- POST /api/v1/problems/analyze
- POST /api/v1/solutions/verify
- GET /api/v1/jobs/{job_id}
- GET /api/v1/health

Secured via optional shared secret bearer/header authentication.
Bound to localhost (127.0.0.1) by default.
"""

from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Query, Security, status
from fastapi.responses import JSONResponse

from agent.api.jobs import JobManager
from agent.api.models import (
    AnalyzeRequest,
    HealthResponse,
    JobDTO,
    ProblemInputDTO,
    ProblemIntakeRequestDTO,
    ProblemIntakeResponseDTO,
    SolveRequest,
    VerifyRequest,
)
from agent.config import Config
from agent.core.models import (
    FinalVerificationReport,
    ProblemSpec,
    SupportedLanguage,
    TestCase,
)
from agent.core.normalizer import ProblemNormalizer
from agent.execution.runner import ExecutionRunner
from agent.intake.service import ProblemIntakeService
from agent.memory.service import MemoryService
from agent.verification.verifier import SolutionVerifier


def create_app(
    job_manager: Optional[JobManager] = None,
    memory_service: Optional[MemoryService] = None,
) -> FastAPI:
    """Application factory for the Agent API."""
    app = FastAPI(
        title="Autonomous DSA Coding Agent API",
        description="Programmatic API for n8n orchestration and external workflow coordination.",
        version="1.0.0",
    )

    mem_svc = memory_service or MemoryService()
    jobs = job_manager or JobManager(memory_service=mem_svc)
    normalizer = ProblemNormalizer()
    verifier = SolutionVerifier()

    def verify_auth(x_api_key: Optional[str] = Header(default=None)):
        """Enforces shared-secret authentication if configured."""
        required_key = Config.API_SECRET_KEY
        if required_key and required_key != "dev-secret-key-change-me":
            if not x_api_key or x_api_key != required_key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or missing X-API-Key header.",
                )

    def _build_problem_spec(dto: ProblemInputDTO) -> ProblemSpec:
        """Parses DTO into strongly validated ProblemSpec."""
        try:
            spec = normalizer.parse(dto.statement, problem_id=dto.problem_id)
            # Apply any explicit overrides from DTO
            updates = {}
            if dto.function_name:
                updates["function_name"] = dto.function_name
            if dto.param_names:
                updates["param_names"] = dto.param_names
            if dto.constraints:
                updates["constraints"] = dto.constraints
            if dto.examples:
                extra_cases = [
                    TestCase(
                        id=f"input_ex_{i}",
                        inputs=ex.get("inputs", {}),
                        expected_output=ex.get("expected_output"),
                        is_sample=True,
                    )
                    for i, ex in enumerate(dto.examples, 1)
                ]
                updates["test_cases"] = spec.test_cases + extra_cases

            if updates:
                spec = spec.model_copy(update=updates)
            return spec
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to normalize problem statement: {str(e)}",
            )

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health_check():
        """Health check endpoint exposing toolchain availability."""
        runner = ExecutionRunner()
        return HealthResponse(
            status="ok",
            adapters_available={
                lang.value: runner.get_adapter(lang).is_toolchain_available()
                for lang in SupportedLanguage
            },
        )


    @app.post("/api/v1/problems/intake", response_model=ProblemIntakeResponseDTO)
    def intake_problem_endpoint(req: ProblemIntakeRequestDTO, _=Security(verify_auth)):
        """
        Stage 19 Dynamic Problem Intake endpoint.
        Validates, normalizes, detects duplicates, and enqueues problem into the Stage 18 queue.
        """
        intake_svc = ProblemIntakeService()
        raw_payload = {
            "title": req.title,
            "statement": req.statement,
            "preferred_language": req.preferred_language,
        }
        item, report = intake_svc.intake_problem(
            raw_input=raw_payload,
            preferred_language=req.preferred_language,
            priority=req.priority,
            max_attempts=req.max_attempts,
            initial_flawed_code=req.initial_flawed_code,
            allow_rerun=req.allow_rerun,
        )

        if not item or not report.is_acceptable:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Problem intake failed: {'; '.join(report.issues)}",
            )

        return ProblemIntakeResponseDTO(
            problem_id=item.problem_id,
            queue_item_id=item.queue_item_id,
            status=item.status.value,
            language=item.preferred_language.value,
            is_acceptable=report.is_acceptable,
            issues=report.issues,
        )

    @app.post("/api/v1/problems/analyze", response_model=ProblemSpec)
    def analyze_problem(req: AnalyzeRequest, _=Security(verify_auth)):
        """Normalizes and analyzes a raw problem statement into a validated ProblemSpec."""
        return _build_problem_spec(req.problem)

    @app.post("/api/v1/problems/solve", response_model=JobDTO)
    def solve_problem(
        req: SolveRequest,
        async_run: bool = Query(default=False, description="Whether to execute asynchronously"),
        _=Security(verify_auth),
    ):
        """
        Orchestration endpoint: Initiates an autonomous self-correction session.
        Respects idempotency keys to prevent duplicate runs on n8n retry.
        """
        # 1. Check idempotency
        if req.idempotency_key:
            existing = jobs.get_job_by_idempotency_key(req.idempotency_key)
            if existing:
                return existing

        # 2. Parse problem
        spec = _build_problem_spec(req.problem)

        # 3. Create job
        job = jobs.create_job(
            problem_id=spec.id,
            language=req.language,
            max_attempts=req.options.max_attempts,
            idempotency_key=req.idempotency_key,
        )

        # 4. Execute
        if async_run:
            import threading
            thread = threading.Thread(
                target=jobs.run_solve_job,
                args=(job.job_id, spec, req.language, req.options.max_attempts, req.override_initial_code),
                daemon=True,
            )
            thread.start()
            return job
        else:
            completed_job = jobs.run_solve_job(
                job_id=job.job_id,
                problem=spec,
                language=req.language,
                max_attempts=req.options.max_attempts,
                override_initial_code=req.override_initial_code,
            )
            return completed_job

    @app.get("/api/v1/jobs/{job_id}", response_model=JobDTO)
    def get_job_status(job_id: str, _=Security(verify_auth)):
        """Retrieves status and audit report of an existing orchestration job."""
        job = jobs.get_job(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found.",
            )
        return job

    @app.post("/api/v1/solutions/verify", response_model=FinalVerificationReport)
    def verify_solution(req: VerifyRequest, _=Security(verify_auth)):
        """
        Verifies a pre-existing or candidate solution against the Stage 10 multi-gate pipeline.
        Enforces execution evidence, complexity audit, and constraint compatibility.
        """
        spec = _build_problem_spec(req.problem)
        report = verifier.verify_solution(
            problem=spec,
            source_code=req.source_code,
            language=req.language,
        )
        return report

    return app


# Default app instance
app = create_app()
