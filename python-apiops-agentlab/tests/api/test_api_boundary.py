"""FastAPI, settings, error, and logging boundary tests."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.api import routes as api_routes
from app.core.errors import ApplicationError, register_exception_handlers
from app.core.logging import LOGGER_NAME
from app.core.settings import AppSettings
from app.main import app as application
from app.memory import MemoryWriteOutcome, MemoryWriteReason
from app.schemas.testcase_dsl import TestCaseDSL as CaseModel
from app.tracing import (
    AgentRun,
    InMemoryTraceSink,
    Latency,
    ModelCall,
    ModelIdentity,
    PayloadDigest,
    PromptIdentity,
    TokenUsage,
    TraceEvent,
    TraceRecord,
    TraceRecorder,
    TraceStatus,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_ROOT = REPOSITORY_ROOT / "examples"
VALID_TESTCASE_FIXTURE = EXAMPLES_ROOT / "testcase-valid.json"
VALIDATION_PATH = "/api/v1/contracts/testcases:validate"


def java_project_envelope(project_id: int = 41) -> dict[str, object]:
    return {
        "success": True,
        "code": "OK",
        "message": "success",
        "data": {
            "id": project_id,
            "projectKey": f"project-{project_id}",
            "projectName": f"Project {project_id}",
            "ownerUserId": 7,
            "status": "ACTIVE",
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        },
    }


def patch_java_project_response(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int = 200,
) -> list[httpx.Request]:
    requests: list[httpx.Request] = []
    real_async_client = httpx.AsyncClient

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if status_code == 200:
            return httpx.Response(200, json=java_project_envelope())
        return httpx.Response(
            status_code,
            json={"success": False, "code": "PROJECT_ACCESS_DENIED", "message": "denied"},
        )

    def async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        assert kwargs.get("trust_env") is False
        return real_async_client(
            *args,
            transport=httpx.MockTransport(handler),
            **kwargs,
        )

    monkeypatch.setattr(api_routes.httpx, "AsyncClient", async_client)
    return requests


@pytest.fixture
def empty_runtime_store():
    api_routes.runtime_evaluation_store.clear()
    yield
    api_routes.runtime_evaluation_store.clear()


def load_fixture(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def asgi_request(
    app: Any,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], BaseException | None]:
    """Exercise an ASGI app without an HTTP client or network access."""

    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = [] if payload is None else [(b"content-type", b"application/json")]
    if headers:
        request_headers.extend(
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in headers.items()
        )
    request_path, _, query_string = path.partition("?")
    messages: list[dict[str, Any]] = []
    receive_state = {"sent": False}

    async def receive() -> dict[str, Any]:
        if receive_state["sent"]:
            return {"type": "http.disconnect"}
        receive_state["sent"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": request_path,
        "raw_path": path.encode("ascii"),
        "query_string": query_string.encode("ascii"),
        "headers": request_headers,
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
    }

    caught: BaseException | None = None
    try:
        asyncio.run(app(scope, receive, send))
    except BaseException as exception:  # pragma: no cover - only unexpected ASGI behavior
        caught = exception

    response_start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return int(response_start["status"]), json.loads(response_body), caught


def test_health_returns_typed_response() -> None:
    status, body, caught = asgi_request(application, "GET", "/health")

    assert caught is None
    assert status == 200
    assert body == {
        "status": "ok",
        "service": "python-apiops-agentlab",
    }


def test_valid_testcase_uses_existing_typed_view() -> None:
    payload = load_fixture(VALID_TESTCASE_FIXTURE)

    status, body, caught = asgi_request(application, "POST", VALIDATION_PATH, payload)

    assert caught is None
    assert status == 200
    assert body == {
        "valid": True,
        "validationScope": "PYTHON_LOCAL",
        "caseId": payload["caseId"],
    }


def test_diagnosis_memory_route_accepts_only_hypothesis_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeDiagnosisService:
        async def remember_verified_diagnosis(self, **kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            return {
                "agentRunId": "agent_run:memory",
                "projectId": 41,
                "runId": 701,
                "outcome": MemoryWriteOutcome.ACCEPT,
                "reason": MemoryWriteReason.ACCEPTED,
                "memoryId": "memory:1",
                "stored": True,
            }

    monkeypatch.setattr(api_routes, "_diagnosis_service", FakeDiagnosisService())
    path = "/api/v1/diagnosis/runs/agent_run:memory/memory"
    status, body, caught = asgi_request(
        application,
        "POST",
        path,
        {"hypothesisIndex": 1},
        headers={"Authorization": "Bearer java-token"},
    )

    assert caught is None
    assert status == 200
    assert body == {
        "agentRunId": "agent_run:memory",
        "projectId": 41,
        "runId": 701,
        "outcome": "ACCEPT",
        "reason": "ACCEPTED",
        "memoryId": "memory:1",
        "stored": True,
    }
    assert calls[0]["agent_run_id"] == "agent_run:memory"
    assert calls[0]["hypothesis_index"] == 1
    assert calls[0]["token"] == "java-token"

    status, _, caught = asgi_request(
        application,
        "POST",
        path,
        {"hypothesisIndex": 1, "apiId": "forged-api"},
        headers={"Authorization": "Bearer java-token"},
    )
    assert caught is None
    assert status == 422
    assert len(calls) == 1


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/evaluation/runtime/summary?projectId=41",
        "/api/v1/evaluation/runtime/runs?projectId=41",
    ),
)
def test_runtime_read_routes_authorize_project_before_returning_data(
    monkeypatch: pytest.MonkeyPatch,
    empty_runtime_store: None,
    path: str,
) -> None:
    requests = patch_java_project_response(monkeypatch)
    api_routes.runtime_evaluation_store.begin(
        agent_run_id="agent_run:authorized",
        trace_id="trace:authorized",
        execution_type="DIAGNOSIS",
        provider="DeepSeek",
        model="deepseek-chat",
        project_id=41,
    )
    api_routes.runtime_evaluation_store.update(
        agent_run_id="agent_run:authorized",
        status="COMPLETED",
    )

    status, body, caught = asgi_request(
        application,
        "GET",
        path,
        headers={"Authorization": "Bearer user-token"},
    )

    assert caught is None
    assert status == 200
    assert body["runCount"] == 1 if "summary" in path else len(body) == 1
    assert requests[0].url.path == "/api/v1/projects/41"
    assert requests[0].headers["authorization"] == "Bearer user-token"


@pytest.mark.parametrize("java_status", (401, 403))
def test_runtime_read_routes_fail_closed_on_java_authentication_or_authorization(
    monkeypatch: pytest.MonkeyPatch,
    empty_runtime_store: None,
    java_status: int,
) -> None:
    requests = patch_java_project_response(monkeypatch, java_status)

    status, body, caught = asgi_request(
        application,
        "GET",
        "/api/v1/evaluation/runtime/summary?projectId=99",
        headers={"Authorization": "Bearer user-token"},
    )

    assert caught is None
    assert status == java_status
    assert body["error"]["code"] == (
        "JAVA_AUTHENTICATION_FAILED" if java_status == 401 else "JAVA_AUTHORIZATION_DENIED"
    )
    assert requests[0].url.path == "/api/v1/projects/99"


def test_runtime_detail_authorizes_record_project_before_returning_data(
    monkeypatch: pytest.MonkeyPatch,
    empty_runtime_store: None,
) -> None:
    requests = patch_java_project_response(monkeypatch, 403)
    api_routes.runtime_evaluation_store.begin(
        agent_run_id="agent_run:cross-project",
        trace_id="trace:cross-project",
        execution_type="DIAGNOSIS",
        provider="DeepSeek",
        model="deepseek-chat",
        project_id=42,
    )
    api_routes.runtime_evaluation_store.update(
        agent_run_id="agent_run:cross-project",
        status="COMPLETED",
    )

    status, body, caught = asgi_request(
        application,
        "GET",
        "/api/v1/evaluation/runtime/runs/agent_run:cross-project",
        headers={"Authorization": "Bearer user-token"},
    )

    assert caught is None
    assert status == 403
    assert body == {
        "error": {
            "code": "JAVA_AUTHORIZATION_DENIED",
            "message": "Java denied access to the requested project resource.",
        }
    }
    assert requests[0].url.path == "/api/v1/projects/42"


def observed_trace_records(
    *,
    trace_id: str = "trace:real",
    agent_run_id: str = "agent_run:real",
    run_id: int = 901,
) -> tuple[TraceRecord, ...]:
    started_at = datetime(2026, 8, 29, 9, 0, 0, tzinfo=UTC)
    recorder = TraceRecorder(InMemoryTraceSink())
    recorder.record(
        AgentRun(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            project_id=41,
            event=TraceEvent.START,
            status=TraceStatus.RUNNING,
            timestamp=started_at,
        ),
    )
    model_call_id = "model_call:real"
    model_input = PayloadDigest.from_value("real prompt")
    recorder.record(
        ModelCall(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            agent_step_id="agent_step:real",
            project_id=41,
            event=TraceEvent.START,
            status=TraceStatus.RUNNING,
            timestamp=started_at,
            model_call_id=model_call_id,
            model_identity=ModelIdentity(provider="DeepSeek", model="deepseek-chat"),
            prompt=PromptIdentity(name="diagnosis", version="1"),
            model_input=model_input,
        ),
    )
    recorder.record(
        ModelCall(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            agent_step_id="agent_step:real",
            project_id=41,
            event=TraceEvent.TERMINAL,
            status=TraceStatus.SUCCESS,
            timestamp=started_at.replace(second=1),
            model_call_id=model_call_id,
            model_identity=ModelIdentity(provider="DeepSeek", model="deepseek-chat"),
            prompt=PromptIdentity(name="diagnosis", version="1"),
            model_input=model_input,
            model_output=PayloadDigest.from_value("real output"),
            token_usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            latency=Latency(duration_ms=1000.0),
        ),
    )
    recorder.record(
        AgentRun(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            project_id=41,
            event=TraceEvent.TERMINAL,
            status=TraceStatus.SUCCESS,
            timestamp=started_at.replace(second=2),
        ),
    )
    return recorder.typed_records


def test_trace_read_routes_return_real_typed_records_after_java_authorization(
    monkeypatch: pytest.MonkeyPatch,
    empty_runtime_store: None,
) -> None:
    requests = patch_java_project_response(monkeypatch)
    records = observed_trace_records()
    api_routes.runtime_evaluation_store.begin(
        agent_run_id="agent_run:real",
        trace_id="trace:real",
        execution_type="DIAGNOSIS",
        provider="DeepSeek",
        model="deepseek-chat",
        project_id=41,
        run_id=901,
    )
    api_routes.runtime_evaluation_store.update(
        agent_run_id="agent_run:real",
        status="COMPLETED",
        trace_records=records,
    )

    list_status, list_body, list_caught = asgi_request(
        application,
        "GET",
        "/api/v1/traces?projectId=41",
        headers={"Authorization": "Bearer user-token"},
    )
    detail_status, detail_body, detail_caught = asgi_request(
        application,
        "GET",
        "/api/v1/traces/trace:real",
        headers={"Authorization": "Bearer user-token"},
    )

    assert list_caught is None
    assert detail_caught is None
    assert list_status == detail_status == 200
    assert list_body == detail_body
    assert list_body[0]["record_type"] == "agent_run"
    assert any(item["record_type"] == "model_call" for item in list_body)
    assert any(
        item["trace_id"] == "trace:real" and item["agent_run_id"] == "agent_run:real"
        for item in list_body
    )
    assert requests[0].url.path == "/api/v1/projects/41"
    assert requests[1].url.path == "/api/v1/projects/41"
    assert all(request.headers["authorization"] == "Bearer user-token" for request in requests)


def test_trace_detail_denies_cross_project_access_before_returning_records(
    monkeypatch: pytest.MonkeyPatch,
    empty_runtime_store: None,
) -> None:
    requests = patch_java_project_response(monkeypatch, 403)
    records = tuple(
        record.model_copy(
            update={
                "agent_run_id": "agent_run:cross-project-trace",
                "project_id": 42,
                "trace_id": "trace:cross-project",
            },
        )
        for record in observed_trace_records()
    )
    api_routes.runtime_evaluation_store.begin(
        agent_run_id="agent_run:cross-project-trace",
        trace_id="trace:cross-project",
        execution_type="DIAGNOSIS",
        provider="DeepSeek",
        model="deepseek-chat",
        project_id=42,
    )
    api_routes.runtime_evaluation_store.update(
        agent_run_id="agent_run:cross-project-trace",
        status="COMPLETED",
        trace_records=records,
    )

    status, body, caught = asgi_request(
        application,
        "GET",
        "/api/v1/traces/trace:cross-project",
        headers={"Authorization": "Bearer user-token"},
    )

    assert caught is None
    assert status == 403
    assert body["error"]["code"] == "JAVA_AUTHORIZATION_DENIED"
    assert requests[0].url.path == "/api/v1/projects/42"


def test_trace_read_requires_bearer_before_project_lookup(
    empty_runtime_store: None,
) -> None:
    status, body, caught = asgi_request(
        application,
        "GET",
        "/api/v1/traces?projectId=41",
    )

    assert caught is None
    assert status == 401
    assert body["error"]["code"] == "JAVA_AUTHENTICATION_REQUIRED"


def test_invalid_testcase_returns_fastapi_422_and_does_not_enter_handler() -> None:
    invalid_payload = load_fixture(VALID_TESTCASE_FIXTURE)
    invalid_payload["projectId"] = "1001"

    status, body, caught = asgi_request(
        application,
        "POST",
        VALIDATION_PATH,
        invalid_payload,
    )

    assert caught is None
    assert status == 422
    assert body["detail"]

    test_app = FastAPI()
    handler_state = {"called": False}

    @test_app.post("/testcase")
    async def test_only_handler(payload: CaseModel) -> dict[str, bool]:
        handler_state["called"] = True
        return {"called": bool(payload.steps)}

    status, _, caught = asgi_request(test_app, "POST", "/testcase", invalid_payload)

    assert caught is None
    assert status == 422
    assert handler_state["called"] is False


def test_application_error_maps_to_stable_4xx_response() -> None:
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/application-error")
    async def application_error_route() -> None:
        raise ApplicationError(
            code="LOCAL_CONTRACT_ERROR",
            message="local contract rejected",
            status_code=409,
        )

    status, body, caught = asgi_request(test_app, "GET", "/application-error")

    assert caught is None
    assert status == 409
    assert body == {
        "error": {
            "code": "LOCAL_CONTRACT_ERROR",
            "message": "local contract rejected",
        }
    }


def test_unexpected_error_maps_without_internal_details() -> None:
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/unexpected-error")
    async def unexpected_error_route() -> None:
        raise RuntimeError("private failure at D:/private/app.py")

    status, body, caught = asgi_request(test_app, "GET", "/unexpected-error")
    serialized = json.dumps(body)

    assert isinstance(caught, RuntimeError)
    assert status == 500
    assert body == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Internal server error",
        }
    }
    for forbidden_detail in ("traceback", "RuntimeError", "D:/private", "private failure"):
        assert forbidden_detail not in serialized


def test_settings_use_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "JAVA_APIOPS_BASE_URL",
        "JAVA_APIOPS_TIMEOUT_SECONDS",
        "LOG_LEVEL",
        "ENVIRONMENT",
    ):
        monkeypatch.delenv(variable, raising=False)

    settings = AppSettings()

    assert settings.java_apiops_base_url == "http://localhost:8080"
    assert settings.java_apiops_timeout_seconds == 5.0
    assert settings.log_level == "INFO"
    assert settings.environment == "development"


def test_settings_read_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JAVA_APIOPS_BASE_URL", "https://java.example.test")
    monkeypatch.setenv("JAVA_APIOPS_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ENVIRONMENT", "test")

    settings = AppSettings()

    assert settings.java_apiops_base_url == "https://java.example.test"
    assert settings.java_apiops_timeout_seconds == 2.5
    assert settings.log_level == "DEBUG"
    assert settings.environment == "test"


@pytest.mark.parametrize("timeout", ("not-a-number", "0", "-1"))
def test_settings_reject_invalid_timeout(
    monkeypatch: pytest.MonkeyPatch,
    timeout: str,
) -> None:
    monkeypatch.setenv("JAVA_APIOPS_TIMEOUT_SECONDS", timeout)

    with pytest.raises(ValidationError):
        AppSettings()


def test_settings_reject_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "TRACE")

    with pytest.raises(ValidationError):
        AppSettings()


def test_sensitive_request_values_are_not_written_to_application_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = copy.deepcopy(load_fixture(VALID_TESTCASE_FIXTURE))
    payload["steps"][0]["request"]["headers"] = {
        "Authorization": "Bearer secret-token",
        "Cookie": "session=secret-cookie",
    }
    payload["steps"][0]["request"]["body"] = {
        "password": "secret-password",
        "apiKey": "secret-api-key",
    }

    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    caplog.clear()
    status, _, caught = asgi_request(
        application,
        "POST",
        VALIDATION_PATH,
        payload,
        headers={
            "Authorization": "Bearer incoming-secret",
            "Cookie": "session=incoming-secret",
        },
    )
    logged_messages = "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith(LOGGER_NAME)
    )

    assert caught is None
    assert status == 200
    for sensitive_value in (
        "Authorization",
        "Cookie",
        "secret-token",
        "secret-cookie",
        "password",
        "secret-password",
        "apiKey",
        "secret-api-key",
    ):
        assert sensitive_value not in logged_messages


def _completed_request_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "app.http" and record.getMessage().startswith("request completed")
    ]


def test_request_without_trace_header_generates_correlation_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.http")

    status, body, caught = asgi_request(application, "GET", "/health")

    assert caught is None
    assert status == 200
    assert body == {
        "status": "ok",
        "service": "python-apiops-agentlab",
    }
    records = _completed_request_logs(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.trace_id
    assert record.request_id
    assert "trace_id=" in record.getMessage()
    assert "request_id=" in record.getMessage()


def test_request_trace_header_is_reused_for_log_correlation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.http")

    status, _, caught = asgi_request(
        application,
        "GET",
        "/health",
        headers={"X-Trace-Id": "T500"},
    )

    assert caught is None
    assert status == 200
    records = _completed_request_logs(caplog)
    assert len(records) == 1
    assert records[0].trace_id == "T500"
    assert "trace_id=T500" in records[0].getMessage()


def test_each_request_gets_a_distinct_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.http")

    first_status, _, first_caught = asgi_request(application, "GET", "/health")
    second_status, _, second_caught = asgi_request(application, "GET", "/health")

    assert first_caught is None
    assert second_caught is None
    assert first_status == 200
    assert second_status == 200
    records = _completed_request_logs(caplog)
    assert len(records) == 2
    assert records[0].request_id != records[1].request_id
