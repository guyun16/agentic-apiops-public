from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from pydantic import SecretStr

import app.services.diagnosis as diagnosis_service_module
import app.services.testcase_generation as generation_service_module
from app.clients.java_apiops import JavaApiOpsClient
from app.core.errors import ApplicationError
from app.core.settings import AppSettings
from app.schemas.runner import TestReport as RunnerTestReport
from app.schemas.testcase_generation_api import TestCaseGenerationRequest as GenerationRequest
from app.services.diagnosis import DiagnosisExecutionService
from app.services.diagnosis_repository import SQLiteDiagnosisRunRepository
from app.services.runtime_evaluation import runtime_evaluation_store
from app.services.testcase_generation import TestCaseGenerationService
from app.tracing import TraceRecorder, query_persisted_trace_records
from app.workflows.approval import ApprovalAction
from app.workflows.generation_context import (
    DocumentedResponse,
    GenerationContext,
    RequestFact,
    TestStrategy,
)

Response = object | Exception | Callable[[str], object]


class _SequenceLLM:
    def __init__(self, responses: Sequence[Response]) -> None:
        self._responses = list(responses)

    async def complete(self, prompt: str) -> str:
        if not self._responses:
            raise AssertionError("unexpected model call")
        response = self._responses.pop(0)
        if callable(response):
            response = response(prompt)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, str) else json.dumps(response)


def _settings(
    tmp_path: Path,
    *,
    max_file_bytes: int = 16 * 1024 * 1024,
) -> AppSettings:
    return AppSettings(
        deepseek_api_key=SecretStr("test-only-key"),
        trace_sink="jsonl",
        trace_jsonl_path=str(tmp_path / "agent-traces.jsonl"),
        trace_max_file_bytes=max_file_bytes,
        runtime_db_path=str(tmp_path / "runtime.sqlite3"),
    )


def _failed_report() -> RunnerTestReport:
    return RunnerTestReport.model_validate(
        {
            "projectId": 41,
            "taskId": 301,
            "runId": 701,
            "reportId": "report:701",
            "status": "ASSERTION_FAILED",
            "startedAt": "2026-08-23T11:59:58Z",
            "finishedAt": "2026-08-23T12:00:00Z",
            "summary": {
                "totalCases": 1,
                "totalSteps": 1,
                "totalAssertions": 1,
                "passedAssertions": 0,
                "failedAssertions": 1,
                "failureType": "ASSERTION_MISMATCH",
            },
            "cases": [
                {
                    "caseId": "case-failed",
                    "status": "ASSERTION_FAILED",
                    "failureType": "ASSERTION_MISMATCH",
                    "steps": [
                        {
                            "stepId": "step-failed",
                            "status": "ASSERTION_FAILED",
                            "failureType": "ASSERTION_MISMATCH",
                            "responseStatusCode": 500,
                            "durationMs": 12,
                            "assertionResults": [
                                {
                                    "type": "STATUS_CODE",
                                    "passed": False,
                                    "expected": 200,
                                    "actual": 500,
                                    "message": "status mismatch",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def _diagnosis_response(prompt: str, *, sufficient: bool = True) -> dict[str, object]:
    match = re.search(r"agentRunId=([^,]+), traceId=([^\r\n]+)", prompt)
    assert match is not None
    trace_id = match.group(2).rstrip(".")
    return {
        "schemaVersion": "0.1.0",
        "reportId": "report:701",
        "agentRunId": match.group(1),
        "projectId": 41,
        "runId": 701,
        "failureType": "ASSERTION_MISMATCH",
        "summary": "The status assertion observed HTTP 500 instead of HTTP 200.",
        "rootCauseHypotheses": [
            {
                "statement": "The endpoint returned an unexpected server response.",
                "confidence": "MEDIUM",
                "evidenceRefs": [{"itemId": "report:701"}],
            }
        ],
        "sufficientEvidence": sufficient,
        "limitations": [] if sufficient else ["Additional authorized evidence is unavailable."],
        "recommendedChecks": ["Inspect the endpoint dependency health."],
        "traceId": trace_id,
    }


def _tool_intent_response() -> dict[str, object]:
    return {
        "tool_name": "redis.read",
        "arguments": {"key": "task:301"},
    }


def _generation_context(strategy: TestStrategy) -> GenerationContext:
    return GenerationContext(
        api_id="api-orders",
        api_doc_id="doc-orders-v1",
        operation_id="getOrder",
        method="GET",
        path="/orders/{order_id}",
        base_url="https://example.test",
        strategy=strategy,
        supporting_evidence=("responseSchemas[0].statusCode=200",),
        request_facts=(
            RequestFact(
                source="parameters[0]",
                kind="PARAMETER",
                name="order_id",
                location="path",
                required=True,
                schema_={"type": "string"},
                example="order-123",
            ),
        ),
        documented_responses=(
            DocumentedResponse(
                status_code="200",
                description="Returns the order.",
                media_type="application/json",
                schema_={"type": "object"},
            ),
        ),
    )


def _candidate_json() -> str:
    return json.dumps(
        {
            "caseId": "case-get-order",
            "projectId": 101,
            "apiId": "api-orders",
            "name": "Get one order",
            "environment": {"baseUrl": "https://example.test", "variables": {}},
            "steps": [
                {
                    "stepId": "get-order",
                    "name": "Get the order",
                    "request": {"method": "GET", "path": "/orders/{order_id}"},
                    "assertions": [{"type": "STATUS_CODE", "expected": 200}],
                    "extractors": [],
                }
            ],
            "schemaVersion": "1.0.0",
        }
    )


def _make_diagnosis_service(
    settings: AppSettings,
    tmp_path: Path,
) -> tuple[DiagnosisExecutionService, SQLiteDiagnosisRunRepository]:
    repository = SQLiteDiagnosisRunRepository(tmp_path / "diagnosis.sqlite3")
    return (
        DiagnosisExecutionService(
            settings,
            run_repository=repository,
            checkpoint_db_path=repository.database_path,
        ),
        repository,
    )


def _patch_diagnosis_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    llm: _SequenceLLM,
    observed_recorders: list[TraceRecorder],
) -> None:
    monkeypatch.setattr(
        diagnosis_service_module,
        "build_diagnosis_llm",
        lambda *_args, **_kwargs: llm,
    )
    original_build = diagnosis_service_module.build_diagnosis_workflow

    def build(*args: object, **kwargs: object) -> object:
        recorder = kwargs["trace_recorder"]
        assert isinstance(recorder, TraceRecorder)
        observed_recorders.append(recorder)
        return original_build(*args, **kwargs)

    monkeypatch.setattr(diagnosis_service_module, "build_diagnosis_workflow", build)


def _patch_generation_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    llm: _SequenceLLM,
    observed_recorders: list[TraceRecorder],
) -> None:
    async def get_api_metadata(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return object()

    monkeypatch.setattr(JavaApiOpsClient, "get_api_metadata", get_api_metadata)
    monkeypatch.setattr(
        generation_service_module,
        "build_generation_context",
        lambda _metadata, strategy: _generation_context(strategy),
    )
    monkeypatch.setattr(
        generation_service_module,
        "build_llm",
        lambda *_args, **_kwargs: llm,
    )
    original_build = generation_service_module.build_testcase_generation_graph

    def build(*args: object, **kwargs: object) -> object:
        recorder = kwargs["trace_recorder"]
        assert isinstance(recorder, TraceRecorder)
        observed_recorders.append(recorder)
        return original_build(*args, **kwargs)

    monkeypatch.setattr(generation_service_module, "build_testcase_generation_graph", build)


@pytest.mark.anyio
async def test_diagnosis_live_runtime_uses_factory_and_persists_trace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    service, repository = _make_diagnosis_service(settings, tmp_path)
    observed_recorders: list[TraceRecorder] = []
    _patch_diagnosis_dependencies(
        monkeypatch,
        _SequenceLLM([lambda prompt: _diagnosis_response(prompt)]),
        observed_recorders,
    )

    async def fetch_report(**kwargs: object) -> RunnerTestReport:
        del kwargs
        return _failed_report()

    monkeypatch.setattr(service, "_fetch_report", fetch_report)
    runtime_evaluation_store.clear()
    try:
        response = await service.start(
            project_id=41,
            run_id=701,
            token="java-token",
            trace_id="trace:diagnosis-live",
            settings=settings,
        )
        detail = runtime_evaluation_store.get_detail(response.agent_run_id)
    finally:
        runtime_evaluation_store.clear()
        repository.close()

    persisted = query_persisted_trace_records(
        trace_id=response.trace_id,
        agent_run_id=response.agent_run_id,
        settings=settings,
    )
    assert response.status == "COMPLETED"
    assert detail is not None
    assert observed_recorders == [service._trace_recorders[response.agent_run_id]]
    assert persisted
    assert any(record.record_type == "retrieval" for record in persisted)
    assert any(record.record_type == "model_call" for record in persisted)
    assert all(
        record.trace_id == response.trace_id and record.agent_run_id == response.agent_run_id
        for record in persisted
    )


@pytest.mark.anyio
async def test_diagnosis_resume_reuses_same_recorder_and_jsonl_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    service, repository = _make_diagnosis_service(settings, tmp_path)
    observed_recorders: list[TraceRecorder] = []
    _patch_diagnosis_dependencies(
        monkeypatch,
        _SequenceLLM(
            [
                _tool_intent_response(),
                lambda prompt: _diagnosis_response(prompt, sufficient=False),
            ]
        ),
        observed_recorders,
    )

    async def fetch_report(**kwargs: object) -> RunnerTestReport:
        del kwargs
        return _failed_report()

    monkeypatch.setattr(service, "_fetch_report", fetch_report)
    runtime_evaluation_store.clear()
    try:
        pending = await service.start(
            project_id=41,
            run_id=701,
            token="java-token",
            trace_id="trace:diagnosis-hitl",
            settings=settings,
        )
        resumed = await service.resume(
            agent_run_id=pending.agent_run_id,
            token="java-token",
            decision=ApprovalAction.REJECT,
            edited_arguments=None,
            trace_id="trace:diagnosis-resume-request",
            settings=settings,
        )
    finally:
        runtime_evaluation_store.clear()
        repository.close()

    recorder = service._trace_recorders[pending.agent_run_id]
    persisted = query_persisted_trace_records(
        agent_run_id=pending.agent_run_id,
        settings=settings,
    )
    assert pending.status == "APPROVAL_REQUIRED"
    assert resumed.status in {"COMPLETED", "REJECTED"}
    assert observed_recorders == [recorder, recorder]
    assert persisted
    assert any(record.record_type == "approval" for record in persisted)
    assert {record.agent_run_id for record in persisted} == {pending.agent_run_id}


@pytest.mark.anyio
async def test_diagnosis_persistence_failure_isolated_from_business_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, max_file_bytes=1)
    service, repository = _make_diagnosis_service(settings, tmp_path)
    observed_recorders: list[TraceRecorder] = []
    _patch_diagnosis_dependencies(
        monkeypatch,
        _SequenceLLM([lambda prompt: _diagnosis_response(prompt)]),
        observed_recorders,
    )

    async def fetch_report(**kwargs: object) -> RunnerTestReport:
        del kwargs
        return _failed_report()

    monkeypatch.setattr(service, "_fetch_report", fetch_report)
    runtime_evaluation_store.clear()
    try:
        response = await service.start(
            project_id=41,
            run_id=701,
            token="java-token",
            trace_id="trace:diagnosis-sink-failure",
            settings=settings,
        )
        detail = runtime_evaluation_store.get_detail(response.agent_run_id)
    finally:
        runtime_evaluation_store.clear()
        repository.close()

    recorder = observed_recorders[0]
    assert response.status == "COMPLETED"
    assert response.report is not None
    assert recorder.degraded is True
    assert recorder.typed_records
    assert detail is not None
    assert detail.status == "COMPLETED"
    assert query_persisted_trace_records(settings=settings) == ()


@pytest.mark.anyio
async def test_diagnosis_business_failure_keeps_failure_trace_best_effort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    service, repository = _make_diagnosis_service(settings, tmp_path)
    observed_recorders: list[TraceRecorder] = []
    _patch_diagnosis_dependencies(
        monkeypatch,
        _SequenceLLM([RuntimeError("provider detail must stay internal")]),
        observed_recorders,
    )

    async def fetch_report(**kwargs: object) -> RunnerTestReport:
        del kwargs
        return _failed_report()

    monkeypatch.setattr(service, "_fetch_report", fetch_report)
    runtime_evaluation_store.clear()
    try:
        with pytest.raises(ApplicationError) as error:
            await service.start(
                project_id=41,
                run_id=701,
                token="java-token",
                trace_id="trace:diagnosis-business-failure",
                settings=settings,
            )
        detail = runtime_evaluation_store.list_runs()[0]
    finally:
        runtime_evaluation_store.clear()
        repository.close()

    agent_run_id = detail.agent_run_id
    persisted = query_persisted_trace_records(
        agent_run_id=agent_run_id,
        settings=settings,
    )
    assert error.value.code == "DIAGNOSIS_FAILED"
    assert observed_recorders[0].degraded is False
    assert any(
        record.record_type == "model_call" and record.status.value == "FAILED"
        for record in persisted
    )
    assert any(record.event.value == "TERMINAL" for record in persisted)


@pytest.mark.anyio
async def test_generation_live_runtime_uses_one_recorder_and_fresh_recorder_per_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    llm = _SequenceLLM([_candidate_json(), _candidate_json()])
    graph_recorders: list[TraceRecorder] = []
    response_recorders: list[TraceRecorder] = []
    sync_recorders: list[TraceRecorder] = []
    _patch_generation_dependencies(monkeypatch, llm, graph_recorders)
    service = TestCaseGenerationService()

    original_response = service._response

    def capture_response(generated: object, recorder: TraceRecorder) -> object:
        response_recorders.append(recorder)
        return original_response(generated, recorder)

    service._response = capture_response
    original_sync = service._sync_runtime

    def capture_sync(**kwargs: object) -> None:
        recorder = kwargs["recorder"]
        assert isinstance(recorder, TraceRecorder)
        sync_recorders.append(recorder)
        original_sync(**kwargs)

    service._sync_runtime = capture_sync
    runtime_evaluation_store.clear()
    try:
        first = await service.generate(
            project_id=101,
            api_id="api-orders",
            request=GenerationRequest(),
            token="java-token",
            trace_id="trace:generation-one",
            settings=settings,
        )
        second = await service.generate(
            project_id=101,
            api_id="api-orders",
            request=GenerationRequest(),
            token="java-token",
            trace_id="trace:generation-two",
            settings=settings,
        )
        first_detail = runtime_evaluation_store.get_detail(first.agent_run_id)
        second_detail = runtime_evaluation_store.get_detail(second.agent_run_id)
    finally:
        runtime_evaluation_store.clear()

    first_persisted = query_persisted_trace_records(
        trace_id="trace:generation-one",
        agent_run_id=first.agent_run_id,
        settings=settings,
    )
    second_persisted = query_persisted_trace_records(
        trace_id="trace:generation-two",
        agent_run_id=second.agent_run_id,
        settings=settings,
    )
    assert len(first.model_calls) == 1
    assert len(second.model_calls) == 1
    assert graph_recorders[0] is response_recorders[0] is sync_recorders[0]
    assert graph_recorders[1] is response_recorders[1] is sync_recorders[1]
    assert graph_recorders[0] is not graph_recorders[1]
    assert first_detail is not None and second_detail is not None
    assert first_detail.status == second_detail.status == "COMPLETED"
    assert any(record.record_type == "model_call" for record in first_persisted)
    assert any(record.record_type == "model_call" for record in second_persisted)
    assert all(record.agent_run_id == first.agent_run_id for record in first_persisted)
    assert all(record.agent_run_id == second.agent_run_id for record in second_persisted)


@pytest.mark.anyio
async def test_generation_persistence_failure_preserves_model_calls_and_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, max_file_bytes=1)
    graph_recorders: list[TraceRecorder] = []
    _patch_generation_dependencies(
        monkeypatch,
        _SequenceLLM([_candidate_json()]),
        graph_recorders,
    )
    service = TestCaseGenerationService()
    runtime_evaluation_store.clear()
    try:
        response = await service.generate(
            project_id=101,
            api_id="api-orders",
            request=GenerationRequest(),
            token="java-token",
            trace_id="trace:generation-sink-failure",
            settings=settings,
        )
        detail = runtime_evaluation_store.get_detail(response.agent_run_id)
    finally:
        runtime_evaluation_store.clear()

    recorder = graph_recorders[0]
    assert response.model_calls
    assert recorder.degraded is True
    assert any(
        record.record_type == "model_call" and record.event.value == "TERMINAL"
        for record in recorder.typed_records
    )
    assert detail is not None
    assert detail.status == "COMPLETED"
    assert query_persisted_trace_records(settings=settings) == ()


@pytest.mark.anyio
async def test_generation_business_failure_keeps_failure_trace_best_effort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    graph_recorders: list[TraceRecorder] = []
    _patch_generation_dependencies(
        monkeypatch,
        _SequenceLLM([RuntimeError("provider detail must stay internal")]),
        graph_recorders,
    )
    service = TestCaseGenerationService()
    runtime_evaluation_store.clear()
    try:
        with pytest.raises(ApplicationError) as error:
            await service.generate(
                project_id=101,
                api_id="api-orders",
                request=GenerationRequest(),
                token="java-token",
                trace_id="trace:generation-business-failure",
                settings=settings,
            )
        detail = runtime_evaluation_store.list_runs()[0]
    finally:
        runtime_evaluation_store.clear()

    persisted = query_persisted_trace_records(
        agent_run_id=detail.agent_run_id,
        settings=settings,
    )
    assert error.value.code == "GENERATOR_FAILED"
    assert graph_recorders[0].degraded is False
    assert any(
        record.record_type == "model_call" and record.status.value == "FAILED"
        for record in persisted
    )
    assert any(record.event.value == "TERMINAL" for record in persisted)
