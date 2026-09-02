"""Stage 20.3 wiring from Java TestReport to a bounded Python diagnosis."""

from __future__ import annotations

import json
from typing import Final, Literal, NotRequired, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.diagnosis import DiagnosisInference, DiagnosisInferenceError
from app.clients.llm import LLMClient
from app.guardrails import ToolPreflightGuard, UntrustedEvidence, UntrustedEvidenceProcessor
from app.memory import HistoricalFailureMemoryEntry, MemoryRetriever
from app.rag.context import (
    ContextItem,
    ContextPack,
    ContextPackBuilder,
    ContextPolicy,
    ContextProvenance,
    ContextSource,
)
from app.rag.models import EvidenceRetrieval
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.runner import TestReport
from app.schemas.tool_call import ToolCall
from app.schemas.tool_result import ToolResult
from app.tools import (
    ToolCatalog,
    ToolIntent,
    ToolRiskClassifier,
    ToolRouter,
    map_tool_intent,
)
from app.tracing import (
    AgentStep,
    EvidenceReference,
    IdentityAuthority,
    InstrumentedLLM,
    PromptIdentity,
    RetrievalFact,
    RetrievalReference,
    ToolPlanningRecord,
    TraceEvent,
    TraceRecorder,
    TraceStatus,
    failure_detail,
    new_identity,
    observe,
    trace_parent,
    trace_step_scope,
)
from app.workflows.approval import new_intent_id
from app.workflows.diagnosis_memory_query import recall_historical_memory
from app.workflows.tool_planning import (
    ToolPlanningDecision,
    ToolPlanningError,
    ToolRequirement,
    build_tool_intent,
)
from app.workflows.tool_use_graph import build_tool_use_graph
from app.workflows.tool_use_state import ToolFailure, ToolUseStatus

MAX_TOOL_CALLS: Final = 1
TOOL_RETRY_LIMIT: Final = 0
_BUILD_CONTEXT: Final = "build_diagnosis_context"
_INITIAL_DIAGNOSIS: Final = "initial_diagnosis"
_PREPARE_TOOL: Final = "prepare_tool_use"
_TOOL_USE: Final = "tool_use"
_COMPLETE_TOOL: Final = "complete_tool_use"
_CONTINUE_DIAGNOSIS: Final = "continue_diagnosis"
_MEMORY_RECALL: Final = "memory_recall"
_MEMORY_REFINEMENT: Final = "memory_refinement"

_DEFAULT_CONTEXT_POLICY = ContextPolicy(
    source_precedence=(
        ContextSource.EXECUTION_FACT,
        ContextSource.RAG_EVIDENCE,
        ContextSource.HISTORICAL_MEMORY,
        ContextSource.API_METADATA,
        ContextSource.SHORT_TERM_CONTEXT,
        ContextSource.USER_INTENT,
    ),
    per_item_char_budget=4_096,
    total_char_budget=12_288,
)


class DiagnosisWorkflowState(TypedDict):
    """Internal parent state; Stage 18 fields retain their existing meanings."""

    report: TestReport
    trace_id: str
    agent_run_id: str
    workflow_id: str
    supporting_context: tuple[ContextItem, ...]
    base_context_items: NotRequired[tuple[ContextItem, ...]]
    context_pack: NotRequired[ContextPack]
    diagnosis_decision: NotRequired[DiagnosisReport | ToolIntent]
    diagnosis_report: NotRequired[DiagnosisReport]
    intent: NotRequired[ToolIntent]
    tool_call: NotRequired[ToolCall]
    tool_result: NotRequired[ToolResult | None]
    status: NotRequired[ToolUseStatus]
    failure: NotRequired[ToolFailure | None]
    tool_calls_used: NotRequired[int]
    result_sanitized: NotRequired[bool | None]
    result_truncated: NotRequired[bool | None]
    project_id: NotRequired[str]
    intent_id: NotRequired[str]
    untrusted_evidence: NotRequired[tuple[UntrustedEvidence, ...]]
    trace_agent_step_id: NotRequired[str]
    tool_result_mapping_status: NotRequired[
        Literal["NOT_APPLICABLE", "SKIPPED_NON_SUCCESS", "SUCCESS", "VALIDATION_FAILED"]
    ]
    tool_result_mapping_error_code: NotRequired[str | None]
    rag_evidence_count: NotRequired[int]
    memory_hit: NotRequired[bool]
    tool_planning_decision: NotRequired[ToolPlanningDecision]


def diagnosis_initial_state(
    report: TestReport,
    *,
    trace_id: str,
    agent_run_id: str,
    workflow_id: str,
    supporting_context: tuple[ContextItem, ...] = (),
) -> DiagnosisWorkflowState:
    """Create the explicit start state without generating any Java-owned identity."""

    if not isinstance(report, TestReport):
        raise TypeError("report must be a TestReport")
    for value, name in (
        (trace_id, "trace_id"),
        (agent_run_id, "agent_run_id"),
        (workflow_id, "workflow_id"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    if any(not isinstance(item, ContextItem) for item in supporting_context):
        raise TypeError("supporting_context must contain only ContextItem values")
    return {
        "report": report,
        "trace_id": trace_id,
        "agent_run_id": agent_run_id,
        "workflow_id": workflow_id,
        "supporting_context": supporting_context,
    }


def test_report_context_item(report: TestReport) -> ContextItem:
    """Select diagnosis-relevant Java execution facts without copying the full report."""

    if not isinstance(report, TestReport):
        raise TypeError("report must be a TestReport")
    relevant_cases: list[dict[str, object]] = []
    for case in report.cases:
        if case.status == "SUCCESS" and case.failure_type == "NONE":
            continue
        relevant_steps: list[dict[str, object]] = []
        for step in case.steps:
            failed_assertions = [
                assertion.model_dump(mode="json")
                for assertion in step.assertion_results
                if not assertion.passed
            ]
            if step.status == "SUCCESS" and step.failure_type == "NONE" and not failed_assertions:
                continue
            relevant_steps.append(
                {
                    "stepId": step.step_id,
                    "status": step.status,
                    "failureType": step.failure_type,
                    "responseStatusCode": step.response_status_code,
                    "durationMs": step.duration_ms,
                    "failedAssertions": failed_assertions,
                }
            )
        relevant_cases.append(
            {
                "caseId": case.case_id,
                "status": case.status,
                "failureType": case.failure_type,
                "relevantSteps": relevant_steps,
            }
        )

    content = {
        "projectId": report.project_id,
        "taskId": report.task_id,
        "runId": report.run_id,
        "reportId": report.report_id,
        "status": report.status,
        "summary": report.summary.model_dump(mode="json"),
        "relevantCases": relevant_cases,
    }
    return ContextItem(
        source_type=ContextSource.EXECUTION_FACT,
        source_id=report.report_id,
        project_scope=report.project_id,
        content=json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        priority=100,
        provenance=(
            ContextProvenance(
                source_type="JAVA_TEST_REPORT",
                source_id=report.report_id,
                project_id=report.project_id,
                run_id=report.run_id,
            ),
        ),
    )


def _build_insufficient_evidence_rag_query(
    report: TestReport,
    *,
    api_id: str,
) -> str:
    """Build the frozen, report-fact-only query for one evidence escalation."""

    if not isinstance(report, TestReport):
        raise TypeError("report must be a TestReport")
    if not isinstance(api_id, str) or not api_id.strip():
        raise ValueError("api_id must be a non-empty string")

    tokens: list[str] = [api_id.strip(), report.summary.failure_type]
    case_failure_types = sorted(
        {
            case.failure_type
            for case in report.cases
            if case.failure_type != "NONE"
        }
    )
    step_failure_types = sorted(
        {
            step.failure_type
            for case in report.cases
            for step in case.steps
            if step.failure_type != "NONE"
        }
    )
    response_status_codes = sorted(
        {
            step.response_status_code
            for case in report.cases
            for step in case.steps
            if step.response_status_code is not None
        }
    )
    failed_assertion_types = sorted(
        {
            assertion.type
            for case in report.cases
            for step in case.steps
            for assertion in step.assertion_results
            if not assertion.passed
        }
    )

    tokens.extend(case_failure_types)
    tokens.extend(step_failure_types)
    tokens.extend(f"http_status_{code}" for code in response_status_codes)
    tokens.extend(f"assertion_{assertion_type}" for assertion_type in failed_assertion_types)
    tokens.extend(["root", "cause", "evidence"])
    return " ".join(dict.fromkeys(tokens))


def _guarded_tool_context_item(
    result: ToolResult,
    evidence: tuple[UntrustedEvidence, ...],
    *,
    tool_name: str,
    project_id: int,
    run_id: int,
) -> ContextItem:
    content = [item.model_dump(mode="json") for item in evidence]
    return ContextItem(
        source_type=(
            ContextSource.RAG_EVIDENCE
            if tool_name == "rag.search"
            else ContextSource.SHORT_TERM_CONTEXT
        ),
        source_id=f"tool-result:{result.tool_call_id}",
        project_scope=project_id,
        content=json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        priority=50,
        provenance=(
            ContextProvenance(
                source_type="JAVA_TOOL_RESULT",
                source_id=result.tool_call_id,
                project_id=project_id,
                run_id=run_id,
            ),
        ),
    )


def _rehydrate_context_items(values: object) -> tuple[ContextItem, ...]:
    if not isinstance(values, (list, tuple)):
        raise TypeError("checkpointed context items must be a sequence")
    hydrated: list[ContextItem] = []
    for value in values:
        if isinstance(value, ContextItem):
            payload = dict(value.__dict__)
            payload["source_type"] = value.source_type.value
            payload["provenance"] = [
                reference if isinstance(reference, dict) else reference.model_dump(mode="json")
                for reference in value.provenance
            ]
            if value.citation is not None:
                payload["citation"] = (
                    value.citation
                    if isinstance(value.citation, dict)
                    else value.citation.model_dump(mode="json", by_alias=True)
                )
        else:
            payload = value
        hydrated.append(ContextItem.model_validate_json(json.dumps(payload)))
    return tuple(hydrated)


def _rehydrate_untrusted_evidence(values: object) -> tuple[UntrustedEvidence, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(
        UntrustedEvidence.model_validate_json(
            value.model_dump_json() if isinstance(value, UntrustedEvidence) else json.dumps(value)
        )
        for value in values
    )


def _insufficient_evidence_report(
    report: TestReport,
    *,
    trace_id: str,
    agent_run_id: str,
    limitation: str,
) -> DiagnosisReport:
    return DiagnosisReport.model_validate(
        {
            "schemaVersion": "0.1.0",
            "reportId": report.report_id,
            "agentRunId": agent_run_id,
            "projectId": report.project_id,
            "runId": report.run_id,
            "failureType": report.summary.failure_type,
            "summary": "Available evidence is insufficient to determine a root cause.",
            "rootCauseHypotheses": [],
            "sufficientEvidence": False,
            "limitations": [limitation],
            "recommendedChecks": ["Review additional project-authorized execution evidence."],
            "traceId": trace_id,
        }
    )


def build_diagnosis_workflow(
    llm: LLMClient,
    tool_router: ToolRouter,
    *,
    project_id: int,
    catalog: ToolCatalog | None = None,
    context_policy: ContextPolicy | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    trace_recorder: TraceRecorder | None = None,
    api_id: str | None = None,
    memory_retriever: MemoryRetriever | None = None,
    planning_decision: ToolPlanningDecision | None = None,
    required_tool_intent: ToolIntent | None = None,
    retrieval_only: bool = False,
):
    """Build initial diagnosis plus at most one existing Stage 18 tool-use subgraph."""

    if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id < 1:
        raise ValueError("project_id must be a positive integer")
    if not isinstance(tool_router, ToolRouter):
        raise TypeError("tool_router must be a ToolRouter")
    if api_id is not None and (not isinstance(api_id, str) or not api_id.strip()):
        raise ValueError("api_id must be a non-empty string when provided")
    if memory_retriever is not None and not isinstance(memory_retriever, MemoryRetriever):
        raise TypeError("memory_retriever must be a MemoryRetriever")
    if planning_decision is not None and not isinstance(planning_decision, ToolPlanningDecision):
        raise TypeError("planning_decision must be a ToolPlanningDecision")
    if required_tool_intent is not None and not isinstance(required_tool_intent, ToolIntent):
        raise TypeError("required_tool_intent must be a ToolIntent")
    if not isinstance(retrieval_only, bool):
        raise TypeError("retrieval_only must be a boolean")
    effective_catalog = catalog or ToolCatalog()
    if retrieval_only and (
        planning_decision is None
        or planning_decision.requirement is not ToolRequirement.REQUIRED
        or planning_decision.selected_tool != "rag.search"
        or required_tool_intent is None
        or required_tool_intent.tool_name != "rag.search"
    ):
        raise ValueError(
            "retrieval_only requires REQUIRED rag.search and a matching ToolIntent"
        )
    if required_tool_intent is not None and (
        planning_decision is None or planning_decision.requirement is not ToolRequirement.REQUIRED
    ):
        raise ValueError("required_tool_intent requires a REQUIRED planning decision")
    if (
        planning_decision is not None
        and planning_decision.selected_tool is not None
        and planning_decision.requirement in {ToolRequirement.REQUIRED, ToolRequirement.OPTIONAL}
        and not effective_catalog.contains(planning_decision.selected_tool)
    ):
        raise ValueError("planning decision selected tool is not in the workflow catalog")
    if (
        planning_decision is not None
        and required_tool_intent is not None
        and required_tool_intent.tool_name != planning_decision.selected_tool
    ):
        raise ValueError("required_tool_intent must match the planning decision")
    effective_checkpointer = checkpointer or InMemorySaver()
    context_builder = ContextPackBuilder(
        context_policy or _DEFAULT_CONTEXT_POLICY,
        project_scope=project_id,
    )
    inference = DiagnosisInference(InstrumentedLLM(llm) if trace_recorder else llm)
    preflight = ToolPreflightGuard(
        ToolRiskClassifier(effective_catalog, trusted_project_id=str(project_id))
    )
    tool_graph = build_tool_use_graph(
        tool_router,
        max_tool_calls=MAX_TOOL_CALLS,
        retry_limit=TOOL_RETRY_LIMIT,
        preflight_guard=preflight,
        evidence_processor=UntrustedEvidenceProcessor(),
        checkpointer=effective_checkpointer,
        trace_recorder=trace_recorder,
    )

    def record_report_reference(state: DiagnosisWorkflowState) -> None:
        report = state["report"]
        observe(
            trace_recorder,
            lambda: RetrievalFact(
                trace_id=state["trace_id"],
                agent_run_id=state["agent_run_id"],
                project_id=report.project_id,
                event=TraceEvent.FACT,
                status=TraceStatus.SUCCESS,
                retrieval_kind="JAVA_TEST_REPORT",
                reference=RetrievalReference(
                    run_id=report.run_id,
                    report_id=report.report_id,
                ),
                result_count=1,
            ),
        )

    def record_planning_decision(state: DiagnosisWorkflowState) -> None:
        decision = planning_decision
        if decision is None:
            return
        if decision.requirement is ToolRequirement.DENY:
            status = TraceStatus.DENIED
            failure = failure_detail(
                "TOOL_PLANNING_DENIED",
                decision.reason,
                code="RUNTIME_POLICY_DENY",
            )
        elif decision.requirement is ToolRequirement.UNRESOLVED:
            status = TraceStatus.FAILED
            failure = failure_detail(
                "TOOL_PLANNING_UNRESOLVED",
                decision.reason,
                code="EXECUTION_TOOL_REQUIREMENT_MISSING",
            )
        else:
            status = TraceStatus.SUCCESS
            failure = None
        observe(
            trace_recorder,
            lambda: ToolPlanningRecord(
                trace_id=state["trace_id"],
                agent_run_id=state["agent_run_id"],
                workflow_id=state["workflow_id"],
                project_id=project_id,
                event=TraceEvent.DECISION,
                status=status,
                failure=failure,
                requirement=decision.requirement,
                selected_tool=decision.selected_tool,
                reason=decision.reason,
                evidence_sufficiency=decision.evidence_sufficiency,
                authority_source=decision.authority_source,
                allowed=decision.allowed,
                capability_available=decision.capability_available,
            ),
        )

    def build_context(state: DiagnosisWorkflowState) -> dict[str, object]:
        report = state["report"]
        if report.project_id != project_id:
            raise ValueError("TestReport projectId must match the trusted workflow project")
        record_planning_decision(state)
        items = (test_report_context_item(report),) + state["supporting_context"]
        record_report_reference(state)
        update: dict[str, object] = {
            "base_context_items": items,
            "context_pack": context_builder.build(items),
        }
        if planning_decision is not None:
            update["tool_planning_decision"] = planning_decision
        return update

    async def infer(
        state: DiagnosisWorkflowState,
        *,
        continuation_reason: str | None,
        step_type: str,
        memory_refinement: bool = False,
    ) -> DiagnosisReport | ToolIntent:
        step_id = new_identity("agent_step")
        parent = trace_parent("agent_run", state["agent_run_id"], IdentityAuthority.PYTHON)
        observe(
            trace_recorder,
            lambda: AgentStep(
                trace_id=state["trace_id"],
                agent_run_id=state["agent_run_id"],
                agent_step_id=step_id,
                parent_identity=parent,
                project_id=project_id,
                event=TraceEvent.START,
                status=TraceStatus.RUNNING,
                step_type=step_type,
            ),
        )
        try:
            with trace_step_scope(
                trace_recorder,
                trace_id=state["trace_id"],
                agent_run_id=state["agent_run_id"],
                agent_step_id=step_id,
                prompt=PromptIdentity(
                    name="diagnosis_memory_refinement" if memory_refinement else "diagnosis",
                    version="v1" if memory_refinement else "1",
                ),
            ):
                if memory_refinement:
                    candidate = state.get("diagnosis_report")
                    if not isinstance(candidate, DiagnosisReport):
                        raise DiagnosisInferenceError(
                            "Historical Memory refinement requires a candidate DiagnosisReport"
                        )
                    decision = await inference.refine(
                        state["context_pack"],
                        report=state["report"],
                        candidate=candidate,
                        trace_id=state["trace_id"],
                        agent_run_id=state["agent_run_id"],
                    )
                else:
                    decision = await inference.generate(
                        state["context_pack"],
                        report=state["report"],
                        trace_id=state["trace_id"],
                        agent_run_id=state["agent_run_id"],
                        continuation_reason=continuation_reason,
                    )
        except Exception as exc:
            error_message = str(exc)
            error_type = type(exc).__name__
            observe(
                trace_recorder,
                lambda: AgentStep(
                    trace_id=state["trace_id"],
                    agent_run_id=state["agent_run_id"],
                    agent_step_id=step_id,
                    parent_identity=parent,
                    project_id=project_id,
                    event=TraceEvent.TERMINAL,
                    status=TraceStatus.FAILED,
                    failure=failure_detail(
                        "DIAGNOSIS_INFERENCE_FAILURE",
                        error_message,
                        code=error_type,
                    ),
                    step_type=step_type,
                ),
            )
            raise
        observe(
            trace_recorder,
            lambda: AgentStep(
                trace_id=state["trace_id"],
                agent_run_id=state["agent_run_id"],
                agent_step_id=step_id,
                parent_identity=parent,
                project_id=project_id,
                event=TraceEvent.TERMINAL,
                status=TraceStatus.SUCCESS,
                step_type=step_type,
            ),
        )
        return decision

    async def initial_diagnosis(state: DiagnosisWorkflowState) -> dict[str, object]:
        planned = state.get("tool_planning_decision")
        if isinstance(planned, ToolPlanningDecision):
            if planned.requirement is ToolRequirement.REQUIRED:
                intent = required_tool_intent
                if intent is None:
                    report = state["report"]
                    query_source = json.dumps(
                        {
                            "failureType": report.summary.failure_type,
                            "summary": report.summary.model_dump(mode="json"),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    try:
                        intent = build_tool_intent(
                            planned,
                            query_source=query_source,
                        )
                    except ToolPlanningError as exc:
                        raise DiagnosisInferenceError(str(exc)) from exc
                return {"diagnosis_decision": intent}
            if planned.requirement in {ToolRequirement.DENY, ToolRequirement.UNRESOLVED}:
                unresolved = _insufficient_evidence_report(
                    state["report"],
                    trace_id=state["trace_id"],
                    agent_run_id=state["agent_run_id"],
                    limitation=planned.reason,
                )
                return {
                    "diagnosis_decision": unresolved,
                    "diagnosis_report": unresolved,
                }
        decision = await infer(
            state,
            continuation_reason=None,
            step_type="diagnosis_initial",
        )
        if (
            isinstance(planned, ToolPlanningDecision)
            and planned.requirement is ToolRequirement.NOT_REQUIRED
            and isinstance(decision, ToolIntent)
        ):
            decision = _insufficient_evidence_report(
                state["report"],
                trace_id=state["trace_id"],
                agent_run_id=state["agent_run_id"],
                limitation=(
                    "Tool planning marked this task NOT_REQUIRED; the model tool "
                    "request was not executed."
                ),
            )
        if (
            planned is None
            and isinstance(decision, DiagnosisReport)
            and decision.sufficient_evidence is False
            and not decision.root_cause_hypotheses
            and api_id is not None
            and MAX_TOOL_CALLS == 1
        ):
            decision = ToolIntent(
                tool_name="rag.search",
                arguments={
                    "query": _build_insufficient_evidence_rag_query(
                        state["report"],
                        api_id=api_id,
                    ),
                    "topK": 5,
                },
            )
        update: dict[str, object] = {"diagnosis_decision": decision}
        if isinstance(decision, DiagnosisReport):
            update["diagnosis_report"] = decision
        return update

    def route_initial(state: DiagnosisWorkflowState) -> Literal["tool", "memory"]:
        planned = state.get("tool_planning_decision")
        if (
            isinstance(planned, ToolPlanningDecision)
            and planned.requirement is ToolRequirement.NOT_REQUIRED
        ):
            return "memory"
        return "tool" if isinstance(state["diagnosis_decision"], ToolIntent) else "memory"

    def prepare_tool(state: DiagnosisWorkflowState) -> dict[str, object]:
        intent = state["diagnosis_decision"]
        if not isinstance(intent, ToolIntent):
            raise TypeError("tool branch requires a ToolIntent")
        step_id = new_identity("agent_step")
        tool_call = map_tool_intent(
            intent,
            catalog=effective_catalog,
            agent_run_id=state["agent_run_id"],
            project_id=str(project_id),
            trace_id=state["trace_id"],
            agent_step_id=step_id,
        )
        return {
            "workflow_id": state["workflow_id"],
            "project_id": str(project_id),
            "intent_id": new_intent_id(),
            "intent": intent,
            "tool_call": tool_call,
            "tool_result": None,
            "status": ToolUseStatus.PENDING,
            "failure": None,
            "tool_calls_used": 0,
            "result_sanitized": None,
            "result_truncated": None,
            "trace_agent_step_id": step_id,
        }

    def record_rag_query(state: DiagnosisWorkflowState, result: ToolResult) -> None:
        if state["intent"].tool_name != "rag.search":
            state["tool_result_mapping_status"] = "NOT_APPLICABLE"
            state["tool_result_mapping_error_code"] = None
            state["rag_evidence_count"] = 0
            return
        if result.status != "SUCCESS":
            state["tool_result_mapping_status"] = "SKIPPED_NON_SUCCESS"
            state["tool_result_mapping_error_code"] = None
            state["rag_evidence_count"] = 0
            return
        mapping_error_code = "RAG_RESULT_SCHEMA_INVALID"
        try:
            retrieval = EvidenceRetrieval.model_validate(result.data)
            if any(
                item.project_id != project_id or item.citation.project_id != project_id
                for item in retrieval.evidence
            ):
                mapping_error_code = "RAG_RESULT_PROJECT_MISMATCH"
                raise ValueError("RAG evidence projectId does not match the trusted project")
        except Exception:  # noqa: BLE001 - observation must not abort guarded continuation
            state["tool_result_mapping_status"] = "VALIDATION_FAILED"
            state["tool_result_mapping_error_code"] = mapping_error_code
            state["rag_evidence_count"] = 0
            observe(
                trace_recorder,
                lambda: AgentStep(
                    trace_id=state["trace_id"],
                    agent_run_id=state["agent_run_id"],
                    agent_step_id=new_identity("agent_step"),
                    workflow_id=state["workflow_id"],
                    thread_id=state["workflow_id"],
                    project_id=project_id,
                    event=TraceEvent.TERMINAL,
                    status=TraceStatus.FAILED,
                    failure=failure_detail(
                        "TOOL_RESULT_MAPPING_FAILED",
                        "RAG ToolResult did not match the trusted EvidenceRetrieval contract.",
                        code=mapping_error_code,
                    ),
                    step_type="tool_result_mapping",
                ),
            )
            return
        references = tuple(
            EvidenceReference(
                source_type=item.citation.source_type,
                source_id=item.citation.source_id,
                project_id=item.project_id,
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                location=item.citation.location,
            )
            for item in retrieval.evidence
        )
        observe(
            trace_recorder,
            lambda: RetrievalFact(
                trace_id=state["trace_id"],
                agent_run_id=state["agent_run_id"],
                agent_step_id=state.get("trace_agent_step_id"),
                project_id=project_id,
                event=TraceEvent.FACT,
                status=TraceStatus.SUCCESS,
                retrieval_kind="JAVA_RAG_TOOL_RESULT",
                reference=RetrievalReference(
                    rag_query_id=retrieval.rag_query_id,
                    run_id=state["report"].run_id,
                    report_id=state["report"].report_id,
                    evidence_references=references,
                ),
                result_count=len(retrieval.evidence),
            ),
        )
        state["tool_result_mapping_status"] = "SUCCESS"
        state["tool_result_mapping_error_code"] = None
        state["rag_evidence_count"] = len(retrieval.evidence)

    def consume_tool_result(state: DiagnosisWorkflowState) -> dict[str, object]:
        """Consume one guarded result into trace facts and bounded context."""

        result = state.get("tool_result")
        base_items = _rehydrate_context_items(state["base_context_items"])
        effective_context_items = base_items
        context_pack = context_builder.build(base_items)
        if isinstance(result, ToolResult):
            record_rag_query(state, result)
        evidence = _rehydrate_untrusted_evidence(state.get("untrusted_evidence", ()))
        mapping_status = state.get("tool_result_mapping_status")
        evidence_valid = bool(evidence) and (
            state["intent"].tool_name != "rag.search"
            or state.get("rag_evidence_count", 0) > 0
        )
        if (
            state.get("status") is ToolUseStatus.CONTINUE
            and isinstance(result, ToolResult)
            and result.status == "SUCCESS"
            and result.sanitized is True
            and mapping_status in {"SUCCESS", "NOT_APPLICABLE"}
            and evidence_valid
        ):
            tool_item = _guarded_tool_context_item(
                result,
                evidence,
                tool_name=state["intent"].tool_name,
                project_id=project_id,
                run_id=state["report"].run_id,
            )
            effective_context_items = base_items + (tool_item,)
            context_pack = context_builder.build(effective_context_items)
        return {
            "base_context_items": effective_context_items,
            "context_pack": context_pack,
            "tool_result_mapping_status": state.get("tool_result_mapping_status"),
            "tool_result_mapping_error_code": state.get("tool_result_mapping_error_code"),
        }

    async def continue_diagnosis(state: DiagnosisWorkflowState) -> dict[str, object]:
        result = state.get("tool_result")
        failure = state.get("failure")
        consumed = consume_tool_result(state)
        effective_context_items = consumed["base_context_items"]
        context_pack = consumed["context_pack"]
        if (
            state.get("status") is ToolUseStatus.CONTINUE
            and isinstance(result, ToolResult)
            and result.status == "SUCCESS"
        ):
            reason = "One guarded Java Tool Gateway result is available; tool budget is exhausted."
        else:
            code = failure.code.value if isinstance(failure, ToolFailure) else "TOOL_UNAVAILABLE"
            reason = f"Tool evidence unavailable ({code}); tool budget is exhausted."
        next_state = dict(state)
        next_state["context_pack"] = context_pack
        decision = await infer(
            next_state,  # type: ignore[arg-type]
            continuation_reason=reason,
            step_type="diagnosis_continuation",
        )
        if isinstance(decision, ToolIntent):
            decision = _insufficient_evidence_report(
                state["report"],
                trace_id=state["trace_id"],
                agent_run_id=state["agent_run_id"],
                limitation="The model requested more evidence after the one-call tool budget.",
            )
        return {
            "base_context_items": effective_context_items,
            "context_pack": context_pack,
            "diagnosis_decision": decision,
            "diagnosis_report": decision,
            "tool_result_mapping_status": state.get("tool_result_mapping_status"),
            "tool_result_mapping_error_code": state.get("tool_result_mapping_error_code"),
        }

    def complete_tool_use(state: DiagnosisWorkflowState) -> dict[str, object]:
        """Finish retrieval-only tasks after the result was safely consumed."""

        return consume_tool_result(state)

    def route_after_tool(state: DiagnosisWorkflowState) -> Literal["complete", "continue"]:
        del state
        return "complete" if retrieval_only else "continue"

    def record_memory_retrieval(
        state: DiagnosisWorkflowState,
        memories: tuple[HistoricalFailureMemoryEntry, ...],
    ) -> None:
        for memory in memories:
            observe(
                trace_recorder,
                lambda memory=memory: RetrievalFact(
                    trace_id=state["trace_id"],
                    agent_run_id=state["agent_run_id"],
                    project_id=project_id,
                    event=TraceEvent.FACT,
                    status=TraceStatus.SUCCESS,
                    retrieval_kind="HISTORICAL_MEMORY",
                    reference=RetrievalReference(
                        memory_id=memory.memory_id,
                        run_id=state["report"].run_id,
                        report_id=state["report"].report_id,
                    ),
                    result_count=len(memories),
                ),
            )

    def memory_recall(state: DiagnosisWorkflowState) -> dict[str, object]:
        candidate = state.get("diagnosis_report")
        if not isinstance(candidate, DiagnosisReport):
            raise DiagnosisInferenceError("Historical Memory recall requires a DiagnosisReport")
        if memory_retriever is None or api_id is None:
            return {"memory_hit": False}

        current_items = _rehydrate_context_items(state["base_context_items"])
        memories = recall_historical_memory(
            project_id=project_id,
            api_id=api_id,
            report=state["report"],
            candidate=candidate,
            retriever=memory_retriever,
        )
        if not memories:
            return {"memory_hit": False}

        record_memory_retrieval(state, memories)
        memory_items = tuple(ContextItem.from_historical_memory(memory) for memory in memories)
        context_pack = context_builder.build(current_items + memory_items)
        included_memory_ids = {
            item.source_id
            for item in context_pack.items
            if item.source_type is ContextSource.HISTORICAL_MEMORY
        }
        return {
            "context_pack": context_pack,
            "memory_hit": any(memory.memory_id in included_memory_ids for memory in memories),
        }

    def route_memory(state: DiagnosisWorkflowState) -> Literal["refinement", "end"]:
        return "refinement" if state.get("memory_hit") is True else "end"

    async def memory_refinement(state: DiagnosisWorkflowState) -> dict[str, object]:
        decision = await infer(
            state,
            continuation_reason=None,
            step_type="diagnosis_memory_refinement",
            memory_refinement=True,
        )
        if isinstance(decision, ToolIntent):
            raise DiagnosisInferenceError("Historical Memory refinement returned a ToolIntent")
        return {
            "diagnosis_decision": decision,
            "diagnosis_report": decision,
        }

    builder = StateGraph(DiagnosisWorkflowState)
    builder.add_node(_BUILD_CONTEXT, build_context)
    builder.add_node(_INITIAL_DIAGNOSIS, initial_diagnosis)
    builder.add_node(_PREPARE_TOOL, prepare_tool)
    builder.add_node(_TOOL_USE, tool_graph)
    builder.add_node(_COMPLETE_TOOL, complete_tool_use)
    builder.add_node(_CONTINUE_DIAGNOSIS, continue_diagnosis)
    builder.add_node(_MEMORY_RECALL, memory_recall)
    builder.add_node(_MEMORY_REFINEMENT, memory_refinement)
    builder.add_edge(START, _BUILD_CONTEXT)
    builder.add_edge(_BUILD_CONTEXT, _INITIAL_DIAGNOSIS)
    builder.add_conditional_edges(
        _INITIAL_DIAGNOSIS,
        route_initial,
        {"tool": _PREPARE_TOOL, "memory": _MEMORY_RECALL},
    )
    builder.add_edge(_PREPARE_TOOL, _TOOL_USE)
    builder.add_conditional_edges(
        _TOOL_USE,
        route_after_tool,
        {"complete": _COMPLETE_TOOL, "continue": _CONTINUE_DIAGNOSIS},
    )
    builder.add_edge(_COMPLETE_TOOL, END)
    builder.add_edge(_CONTINUE_DIAGNOSIS, _MEMORY_RECALL)
    builder.add_conditional_edges(
        _MEMORY_RECALL,
        route_memory,
        {"refinement": _MEMORY_REFINEMENT, "end": END},
    )
    builder.add_edge(_MEMORY_REFINEMENT, END)
    return builder.compile(checkpointer=effective_checkpointer)


__all__ = [
    "DiagnosisWorkflowState",
    "MAX_TOOL_CALLS",
    "TOOL_RETRY_LIMIT",
    "build_diagnosis_workflow",
    "diagnosis_initial_state",
    "test_report_context_item",
]
