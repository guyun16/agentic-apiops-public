"""Stage 21 Tool Planning and evidence-acquisition acceptance tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.guardrails import ToolPreflightGuard
from app.rag.context import ContextItem, ContextProvenance, ContextSource
from app.schemas.runner import TestReport as RunnerTestReport
from app.schemas.tool_call import ToolCall
from app.schemas.tool_result import ToolResult
from app.tools import (
    FakeToolGatewayAdapter,
    ToolCatalog,
    ToolIntent,
    ToolRiskClassifier,
    ToolRouter,
    map_tool_intent,
)
from app.tracing import InMemoryTraceSink, TraceRecorder
from app.workflows.diagnosis_workflow import build_diagnosis_workflow, diagnosis_initial_state
from app.workflows.runtime_control import checkpoint_config
from app.workflows.tool_planning import (
    EvidenceSufficiency,
    ToolPlanningError,
    ToolRequirement,
    assess_evidence_sufficiency,
    build_tool_intent,
    decide_tool_requirement,
)
from app.workflows.tool_use_graph import build_tool_use_graph
from app.workflows.tool_use_state import ToolFailureCode


class SequenceLLM:
    def __init__(self, responses: Sequence[dict[str, object]]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("unexpected model call")
        return json.dumps(self._responses.pop(0))


def report() -> RunnerTestReport:
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
                    "caseId": "case-1",
                    "status": "ASSERTION_FAILED",
                    "failureType": "ASSERTION_MISMATCH",
                    "steps": [
                        {
                            "stepId": "step-1",
                            "status": "ASSERTION_FAILED",
                            "failureType": "ASSERTION_MISMATCH",
                            "responseStatusCode": 500,
                            "durationMs": 12,
                            "assertionResults": [],
                        }
                    ],
                }
            ],
        }
    )


def successful_http_report(response_status: int) -> RunnerTestReport:
    payload = report().model_dump(mode="json", by_alias=True)
    payload["status"] = "SUCCESS"
    payload["summary"] |= {
        "passedAssertions": 1,
        "failedAssertions": 0,
        "failureType": "NONE",
    }
    payload["cases"][0]["status"] = "SUCCESS"
    payload["cases"][0]["failureType"] = "NONE"
    payload["cases"][0]["steps"][0] |= {
        "status": "SUCCESS",
        "failureType": "NONE",
        "responseStatusCode": response_status,
    }
    return RunnerTestReport.model_validate(payload)


def tool_result(
    status: str = "SUCCESS",
    *,
    data: dict[str, object] | None = None,
    sanitized: bool = True,
) -> ToolResult:
    if data is None:
        data = {
            "ragQueryId": "rag-query-1",
            "results": [
                {
                    "projectId": 41,
                    "documentId": "doc-1",
                    "chunkId": "chunk-1",
                    "content": "The authorized runtime evidence is bounded.",
                    "relevanceScore": 0.9,
                    "citation": {
                        "sourceType": "JAVA_RAG",
                        "sourceId": "evidence-1",
                        "projectId": 41,
                        "documentId": "doc-1",
                        "chunkId": "chunk-1",
                        "score": 0.9,
                        "title": "Runtime evidence",
                        "location": "doc-1#chunk-1",
                        "excerpt": "The authorized runtime evidence is bounded.",
                    },
                }
            ],
        }
    return ToolResult.model_validate(
        {
            "schemaVersion": "0.1.0",
            "toolCallId": "java-tool-call-1",
            "status": status,
            "data": data,
            "error": None if status == "SUCCESS" else {"code": status},
            "sanitized": sanitized,
            "traceId": "trace-planning",
        }
    )


def diagnosis_payload() -> dict[str, object]:
    return {
        "schemaVersion": "0.1.0",
        "reportId": "report:701",
        "agentRunId": "agent-run-planning",
        "projectId": 41,
        "runId": 701,
        "failureType": "ASSERTION_MISMATCH",
        "summary": "The observed response failed the status assertion.",
        "rootCauseHypotheses": [
            {
                "statement": (
                    "The observed execution failure remains a provisional mechanism hypothesis."
                ),
                "confidence": "MEDIUM",
                "evidenceRefs": [{"itemId": "report:701"}],
            }
        ],
        "sufficientEvidence": False,
        "limitations": ["No root cause can be assigned from the bounded evidence."],
        "recommendedChecks": ["Collect the next authorized evidence item."],
        "traceId": "trace-planning",
    }


def initial_state() -> dict[str, object]:
    return diagnosis_initial_state(
        report(),
        trace_id="trace-planning",
        agent_run_id="agent-run-planning",
        workflow_id="workflow-planning",
    )


def graph(llm: SequenceLLM, adapter: FakeToolGatewayAdapter, **kwargs: object):
    catalog = ToolCatalog()
    return build_diagnosis_workflow(
        llm,
        ToolRouter(catalog, {"rag.search": adapter}),
        project_id=41,
        catalog=catalog,
        checkpointer=InMemorySaver(),
        **kwargs,
    )


def test_rag_and_generation_defaults_are_deterministic() -> None:
    rag = decide_tool_requirement(
        "RAG_EVIDENCE_RETRIEVAL",
        allowed_tools=("rag.search",),
        instruction="Retrieve the evidence identity.",
        project_id=41,
        query_source="runtime evidence query",
        capability_available=True,
    )
    testcase = decide_tool_requirement(
        "TESTCASE_GENERATION",
        allowed_tools=("rag.search",),
        instruction="Generate a testcase.",
    )

    assert rag.requirement is ToolRequirement.REQUIRED
    assert rag.selected_tool == "rag.search"
    assert testcase.requirement is ToolRequirement.NOT_REQUIRED
    assert testcase.selected_tool is None
    assert rag.authority_source == "TASK_TYPE_RUNTIME_CONTRACT"


def test_evidence_sufficiency_uses_structured_runtime_facts_only() -> None:
    assert assess_evidence_sufficiency(report()) is EvidenceSufficiency.UNRESOLVED
    assert (
        assess_evidence_sufficiency(
            report(), observed_facts={"missingEvidence": ["response-body"]}
        )
        is EvidenceSufficiency.INSUFFICIENT
    )
    assert (
        assess_evidence_sufficiency(
            observed_facts={
                "failureType": "CONNECT_ERROR",
                "responseSnapshotPresent": False,
                "assertionCount": 0,
                "diagnosisBoundary": "TRANSPORT_NOT_HTTP",
            }
        )
        is EvidenceSufficiency.SUFFICIENT
    )
    assert (
        assess_evidence_sufficiency(
            observed_facts={
                "failureType": "ASSERTION_MISMATCH",
                "responseSnapshotPresent": True,
                "assertionCount": 1,
            }
        )
        is EvidenceSufficiency.UNRESOLVED
    )
    assert assess_evidence_sufficiency() is EvidenceSufficiency.UNRESOLVED


def test_successful_runner_status_does_not_erase_error_http_semantics() -> None:
    assert (
        assess_evidence_sufficiency(successful_http_report(409))
        is EvidenceSufficiency.UNRESOLVED
    )
    assert (
        assess_evidence_sufficiency(successful_http_report(200))
        is EvidenceSufficiency.SUFFICIENT
    )


def test_empty_rag_context_is_not_sufficient() -> None:
    item = ContextItem(
        source_type=ContextSource.RAG_EVIDENCE,
        source_id="empty-rag",
        project_scope=41,
        content="[]",
        provenance=(
            ContextProvenance(
                source_type="JAVA_RAG",
                source_id="empty-rag",
                project_id=41,
            ),
        ),
    )

    assert assess_evidence_sufficiency(context_items=(item,)) is EvidenceSufficiency.UNRESOLVED


@pytest.mark.parametrize(
    "overrides",
    [
        {"project_id": None},
        {"query_source": ""},
        {"capability_available": False},
        {"allowed_tools": ()},
    ],
)
def test_rag_required_needs_all_runtime_readiness_authority(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "allowed_tools": ("rag.search",),
        "instruction": "Retrieve runtime evidence.",
        "project_id": 41,
        "query_source": "runtime evidence query",
        "capability_available": True,
    }
    values.update(overrides)

    decision = decide_tool_requirement("RAG_EVIDENCE_RETRIEVAL", **values)

    assert decision.requirement is ToolRequirement.UNRESOLVED
    assert decision.selected_tool == "rag.search"
    assert decision.allowed is False
    assert decision.authority_source == "RAG_RUNTIME_READINESS"


def test_do_not_retrieve_does_not_create_tool_authority() -> None:
    decision = decide_tool_requirement(
        "FAILURE_DIAGNOSIS",
        allowed_tools=("rag.search",),
        instruction="Do not retrieve anything; state the bounded limitation.",
    )

    assert decision.requirement is ToolRequirement.UNRESOLVED
    assert decision.requirement not in {ToolRequirement.REQUIRED, ToolRequirement.DENY}


def test_rag_task_cannot_silently_replace_an_explicit_non_rag_tool() -> None:
    decision = decide_tool_requirement(
        "RAG_EVIDENCE_RETRIEVAL",
        allowed_tools=("rag.search", "redis.read"),
        instruction="Retrieve runtime evidence.",
        project_id=41,
        query_source="runtime evidence query",
        capability_available=True,
        selected_tool="redis.read",
    )

    assert decision.requirement is ToolRequirement.UNRESOLVED
    assert decision.selected_tool == "redis.read"


@pytest.mark.anyio
async def test_missing_query_is_unresolved_without_entering_tool_graph() -> None:
    decision = decide_tool_requirement(
        "RAG_EVIDENCE_RETRIEVAL",
        allowed_tools=("rag.search",),
        instruction="",
        project_id=41,
        query_source="",
        capability_available=True,
    )
    llm = SequenceLLM([])
    adapter = FakeToolGatewayAdapter(tool_result())

    result = await graph(
        llm,
        adapter,
        planning_decision=decision,
    ).ainvoke(initial_state(), config=checkpoint_config("workflow-missing-query"))

    assert decision.requirement is ToolRequirement.UNRESOLVED
    assert adapter.calls == []
    assert llm.prompts == []
    assert result["diagnosis_report"].sufficient_evidence is False


@pytest.mark.anyio
async def test_required_rag_bypasses_initial_model_and_completes_after_result() -> None:
    decision = decide_tool_requirement(
        "RAG_EVIDENCE_RETRIEVAL",
        allowed_tools=("rag.search",),
        instruction="Retrieve the evidence identity from runtime context.",
        project_id=41,
        query_source="runtime failure context",
        capability_available=True,
    )
    intent = build_tool_intent(decision, query_source="runtime failure context")
    llm = SequenceLLM([])
    adapter = FakeToolGatewayAdapter(tool_result())
    sink = InMemoryTraceSink()
    result = await graph(
        llm,
        adapter,
        planning_decision=decision,
        required_tool_intent=intent,
        retrieval_only=True,
        trace_recorder=TraceRecorder(sink),
    ).ainvoke(initial_state(), config=checkpoint_config("workflow-rag-required"))

    assert adapter.calls[0].params["query"] == "runtime failure context"
    assert llm.prompts == []
    assert result["tool_result_mapping_status"] == "SUCCESS"
    assert result["context_pack"].items[-1].source_type is ContextSource.RAG_EVIDENCE
    assert any(record["record_type"] == "tool_planning" for record in sink.records)
    assert any(record["record_type"] == "retrieval" for record in sink.records)


@pytest.mark.anyio
async def test_successful_empty_rag_result_does_not_enter_context_pack() -> None:
    decision = decide_tool_requirement(
        "RAG_EVIDENCE_RETRIEVAL",
        allowed_tools=("rag.search",),
        instruction="Retrieve runtime evidence.",
        project_id=41,
        query_source="runtime evidence query",
        capability_available=True,
    )
    empty_result = tool_result(
        data={"ragQueryId": "rag-query-empty", "results": []},
    )
    adapter = FakeToolGatewayAdapter(empty_result)

    result = await graph(
        SequenceLLM([]),
        adapter,
        planning_decision=decision,
        required_tool_intent=build_tool_intent(decision, query_source="runtime evidence query"),
        retrieval_only=True,
    ).ainvoke(initial_state(), config=checkpoint_config("workflow-rag-empty"))

    assert result["tool_result_mapping_status"] == "SUCCESS"
    assert all(
        item.source_type is not ContextSource.RAG_EVIDENCE
        for item in result["context_pack"].items
    )


@pytest.mark.anyio
async def test_sufficient_diagnosis_is_not_forced_through_rag() -> None:
    decision = decide_tool_requirement(
        "FAILURE_DIAGNOSIS",
        evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
        allowed_tools=("rag.search",),
        instruction="Diagnose the failure from the execution report.",
    )
    llm = SequenceLLM([])
    adapter = FakeToolGatewayAdapter(tool_result())
    result = await graph(
        llm,
        adapter,
        planning_decision=decision,
    ).ainvoke(initial_state(), config=checkpoint_config("workflow-sufficient"))

    assert decision.requirement is ToolRequirement.UNRESOLVED
    assert adapter.calls == []
    assert llm.prompts == []
    assert result["diagnosis_report"].sufficient_evidence is False
    assert "formal execution-side Tool Requirement Contract is missing" in (
        result["diagnosis_report"].limitations[0]
    )


@pytest.mark.anyio
async def test_not_required_gate_blocks_model_tool_request() -> None:
    decision = decide_tool_requirement(
        "FAILURE_DIAGNOSIS",
        evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
        allowed_tools=("rag.search",),
        instruction="Diagnose the failure from the execution report.",
        runtime_requirement=ToolRequirement.NOT_REQUIRED,
    )
    llm = SequenceLLM(
        [{"tool_name": "rag.search", "arguments": {"query": "unneeded", "topK": 1}}]
    )
    adapter = FakeToolGatewayAdapter(tool_result())
    result = await graph(llm, adapter, planning_decision=decision).ainvoke(
        initial_state(), config=checkpoint_config("workflow-not-required-model-tool")
    )

    assert adapter.calls == []
    assert len(llm.prompts) == 1
    assert result["diagnosis_report"].sufficient_evidence is False
    assert "NOT_REQUIRED" in result["diagnosis_report"].limitations[0]


@pytest.mark.anyio
async def test_insufficient_diagnosis_with_runtime_evidence_need_enters_rag() -> None:
    decision = decide_tool_requirement(
        "FAILURE_DIAGNOSIS",
        evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT,
        allowed_tools=("rag.search",),
        instruction="Diagnose the failure with the authorized runtime evidence.",
        project_id=41,
        query_source="runtime report and missing context",
        capability_available=True,
        runtime_requirement=ToolRequirement.REQUIRED,
        selected_tool="rag.search",
    )
    intent = build_tool_intent(decision, query_source="runtime report and missing context")
    llm = SequenceLLM([diagnosis_payload()])
    adapter = FakeToolGatewayAdapter(tool_result())
    result = await graph(
        llm,
        adapter,
        planning_decision=decision,
        required_tool_intent=intent,
    ).ainvoke(initial_state(), config=checkpoint_config("workflow-insufficient"))

    assert decision.requirement is ToolRequirement.REQUIRED
    assert len(adapter.calls) == 1
    assert len(llm.prompts) == 1
    assert result["context_pack"].items[-1].source_type is ContextSource.RAG_EVIDENCE


@pytest.mark.anyio
async def test_unresolved_and_deny_are_safe_zero_call_terminations() -> None:
    unresolved = decide_tool_requirement(
        "FAILURE_DIAGNOSIS",
        evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT,
        allowed_tools=("rag.search",),
        instruction="State the evidence limitation without making a root-cause guess.",
    )
    denied = decide_tool_requirement(
        "TOOL_SAFETY",
        allowed_tools=("rag.search",),
        instruction="Reject the operation under the runtime safety policy.",
        runtime_requirement=ToolRequirement.DENY,
        selected_tool="rag.search",
    )
    assert unresolved.requirement is ToolRequirement.UNRESOLVED
    assert denied.requirement is ToolRequirement.DENY

    for decision, name in ((unresolved, "workflow-unresolved"), (denied, "workflow-deny")):
        llm = SequenceLLM([])
        adapter = FakeToolGatewayAdapter(tool_result())
        result = await graph(
            llm,
            adapter,
            planning_decision=decision,
        ).ainvoke(initial_state(), config=checkpoint_config(name))
        assert adapter.calls == []
        assert llm.prompts == []
        assert result["diagnosis_report"].sufficient_evidence is False


@pytest.mark.anyio
async def test_python_preflight_deny_stops_before_java_adapter() -> None:
    adapter = FakeToolGatewayAdapter(tool_result())
    catalog = ToolCatalog()
    intent = ToolIntent(tool_name="rag.search", arguments={"query": "cross project", "topK": 2})
    call = ToolCall.model_validate(
        {
            "schemaVersion": "0.2.0",
            "agentRunId": "agent-run-preflight",
            "projectId": "42",
            "toolName": "rag.search",
            "params": intent.arguments,
            "traceId": "trace-preflight",
        }
    )
    state = {
        "intent": intent,
        "tool_call": call,
        "tool_result": None,
        "status": "PENDING",
        "failure": None,
        "tool_calls_used": 0,
        "result_sanitized": None,
        "result_truncated": None,
    }

    result = await build_tool_use_graph(
        ToolRouter(catalog, {"rag.search": adapter}),
        preflight_guard=ToolPreflightGuard(
            ToolRiskClassifier(catalog, trusted_project_id="41")
        ),
    ).ainvoke(state)

    assert result["failure"].code is ToolFailureCode.PYTHON_PREFLIGHT_DENIED
    assert adapter.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["FORBIDDEN", "FAILED"])
async def test_non_success_tool_result_is_consumed_without_retry(status: str) -> None:
    decision = decide_tool_requirement(
        "RAG_EVIDENCE_RETRIEVAL",
        allowed_tools=("rag.search",),
        instruction="Retrieve the evidence result through the Gateway.",
        project_id=41,
        query_source="runtime query",
        capability_available=True,
    )
    llm = SequenceLLM([])
    adapter = FakeToolGatewayAdapter(tool_result(status))
    result = await graph(
        llm,
        adapter,
        planning_decision=decision,
        required_tool_intent=build_tool_intent(decision, query_source="runtime query"),
        retrieval_only=True,
    ).ainvoke(initial_state(), config=checkpoint_config(f"workflow-{status.lower()}"))

    assert len(adapter.calls) == 1
    assert llm.prompts == []
    assert result["tool_result"].status == status
    assert result["tool_result_mapping_status"] == "SKIPPED_NON_SUCCESS"


def test_tool_arguments_use_runtime_identity_and_context() -> None:
    decision = decide_tool_requirement(
        "RAG_EVIDENCE_RETRIEVAL",
        allowed_tools=("rag.search",),
        instruction="Retrieve runtime evidence.",
        project_id=41,
        query_source="runtime instruction and report facts",
        capability_available=True,
    )
    intent = build_tool_intent(
        decision,
        query_source="runtime instruction and report facts",
        target_project_id=42,
    )
    call = map_tool_intent(
        intent,
        catalog=ToolCatalog(),
        agent_run_id="agent-run-runtime",
        project_id="41",
        trace_id="trace-runtime",
    )

    assert call.project_id == "41"
    assert call.params["query"] == "runtime instruction and report facts"
    assert call.params["targetProjectId"] == 42
    with pytest.raises(ToolPlanningError):
        build_tool_intent(decision, query_source="", target_project_id=42)
    with pytest.raises(ToolPlanningError):
        build_tool_intent(decision, query_source="runtime", target_project_id=True)


@pytest.mark.anyio
async def test_rag_mapping_validation_failure_never_enters_evidence_context() -> None:
    decision = decide_tool_requirement(
        "RAG_EVIDENCE_RETRIEVAL",
        allowed_tools=("rag.search",),
        instruction="Retrieve runtime evidence.",
        project_id=41,
        query_source="runtime evidence query",
        capability_available=True,
    )
    invalid = tool_result(
        data={"ragQueryId": "rag-query-invalid", "results": [{"unexpected": "shape"}]}
    )
    sink = InMemoryTraceSink()
    result = await graph(
        SequenceLLM([]),
        FakeToolGatewayAdapter(invalid),
        planning_decision=decision,
        required_tool_intent=build_tool_intent(decision, query_source="runtime evidence query"),
        retrieval_only=True,
        trace_recorder=TraceRecorder(sink),
    ).ainvoke(initial_state(), config=checkpoint_config("workflow-mapping-invalid"))

    assert result["tool_result"].status == "SUCCESS"
    assert result["tool_result_mapping_status"] == "VALIDATION_FAILED"
    assert all(
        item.source_type is not ContextSource.RAG_EVIDENCE
        for item in result["context_pack"].items
    )
    assert any(
        record["record_type"] == "retrieval"
        and record["retrieval_kind"] == "JAVA_TEST_REPORT"
        for record in sink.records
    )
    assert not any(
        record["record_type"] == "retrieval"
        and record["retrieval_kind"] == "JAVA_RAG_TOOL_RESULT"
        for record in sink.records
    )


def test_retrieval_only_rejects_non_rag_selected_tool() -> None:
    decision = decide_tool_requirement(
        "FAILURE_DIAGNOSIS",
        allowed_tools=("redis.read",),
        instruction="Use the explicitly contracted runtime lookup.",
        project_id=41,
        capability_available=True,
        runtime_requirement=ToolRequirement.REQUIRED,
        selected_tool="redis.read",
    )
    intent = build_tool_intent(decision, arguments={"key": "runtime-key"})

    with pytest.raises(ValueError, match="retrieval_only requires REQUIRED rag.search"):
        graph(
            SequenceLLM([]),
            FakeToolGatewayAdapter(tool_result()),
            planning_decision=decision,
            required_tool_intent=intent,
            retrieval_only=True,
        )


def test_planning_source_contains_no_evaluation_side_tool_fields() -> None:
    root = Path(__file__).resolve().parents[2]
    sources = (
        (root / "app" / "workflows" / "tool_planning.py").read_text(encoding="utf-8"),
        (root / "app" / "benchmark" / "real_model.py").read_text(encoding="utf-8"),
    )
    for source in sources:
        assert "expected_tools" not in source
        assert "expected_tool_calls" not in source
        assert "expected_evidence_ids" not in source
