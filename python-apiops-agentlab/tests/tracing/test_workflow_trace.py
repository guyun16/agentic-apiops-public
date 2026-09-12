from __future__ import annotations

import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.testcase_generator import TestCaseGenerator
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
from app.tracing import (
    AgentRun,
    ApprovalFact,
    InMemoryTraceSink,
    InterruptFact,
    JsonlTraceSink,
    ModelCall,
    ResumeFact,
    ToolResultRecord,
    TraceEvent,
    TraceRecorder,
    TraceStatus,
    read_trace_jsonl,
)
from app.workflows.approval import ApprovalAction, ApprovalDecision, ApprovalRequest
from app.workflows.generation_context import (
    DocumentedResponse,
    GenerationContext,
    RequestFact,
)
from app.workflows.generation_context import TestStrategy as Strategy
from app.workflows.runtime_control import checkpoint_config
from app.workflows.state import (
    APIOpsAgentState,
    TestCaseGenerationStatus,
    WorkflowPhase,
    WorkflowRoute,
)
from app.workflows.testcase_generation_graph import build_testcase_generation_graph
from app.workflows.tool_use_graph import build_tool_use_graph
from app.workflows.tool_use_state import ToolFailureCode, ToolUseState, ToolUseStatus


def generation_context() -> GenerationContext:
    return GenerationContext(
        api_id="api-orders",
        api_doc_id="doc-orders-v1",
        operation_id="getOrder",
        method="GET",
        path="/orders/{order_id}",
        base_url="https://example.test",
        strategy=Strategy.HAPPY_PATH,
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


def candidate_json(*, project_id: int = 101, include_schema_version: bool = True) -> str:
    payload: dict[str, object] = {
        "caseId": "case-get-order",
        "projectId": project_id,
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
    }
    if include_schema_version:
        payload["schemaVersion"] = "1.0.0"
    return json.dumps(payload)


class SequenceLLM:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = responses.copy()
        self.calls = 0

    async def complete(self, prompt: str) -> str:
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class DeepSeekSequenceLLM(SequenceLLM):
    provider = "DeepSeek"
    model = "deepseek-test-model"


def generation_state() -> APIOpsAgentState:
    return {
        "trace_id": "trace-generation",
        "agent_run_id": "run-generation",
        "phase": WorkflowPhase.INITIAL,
        "route": None,
        "error": None,
        "attempt_count": 0,
        "max_attempts": 0,
        "project_id": 101,
        "api_id": "api-orders",
        "generation_intent": Strategy.HAPPY_PATH.value,
        "api_metadata": None,
        "generation_context": generation_context(),
        "context_pack": None,
        "context_status": None,
        "context_error": None,
        "candidate": None,
        "validation_result": None,
        "repair_attempts": 0,
        "max_repair_attempts": 1,
        "generation_status": None,
    }


def records(sink: InMemoryTraceSink) -> tuple[dict[str, object], ...]:
    return sink.records


@pytest.mark.anyio
async def test_generation_trace_has_success_steps_and_nested_model_call() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    graph = build_testcase_generation_graph(
        TestCaseGenerator(SequenceLLM([candidate_json()])),
        trace_recorder=recorder,
    )

    result = await graph.ainvoke(generation_state())
    stored = records(sink)
    steps = [record for record in stored if record["record_type"] == "agent_step"]
    calls = [record for record in stored if record["record_type"] == "model_call"]
    runs = [record for record in stored if record["record_type"] == "agent_run"]

    assert result["phase"] is WorkflowPhase.FINISHED
    assert result["generation_status"] is TestCaseGenerationStatus.ACCEPTED
    assert [record["step_type"] for record in steps if record["event"] == "START"] == [
        "context_enrichment",
        "generate",
        "validate",
    ]
    assert {record["status"] for record in steps if record["event"] == "TERMINAL"} == {"SUCCESS"}
    assert [record["status"] for record in runs] == ["RUNNING", "SUCCESS"]
    assert len(calls) == 2
    assert calls[0]["event"] == "START"
    assert calls[1]["event"] == "TERMINAL"
    assert calls[0]["model_call_id"] == calls[1]["model_call_id"]
    assert calls[0]["agent_step_id"] == calls[1]["agent_step_id"]
    assert calls[0]["parent_identity"]["identity"] == calls[0]["agent_step_id"]
    assert calls[1]["model_output"] is not None
    assert [record["sequence"] for record in stored] == list(range(1, len(stored) + 1))


@pytest.mark.anyio
async def test_generation_model_call_jsonl_readback_is_typed_and_bounded(tmp_path) -> None:
    path = tmp_path / "generation-trace.jsonl"
    recorder = TraceRecorder(JsonlTraceSink(path))
    graph = build_testcase_generation_graph(
        TestCaseGenerator(DeepSeekSequenceLLM([candidate_json()])),
        trace_recorder=recorder,
    )

    result = await graph.ainvoke(generation_state())
    persisted = read_trace_jsonl(path)
    calls = [record for record in persisted if isinstance(record, ModelCall)]
    start, terminal = calls

    assert result["generation_status"] is TestCaseGenerationStatus.ACCEPTED
    assert start.event is TraceEvent.START
    assert terminal.event is TraceEvent.TERMINAL
    assert terminal.status is TraceStatus.SUCCESS
    assert start.model_call_id == terminal.model_call_id
    assert start.model_identity.provider == terminal.model_identity.provider == "DeepSeek"
    assert start.model_identity.model == terminal.model_identity.model == "deepseek-test-model"
    assert start.prompt.name == "testcase_generate"
    assert start.prompt.version == "v1"
    assert start.trace_id == terminal.trace_id == "trace-generation"
    assert start.agent_run_id == terminal.agent_run_id == "run-generation"
    assert start.model_input.summary
    assert terminal.model_output is not None


@pytest.mark.anyio
async def test_failed_validation_fact_remains_before_repair_and_successful_run() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    graph = build_testcase_generation_graph(
        TestCaseGenerator(SequenceLLM([candidate_json(project_id=999), candidate_json()])),
        trace_recorder=recorder,
    )

    result = await graph.ainvoke(generation_state())
    stored = records(sink)
    validation_steps = [
        record
        for record in stored
        if record["record_type"] == "agent_step" and record["step_type"] == "validate"
    ]
    terminal_run = [
        record
        for record in stored
        if record["record_type"] == "agent_run" and record["event"] == "TERMINAL"
    ][0]

    assert result["phase"] is WorkflowPhase.FINISHED
    assert result["route"] is WorkflowRoute.READY
    assert [record["status"] for record in validation_steps] == [
        "RUNNING",
        "FAILED",
        "RUNNING",
        "SUCCESS",
    ]
    assert terminal_run["status"] == "SUCCESS"
    assert terminal_run["failure"] is None


@pytest.mark.anyio
async def test_repair_exhausted_path_is_trace_rejected() -> None:
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    graph = build_testcase_generation_graph(
        TestCaseGenerator(
            SequenceLLM(
                [
                    candidate_json(project_id=999),
                    candidate_json(include_schema_version=False),
                ]
            )
        ),
        trace_recorder=recorder,
    )

    result = await graph.ainvoke(generation_state())
    terminal_run = [
        record
        for record in records(sink)
        if record["record_type"] == "agent_run" and record["event"] == "TERMINAL"
    ][0]

    assert result["phase"] is WorkflowPhase.REJECTED
    assert result["generation_status"] is TestCaseGenerationStatus.REPAIR_EXHAUSTED
    assert terminal_run["status"] == "REJECTED"
    assert terminal_run["failure"]["failure_category"] == "REPAIR_EXHAUSTED"


@pytest.mark.anyio
async def test_recorder_failure_does_not_change_generation_route_or_terminal_result() -> None:
    class FailingSink:
        def write(self, record: dict[str, object]) -> None:
            raise RuntimeError("trace sink unavailable")

    recorder = TraceRecorder(FailingSink())
    llm = SequenceLLM([candidate_json()])
    graph = build_testcase_generation_graph(
        TestCaseGenerator(llm),
        trace_recorder=recorder,
    )

    result = await graph.ainvoke(generation_state())

    assert result["phase"] is WorkflowPhase.FINISHED
    assert result["route"] is WorkflowRoute.READY
    assert result["generation_status"] is TestCaseGenerationStatus.ACCEPTED
    assert llm.calls == 1
    assert recorder.degraded is True


def tool_call(
    *,
    name: str = "rag.search",
    project_id: str = "41",
    trace_id: str = "trace-tool",
    agent_run_id: str = "run-tool",
    params: dict[str, object] | None = None,
) -> ToolCall:
    return ToolCall.model_validate(
        {
            "schemaVersion": "0.2.0",
            "agentRunId": agent_run_id,
            "projectId": project_id,
            "toolName": name,
            "params": {"query": "orders", "topK": 2} if params is None else params,
            "traceId": trace_id,
        }
    )


def tool_result(*, tool_call_id: str = "java-authority-call") -> ToolResult:
    return ToolResult.model_validate(
        {
            "schemaVersion": "0.1.0",
            "toolCallId": tool_call_id,
            "status": "SUCCESS",
            "data": {"rows": [{"id": "order-1"}]},
            "error": None,
            "sanitized": True,
            "traceId": "trace-tool",
        }
    )


def tool_state(
    *,
    call: ToolCall,
    intent: ToolIntent,
    intent_id: str | None = "intent-tool",
    workflow_id: str | None = None,
) -> ToolUseState:
    state: ToolUseState = {
        "intent": intent,
        "tool_call": call,
        "tool_result": None,
        "status": ToolUseStatus.PENDING,
        "failure": None,
        "tool_calls_used": 0,
        "result_sanitized": None,
        "result_truncated": None,
    }
    if intent_id is not None:
        state["intent_id"] = intent_id
    if workflow_id is not None:
        state["workflow_id"] = workflow_id
        state["project_id"] = call.project_id
    return state


@pytest.mark.anyio
async def test_tool_trace_preserves_java_tool_call_id_and_nested_parent() -> None:
    gateway = FakeToolGatewayAdapter(tool_result(tool_call_id="java-authority-007"))
    intent = ToolIntent(tool_name="rag.search", arguments={"query": "orders", "topK": 2})
    state = tool_state(call=tool_call(), intent=intent)
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    graph = build_tool_use_graph(
        ToolRouter(ToolCatalog(), {"rag.search": gateway}),
        trace_recorder=recorder,
    )

    result = await graph.ainvoke(state)
    stored = records(sink)
    step = [record for record in stored if record["record_type"] == "agent_step"][0]
    tool_result_record = [record for record in stored if record["record_type"] == "tool_result"][0]

    assert result["status"] is ToolUseStatus.CONTINUE
    assert result["tool_result"].tool_call_id == "java-authority-007"
    assert result["trace_agent_step_id"] == step["agent_step_id"]
    assert tool_result_record["java_tool_call_id"] == "java-authority-007"
    assert tool_result_record["tool_intent_id"] == "intent-tool"
    assert tool_result_record["parent_identity"]["identity"] == step["agent_step_id"]
    assert all(record["agent_run_id"] == "run-tool" for record in stored)


@pytest.mark.anyio
async def test_tool_result_jsonl_readback_preserves_java_owned_identity(tmp_path) -> None:
    path = tmp_path / "tool-trace.jsonl"
    gateway = FakeToolGatewayAdapter(tool_result(tool_call_id="java-authority-jsonl-007"))
    call = tool_call()
    intent = ToolIntent(tool_name="rag.search", arguments={"query": "orders", "topK": 2})
    sink = JsonlTraceSink(path)
    recorder = TraceRecorder(sink)
    graph = build_tool_use_graph(
        ToolRouter(ToolCatalog(), {"rag.search": gateway}),
        trace_recorder=recorder,
    )

    result = await graph.ainvoke(tool_state(call=call, intent=intent))
    persisted = read_trace_jsonl(path)
    tool_record = next(record for record in persisted if isinstance(record, ToolResultRecord))

    assert result["tool_result"].tool_call_id == "java-authority-jsonl-007"
    assert tool_record.java_tool_call_id == "java-authority-jsonl-007"
    assert tool_record.tool_call_id == "java-authority-jsonl-007"
    assert "toolCallId" not in call.model_dump(by_alias=True)
    assert all(record.agent_run_id == "run-tool" for record in persisted)


def test_missing_java_tool_call_id_and_redacted_summary_survive_typed_jsonl_readback(
    tmp_path,
) -> None:
    path = tmp_path / "safe-tool-trace.jsonl"
    recorder = TraceRecorder(JsonlTraceSink(path))
    recorder.record(
        ToolResultRecord(
            trace_id="trace-safe-tool",
            agent_run_id="run-safe-tool",
            tool_name="rag.search",
            java_tool_call_id=None,
            result_summary=(
                "Authorization: Bearer test-secret-token; "
                "Cookie: session=test-cookie; "
                "apiKey=test-api-key; password=test-password"
            ),
            sanitized=True,
            truncated=False,
            status=TraceStatus.SUCCESS,
        )
    )

    raw = path.read_text(encoding="utf-8")
    persisted = read_trace_jsonl(path)
    record = persisted[0]

    assert isinstance(record, ToolResultRecord)
    assert record.java_tool_call_id is None
    assert all(secret not in raw for secret in (
        "test-secret-token",
        "test-cookie",
        "test-api-key",
        "test-password",
    ))
    typed_text = str(record.model_dump(mode="json", exclude_none=False))
    assert all(secret not in typed_text for secret in (
        "test-secret-token",
        "test-cookie",
        "test-api-key",
        "test-password",
    ))


@pytest.mark.anyio
async def test_preflight_denial_is_trace_denied_with_safety_fact() -> None:
    gateway = FakeToolGatewayAdapter(tool_result())
    intent = ToolIntent(tool_name="rag.search", arguments={"query": "orders", "topK": 2})
    state = tool_state(
        call=tool_call(project_id="99"),
        intent=intent,
        intent_id="intent-denied",
    )
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    graph = build_tool_use_graph(
        ToolRouter(ToolCatalog(), {"rag.search": gateway}),
        preflight_guard=ToolPreflightGuard(
            ToolRiskClassifier(ToolCatalog(), trusted_project_id="41")
        ),
        trace_recorder=recorder,
    )

    result = await graph.ainvoke(state)
    stored = records(sink)
    terminal_run = [
        record
        for record in stored
        if record["record_type"] == "agent_run" and record["event"] == "TERMINAL"
    ][0]

    assert result["failure"].code is ToolFailureCode.PYTHON_PREFLIGHT_DENIED
    assert terminal_run["status"] == "DENIED"
    assert any(record["record_type"] == "safety_violation" for record in stored)
    assert gateway.calls == []


@pytest.mark.anyio
async def test_hitl_interrupt_resume_keeps_run_and_approval_correlation() -> None:
    params = {"key": "task:41"}
    call = tool_call(
        name="redis.read",
        params=params,
        trace_id="trace-hitl",
        agent_run_id="run-hitl",
    )
    intent = ToolIntent(tool_name="redis.read", arguments=params)
    state = tool_state(
        call=call,
        intent=intent,
        intent_id="intent-hitl",
        workflow_id="workflow-hitl",
    )
    gateway = FakeToolGatewayAdapter(
        tool_result(tool_call_id="java-hitl-009").model_copy(update={"trace_id": "trace-hitl"})
    )
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink)
    config = checkpoint_config("workflow-hitl")
    graph = build_tool_use_graph(
        ToolRouter(ToolCatalog(), {"redis.read": gateway}),
        preflight_guard=ToolPreflightGuard(
            ToolRiskClassifier(ToolCatalog(), trusted_project_id="41")
        ),
        checkpointer=InMemorySaver(),
        trace_recorder=recorder,
    )

    paused = await graph.ainvoke(state, config=config)
    request = ApprovalRequest.model_validate(paused["__interrupt__"][0].value)
    decision = ApprovalDecision.model_validate(
        {
            **request.model_dump(),
            "decision": ApprovalAction.APPROVE,
            "edited_arguments": None,
        }
    )
    resumed = await graph.ainvoke(
        Command(resume=decision.model_dump(mode="json")),
        config=config,
    )
    stored = records(sink)
    run_records = [record for record in stored if record["record_type"] == "agent_run"]
    approval_records = [record for record in stored if record["record_type"] == "approval"]

    assert resumed["status"] is ToolUseStatus.CONTINUE
    assert len([record for record in run_records if record["event"] == "START"]) == 1
    assert [record["event"] for record in run_records] == [
        "START",
        "INTERRUPT",
        "RESUME",
        "TERMINAL",
    ]
    assert {record["agent_run_id"] for record in stored} == {"run-hitl"}
    assert [record["event"] for record in approval_records] == ["REQUEST", "DECISION"]
    assert approval_records[0]["intent_id"] == approval_records[1]["intent_id"] == "intent-hitl"
    assert (
        approval_records[0]["arguments_fingerprint"] == approval_records[1]["arguments_fingerprint"]
    )
    assert resumed["tool_result"].tool_call_id == "java-hitl-009"
    assert all("approval_id" not in record for record in stored)


@pytest.mark.anyio
async def test_hitl_jsonl_readback_persists_interrupt_resume_and_terminal_facts(tmp_path) -> None:
    params = {"key": "task:41"}
    call = tool_call(
        name="redis.read",
        params=params,
        trace_id="trace-hitl-jsonl",
        agent_run_id="run-hitl-jsonl",
    )
    intent = ToolIntent(tool_name="redis.read", arguments=params)
    state = tool_state(
        call=call,
        intent=intent,
        intent_id="intent-hitl-jsonl",
        workflow_id="workflow-hitl-jsonl",
    )
    gateway = FakeToolGatewayAdapter(
        tool_result(tool_call_id="java-hitl-jsonl-009").model_copy(
            update={"trace_id": "trace-hitl-jsonl"}
        )
    )
    path = tmp_path / "hitl-trace.jsonl"
    recorder = TraceRecorder(JsonlTraceSink(path))
    config = checkpoint_config("workflow-hitl-jsonl")
    graph = build_tool_use_graph(
        ToolRouter(ToolCatalog(), {"redis.read": gateway}),
        preflight_guard=ToolPreflightGuard(
            ToolRiskClassifier(ToolCatalog(), trusted_project_id="41")
        ),
        checkpointer=InMemorySaver(),
        trace_recorder=recorder,
    )

    paused = await graph.ainvoke(state, config=config)
    request = ApprovalRequest.model_validate(paused["__interrupt__"][0].value)
    decision = ApprovalDecision.model_validate(
        {
            **request.model_dump(),
            "decision": ApprovalAction.APPROVE,
            "edited_arguments": None,
        }
    )
    resumed = await graph.ainvoke(
        Command(resume=decision.model_dump(mode="json")),
        config=config,
    )
    persisted = read_trace_jsonl(path)
    run_records = [record for record in persisted if isinstance(record, AgentRun)]
    approval_records = [record for record in persisted if isinstance(record, ApprovalFact)]

    assert resumed["status"] is ToolUseStatus.CONTINUE
    assert [record.event for record in run_records] == [
        TraceEvent.START,
        TraceEvent.INTERRUPT,
        TraceEvent.RESUME,
        TraceEvent.TERMINAL,
    ]
    assert {record.trace_id for record in persisted} == {"trace-hitl-jsonl"}
    assert {record.agent_run_id for record in persisted} == {"run-hitl-jsonl"}
    assert [record.event for record in approval_records] == [
        TraceEvent.REQUEST,
        TraceEvent.DECISION,
    ]
    assert any(isinstance(record, InterruptFact) for record in persisted)
    assert any(isinstance(record, ResumeFact) for record in persisted)
    assert all(record.sequence == index for index, record in enumerate(persisted, start=1))
    assert all(
        "approval_id" not in record.model_dump(mode="json", exclude_none=False)
        for record in approval_records
    )


@pytest.mark.anyio
async def test_hitl_rejection_is_trace_rejected_without_gateway_call() -> None:
    params = {"key": "task:41"}
    call = tool_call(
        name="redis.read",
        params=params,
        trace_id="trace-reject",
        agent_run_id="run-reject",
    )
    intent = ToolIntent(tool_name="redis.read", arguments=params)
    state = tool_state(
        call=call,
        intent=intent,
        intent_id="intent-reject",
        workflow_id="workflow-reject",
    )
    gateway = FakeToolGatewayAdapter(tool_result(tool_call_id="java-must-not-run"))
    sink = InMemoryTraceSink()
    graph = build_tool_use_graph(
        ToolRouter(ToolCatalog(), {"redis.read": gateway}),
        preflight_guard=ToolPreflightGuard(
            ToolRiskClassifier(ToolCatalog(), trusted_project_id="41")
        ),
        checkpointer=InMemorySaver(),
        trace_recorder=TraceRecorder(sink),
    )
    config = checkpoint_config("workflow-reject")

    paused = await graph.ainvoke(state, config=config)
    request = ApprovalRequest.model_validate(paused["__interrupt__"][0].value)
    decision = ApprovalDecision.model_validate(
        {
            **request.model_dump(),
            "decision": ApprovalAction.REJECT,
            "edited_arguments": None,
        }
    )
    result = await graph.ainvoke(
        Command(resume=decision.model_dump(mode="json")),
        config=config,
    )
    stored = records(sink)
    terminal_run = [
        record
        for record in stored
        if record["record_type"] == "agent_run" and record["event"] == "TERMINAL"
    ][0]
    approval_decision = [
        record
        for record in stored
        if record["record_type"] == "approval" and record["event"] == "DECISION"
    ][0]

    assert result["failure"].code is ToolFailureCode.HUMAN_REJECTED
    assert terminal_run["status"] == "REJECTED"
    assert approval_decision["status"] == "REJECTED"
    assert gateway.calls == []


def test_trace_tests_do_not_use_real_credentials() -> None:
    payload = json.dumps(records(InMemoryTraceSink()))
    assert "Bearer " not in payload
    assert "password=" not in payload
