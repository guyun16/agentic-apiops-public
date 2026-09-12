"""New-service recovery tests for DiagnosisRun plus its HITL checkpoint."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.settings import AppSettings
from app.schemas.runner import TestReport as RunnerTestReport
from app.services.diagnosis import DiagnosisExecutionService
from app.services.diagnosis_repository import SQLiteDiagnosisRunRepository
from app.tools import FakeToolGatewayAdapter
from app.workflows.approval import ApprovalAction


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
                    "steps": [],
                }
            ],
        }
    )


def _tool_intent() -> dict[str, object]:
    return {"tool_name": "redis.read", "arguments": {"key": "task:701"}}


def _report_from_prompt(prompt: str) -> dict[str, object]:
    match = re.search(r"Copy exactly: agentRunId=(\S+), traceId=(\S+)\.", prompt)
    assert match is not None
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
        "sufficientEvidence": True,
        "limitations": [],
        "recommendedChecks": ["Inspect the endpoint dependency health."],
        "traceId": match.group(2),
    }


def _tool_result() -> dict[str, object]:
    return {
        "schemaVersion": "0.1.0",
        "toolCallId": "java-call-restart",
        "status": "SUCCESS",
        "data": {"value": "ready"},
        "error": None,
        "sanitized": True,
        "traceId": "trace:restart",
    }


class _SequenceDeepSeek:
    response_factories: list[Callable[[str], dict[str, object]]] = []
    models: list[str] = []

    def __init__(
        self,
        http_client: object,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        del http_client, api_key, base_url, timeout_seconds
        self.model = model
        self.provider = "FakeDeepSeek"
        self._response_factory = self.response_factories.pop(0)
        self.models.append(model)

    async def complete(self, prompt: str) -> str:
        return json.dumps(self._response_factory(prompt))


class _FakeJavaGateway(FakeToolGatewayAdapter):
    instances: list[_FakeJavaGateway] = []

    def __init__(
        self,
        java_client: object,
        *,
        project_id: int,
        token_provider: Callable[[], str],
    ) -> None:
        del java_client, project_id, token_provider
        super().__init__(_tool_result())
        self.instances.append(self)


@pytest.mark.anyio
async def test_new_service_recovers_pending_approval_and_resumes_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "app.clients.llm_provider.DeepSeekClient",
        _SequenceDeepSeek,
    )
    monkeypatch.setattr(
        "app.services.diagnosis.JavaApiOpsToolGatewayAdapter",
        _FakeJavaGateway,
    )
    _SequenceDeepSeek.models = []
    _SequenceDeepSeek.response_factories = [lambda _: _tool_intent(), _report_from_prompt]
    _FakeJavaGateway.instances = []
    report = _failed_report()
    database_path = tmp_path / "agentlab-runtime.sqlite3"
    settings_a = AppSettings(
        deepseek_api_key=SecretStr("test-key"),
        deepseek_model="model-before-restart",
    )
    repository_a = SQLiteDiagnosisRunRepository(database_path)
    service_a = DiagnosisExecutionService(
        settings_a,
        run_repository=repository_a,
        checkpoint_db_path=repository_a.database_path,
    )
    fetches: list[tuple[str, str]] = []

    async def fetch_a(**kwargs: object) -> RunnerTestReport:
        fetches.append(("service-a", kwargs["token"]))  # type: ignore[arg-type]
        return report

    monkeypatch.setattr(service_a, "_fetch_report", fetch_a)
    pending = await service_a.start(
        project_id=41,
        run_id=701,
        token="java-token-initial",
        trace_id="trace:restart",
        settings=settings_a,
    )

    assert pending.status == "APPROVAL_REQUIRED"
    assert pending.approval_request is not None
    assert pending.approval_request.arguments == {"key": "task:701"}
    assert _FakeJavaGateway.instances[0].calls == []
    repository_a.close()

    settings_b = AppSettings(
        deepseek_api_key=SecretStr("test-key"),
        deepseek_model="model-before-restart",
    )
    repository_b = SQLiteDiagnosisRunRepository(database_path)
    service_b = DiagnosisExecutionService(
        settings_b,
        run_repository=repository_b,
        checkpoint_db_path=repository_b.database_path,
    )

    async def fetch_b(**kwargs: object) -> RunnerTestReport:
        fetches.append(("service-b", kwargs["token"]))  # type: ignore[arg-type]
        return report

    monkeypatch.setattr(service_b, "_fetch_report", fetch_b)
    recovered_history = service_b.list(project_id=41)
    assert len(recovered_history) == 1
    assert recovered_history[0].agent_run_id == pending.agent_run_id
    assert recovered_history[0].status == "APPROVAL_REQUIRED"

    recovered = await service_b.get(
        agent_run_id=pending.agent_run_id,
        token="java-token-restart",
        settings=settings_b,
    )

    assert recovered.status == "APPROVAL_REQUIRED"
    assert recovered.agent_run_id == pending.agent_run_id
    assert recovered.workflow_id == pending.workflow_id
    assert recovered.approval_request == pending.approval_request
    assert recovered.approval_request is not None
    assert recovered.approval_request.arguments == pending.approval_request.arguments
    assert recovered.approval_request.risk == pending.approval_request.risk
    assert recovered.steps == pending.steps
    assert recovered.context == pending.context
    assert {step.id for step in recovered.steps} >= {
        "java-test-report",
        "context-pack",
        "diagnosis-llm",
        "hitl-approval",
    }
    assert recovered.context.evidence_items > 0
    assert recovered.context.context_characters > 0
    assert recovered.context.model_calls == 1
    assert recovered.context.unavailable_fields == ()

    resumed = await service_b.resume(
        agent_run_id=pending.agent_run_id,
        token="java-token-restart",
        decision=ApprovalAction.APPROVE,
        edited_arguments=None,
        trace_id="trace:resume",
        settings=settings_b,
    )

    assert resumed.status == "COMPLETED"
    assert resumed.agent_run_id == pending.agent_run_id
    assert resumed.workflow_id == pending.workflow_id
    assert len(_FakeJavaGateway.instances) == 2
    assert _FakeJavaGateway.instances[0].calls == []
    assert len(_FakeJavaGateway.instances[1].calls) == 1
    assert _SequenceDeepSeek.models == ["model-before-restart", "model-before-restart"]
    assert fetches == [
        ("service-a", "java-token-initial"),
        ("service-b", "java-token-restart"),
        ("service-b", "java-token-restart"),
    ]
    completed_history = service_b.list(project_id=41)
    assert completed_history[0].status == "COMPLETED"
    assert completed_history[0].summary == resumed.report.summary
    repository_b.close()

    repository_c = SQLiteDiagnosisRunRepository(database_path)
    service_c = DiagnosisExecutionService(
        settings_b,
        run_repository=repository_c,
        checkpoint_db_path=repository_c.database_path,
    )

    async def fetch_c(**kwargs: object) -> RunnerTestReport:
        fetches.append(("service-c", kwargs["token"]))  # type: ignore[arg-type]
        return report

    monkeypatch.setattr(service_c, "_fetch_report", fetch_c)
    completed = await service_c.get(
        agent_run_id=pending.agent_run_id,
        token="java-token-second-restart",
        settings=settings_b,
    )

    assert completed.status == "COMPLETED"
    assert completed.report == resumed.report
    assert completed.steps == resumed.steps
    assert completed.context == resumed.context
    assert {step.id for step in completed.steps} >= {
        "java-test-report",
        "context-pack",
        "diagnosis-llm",
        "hitl-approval",
        "java-tool-gateway",
        "diagnosis-report",
    }
    assert completed.context.model_calls == 2
    assert completed.context.tool_calls == 1
    assert completed.context.unavailable_fields == ()
    assert fetches[-1] == ("service-c", "java-token-second-restart")
    repository_c.close()
