"""SQLite checkpoint reopen/resume evidence for the bounded HITL graph."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.guardrails import ToolPreflightGuard
from app.schemas.tool_call import ToolCall
from app.schemas.tool_result import ToolResult
from app.tools import (
    FakeToolGatewayAdapter,
    ToolCatalog,
    ToolIntent,
    ToolRiskClassifier,
    ToolRouter,
)
from app.workflows.approval import ApprovalAction, ApprovalDecision, ApprovalRequest
from app.workflows.runtime_control import checkpoint_config
from app.workflows.tool_use_graph import build_tool_use_graph
from app.workflows.tool_use_state import ToolUseState, ToolUseStatus


def _tool_call(arguments: dict[str, object]) -> ToolCall:
    return ToolCall.model_validate(
        {
            "schemaVersion": "0.2.0",
            "agentRunId": "run-sqlite",
            "projectId": "41",
            "toolName": "redis.read",
            "params": arguments,
            "traceId": "trace-sqlite",
        }
    )


def _tool_result() -> ToolResult:
    return ToolResult.model_validate(
        {
            "schemaVersion": "0.1.0",
            "toolCallId": "java-call-sqlite",
            "status": "SUCCESS",
            "data": {"value": "ready"},
            "error": None,
            "sanitized": True,
            "traceId": "trace-sqlite",
        }
    )


def _state(workflow_id: str) -> ToolUseState:
    arguments = {"key": "task:41"}
    return {
        "workflow_id": workflow_id,
        "project_id": "41",
        "intent_id": "intent-sqlite",
        "intent": ToolIntent(tool_name="redis.read", arguments=arguments),
        "tool_call": _tool_call(arguments),
        "tool_result": None,
        "status": ToolUseStatus.PENDING,
        "failure": None,
        "tool_calls_used": 0,
        "result_sanitized": None,
        "result_truncated": None,
    }


def _graph(
    gateway: FakeToolGatewayAdapter,
    checkpointer: BaseCheckpointSaver,
):
    catalog = ToolCatalog()
    router = ToolRouter(catalog, {"redis.read": gateway})
    guard = ToolPreflightGuard(ToolRiskClassifier(catalog, trusted_project_id="41"))
    return build_tool_use_graph(
        router,
        preflight_guard=guard,
        checkpointer=checkpointer,
    )


def _request(result: dict[str, object]) -> ApprovalRequest:
    return ApprovalRequest.model_validate(result["__interrupt__"][0].value)  # type: ignore[index]


def _decision(request: ApprovalRequest, action: ApprovalAction) -> dict[str, object]:
    return ApprovalDecision.model_validate(
        request.model_dump() | {"decision": action, "edited_arguments": None}
    ).model_dump(mode="json")


@pytest.mark.anyio
async def test_sqlite_checkpoint_reopens_and_approves_exact_interrupt(tmp_path: Path) -> None:
    runtime_db = tmp_path / "agentlab-runtime.sqlite3"
    workflow_id = "workflow-sqlite-approve"
    config = checkpoint_config(workflow_id)
    gateway_a = FakeToolGatewayAdapter(_tool_result())

    async with AsyncSqliteSaver.from_conn_string(str(runtime_db)) as saver_a:
        graph_a = _graph(gateway_a, saver_a)
        paused = await graph_a.ainvoke(_state(workflow_id), config=config)
        request = _request(paused)
        assert paused["status"] is ToolUseStatus.AWAITING_APPROVAL
        assert request.workflow_id == workflow_id
        assert gateway_a.calls == []

    gateway_b = FakeToolGatewayAdapter(_tool_result())
    async with AsyncSqliteSaver.from_conn_string(str(runtime_db)) as saver_b:
        graph_b = _graph(gateway_b, saver_b)
        resumed = await graph_b.ainvoke(
            Command(resume=_decision(request, ApprovalAction.APPROVE)),
            config=config,
        )

    assert resumed["status"] is ToolUseStatus.CONTINUE
    assert resumed["approval_consumed"] is True
    assert len(gateway_b.calls) == 1


@pytest.mark.anyio
async def test_sqlite_checkpoint_reopens_and_rejects_without_gateway_call(
    tmp_path: Path,
) -> None:
    runtime_db = tmp_path / "agentlab-runtime.sqlite3"
    workflow_id = "workflow-sqlite-reject"
    config = checkpoint_config(workflow_id)
    gateway_a = FakeToolGatewayAdapter(_tool_result())

    async with AsyncSqliteSaver.from_conn_string(str(runtime_db)) as saver_a:
        graph_a = _graph(gateway_a, saver_a)
        paused = await graph_a.ainvoke(_state(workflow_id), config=config)
        request = _request(paused)

    gateway_b = FakeToolGatewayAdapter(_tool_result())
    async with AsyncSqliteSaver.from_conn_string(str(runtime_db)) as saver_b:
        graph_b = _graph(gateway_b, saver_b)
        rejected = await graph_b.ainvoke(
            Command(resume=_decision(request, ApprovalAction.REJECT)),
            config=config,
        )

    assert rejected["status"] is ToolUseStatus.REJECTED
    assert rejected["failure"].code.value == "HUMAN_REJECTED"
    assert gateway_b.calls == []
