"""Fake-Gateway E2E tests for the bounded Stage 18 Tool-use workflow."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.clients import JavaApiOpsClient, JavaApiOpsToolGatewayAdapter
from app.core.settings import AppSettings
from app.schemas.tool_call import ToolCall
from app.schemas.tool_result import ToolResult
from app.tools import (
    FakeToolGatewayAdapter,
    ToolCatalog,
    ToolGatewayTimeoutError,
    ToolGatewayTransportError,
    ToolIntent,
    ToolRouter,
)
from app.tracing import InMemoryTraceSink, TraceRecorder
from app.workflows.tool_use_graph import build_tool_use_graph
from app.workflows.tool_use_state import ToolFailureCode, ToolUseState, ToolUseStatus

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
JAVA_CONTRACT_FIXTURES = (
    REPOSITORY_ROOT
    / "java-apiops-platform"
    / "apiops-web"
    / "src"
    / "test"
    / "resources"
    / "contracts"
)


def tool_call() -> ToolCall:
    return ToolCall.model_validate(
        {
            "schemaVersion": "0.2.0",
            "agentRunId": "run-1",
            "projectId": "41",
            "toolName": "rag.search",
            "params": {"query": "order timeout", "topK": 2},
            "traceId": "trace-1",
        }
    )


def tool_result(
    status: str = "SUCCESS",
    *,
    tool_call_id: str = "fake-java-call-1",
    data: object = None,
    sanitized: bool = True,
) -> ToolResult:
    return ToolResult.model_validate(
        {
            "schemaVersion": "0.1.0",
            "toolCallId": tool_call_id,
            "status": status,
            "data": {"rows": []} if data is None else data,
            "error": None if status == "SUCCESS" else {"code": status},
            "sanitized": sanitized,
            "traceId": "trace-1",
        }
    )


def state(*, calls_used: int = 0) -> ToolUseState:
    return {
        "intent": ToolIntent(
            tool_name="rag.search",
            arguments={"query": "order timeout", "topK": 2},
        ),
        "tool_call": tool_call(),
        "tool_result": None,
        "status": ToolUseStatus.PENDING,
        "failure": None,
        "tool_calls_used": calls_used,
        "result_sanitized": None,
        "result_truncated": None,
    }


def router(
    selected: object,
    *,
    alternate: FakeToolGatewayAdapter | None = None,
) -> tuple[ToolRouter, FakeToolGatewayAdapter]:
    adapter = FakeToolGatewayAdapter(selected)
    adapters = {"rag.search": adapter}
    if alternate is not None:
        adapters["redis.read"] = alternate
    return ToolRouter(ToolCatalog(), adapters), adapter


@pytest.mark.anyio
async def test_intent_routes_through_fake_gateway_success_and_continues() -> None:
    gateway_result = tool_result(tool_call_id="fake-java-success")
    tool_router, adapter = router(gateway_result)

    result = await build_tool_use_graph(tool_router).ainvoke(state())

    assert result["status"] is ToolUseStatus.CONTINUE
    assert result["failure"] is None
    assert result["tool_result"] == gateway_result
    assert result["tool_result"].tool_call_id == "fake-java-success"
    assert result["tool_calls_used"] == 1
    assert adapter.calls == [tool_call()]


@pytest.mark.anyio
async def test_java_denied_is_stable_failure_and_never_falls_back() -> None:
    denied = tool_result("FORBIDDEN", tool_call_id="fake-java-denied")
    alternate = FakeToolGatewayAdapter(tool_result())
    tool_router, selected = router(denied, alternate=alternate)

    result = await build_tool_use_graph(tool_router).ainvoke(state())

    assert result["status"] is ToolUseStatus.FAILED
    assert result["failure"].code is ToolFailureCode.JAVA_AUTHORIZATION_DENIED
    assert result["tool_result"] == denied
    assert result["tool_result"].tool_call_id == "fake-java-denied"
    assert "toolCallId" not in result["tool_call"].model_dump(by_alias=True)
    assert len(selected.calls) == 1
    assert alternate.calls == []


@pytest.mark.anyio
async def test_java_returned_failed_is_execution_failure() -> None:
    tool_router, adapter = router(tool_result("FAILED"))
    sink = InMemoryTraceSink()

    result = await build_tool_use_graph(
        tool_router,
        trace_recorder=TraceRecorder(sink),
    ).ainvoke(state())

    assert result["failure"].code is ToolFailureCode.JAVA_EXECUTION_FAILED
    assert result["tool_result"].status == "FAILED"
    assert len(adapter.calls) == 1
    tool_records = [record for record in sink.records if record["record_type"] == "tool_result"]
    assert tool_records[0]["tool_result_status"] == "FAILED"
    assert tool_records[0]["java_error_code"] == "FAILED"
    assert tool_records[0]["has_data"] is True


@pytest.mark.anyio
async def test_gateway_timeout_has_no_fabricated_java_tool_call_id() -> None:
    tool_router, adapter = router(ToolGatewayTimeoutError("late"))

    result = await build_tool_use_graph(tool_router).ainvoke(state())

    assert result["failure"].code is ToolFailureCode.JAVA_TIMEOUT
    assert result["tool_result"] is None
    assert result["result_sanitized"] is None
    assert len(adapter.calls) == 1


@pytest.mark.anyio
async def test_transport_failure_is_distinct_from_java_returned_failed() -> None:
    tool_router, adapter = router(ToolGatewayTransportError("offline"))

    result = await build_tool_use_graph(tool_router).ainvoke(state())

    assert result["failure"].code is ToolFailureCode.JAVA_TRANSPORT_UNAVAILABLE
    assert result["tool_result"] is None
    assert len(adapter.calls) == 1


@pytest.mark.anyio
async def test_present_but_contract_invalid_gateway_body_is_invalid_result() -> None:
    tool_router, adapter = router(
        {
            "schemaVersion": "0.1.0",
            "status": "SUCCESS",
            "data": {},
        }
    )

    result = await build_tool_use_graph(tool_router).ainvoke(state())

    assert result["failure"].code is ToolFailureCode.INVALID_GATEWAY_RESULT
    assert result["tool_result"] is None
    assert len(adapter.calls) == 1


@pytest.mark.anyio
async def test_success_preserves_sanitized_and_truncated_facts() -> None:
    gateway_result = tool_result(
        data={"items": [], "_resultTruncated": True},
        sanitized=True,
    )
    tool_router, _ = router(gateway_result)

    result = await build_tool_use_graph(tool_router).ainvoke(state())

    assert result["status"] is ToolUseStatus.CONTINUE
    assert result["tool_result"] == gateway_result
    assert result["result_sanitized"] is True
    assert result["result_truncated"] is True


@pytest.mark.anyio
async def test_max_tool_calls_terminates_before_gateway() -> None:
    tool_router, adapter = router(tool_result())

    result = await build_tool_use_graph(tool_router, max_tool_calls=1).ainvoke(state(calls_used=1))

    assert result["status"] is ToolUseStatus.LIMIT_EXCEEDED
    assert result["failure"].code is ToolFailureCode.TOOL_CALL_LIMIT_EXCEEDED
    assert result["tool_calls_used"] == 1
    assert adapter.calls == []


@pytest.mark.anyio
async def test_default_retry_limit_does_not_retry_failure() -> None:
    tool_router, adapter = router(tool_result("FAILED"))

    result = await build_tool_use_graph(tool_router).ainvoke(state())

    assert result["failure"].code is ToolFailureCode.JAVA_EXECUTION_FAILED
    assert len(adapter.calls) == 1


@pytest.mark.anyio
async def test_graph_timeout_is_a_real_upper_bound() -> None:
    class SlowAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, call: ToolCall) -> ToolResult:
            self.calls += 1
            await asyncio.sleep(1)
            return tool_result()

    slow = SlowAdapter()
    tool_router = ToolRouter(ToolCatalog(), {"rag.search": slow})

    result = await build_tool_use_graph(
        tool_router,
        settings=AppSettings(java_apiops_timeout_seconds=0.001),
    ).ainvoke(state())

    assert result["failure"].code is ToolFailureCode.JAVA_TIMEOUT
    assert result["tool_result"] is None
    assert slow.calls == 1


def test_nonzero_retry_limit_is_not_implemented_implicitly() -> None:
    tool_router, _ = router(tool_result())

    with pytest.raises(ValueError, match="retry_limit=0 only"):
        build_tool_use_graph(tool_router, retry_limit=1)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("fixture_name", "expected_status", "expected_failure"),
    (
        ("tool-result-success.json", ToolUseStatus.CONTINUE, None),
        (
            "tool-result-forbidden.json",
            ToolUseStatus.FAILED,
            ToolFailureCode.JAVA_AUTHORIZATION_DENIED,
        ),
    ),
)
async def test_http_gateway_contract_fixture_runs_through_production_workflow(
    fixture_name: str,
    expected_status: ToolUseStatus,
    expected_failure: ToolFailureCode | None,
) -> None:
    requests: list[httpx.Request] = []
    payload = json.loads((JAVA_CONTRACT_FIXTURES / fixture_name).read_text(encoding="utf-8"))

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=2,
        )
        adapter = JavaApiOpsToolGatewayAdapter(
            client,
            project_id=41,
            token_provider=lambda: "secret-token",
        )
        graph = build_tool_use_graph(ToolRouter(ToolCatalog(), {"rag.search": adapter}))
        result = await graph.ainvoke(
            {
                **state(),
                "tool_call": tool_call().model_copy(update={"trace_id": "trace-contract-1"}),
            }
        )

    assert result["status"] is expected_status
    assert result["tool_result"].tool_call_id == payload["toolCallId"]
    assert (None if result["failure"] is None else result["failure"].code) is expected_failure
    assert len(requests) == 1
    assert "toolCallId" not in json.loads(requests[0].content)
