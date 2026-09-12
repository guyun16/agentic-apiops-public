from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.api import routes as api_routes
from app.core.errors import ApplicationError
from app.core.settings import AppSettings, get_settings
from app.main import app as application
from app.services.runtime_evaluation import runtime_evaluation_store
from app.tracing import (
    AgentRun,
    InMemoryTraceSink,
    TraceEvent,
    TraceRecord,
    TraceRecorder,
    TraceStatus,
    create_trace_recorder,
)

_UNSET = object()


def _asgi_request(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    async def request() -> tuple[int, dict[str, Any]]:
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.request(method, path, headers=headers)
        return response.status_code, response.json()

    return asyncio.run(request())


def _settings(tmp_path: Path, *, trace_sink: str = "jsonl") -> AppSettings:
    return AppSettings(
        trace_sink=trace_sink,
        trace_jsonl_path=str(tmp_path / "agent-traces.jsonl"),
        trace_max_file_bytes=16 * 1024 * 1024,
    )


def _records(
    *,
    trace_id: str,
    agent_run_id: str,
    project_id: int | str | None,
    terminal_project_id: int | str | None | object = _UNSET,
) -> tuple[AgentRun, ...]:
    recorder = TraceRecorder(InMemoryTraceSink())
    timestamp = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    recorder.record(
        AgentRun(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            project_id=project_id,
            event=TraceEvent.START,
            status=TraceStatus.RUNNING,
            timestamp=timestamp,
        )
    )
    recorder.record(
        AgentRun(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            project_id=project_id if terminal_project_id is _UNSET else terminal_project_id,
            event=TraceEvent.TERMINAL,
            status=TraceStatus.SUCCESS,
            timestamp=timestamp.replace(second=1),
        )
    )
    return recorder.typed_records


def _persist(settings: AppSettings, *record_groups: tuple[AgentRun, ...]) -> None:
    recorder = create_trace_recorder(settings)
    for records in record_groups:
        for record in records:
            recorder.record(record)


@pytest.fixture
def jsonl_settings(tmp_path: Path):
    settings = _settings(tmp_path)
    previous = application.dependency_overrides.get(get_settings)
    application.dependency_overrides[get_settings] = lambda: settings
    runtime_evaluation_store.clear()
    try:
        yield settings
    finally:
        runtime_evaluation_store.clear()
        if previous is None:
            application.dependency_overrides.pop(get_settings, None)
        else:
            application.dependency_overrides[get_settings] = previous


def _allow_authorization(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    authorized_projects: list[int] = []

    async def allow(*, project_id: int, authorization: str | None, settings: AppSettings) -> None:
        del authorization, settings
        authorized_projects.append(project_id)

    monkeypatch.setattr(api_routes, "_authorize_runtime_project", allow)
    return authorized_projects


def test_jsonl_trace_list_and_detail_survive_empty_runtime_store(
    monkeypatch: pytest.MonkeyPatch,
    jsonl_settings: AppSettings,
) -> None:
    authorized_projects = _allow_authorization(monkeypatch)
    owner_records = _records(
        trace_id="trace:durable",
        agent_run_id="agent_run:durable",
        project_id=41,
        terminal_project_id=None,
    )
    other_records = _records(
        trace_id="trace:other",
        agent_run_id="agent_run:other",
        project_id=42,
    )
    _persist(jsonl_settings, owner_records, other_records)
    assert runtime_evaluation_store.get_trace_records("trace:durable") == ()

    list_status, list_body = _asgi_request(
        "GET",
        "/api/v1/traces?projectId=41&agentRunId=agent_run:durable",
        headers={"Authorization": "Bearer user-token"},
    )
    detail_status, detail_body = _asgi_request(
        "GET",
        "/api/v1/traces/trace:durable",
        headers={"Authorization": "Bearer user-token"},
    )

    assert list_status == detail_status == 200
    assert len(list_body) == 1
    assert len(detail_body) == 2
    assert {item["trace_id"] for item in detail_body} == {"trace:durable"}
    assert {item["agent_run_id"] for item in detail_body} == {"agent_run:durable"}
    assert authorized_projects == [41, 41]


def test_jsonl_list_agent_run_filter_cannot_cross_project_scope(
    monkeypatch: pytest.MonkeyPatch,
    jsonl_settings: AppSettings,
) -> None:
    authorized_projects = _allow_authorization(monkeypatch)
    _persist(
        jsonl_settings,
        _records(
            trace_id="trace:owner",
            agent_run_id="agent_run:owner",
            project_id=41,
        ),
        _records(
            trace_id="trace:other",
            agent_run_id="agent_run:other",
            project_id=42,
        ),
    )

    status, body = _asgi_request(
        "GET",
        "/api/v1/traces?projectId=41&agentRunId=agent_run:other",
        headers={"Authorization": "Bearer user-token"},
    )

    assert status == 200
    assert body == []
    assert authorized_projects == [41]


def test_memory_trace_list_behavior_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, trace_sink="memory")
    previous = application.dependency_overrides.get(get_settings)
    application.dependency_overrides[get_settings] = lambda: settings
    authorized_projects = _allow_authorization(monkeypatch)
    records = _records(
        trace_id="trace:memory",
        agent_run_id="agent_run:memory",
        project_id=41,
    )
    runtime_evaluation_store.begin(
        agent_run_id="agent_run:memory",
        trace_id="trace:memory",
        execution_type="DIAGNOSIS",
        provider="DeepSeek",
        model="deepseek-chat",
        project_id=41,
    )
    runtime_evaluation_store.update(
        agent_run_id="agent_run:memory",
        status="COMPLETED",
        trace_records=records,
    )
    try:
        status, body = _asgi_request(
            "GET",
            "/api/v1/traces?projectId=41&agentRunId=agent_run:memory",
            headers={"Authorization": "Bearer user-token"},
        )
    finally:
        runtime_evaluation_store.clear()
        if previous is None:
            application.dependency_overrides.pop(get_settings, None)
        else:
            application.dependency_overrides[get_settings] = previous

    assert status == 200
    assert len(body) == 2
    assert authorized_projects == [41]


def test_missing_jsonl_is_empty_after_project_authorization(
    monkeypatch: pytest.MonkeyPatch,
    jsonl_settings: AppSettings,
) -> None:
    authorized_projects = _allow_authorization(monkeypatch)

    status, body = _asgi_request(
        "GET",
        "/api/v1/traces?projectId=41",
        headers={"Authorization": "Bearer user-token"},
    )

    assert status == 200
    assert body == []
    assert authorized_projects == [41]


@pytest.mark.parametrize(
    "records",
    (
        _records(
            trace_id="trace:no-owner",
            agent_run_id="agent_run:no-owner",
            project_id=None,
        ),
        _records(
            trace_id="trace:ambiguous",
            agent_run_id="agent_run:ambiguous-a",
            project_id=41,
        )
        + _records(
            trace_id="trace:ambiguous",
            agent_run_id="agent_run:ambiguous-b",
            project_id=42,
        ),
    ),
)
def test_jsonl_trace_detail_fails_closed_without_unique_project_owner(
    monkeypatch: pytest.MonkeyPatch,
    jsonl_settings: AppSettings,
    records: tuple[AgentRun, ...],
) -> None:
    authorized_projects = _allow_authorization(monkeypatch)
    recorder = create_trace_recorder(jsonl_settings)
    for record in records:
        recorder.record(record)

    trace_id = records[0].trace_id
    status, body = _asgi_request(
        "GET",
        f"/api/v1/traces/{trace_id}",
        headers={"Authorization": "Bearer user-token"},
    )

    assert status == 404
    assert body == {"error": {"code": "TRACE_NOT_FOUND", "message": "Trace was not found."}}
    assert authorized_projects == []


def test_jsonl_trace_detail_keeps_java_authorization_boundary(
    monkeypatch: pytest.MonkeyPatch,
    jsonl_settings: AppSettings,
) -> None:
    _persist(
        jsonl_settings,
        _records(
            trace_id="trace:denied",
            agent_run_id="agent_run:denied",
            project_id=41,
        ),
    )

    async def deny(*, project_id: int, authorization: str | None, settings: AppSettings) -> None:
        del project_id, authorization, settings
        raise ApplicationError(
            "JAVA_AUTHORIZATION_DENIED",
            "Java denied access to the requested project resource.",
            403,
        )

    monkeypatch.setattr(api_routes, "_authorize_runtime_project", deny)
    status, body = _asgi_request(
        "GET",
        "/api/v1/traces/trace:denied",
        headers={"Authorization": "Bearer user-token"},
    )

    assert status == 403
    assert body == {
        "error": {
            "code": "JAVA_AUTHORIZATION_DENIED",
            "message": "Java denied access to the requested project resource.",
        }
    }


def test_trace_detail_requires_bearer_before_persisted_lookup(
    monkeypatch: pytest.MonkeyPatch,
    jsonl_settings: AppSettings,
) -> None:
    queried = False

    def query(*args: object, **kwargs: object) -> tuple[TraceRecord, ...]:
        del args, kwargs
        nonlocal queried
        queried = True
        return ()

    monkeypatch.setattr(api_routes, "query_persisted_trace_records", query)
    status, body = _asgi_request("GET", "/api/v1/traces/trace:missing")

    assert status == 401
    assert body["error"]["code"] == "JAVA_AUTHENTICATION_REQUIRED"
    assert queried is False


def test_malformed_jsonl_maps_to_stable_503_without_storage_details(
    monkeypatch: pytest.MonkeyPatch,
    jsonl_settings: AppSettings,
) -> None:
    _allow_authorization(monkeypatch)
    _persist(
        jsonl_settings,
        _records(
            trace_id="trace:malformed",
            agent_run_id="agent_run:malformed",
            project_id=41,
        ),
    )
    with Path(jsonl_settings.trace_jsonl_path).open("a", encoding="utf-8") as stream:
        stream.write("{malformed secret-looking line\n")

    status, body = _asgi_request(
        "GET",
        "/api/v1/traces?projectId=41",
        headers={"Authorization": "Bearer user-token"},
    )

    assert status == 503
    assert body == {
        "error": {
            "code": "TRACE_HISTORY_UNAVAILABLE",
            "message": "Trace history is unavailable.",
        }
    }
    assert "malformed" not in str(body)
    assert "secret-looking" not in str(body)


def test_persisted_oserror_maps_to_stable_503(
    monkeypatch: pytest.MonkeyPatch,
    jsonl_settings: AppSettings,
) -> None:
    _allow_authorization(monkeypatch)

    def fail(*args: object, **kwargs: object) -> tuple[TraceRecord, ...]:
        del args, kwargs
        raise OSError("D:/private/trace-history.jsonl")

    monkeypatch.setattr(api_routes, "query_persisted_trace_records", fail)
    status, body = _asgi_request(
        "GET",
        "/api/v1/traces?projectId=41",
        headers={"Authorization": "Bearer user-token"},
    )

    assert status == 503
    assert body == {
        "error": {
            "code": "TRACE_HISTORY_UNAVAILABLE",
            "message": "Trace history is unavailable.",
        }
    }
