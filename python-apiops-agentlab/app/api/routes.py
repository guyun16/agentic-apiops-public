"""HTTP routes for health, contract validation, and real agent execution."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.clients.java_apiops import (
    JavaApiOpsAuthenticationError,
    JavaApiOpsAuthorizationError,
    JavaApiOpsClient,
    JavaApiOpsClientError,
    JavaApiOpsError,
    JavaApiOpsMalformedResponseError,
    JavaApiOpsNotFoundError,
    JavaApiOpsResponseValidationError,
    JavaApiOpsServerError,
    JavaApiOpsTimeoutError,
    JavaApiOpsTransportError,
)
from app.core.errors import ApplicationError
from app.core.http_tls import client_tls_context
from app.core.logging import configure_logging, correlation_log_extra
from app.core.settings import AppSettings, get_settings
from app.memory import MemoryRetriever, MemoryWritePolicy, SQLiteMemoryStore
from app.schemas.diagnosis_api import (
    DiagnosisExecutionResponse,
    DiagnosisMemoryWriteRequest,
    DiagnosisMemoryWriteResponse,
    DiagnosisResumeRequest,
    DiagnosisRunSummary,
    DiagnosisStartRequest,
)
from app.schemas.testcase_dsl import TestCaseDSL
from app.schemas.testcase_generation_api import (
    TestCaseGenerationRequest,
    TestCaseGenerationResponse,
)
from app.services.benchmark_results import (
    BenchmarkArtifactStore,
    BenchmarkResultDetail,
    BenchmarkResultSummary,
    BenchmarkTaskResultView,
)
from app.services.diagnosis import DiagnosisExecutionService
from app.services.diagnosis_repository import SQLiteDiagnosisRunRepository
from app.services.runtime_evaluation import (
    RuntimeEvaluationSummary,
    RuntimeRunDetail,
    RuntimeRunSummary,
    runtime_evaluation_store,
)
from app.services.testcase_generation import TestCaseGenerationService
from app.tracing import (
    TraceRecord,
    normalize_trace_project_id,
    query_persisted_trace_records,
    resolve_trace_project_id,
)

logger = logging.getLogger("app.api")
router = APIRouter()
_application_settings = get_settings()
_historical_memory_store = SQLiteMemoryStore(_application_settings.memory_db_path)
_historical_memory_write_policy = MemoryWritePolicy(_historical_memory_store)
_runtime_diagnosis_store = SQLiteDiagnosisRunRepository(_application_settings.runtime_db_path)
_diagnosis_service = DiagnosisExecutionService(
    settings=_application_settings,
    memory_retriever=MemoryRetriever(_historical_memory_store),
    memory_write_policy=_historical_memory_write_policy,
    run_repository=_runtime_diagnosis_store,
    checkpoint_db_path=_application_settings.runtime_db_path,
)
_testcase_generation_service = TestCaseGenerationService()
_benchmark_results_store = BenchmarkArtifactStore()


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["python-apiops-agentlab"]


class TestCaseValidationResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        strict=True,
    )

    valid: Literal[True]
    validation_scope: Literal["PYTHON_LOCAL"] = Field(alias="validationScope")
    case_id: StrictStr = Field(alias="caseId", min_length=1)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="python-apiops-agentlab")


@router.get(
    "/api/v1/benchmark/results",
    response_model=list[BenchmarkResultSummary],
)
async def list_benchmark_results() -> list[BenchmarkResultSummary]:
    """List completed Benchmark runs already present in the artifact store."""

    return _benchmark_results_store.list()


@router.get(
    "/api/v1/benchmark/results/{evaluation_run_id}/tasks",
    response_model=list[BenchmarkTaskResultView],
)
async def benchmark_result_tasks(evaluation_run_id: str) -> list[BenchmarkTaskResultView]:
    """Read task envelopes and persisted EvaluationResult facts for one run."""

    tasks = _benchmark_results_store.tasks(evaluation_run_id)
    if tasks is None:
        raise ApplicationError(
            "BENCHMARK_RESULT_NOT_FOUND",
            "Benchmark result was not found.",
            404,
        )
    return tasks


@router.get(
    "/api/v1/benchmark/results/{evaluation_run_id}",
    response_model=BenchmarkResultDetail,
)
async def benchmark_result(evaluation_run_id: str) -> BenchmarkResultDetail:
    """Read one Benchmark result without executing or recomputing the run."""

    result = _benchmark_results_store.get(evaluation_run_id)
    if result is None:
        raise ApplicationError(
            "BENCHMARK_RESULT_NOT_FOUND",
            "Benchmark result was not found.",
            404,
        )
    return result


@router.post(
    "/api/v1/contracts/testcases:validate",
    response_model=TestCaseValidationResponse,
)
async def validate_testcase(
    testcase: TestCaseDSL,
    settings: AppSettings = Depends(get_settings),
) -> TestCaseValidationResponse:
    """Run Python-local Pydantic validation without contacting Java Runner."""

    configure_logging(settings.log_level)
    extra = correlation_log_extra()
    logger.info(
        "local testcase validation passed case_id=%s trace_id=%s request_id=%s",
        testcase.case_id,
        extra["trace_id"],
        extra["request_id"],
        extra=extra,
    )
    return TestCaseValidationResponse(
        valid=True,
        validation_scope="PYTHON_LOCAL",
        case_id=testcase.case_id,
    )


@router.post(
    "/api/v1/projects/{project_id}/openapi/apis/{api_id}/testcases:generate",
    response_model=TestCaseGenerationResponse,
)
async def generate_testcase(
    project_id: int,
    api_id: str,
    request: TestCaseGenerationRequest,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: AppSettings = Depends(get_settings),
) -> TestCaseGenerationResponse:
    """Generate one accepted Shared TestCase DSL through the existing workflow."""

    token = _bearer_token(authorization)
    trace_id = correlation_log_extra()["trace_id"]
    return await _testcase_generation_service.generate(
        project_id=project_id,
        api_id=api_id,
        request=request,
        token=token,
        trace_id=trace_id,
        settings=settings,
    )


@router.get(
    "/api/v1/evaluation/runtime/summary",
    response_model=RuntimeEvaluationSummary,
)
async def runtime_evaluation_summary(
    project_id: int = Query(..., alias="projectId", ge=1),
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: AppSettings = Depends(get_settings),
) -> RuntimeEvaluationSummary:
    """Return runtime facts only after Java authorizes the requested project."""

    await _authorize_runtime_project(
        project_id=project_id,
        authorization=authorization,
        settings=settings,
    )
    return runtime_evaluation_store.summary(project_id=project_id)


@router.get(
    "/api/v1/evaluation/runtime/runs",
    response_model=list[RuntimeRunSummary],
)
async def runtime_evaluation_runs(
    project_id: int = Query(..., alias="projectId", ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: AppSettings = Depends(get_settings),
) -> list[RuntimeRunSummary]:
    """List runtime runs only after Java authorizes the requested project."""

    await _authorize_runtime_project(
        project_id=project_id,
        authorization=authorization,
        settings=settings,
    )
    return list(runtime_evaluation_store.list_runs(project_id=project_id, limit=limit))


@router.get(
    "/api/v1/evaluation/runtime/runs/{agent_run_id}",
    response_model=RuntimeRunDetail,
)
async def runtime_evaluation_run(
    agent_run_id: str,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: AppSettings = Depends(get_settings),
) -> RuntimeRunDetail:
    """Return one runtime execution after Java authorizes its project."""

    project_id = runtime_evaluation_store.get_project_id(agent_run_id)
    if project_id is None:
        raise ApplicationError(
            "RUNTIME_EVALUATION_NOT_FOUND",
            "Runtime evaluation run was not found.",
            404,
        )
    await _authorize_runtime_project(
        project_id=project_id,
        authorization=authorization,
        settings=settings,
    )
    detail = runtime_evaluation_store.get_detail(agent_run_id)
    if detail is None:
        raise ApplicationError(
            "RUNTIME_EVALUATION_NOT_FOUND",
            "Runtime evaluation run was not found.",
            404,
        )
    return detail


@router.get(
    "/api/v1/traces",
    response_model=list[TraceRecord],
)
async def list_traces(
    project_id: int = Query(..., alias="projectId", ge=1),
    agent_run_id: str | None = Query(default=None, alias="agentRunId", min_length=1),
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: AppSettings = Depends(get_settings),
) -> list[TraceRecord]:
    """Return observed typed Trace records after Java project authorization."""

    await _authorize_runtime_project(
        project_id=project_id,
        authorization=authorization,
        settings=settings,
    )
    if settings.trace_sink == "jsonl":
        return list(
            _query_persisted_trace_records(
                settings=settings,
                project_id=project_id,
                agent_run_id=agent_run_id,
            )
        )
    records = runtime_evaluation_store.list_trace_records(project_id=project_id)
    return [
        record
        for record in records
        if agent_run_id is None or record.agent_run_id == agent_run_id
    ]


@router.get(
    "/api/v1/traces/{trace_id}",
    response_model=list[TraceRecord],
)
async def get_trace(
    trace_id: str,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: AppSettings = Depends(get_settings),
) -> list[TraceRecord]:
    """Return one observed correlation after authorizing its owning project."""

    _bearer_token(authorization)
    if settings.trace_sink == "jsonl":
        records = _query_persisted_trace_records(settings=settings, trace_id=trace_id)
        project_id = resolve_trace_project_id(records)
        if project_id is None:
            raise ApplicationError("TRACE_NOT_FOUND", "Trace was not found.", 404)
        await _authorize_runtime_project(
            project_id=project_id,
            authorization=authorization,
            settings=settings,
        )
        return [
            record
            for record in records
            if record.trace_id == trace_id
            and (
                record.project_id is None
                or normalize_trace_project_id(record.project_id) == project_id
            )
        ]
    project_id = runtime_evaluation_store.get_trace_project_id(trace_id)
    if project_id is None:
        raise ApplicationError("TRACE_NOT_FOUND", "Trace was not found.", 404)
    await _authorize_runtime_project(
        project_id=project_id,
        authorization=authorization,
        settings=settings,
    )
    records = runtime_evaluation_store.get_trace_records(trace_id)
    if not records:
        raise ApplicationError("TRACE_NOT_FOUND", "Trace was not found.", 404)
    return list(records)


def _query_persisted_trace_records(
    *,
    settings: AppSettings,
    trace_id: str | None = None,
    agent_run_id: str | None = None,
    project_id: int | None = None,
) -> tuple[TraceRecord, ...]:
    """Map local trace storage failures to one stable HTTP boundary error."""

    try:
        return query_persisted_trace_records(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            project_id=project_id,
            settings=settings,
        )
    except (OSError, ValueError) as exc:
        raise ApplicationError(
            "TRACE_HISTORY_UNAVAILABLE",
            "Trace history is unavailable.",
            503,
        ) from exc


async def _authorize_runtime_project(
    *,
    project_id: int,
    authorization: str | None,
    settings: AppSettings,
) -> None:
    """Use Java's project read boundary before exposing runtime facts."""

    token = _bearer_token(authorization)
    trace_id = correlation_log_extra()["trace_id"]
    try:
        async with httpx.AsyncClient(trust_env=False, verify=client_tls_context()) as http_client:
            client = JavaApiOpsClient(
                http_client,
                base_url=settings.java_apiops_base_url,
                timeout_seconds=settings.java_apiops_timeout_seconds,
            )
            await client.assert_project_readable(
                project_id=project_id,
                token=token,
                trace_id=trace_id,
            )
    except JavaApiOpsError as exc:
        raise _map_runtime_java_error(exc) from exc


def _map_runtime_java_error(exc: JavaApiOpsError) -> ApplicationError:
    if isinstance(exc, JavaApiOpsAuthenticationError):
        return ApplicationError(
            "JAVA_AUTHENTICATION_FAILED",
            "Java rejected the supplied credential.",
            401,
        )
    if isinstance(exc, JavaApiOpsAuthorizationError):
        return ApplicationError(
            "JAVA_AUTHORIZATION_DENIED",
            "Java denied access to the requested project resource.",
            403,
        )
    if isinstance(exc, JavaApiOpsNotFoundError):
        return ApplicationError(
            "JAVA_RESOURCE_NOT_FOUND",
            "The requested Java project resource was not found.",
            404,
        )
    if isinstance(exc, (JavaApiOpsTimeoutError, JavaApiOpsTransportError, JavaApiOpsServerError)):
        return ApplicationError(
            "JAVA_UNAVAILABLE",
            "Java API Ops is unavailable.",
            503,
        )
    if isinstance(exc, (JavaApiOpsMalformedResponseError, JavaApiOpsResponseValidationError)):
        return ApplicationError(
            "JAVA_INVALID_RESPONSE",
            "Java API Ops returned an invalid response.",
            502,
        )
    if isinstance(exc, JavaApiOpsClientError):
        return ApplicationError(
            "JAVA_REQUEST_FAILED",
            "Java API Ops rejected the request.",
            502,
        )
    return ApplicationError("JAVA_REQUEST_FAILED", "Java API Ops request failed.", 502)


def _bearer_token(authorization: str | None) -> str:
    """Extract the Java credential without logging or persisting it."""

    if authorization is None:
        from app.core.errors import ApplicationError

        raise ApplicationError(
            "JAVA_AUTHENTICATION_REQUIRED",
            "A Bearer token is required.",
            401,
        )
    scheme, separator, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not value.strip():
        from app.core.errors import ApplicationError

        raise ApplicationError(
            "JAVA_AUTHENTICATION_REQUIRED",
            "A Bearer token is required.",
            401,
        )
    return value.strip()


@router.post(
    "/api/v1/diagnosis/runs",
    response_model=DiagnosisExecutionResponse,
)
async def start_diagnosis(
    request: DiagnosisStartRequest,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: AppSettings = Depends(get_settings),
) -> DiagnosisExecutionResponse:
    """Start one real failed-run diagnosis from Java TestReport."""

    token = _bearer_token(authorization)
    trace_id = correlation_log_extra()["trace_id"]
    return await _diagnosis_service.start(
        project_id=request.project_id,
        run_id=request.run_id,
        token=token,
        trace_id=trace_id,
        settings=settings,
    )


@router.get(
    "/api/v1/diagnosis/runs",
    response_model=list[DiagnosisRunSummary],
)
async def list_diagnosis_runs(
    project_id: int = Query(..., alias="projectId", ge=1),
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: AppSettings = Depends(get_settings),
) -> list[DiagnosisRunSummary]:
    """List SQLite-backed Diagnosis history after Java authorizes the project."""

    await _authorize_runtime_project(
        project_id=project_id,
        authorization=authorization,
        settings=settings,
    )
    return list(_diagnosis_service.list(project_id=project_id))


@router.get(
    "/api/v1/diagnosis/runs/{agent_run_id}",
    response_model=DiagnosisExecutionResponse,
)
async def get_diagnosis(
    agent_run_id: str,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: AppSettings = Depends(get_settings),
) -> DiagnosisExecutionResponse:
    """Read a diagnosis result after re-authorizing its Java TestReport."""

    token = _bearer_token(authorization)
    return await _diagnosis_service.get(
        agent_run_id=agent_run_id,
        token=token,
        settings=settings,
    )


@router.post(
    "/api/v1/diagnosis/runs/{agent_run_id}/resume",
    response_model=DiagnosisExecutionResponse,
)
async def resume_diagnosis(
    agent_run_id: str,
    request: DiagnosisResumeRequest,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: AppSettings = Depends(get_settings),
) -> DiagnosisExecutionResponse:
    """Resume the existing bounded HITL workflow with an exact decision."""

    token = _bearer_token(authorization)
    trace_id = correlation_log_extra()["trace_id"]
    from app.workflows.approval import ApprovalAction

    return await _diagnosis_service.resume(
        agent_run_id=agent_run_id,
        token=token,
        decision=ApprovalAction(request.decision),
        edited_arguments=request.edited_arguments,
        trace_id=trace_id,
        settings=settings,
    )


@router.post(
    "/api/v1/diagnosis/runs/{agent_run_id}/memory",
    response_model=DiagnosisMemoryWriteResponse,
)
async def remember_verified_diagnosis(
    agent_run_id: str,
    request: DiagnosisMemoryWriteRequest,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: AppSettings = Depends(get_settings),
) -> DiagnosisMemoryWriteResponse:
    """Persist one final hypothesis only after this explicit human action."""

    token = _bearer_token(authorization)
    return await _diagnosis_service.remember_verified_diagnosis(
        agent_run_id=agent_run_id,
        hypothesis_index=request.hypothesis_index,
        token=token,
        settings=settings,
    )
