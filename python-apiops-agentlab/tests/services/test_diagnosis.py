"""Diagnosis service composition and Java apiId resolution tests."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.api import routes as api_routes
from app.clients.java_apiops import JavaApiOpsClient, JavaApiOpsTransportError, JavaRunSummary
from app.core.errors import ApplicationError
from app.core.settings import AppSettings
from app.memory import (
    InMemoryMemoryStore,
    MemoryLifecycleStatus,
    MemoryRetriever,
    MemoryWriteOutcome,
    MemoryWritePolicy,
    MemoryWriteReason,
    SQLiteMemoryStore,
    VerificationStatus,
)
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.runner import TestReport as RunnerTestReport
from app.services.diagnosis import DiagnosisExecutionService, _DiagnosisRun
from app.services.diagnosis_repository import SQLiteDiagnosisRunRepository, StoredDiagnosisRun
from app.services.runtime_evaluation import runtime_evaluation_store
from app.tracing import InMemoryTraceSink, TraceRecorder
from app.workflows.approval import ApprovalAction, ApprovalRequest
from app.workflows.diagnosis_memory_query import build_memory_symptoms


class _AsyncClientContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("summaries", "expected"),
    [
        (
            (
                JavaRunSummary(run_id=701, case_id="case-701", api_id="orders.get"),
                JavaRunSummary(run_id=702, case_id="case-702", api_id="billing.get"),
            ),
            "orders.get",
        ),
        ((JavaRunSummary(run_id=702, case_id="case-702", api_id="billing.get"),), None),
        (
            (
                JavaRunSummary(run_id=701, case_id="case-701-a", api_id="orders.get"),
                JavaRunSummary(run_id=701, case_id="case-701-b", api_id="billing.get"),
            ),
            None,
        ),
    ],
)
async def test_api_id_resolution_requires_one_exact_run_match(
    monkeypatch: pytest.MonkeyPatch,
    summaries: tuple[JavaRunSummary, ...],
    expected: str | None,
) -> None:
    async def list_test_runs(
        client: JavaApiOpsClient,
        *,
        project_id: int,
        token: str,
        trace_id: str,
    ) -> tuple[JavaRunSummary, ...]:
        assert isinstance(client, JavaApiOpsClient)
        assert (project_id, token, trace_id) == (41, "java-token", "trace-api-id")
        return summaries

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _AsyncClientContext())
    monkeypatch.setattr(JavaApiOpsClient, "list_test_runs", list_test_runs)
    service = DiagnosisExecutionService(
        AppSettings(),
        memory_retriever=MemoryRetriever(InMemoryMemoryStore()),
    )

    result = await service._resolve_api_id(
        project_id=41,
        run_id=701,
        token="java-token",
        trace_id="trace-api-id",
        settings=AppSettings(),
    )

    assert result == expected


@pytest.mark.anyio
async def test_api_id_resolution_skips_recall_when_java_summary_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def list_test_runs(*args: object, **kwargs: object) -> tuple[JavaRunSummary, ...]:
        del args, kwargs
        raise JavaApiOpsTransportError("Java API Ops request failed during transport")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _AsyncClientContext())
    monkeypatch.setattr(JavaApiOpsClient, "list_test_runs", list_test_runs)
    service = DiagnosisExecutionService(
        AppSettings(),
        memory_retriever=MemoryRetriever(InMemoryMemoryStore()),
    )

    result = await service._resolve_api_id(
        project_id=41,
        run_id=701,
        token="java-token",
        trace_id="trace-api-id",
        settings=AppSettings(),
    )

    assert result is None


def test_routes_compose_one_shared_sqlite_retriever_for_diagnosis() -> None:
    assert isinstance(api_routes._historical_memory_store, SQLiteMemoryStore)
    assert isinstance(api_routes._diagnosis_service._memory_retriever, MemoryRetriever)
    assert isinstance(api_routes._historical_memory_write_policy, MemoryWritePolicy)
    assert (
        api_routes._diagnosis_service._memory_write_policy
        is api_routes._historical_memory_write_policy
    )


def memory_test_report(
    *,
    report_id: str = "report:701",
    project_id: int = 41,
    run_id: int = 701,
) -> RunnerTestReport:
    return RunnerTestReport.model_validate(
        {
            "projectId": project_id,
            "taskId": 301,
            "runId": run_id,
            "reportId": report_id,
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


def memory_diagnosis_report(
    *,
    agent_run_id: str = "agent_run:memory-write",
    report_id: str = "report:701",
    project_id: int = 41,
    run_id: int = 701,
    summary: str = "The status assertion observed HTTP 500 instead of HTTP 200.",
    root_causes: tuple[str, ...] = (
        "The endpoint returned an unexpected server response.",
        "The upstream dependency returned an invalid status.",
    ),
    recommended_checks: tuple[str, ...] = ("Inspect the endpoint dependency health.",),
) -> DiagnosisReport:
    return DiagnosisReport.model_validate(
        {
            "schemaVersion": "0.1.0",
            "reportId": report_id,
            "agentRunId": agent_run_id,
            "projectId": project_id,
            "runId": run_id,
            "failureType": "ASSERTION_MISMATCH",
            "summary": summary,
            "rootCauseHypotheses": [
                {
                    "statement": statement,
                    "confidence": "MEDIUM",
                    "evidenceRefs": [{"itemId": report_id}],
                }
                for statement in root_causes
            ],
            "sufficientEvidence": True,
            "limitations": [],
            "recommendedChecks": list(recommended_checks),
            "traceId": "trace:memory-write",
        }
    )


@pytest.fixture
def memory_service(tmp_path: Path):
    store = SQLiteMemoryStore(tmp_path / "historical-memory.sqlite3")
    runtime_store = SQLiteDiagnosisRunRepository(tmp_path / "agentlab-runtime.sqlite3")
    service = DiagnosisExecutionService(
        AppSettings(),
        memory_retriever=MemoryRetriever(store),
        memory_write_policy=MemoryWritePolicy(store),
        run_repository=runtime_store,
        checkpoint_db_path=runtime_store.database_path,
    )
    try:
        yield service, store
    finally:
        runtime_store.close()
        store.close()


def add_memory_record(
    service: DiagnosisExecutionService,
    *,
    test_report: RunnerTestReport,
    diagnosis_report: DiagnosisReport,
    agent_run_id: str,
    api_id: str | None = "orders.get",
    status: str = "COMPLETED",
) -> _DiagnosisRun:
    record = _DiagnosisRun(
        agent_run_id=agent_run_id,
        workflow_id=f"diagnosis-workflow:{agent_run_id}",
        trace_id="trace:memory-write",
        project_id=test_report.project_id,
        run_id=test_report.run_id,
        api_id=api_id,
        test_report=test_report,
        trace_recorder=TraceRecorder(InMemoryTraceSink()),
        model="deepseek-v4-flash",
        status=status,
        diagnosis_report=diagnosis_report,
    )
    service._persist_record(record)
    return record


def test_legacy_diagnosis_snapshot_marks_unpersisted_projection_unavailable(
    tmp_path: Path,
) -> None:
    repository = SQLiteDiagnosisRunRepository(tmp_path / "agentlab-runtime.sqlite3")
    report = memory_test_report()
    diagnosis = memory_diagnosis_report(agent_run_id="agent_run:legacy")
    repository.save(
        StoredDiagnosisRun(
            agent_run_id="agent_run:legacy",
            workflow_id="workflow:legacy",
            trace_id="trace:legacy",
            project_id=41,
            run_id=701,
            api_id="orders.get",
            test_report=report,
            model="deepseek-v4-flash",
            status="COMPLETED",
            diagnosis_report=diagnosis,
        )
    )
    service = DiagnosisExecutionService(
        AppSettings(trace_jsonl_path=str(tmp_path / "missing.jsonl")),
        run_repository=repository,
        checkpoint_db_path=repository.database_path,
    )

    response = service._snapshot(service._get_record("agent_run:legacy"))

    assert {step.id for step in response.steps} == {"java-test-report", "diagnosis-report"}
    assert set(response.context.unavailable_fields) == {
        "evidenceItems",
        "contextCharacters",
        "modelCalls",
        "toolCalls",
    }
    repository.close()


def patch_memory_fetch(
    monkeypatch: pytest.MonkeyPatch,
    service: DiagnosisExecutionService,
    refreshed: RunnerTestReport,
) -> None:
    async def fetch_report(**kwargs: object) -> RunnerTestReport:
        del kwargs
        return refreshed

    monkeypatch.setattr(service, "_fetch_report", fetch_report)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("settings", "expected_provider", "expected_model"),
    (
        (
            AppSettings(deepseek_api_key=SecretStr("fake-deepseek-key")),
            "DeepSeek",
            "deepseek-v4-flash",
        ),
        (
            AppSettings(
                diagnosis_llm_provider="qwen",
                qwen_api_key=SecretStr("fake-qwen-key"),
            ),
            "Qwen",
            "qwen3.8-max",
        ),
    ),
)
async def test_start_records_selected_diagnosis_provider_and_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    settings: AppSettings,
    expected_provider: str,
    expected_model: str,
) -> None:
    repository = SQLiteDiagnosisRunRepository(tmp_path / "diagnosis.sqlite3")
    service = DiagnosisExecutionService(
        settings,
        run_repository=repository,
        checkpoint_db_path=repository.database_path,
    )
    report = memory_test_report()

    async def fetch_report(**kwargs: object) -> RunnerTestReport:
        del kwargs
        return report

    async def invoke(**kwargs: object) -> dict[str, object]:
        record = kwargs["record"]
        assert isinstance(record, _DiagnosisRun)
        return {
            "diagnosis_report": memory_diagnosis_report(
                agent_run_id=record.agent_run_id,
            )
        }

    monkeypatch.setattr(service, "_fetch_report", fetch_report)
    monkeypatch.setattr(service, "_invoke", invoke)
    runtime_evaluation_store.clear()
    try:
        response = await service.start(
            project_id=41,
            run_id=701,
            token="java-token",
            trace_id="trace:composition",
            settings=settings,
        )
        detail = runtime_evaluation_store.get_detail(response.agent_run_id)
        stored = repository.get(response.agent_run_id)
    finally:
        runtime_evaluation_store.clear()
        repository.close()

    assert response.provider == expected_provider
    assert response.model == expected_model
    assert detail is not None
    assert detail.provider == expected_provider
    assert detail.model == expected_model
    assert stored is not None
    assert stored.provider == expected_provider
    assert stored.model == expected_model


@pytest.mark.anyio
async def test_resume_rejects_provider_or_model_switch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = SQLiteDiagnosisRunRepository(tmp_path / "diagnosis.sqlite3")
    service = DiagnosisExecutionService(
        AppSettings(deepseek_api_key=SecretStr("fake-deepseek-key")),
        run_repository=repository,
        checkpoint_db_path=repository.database_path,
    )
    pending = _DiagnosisRun(
        agent_run_id="agent_run:provider-switch",
        workflow_id="workflow:provider-switch",
        trace_id="trace:provider-switch",
        project_id=41,
        run_id=701,
        api_id=None,
        test_report=memory_test_report(),
        trace_recorder=TraceRecorder(InMemoryTraceSink()),
        provider="DeepSeek",
        model="deepseek-v4-flash",
        status="APPROVAL_REQUIRED",
        approval_request=ApprovalRequest(
            workflow_id="workflow:provider-switch",
            project_id="41",
            intent_id="intent:provider-switch",
            tool_name="redis.read",
            arguments_fingerprint="0" * 64,
        ),
    )
    service._persist_record(pending)

    async def unexpected_fetch(**kwargs: object) -> RunnerTestReport:
        del kwargs
        raise AssertionError("provider switch must be rejected before Java re-authorization")

    monkeypatch.setattr(service, "_fetch_report", unexpected_fetch)
    try:
        with pytest.raises(ApplicationError) as captured:
            await service.resume(
                agent_run_id=pending.agent_run_id,
                token="java-token",
                decision=ApprovalAction.APPROVE,
                edited_arguments=None,
                trace_id="trace:resume",
                settings=AppSettings(
                    diagnosis_llm_provider="qwen",
                    qwen_api_key=SecretStr("fake-qwen-key"),
                ),
            )
    finally:
        repository.close()

    assert captured.value.status_code == 409
    assert captured.value.code == "DIAGNOSIS_PROVIDER_MISMATCH"


@pytest.mark.anyio
async def test_explicit_remember_writes_verified_memory_and_is_recallable(
    memory_service: tuple[DiagnosisExecutionService, SQLiteMemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store = memory_service
    report = memory_test_report()
    final_report = memory_diagnosis_report()
    add_memory_record(
        service,
        test_report=report,
        diagnosis_report=final_report,
        agent_run_id="agent_run:memory-write",
    )
    patch_memory_fetch(monkeypatch, service, report)

    assert len(store) == 0
    response = await service.remember_verified_diagnosis(
        agent_run_id="agent_run:memory-write",
        hypothesis_index=1,
        token="java-token",
        settings=AppSettings(),
    )

    assert response.outcome is MemoryWriteOutcome.ACCEPT
    assert response.reason is MemoryWriteReason.ACCEPTED
    assert response.stored is True
    assert response.memory_id is not None
    entry = store.get(response.memory_id)
    assert entry is not None
    assert entry.project_id == 41
    assert entry.api_id == "orders.get"
    assert entry.source_run_id == 701
    assert entry.symptoms == list(build_memory_symptoms(report))
    assert entry.root_cause == final_report.root_cause_hypotheses[1].statement
    assert entry.summary == final_report.summary
    assert entry.resolution == "Inspect the endpoint dependency health."
    assert entry.verification_status is VerificationStatus.VERIFIED
    assert entry.lifecycle_status is MemoryLifecycleStatus.ACTIVE
    assert MemoryRetriever(store).retrieve_similar(
        project_id=41,
        api_id="orders.get",
        symptoms=build_memory_symptoms(report),
        root_cause=final_report.root_cause_hypotheses[1].statement,
    ) == [entry]


@pytest.mark.anyio
async def test_remember_is_idempotent_and_preserves_duplicate_conflict(
    memory_service: tuple[DiagnosisExecutionService, SQLiteMemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store = memory_service
    report = memory_test_report()
    final_report = memory_diagnosis_report()
    add_memory_record(
        service,
        test_report=report,
        diagnosis_report=final_report,
        agent_run_id="agent_run:memory-write",
    )
    patch_memory_fetch(monkeypatch, service, report)

    first = await service.remember_verified_diagnosis(
        agent_run_id="agent_run:memory-write",
        hypothesis_index=0,
        token="java-token",
    )
    second = await service.remember_verified_diagnosis(
        agent_run_id="agent_run:memory-write",
        hypothesis_index=0,
        token="java-token",
    )

    assert first.outcome is MemoryWriteOutcome.ACCEPT
    assert second.outcome is MemoryWriteOutcome.IDEMPOTENT
    assert second.memory_id == first.memory_id
    assert second.stored is True
    assert len(store) == 1

    conflict_report = memory_diagnosis_report(
        agent_run_id="agent_run:memory-conflict",
        summary="A different verified summary for the same failure identity.",
        recommended_checks=("Use a different deterministic follow-up check.",),
    )
    add_memory_record(
        service,
        test_report=report,
        diagnosis_report=conflict_report,
        agent_run_id="agent_run:memory-conflict",
    )
    conflict = await service.remember_verified_diagnosis(
        agent_run_id="agent_run:memory-conflict",
        hypothesis_index=0,
        token="java-token",
    )

    assert conflict.outcome is MemoryWriteOutcome.DUPLICATE_CONFLICT
    assert conflict.reason is MemoryWriteReason.FAILURE_FINGERPRINT_CONFLICT
    assert conflict.stored is False
    assert conflict.memory_id == first.memory_id
    assert len(store) == 1


@pytest.mark.anyio
async def test_remember_rejects_invalid_selection_without_writing(
    memory_service: tuple[DiagnosisExecutionService, SQLiteMemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store = memory_service
    report = memory_test_report()
    add_memory_record(
        service,
        test_report=report,
        diagnosis_report=memory_diagnosis_report(),
        agent_run_id="agent_run:memory-write",
    )
    patch_memory_fetch(monkeypatch, service, report)

    with pytest.raises(ApplicationError) as error:
        await service.remember_verified_diagnosis(
            agent_run_id="agent_run:memory-write",
            hypothesis_index=99,
            token="java-token",
        )

    assert error.value.code == "DIAGNOSIS_HYPOTHESIS_NOT_FOUND"
    assert len(store) == 0


@pytest.mark.anyio
async def test_remember_rejects_non_completed_or_missing_api_id_without_writing(
    memory_service: tuple[DiagnosisExecutionService, SQLiteMemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store = memory_service
    report = memory_test_report()
    add_memory_record(
        service,
        test_report=report,
        diagnosis_report=memory_diagnosis_report(),
        agent_run_id="agent_run:pending",
        status="APPROVAL_REQUIRED",
    )

    async def unexpected_fetch(**kwargs: object) -> RunnerTestReport:
        del kwargs
        raise AssertionError("non-completed diagnosis must not re-read Java")

    monkeypatch.setattr(service, "_fetch_report", unexpected_fetch)
    with pytest.raises(ApplicationError) as pending_error:
        await service.remember_verified_diagnosis(
            agent_run_id="agent_run:pending",
            hypothesis_index=0,
            token="java-token",
        )
    assert pending_error.value.code == "DIAGNOSIS_NOT_COMPLETED"

    add_memory_record(
        service,
        test_report=report,
        diagnosis_report=memory_diagnosis_report(agent_run_id="agent_run:no-api-id"),
        agent_run_id="agent_run:no-api-id",
        api_id=None,
    )
    patch_memory_fetch(monkeypatch, service, report)
    with pytest.raises(ApplicationError) as api_id_error:
        await service.remember_verified_diagnosis(
            agent_run_id="agent_run:no-api-id",
            hypothesis_index=0,
            token="java-token",
        )
    assert api_id_error.value.code == "MEMORY_API_ID_UNAVAILABLE"
    assert len(store) == 0


@pytest.mark.anyio
async def test_remember_rejects_changed_or_unauthorized_java_report(
    memory_service: tuple[DiagnosisExecutionService, SQLiteMemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store = memory_service
    report = memory_test_report()
    add_memory_record(
        service,
        test_report=report,
        diagnosis_report=memory_diagnosis_report(),
        agent_run_id="agent_run:changed-report",
    )
    patch_memory_fetch(
        monkeypatch,
        service,
        report.model_copy(update={"report_id": "report:changed"}),
    )
    with pytest.raises(ApplicationError) as changed_error:
        await service.remember_verified_diagnosis(
            agent_run_id="agent_run:changed-report",
            hypothesis_index=0,
            token="java-token",
        )
    assert changed_error.value.code == "TEST_REPORT_CHANGED"

    add_memory_record(
        service,
        test_report=report,
        diagnosis_report=memory_diagnosis_report(agent_run_id="agent_run:unauthorized"),
        agent_run_id="agent_run:unauthorized",
    )

    async def unauthorized_fetch(**kwargs: object) -> RunnerTestReport:
        del kwargs
        raise ApplicationError("JAVA_AUTHORIZATION_DENIED", "denied", 403)

    monkeypatch.setattr(service, "_fetch_report", unauthorized_fetch)
    with pytest.raises(ApplicationError) as unauthorized_error:
        await service.remember_verified_diagnosis(
            agent_run_id="agent_run:unauthorized",
            hypothesis_index=0,
            token="java-token",
        )
    assert unauthorized_error.value.code == "JAVA_AUTHORIZATION_DENIED"
    assert len(store) == 0


@pytest.mark.anyio
async def test_remember_requires_recommended_checks_for_resolution(
    memory_service: tuple[DiagnosisExecutionService, SQLiteMemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store = memory_service
    report = memory_test_report()
    add_memory_record(
        service,
        test_report=report,
        diagnosis_report=memory_diagnosis_report(
            agent_run_id="agent_run:no-resolution",
            recommended_checks=(),
        ),
        agent_run_id="agent_run:no-resolution",
    )
    patch_memory_fetch(monkeypatch, service, report)

    with pytest.raises(ApplicationError) as error:
        await service.remember_verified_diagnosis(
            agent_run_id="agent_run:no-resolution",
            hypothesis_index=0,
            token="java-token",
        )

    assert error.value.code == "DIAGNOSIS_RESOLUTION_MISSING"
    assert len(store) == 0
