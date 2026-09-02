"""Stage 18 section 4 intent-bound HITL tests."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.guardrails import PreflightOutcome, ToolPreflightGuard
from app.schemas.tool_call import ToolCall
from app.schemas.tool_result import ToolResult
from app.tools import (
    FakeToolGatewayAdapter,
    ToolCatalog,
    ToolIntent,
    ToolRiskClassifier,
    ToolRouter,
)
from app.workflows.approval import (
    ApprovalAction,
    ApprovalDecision,
    ApprovalRequest,
    fingerprint_arguments,
)
from app.workflows.runtime_control import checkpoint_config
from app.workflows.tool_use_graph import build_tool_use_graph
from app.workflows.tool_use_state import ToolFailureCode, ToolUseState, ToolUseStatus


class CountingGuard(ToolPreflightGuard):
    def __init__(self) -> None:
        super().__init__(ToolRiskClassifier(ToolCatalog(), trusted_project_id="41"))
        self.calls = 0

    def evaluate(self, intent: ToolIntent, tool_call: ToolCall) -> PreflightOutcome:
        self.calls += 1
        return super().evaluate(intent, tool_call)


class CountingRouter(ToolRouter):
    def __init__(self, adapters: dict[str, FakeToolGatewayAdapter]) -> None:
        super().__init__(ToolCatalog(), adapters)
        self.validations = 0

    def validate(self, intent: ToolIntent, tool_call: ToolCall):
        self.validations += 1
        return super().validate(intent, tool_call)


def tool_call(params: dict[str, object]) -> ToolCall:
    return ToolCall.model_validate(
        {
            "schemaVersion": "0.2.0",
            "agentRunId": "run-1",
            "projectId": "41",
            "toolName": "redis.read",
            "params": params,
            "traceId": "trace-1",
        }
    )


def tool_result(status: str = "SUCCESS") -> ToolResult:
    return ToolResult.model_validate(
        {
            "schemaVersion": "0.1.0",
            "toolCallId": "java-call-1",
            "status": status,
            "data": {"value": "ready"},
            "error": None if status == "SUCCESS" else {"code": status},
            "sanitized": True,
            "traceId": "trace-1",
        }
    )


def state(
    workflow_id: str,
    *,
    intent_id: str = "intent-1",
    params: dict[str, object] | None = None,
) -> ToolUseState:
    arguments = {"key": "task:41"} if params is None else params
    return {
        "workflow_id": workflow_id,
        "project_id": "41",
        "intent_id": intent_id,
        "intent": ToolIntent(tool_name="redis.read", arguments=arguments),
        "tool_call": tool_call(arguments),
        "tool_result": None,
        "status": ToolUseStatus.PENDING,
        "failure": None,
        "tool_calls_used": 0,
        "result_sanitized": None,
        "result_truncated": None,
    }


def decision(
    request: ApprovalRequest,
    action: ApprovalAction,
    *,
    edited_arguments: dict[str, object] | None = None,
    **binding_changes: str,
) -> ApprovalDecision:
    payload = request.model_dump()
    payload.update(binding_changes)
    return ApprovalDecision.model_validate(
        payload
        | {
            "decision": action,
            "edited_arguments": edited_arguments,
        }
    )


def hitl_graph(
    response: ToolResult,
    *,
    alternate: FakeToolGatewayAdapter | None = None,
    max_approval_rounds: int = 2,
):
    selected = FakeToolGatewayAdapter(response)
    adapters = {"redis.read": selected}
    if alternate is not None:
        adapters["rag.search"] = alternate
    router = CountingRouter(adapters)
    guard = CountingGuard()
    saver = InMemorySaver()
    graph = build_tool_use_graph(
        router,
        max_approval_rounds=max_approval_rounds,
        preflight_guard=guard,
        checkpointer=saver,
    )
    return graph, selected, router, guard, saver


def interrupted_request(result: dict[str, object]) -> ApprovalRequest:
    interrupts = result["__interrupt__"]
    return ApprovalRequest.model_validate(interrupts[0].value)  # type: ignore[index,union-attr]


def test_arguments_fingerprint_is_canonical_and_content_bound() -> None:
    first = {"query": "timeout", "filters": {"b": 2, "a": 1}}
    reordered = {"filters": {"a": 1, "b": 2}, "query": "timeout"}
    changed = {"query": "timeout", "filters": {"a": 1, "b": 3}}

    assert fingerprint_arguments(first) == fingerprint_arguments(reordered)
    assert fingerprint_arguments(first) != fingerprint_arguments(changed)


@pytest.mark.anyio
async def test_require_approval_interrupts_and_checkpoints_before_gateway() -> None:
    graph, gateway, _, guard, saver = hitl_graph(tool_result())
    config = checkpoint_config("workflow-interrupt")

    result = await graph.ainvoke(state("workflow-interrupt"), config=config)
    request = interrupted_request(result)
    snapshot = graph.get_state(config)

    assert request.workflow_id == "workflow-interrupt"
    assert request.project_id == "41"
    assert request.intent_id == "intent-1"
    assert request.tool_name == "redis.read"
    assert request.arguments_fingerprint == fingerprint_arguments({"key": "task:41"})
    assert result["status"] is ToolUseStatus.AWAITING_APPROVAL
    assert snapshot.next == ("request_approval",)
    assert list(saver.list(config))
    assert guard.calls == 1
    assert gateway.calls == []


@pytest.mark.anyio
async def test_project_scope_change_before_resume_invalidates_approval() -> None:
    graph, gateway, _, _, _ = hitl_graph(tool_result())
    config = checkpoint_config("workflow-project-change")
    paused = await graph.ainvoke(state("workflow-project-change"), config=config)
    request = interrupted_request(paused)
    graph.update_state(config, {"project_id": "42"})

    result = await graph.ainvoke(
        Command(resume=decision(request, ApprovalAction.APPROVE).model_dump(mode="json")),
        config=config,
    )

    assert result["failure"].code is ToolFailureCode.STALE_APPROVAL
    assert gateway.calls == []


@pytest.mark.anyio
async def test_approval_decision_project_mismatch_is_stale() -> None:
    graph, gateway, _, _, _ = hitl_graph(tool_result())
    config = checkpoint_config("workflow-project-response")
    paused = await graph.ainvoke(state("workflow-project-response"), config=config)
    request = interrupted_request(paused)

    result = await graph.ainvoke(
        Command(
            resume=decision(
                request,
                ApprovalAction.APPROVE,
                project_id="42",
            ).model_dump(mode="json")
        ),
        config=config,
    )

    assert result["failure"].code is ToolFailureCode.STALE_APPROVAL
    assert gateway.calls == []


@pytest.mark.anyio
async def test_approve_resumes_same_thread_revalidates_and_java_deny_wins() -> None:
    graph, gateway, router, guard, _ = hitl_graph(tool_result("FORBIDDEN"))
    config = checkpoint_config("workflow-approve-deny")
    paused = await graph.ainvoke(state("workflow-approve-deny"), config=config)
    request = interrupted_request(paused)

    result = await graph.ainvoke(
        Command(resume=decision(request, ApprovalAction.APPROVE).model_dump(mode="json")),
        config=config,
    )

    assert result["approval_consumed"] is True
    assert result["failure"].code is ToolFailureCode.JAVA_AUTHORIZATION_DENIED
    assert result["tool_result"].status == "FORBIDDEN"
    assert guard.calls == 2
    assert router.validations == 3
    assert len(gateway.calls) == 1


@pytest.mark.anyio
async def test_resume_continues_at_interrupt_node_not_graph_start() -> None:
    graph, gateway, _, guard, _ = hitl_graph(tool_result())
    config = checkpoint_config("workflow-resume-position")
    paused = await graph.ainvoke(state("workflow-resume-position"), config=config)
    request = interrupted_request(paused)

    result = await graph.ainvoke(
        Command(resume=decision(request, ApprovalAction.APPROVE).model_dump(mode="json")),
        config=config,
    )

    assert result["status"] is ToolUseStatus.CONTINUE
    assert guard.calls == 2
    assert len(gateway.calls) == 1


@pytest.mark.anyio
async def test_edit_creates_new_intent_and_interrupts_again() -> None:
    graph, gateway, _, guard, _ = hitl_graph(tool_result())
    config = checkpoint_config("workflow-edit")
    paused = await graph.ainvoke(state("workflow-edit"), config=config)
    original = interrupted_request(paused)
    assert paused["approval_round"] == 1
    assert paused["max_approval_rounds"] == 2

    edited = await graph.ainvoke(
        Command(
            resume=decision(
                original,
                ApprovalAction.EDIT,
                edited_arguments={"key": "task:42"},
            ).model_dump(mode="json")
        ),
        config=config,
    )
    replacement = interrupted_request(edited)

    assert replacement.intent_id != original.intent_id
    assert replacement.arguments_fingerprint != original.arguments_fingerprint
    assert replacement.arguments_fingerprint == fingerprint_arguments({"key": "task:42"})
    assert edited["approval_round"] == 2
    assert edited["max_approval_rounds"] == 2
    assert edited["intent"].arguments == {"key": "task:42"}
    assert edited["tool_call"].params == {"key": "task:42"}
    assert guard.calls == 2
    assert gateway.calls == []


@pytest.mark.anyio
async def test_continuous_edit_stops_at_max_approval_rounds() -> None:
    graph, gateway, _, _, _ = hitl_graph(tool_result(), max_approval_rounds=2)
    config = checkpoint_config("workflow-round-limit")
    first_pause = await graph.ainvoke(state("workflow-round-limit"), config=config)
    first_request = interrupted_request(first_pause)
    second_pause = await graph.ainvoke(
        Command(
            resume=decision(
                first_request,
                ApprovalAction.EDIT,
                edited_arguments={"key": "task:42"},
            ).model_dump(mode="json")
        ),
        config=config,
    )
    second_request = interrupted_request(second_pause)

    exhausted = await graph.ainvoke(
        Command(
            resume=decision(
                second_request,
                ApprovalAction.EDIT,
                edited_arguments={"key": "task:43"},
            ).model_dump(mode="json")
        ),
        config=config,
    )

    assert "__interrupt__" not in exhausted
    assert exhausted["status"] is ToolUseStatus.FAILED
    assert exhausted["failure"].code is ToolFailureCode.APPROVAL_ROUND_LIMIT_EXCEEDED
    assert exhausted["approval_round"] == 2
    assert exhausted["max_approval_rounds"] == 2
    assert graph.get_state(config).next == ()
    assert gateway.calls == []


@pytest.mark.anyio
async def test_edited_intent_requires_new_approval_before_execution() -> None:
    graph, gateway, _, _, _ = hitl_graph(tool_result())
    config = checkpoint_config("workflow-edit-approve")
    first_pause = await graph.ainvoke(state("workflow-edit-approve"), config=config)
    original = interrupted_request(first_pause)
    second_pause = await graph.ainvoke(
        Command(
            resume=decision(
                original,
                ApprovalAction.EDIT,
                edited_arguments={"key": "task:42"},
            ).model_dump(mode="json")
        ),
        config=config,
    )
    replacement = interrupted_request(second_pause)

    result = await graph.ainvoke(
        Command(resume=decision(replacement, ApprovalAction.APPROVE).model_dump(mode="json")),
        config=config,
    )

    assert result["status"] is ToolUseStatus.CONTINUE
    assert result["intent_id"] == replacement.intent_id
    assert result["untrusted_evidence"][0].trusted_instruction is False
    assert result["untrusted_evidence"][0].text == "ready"
    assert len(gateway.calls) == 1
    assert gateway.calls[0].params == {"key": "task:42"}


@pytest.mark.anyio
async def test_old_approval_cannot_approve_edited_arguments() -> None:
    graph, gateway, _, _, _ = hitl_graph(tool_result())
    config = checkpoint_config("workflow-edit-stale")
    first_pause = await graph.ainvoke(state("workflow-edit-stale"), config=config)
    original = interrupted_request(first_pause)
    second_pause = await graph.ainvoke(
        Command(
            resume=decision(
                original,
                ApprovalAction.EDIT,
                edited_arguments={"key": "task:42"},
            ).model_dump(mode="json")
        ),
        config=config,
    )
    _ = interrupted_request(second_pause)

    result = await graph.ainvoke(
        Command(resume=decision(original, ApprovalAction.APPROVE).model_dump(mode="json")),
        config=config,
    )

    assert result["failure"].code is ToolFailureCode.STALE_APPROVAL
    assert gateway.calls == []


@pytest.mark.anyio
async def test_reject_is_terminal_and_never_falls_back() -> None:
    fallback = FakeToolGatewayAdapter(tool_result())
    graph, gateway, _, _, _ = hitl_graph(tool_result(), alternate=fallback)
    config = checkpoint_config("workflow-reject")
    paused = await graph.ainvoke(state("workflow-reject"), config=config)
    request = interrupted_request(paused)

    result = await graph.ainvoke(
        Command(resume=decision(request, ApprovalAction.REJECT).model_dump(mode="json")),
        config=config,
    )

    assert result["status"] is ToolUseStatus.REJECTED
    assert result["failure"].code is ToolFailureCode.HUMAN_REJECTED
    assert result["approval_consumed"] is True
    assert gateway.calls == []
    assert fallback.calls == []


@pytest.mark.parametrize(
    ("binding_changes"),
    [
        {"workflow_id": "another-workflow"},
        {"intent_id": "another-intent"},
        {"tool_name": "rag.search"},
        {"arguments_fingerprint": "0" * 64},
    ],
)
@pytest.mark.anyio
async def test_stale_or_cross_workflow_binding_cannot_execute(
    binding_changes: dict[str, str],
) -> None:
    graph, gateway, _, _, _ = hitl_graph(tool_result())
    config = checkpoint_config("workflow-stale")
    paused = await graph.ainvoke(state("workflow-stale"), config=config)
    request = interrupted_request(paused)

    result = await graph.ainvoke(
        Command(
            resume=decision(
                request,
                ApprovalAction.APPROVE,
                **binding_changes,
            ).model_dump(mode="json")
        ),
        config=config,
    )

    assert result["failure"].code is ToolFailureCode.STALE_APPROVAL
    assert gateway.calls == []


@pytest.mark.parametrize("changed_identity", ["workflow", "intent", "tool", "arguments"])
@pytest.mark.anyio
async def test_checkpoint_state_change_invalidates_old_approval(
    changed_identity: str,
) -> None:
    graph, gateway, _, _, _ = hitl_graph(tool_result())
    config = checkpoint_config("workflow-state-change")
    paused = await graph.ainvoke(state("workflow-state-change"), config=config)
    request = interrupted_request(paused)
    if changed_identity == "workflow":
        update: dict[str, object] = {"workflow_id": "another-workflow"}
    elif changed_identity == "intent":
        update = {"intent_id": "another-intent"}
    elif changed_identity == "tool":
        arguments = {"query": "timeout", "topK": 2}
        update = {
            "intent": ToolIntent(tool_name="rag.search", arguments=arguments),
            "tool_call": tool_call({"key": "task:41"}).model_copy(
                update={"tool_name": "rag.search", "params": arguments}
            ),
        }
    else:
        arguments = {"key": "task:42"}
        update = {
            "intent": ToolIntent(tool_name="redis.read", arguments=arguments),
            "tool_call": tool_call(arguments),
        }
    graph.update_state(config, update)

    result = await graph.ainvoke(
        Command(resume=decision(request, ApprovalAction.APPROVE).model_dump(mode="json")),
        config=config,
    )

    assert result["failure"].code is ToolFailureCode.STALE_APPROVAL
    assert gateway.calls == []


@pytest.mark.anyio
async def test_consumed_approval_replay_does_not_execute_twice() -> None:
    graph, gateway, _, _, _ = hitl_graph(tool_result())
    config = checkpoint_config("workflow-one-shot")
    paused = await graph.ainvoke(state("workflow-one-shot"), config=config)
    request = interrupted_request(paused)
    approval = decision(request, ApprovalAction.APPROVE).model_dump(mode="json")

    first = await graph.ainvoke(Command(resume=approval), config=config)
    replay = await graph.ainvoke(Command(resume=approval), config=config)

    assert first["status"] is ToolUseStatus.CONTINUE
    assert replay["status"] is ToolUseStatus.CONTINUE
    assert replay["approval_consumed"] is True
    assert len(gateway.calls) == 1
