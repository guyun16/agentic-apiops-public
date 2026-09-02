"""Bounded Tool-use workflow with intent-bound human approval."""

from __future__ import annotations

import asyncio
from typing import Final, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from app.core.settings import AppSettings, get_settings
from app.guardrails import (
    EvidenceSource,
    PreflightDecision,
    ToolPreflightGuard,
    UntrustedEvidenceProcessor,
    ViolationCode,
)
from app.schemas.tool_result import ToolResult
from app.tools import (
    InvalidGatewayResultError,
    ToolAdapterUnavailableError,
    ToolCatalogError,
    ToolGatewayAuthenticationError,
    ToolGatewayAuthorizationError,
    ToolGatewayNotFoundError,
    ToolGatewayTimeoutError,
    ToolGatewayTransportError,
    ToolIntent,
    ToolRouter,
)
from app.tracing import (
    AgentRun,
    AgentStep,
    ApprovalFact,
    IdentityAuthority,
    InterruptFact,
    ResumeFact,
    SafetyViolationFact,
    ToolIntentRecord,
    ToolResultRecord,
    TraceEvent,
    TraceRecorder,
    TraceStatus,
    digest_payload,
    failure_detail,
    new_identity,
    observe,
    trace_parent,
)
from app.workflows.approval import (
    ApprovalAction,
    ApprovalDecision,
    ApprovalRequest,
    approval_request,
    new_intent_id,
)
from app.workflows.tool_use_state import (
    ToolFailure,
    ToolFailureCode,
    ToolUseState,
    ToolUseStatus,
)

_PREFLIGHT_NODE: Final = "preflight_tool"
_APPROVAL_NODE: Final = "request_approval"
_EXECUTE_NODE: Final = "execute_tool"
_TRACE_TERMINAL_NODE: Final = "trace_terminal"
PreflightRoute = Literal["approval", "execute", "end"]


def _tool_result_error_code(result: ToolResult) -> str | None:
    if not isinstance(result.error, dict):
        return None
    for key in ("code", "errorCode"):
        value = result.error.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _failure(
    code: ToolFailureCode,
    message: str,
    *,
    calls_used: int,
    result: ToolResult | None = None,
) -> dict[str, object]:
    if code is ToolFailureCode.TOOL_CALL_LIMIT_EXCEEDED:
        status = ToolUseStatus.LIMIT_EXCEEDED
    elif code is ToolFailureCode.HUMAN_REJECTED:
        status = ToolUseStatus.REJECTED
    else:
        status = ToolUseStatus.FAILED
    return {
        "tool_result": result,
        "status": status,
        "failure": ToolFailure(code=code, message=message),
        "tool_calls_used": calls_used,
        "result_sanitized": None if result is None else result.sanitized,
        "result_truncated": None if result is None else _is_truncated(result),
    }


def _is_truncated(result: ToolResult) -> bool:
    return isinstance(result.data, dict) and (
        result.data.get("truncated") is True or result.data.get("_resultTruncated") is True
    )


def _validate_calls_used(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("tool_calls_used must be a non-negative integer")
    return value


def _validate_approval_round(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("approval_round must be a non-negative integer")
    return value


def _workflow_identity(
    state: ToolUseState,
    config: RunnableConfig,
) -> tuple[str, str, str] | None:
    workflow_id = state.get("workflow_id")
    project_id = state.get("project_id")
    intent_id = state.get("intent_id")
    thread_id = config.get("configurable", {}).get("thread_id")
    if not isinstance(workflow_id, str) or not workflow_id:
        return None
    if not isinstance(intent_id, str) or not intent_id:
        return None
    if not isinstance(project_id, str) or not project_id:
        return None
    if thread_id != workflow_id:
        return None
    return workflow_id, project_id, intent_id


def _current_request(state: ToolUseState, config: RunnableConfig) -> ApprovalRequest | None:
    identity = _workflow_identity(state, config)
    if identity is None:
        return None
    workflow_id, project_id, intent_id = identity
    if state["tool_call"].project_id != project_id:
        return None
    return approval_request(
        workflow_id=workflow_id,
        project_id=project_id,
        intent_id=intent_id,
        intent=state["intent"],
    )


def _route_after_preflight(state: ToolUseState) -> PreflightRoute:
    if state["failure"] is not None:
        return "end"
    if state.get("preflight_decision") is PreflightDecision.REQUIRE_APPROVAL:
        return "approval"
    return "execute"


def build_tool_use_graph(
    router: ToolRouter,
    *,
    max_tool_calls: int = 1,
    max_approval_rounds: int = 2,
    settings: AppSettings | None = None,
    retry_limit: int = 0,
    preflight_guard: ToolPreflightGuard | None = None,
    evidence_processor: UntrustedEvidenceProcessor | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    trace_recorder: TraceRecorder | None = None,
):
    """Build one bounded call with the supplied durable or in-memory saver."""

    if not isinstance(router, ToolRouter):
        raise TypeError("router must be a ToolRouter")
    if isinstance(max_tool_calls, bool) or not isinstance(max_tool_calls, int):
        raise ValueError("max_tool_calls must be a positive integer")
    if max_tool_calls < 1:
        raise ValueError("max_tool_calls must be a positive integer")
    if isinstance(max_approval_rounds, bool) or not isinstance(max_approval_rounds, int):
        raise ValueError("max_approval_rounds must be a positive integer")
    if max_approval_rounds < 1:
        raise ValueError("max_approval_rounds must be a positive integer")
    configured_timeout = (settings or get_settings()).java_apiops_timeout_seconds
    if (
        isinstance(configured_timeout, bool)
        or not isinstance(configured_timeout, (int, float))
        or configured_timeout <= 0
    ):
        raise ValueError("java_apiops_timeout_seconds must be greater than zero")
    if retry_limit != 0:
        raise ValueError("Stage 18 section 2 supports retry_limit=0 only")
    if preflight_guard is not None and not isinstance(preflight_guard, ToolPreflightGuard):
        raise TypeError("preflight_guard must be a ToolPreflightGuard")
    if evidence_processor is not None and not isinstance(
        evidence_processor, UntrustedEvidenceProcessor
    ):
        raise TypeError("evidence_processor must be an UntrustedEvidenceProcessor")
    if checkpointer is not None and not isinstance(checkpointer, BaseCheckpointSaver):
        raise TypeError("checkpointer must implement BaseCheckpointSaver")
    if trace_recorder is not None and not isinstance(trace_recorder, TraceRecorder):
        raise TypeError("trace_recorder must be a TraceRecorder")
    result_evidence = evidence_processor or UntrustedEvidenceProcessor()

    def _trace_ids(state: ToolUseState) -> tuple[str, str, str] | None:
        tool_call = state["tool_call"]
        trace_id = tool_call.trace_id
        agent_run_id = tool_call.agent_run_id
        step_id = state.get("trace_agent_step_id")
        if not isinstance(step_id, str) or not step_id:
            supplied_step_id = tool_call.agent_step_id
            step_id = supplied_step_id if isinstance(supplied_step_id, str) else ""
        if not trace_id or not agent_run_id or not step_id:
            return None
        return trace_id, agent_run_id, step_id

    def _trace_start(state: ToolUseState) -> dict[str, object]:
        if trace_recorder is None:
            return {}
        tool_call = state["tool_call"]
        trace_id = tool_call.trace_id
        agent_run_id = tool_call.agent_run_id
        existing_step_id = state.get("trace_agent_step_id")
        supplied_step_id = tool_call.agent_step_id
        step_id = (
            existing_step_id
            if isinstance(existing_step_id, str) and existing_step_id
            else supplied_step_id
            if isinstance(supplied_step_id, str) and supplied_step_id
            else new_identity("agent_step")
        )
        if isinstance(existing_step_id, str) and existing_step_id:
            return {}
        parent = trace_parent("agent_run", agent_run_id, IdentityAuthority.PYTHON)
        observe(
            trace_recorder,
            lambda: AgentRun(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                workflow_id=state.get("workflow_id"),
                thread_id=state.get("workflow_id"),
                project_id=state.get("project_id"),
                event=TraceEvent.START,
                status=TraceStatus.RUNNING,
            ),
        )
        observe(
            trace_recorder,
            lambda: AgentStep(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                step_type="tool_use",
                parent_identity=parent,
                workflow_id=state.get("workflow_id"),
                thread_id=state.get("workflow_id"),
                project_id=state.get("project_id"),
                event=TraceEvent.START,
                status=TraceStatus.RUNNING,
            ),
        )
        return {"trace_agent_step_id": step_id}

    def _trace_failure(value: object) -> object | None:
        if not isinstance(value, ToolFailure):
            return None
        return failure_detail(
            value.code.value,
            value.message,
            code=value.code.value,
        )

    def _trace_intent(
        state: ToolUseState,
        *,
        event: TraceEvent,
        status: TraceStatus,
        failure: object | None = None,
        decision: PreflightDecision | None = None,
    ) -> None:
        if trace_recorder is None:
            return
        ids = _trace_ids(state)
        intent_id = state.get("intent_id")
        if ids is None or not isinstance(intent_id, str) or not intent_id:
            return
        trace_id, agent_run_id, step_id = ids
        observe(
            trace_recorder,
            lambda: ToolIntentRecord(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                parent_identity=trace_parent(
                    "agent_step",
                    step_id,
                    IdentityAuthority.PYTHON,
                ),
                workflow_id=state.get("workflow_id"),
                thread_id=state.get("workflow_id"),
                project_id=state.get("project_id"),
                event=event,
                status=status,
                failure=failure,
                tool_intent_id=intent_id,
                tool_name=state["intent"].tool_name,
                arguments_digest=digest_payload(state["intent"].arguments),
                risk=state.get("tool_risk"),
                python_decision=decision,
            ),
        )

    def _trace_safety_violation(
        state: ToolUseState,
        outcome_code: ViolationCode | None,
        *,
        message: str,
    ) -> None:
        if trace_recorder is None or outcome_code is None:
            return
        ids = _trace_ids(state)
        if ids is None:
            return
        trace_id, agent_run_id, step_id = ids
        observe(
            trace_recorder,
            lambda: SafetyViolationFact(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                parent_identity=trace_parent(
                    "agent_step",
                    step_id,
                    IdentityAuthority.PYTHON,
                ),
                workflow_id=state.get("workflow_id"),
                thread_id=state.get("workflow_id"),
                project_id=state.get("project_id"),
                status=TraceStatus.DENIED,
                failure=failure_detail(
                    "SAFETY_VIOLATION",
                    message,
                    code=outcome_code.value,
                ),
                code=outcome_code,
                source=EvidenceSource.PREFLIGHT,
                tool_name=state["intent"].tool_name,
                summary=message,
            ),
        )

    def _trace_approval_interrupt(
        state: ToolUseState,
        request: ApprovalRequest,
    ) -> None:
        if trace_recorder is None:
            return
        ids = _trace_ids(state)
        if ids is None:
            return
        trace_id, agent_run_id, step_id = ids
        parent = trace_parent("agent_step", step_id, IdentityAuthority.PYTHON)
        observe(
            trace_recorder,
            lambda: AgentRun(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                workflow_id=request.workflow_id,
                thread_id=request.workflow_id,
                project_id=request.project_id,
                event=TraceEvent.INTERRUPT,
                status=TraceStatus.INTERRUPTED,
            ),
        )
        observe(
            trace_recorder,
            lambda: AgentStep(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                step_type="tool_use",
                parent_identity=trace_parent(
                    "agent_run",
                    agent_run_id,
                    IdentityAuthority.PYTHON,
                ),
                workflow_id=request.workflow_id,
                thread_id=request.workflow_id,
                project_id=request.project_id,
                event=TraceEvent.INTERRUPT,
                status=TraceStatus.INTERRUPTED,
            ),
        )
        observe(
            trace_recorder,
            lambda: InterruptFact(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                parent_identity=parent,
                workflow_id=request.workflow_id,
                thread_id=request.workflow_id,
                project_id=request.project_id,
                status=TraceStatus.INTERRUPTED,
                intent_id=request.intent_id,
                reason="human approval required",
            ),
        )
        observe(
            trace_recorder,
            lambda: ApprovalFact(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                parent_identity=parent,
                workflow_id=request.workflow_id,
                thread_id=request.workflow_id,
                project_id=request.project_id,
                status=TraceStatus.INTERRUPTED,
                intent_id=request.intent_id,
                tool_name=request.tool_name,
                arguments_fingerprint=request.arguments_fingerprint,
            ),
        )

    def _trace_approval_decision(
        state: ToolUseState,
        decision: ApprovalDecision,
    ) -> None:
        if trace_recorder is None:
            return
        ids = _trace_ids(state)
        if ids is None:
            return
        trace_id, agent_run_id, step_id = ids
        parent = trace_parent("agent_step", step_id, IdentityAuthority.PYTHON)
        observe(
            trace_recorder,
            lambda: AgentRun(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                workflow_id=decision.workflow_id,
                thread_id=decision.workflow_id,
                project_id=decision.project_id,
                event=TraceEvent.RESUME,
                status=TraceStatus.RUNNING,
            ),
        )
        observe(
            trace_recorder,
            lambda: AgentStep(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                step_type="tool_use",
                parent_identity=trace_parent(
                    "agent_run",
                    agent_run_id,
                    IdentityAuthority.PYTHON,
                ),
                workflow_id=decision.workflow_id,
                thread_id=decision.workflow_id,
                project_id=decision.project_id,
                event=TraceEvent.RESUME,
                status=TraceStatus.RUNNING,
            ),
        )
        observe(
            trace_recorder,
            lambda: ResumeFact(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                parent_identity=parent,
                workflow_id=decision.workflow_id,
                thread_id=decision.workflow_id,
                project_id=decision.project_id,
                status=TraceStatus.RUNNING,
                intent_id=decision.intent_id,
            ),
        )
        decision_status = (
            TraceStatus.REJECTED
            if decision.decision is ApprovalAction.REJECT
            else TraceStatus.RUNNING
        )
        decision_failure = (
            failure_detail(
                ToolFailureCode.HUMAN_REJECTED.value,
                "human rejected this exact tool intent",
                code=ToolFailureCode.HUMAN_REJECTED.value,
            )
            if decision.decision is ApprovalAction.REJECT
            else None
        )
        edited_fingerprint = None
        if decision.edited_arguments is not None:
            from app.workflows.approval import fingerprint_arguments

            edited_fingerprint = fingerprint_arguments(decision.edited_arguments)
        observe(
            trace_recorder,
            lambda: ApprovalFact(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                parent_identity=parent,
                workflow_id=decision.workflow_id,
                thread_id=decision.workflow_id,
                project_id=decision.project_id,
                event=TraceEvent.DECISION,
                status=decision_status,
                failure=decision_failure,
                intent_id=decision.intent_id,
                tool_name=decision.tool_name,
                arguments_fingerprint=decision.arguments_fingerprint,
                decision=decision.decision,
                edited_arguments_fingerprint=edited_fingerprint,
            ),
        )

    def _trace_tool_result(state: ToolUseState, update: dict[str, object]) -> None:
        if trace_recorder is None:
            return
        ids = _trace_ids(state)
        if ids is None:
            return
        result = update.get("tool_result")
        failure = update.get("failure")
        if not isinstance(result, ToolResult):
            return
        trace_id, agent_run_id, step_id = ids
        result_status = (
            TraceStatus.SUCCESS
            if result.status == "SUCCESS"
            else TraceStatus.DENIED
            if result.status == "FORBIDDEN"
            else TraceStatus.FAILED
        )
        observe(
            trace_recorder,
            lambda: ToolResultRecord(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                parent_identity=trace_parent(
                    "agent_step",
                    step_id,
                    IdentityAuthority.PYTHON,
                ),
                workflow_id=state.get("workflow_id"),
                thread_id=state.get("workflow_id"),
                project_id=state.get("project_id"),
                status=result_status,
                failure=_trace_failure(failure),
                tool_intent_id=(
                    state.get("intent_id") if isinstance(state.get("intent_id"), str) else None
                ),
                tool_name=state["intent"].tool_name,
                java_tool_call_id=result.tool_call_id,
                tool_result_status=result.status,
                java_error_code=_tool_result_error_code(result),
                has_data=result.data is not None,
                result_summary=digest_payload(result.data).summary,
                sanitized=result.sanitized,
                truncated=_is_truncated(result),
            ),
        )

    def _trace_preflight_result(
        state: ToolUseState,
        start_update: dict[str, object],
        update: dict[str, object],
        outcome: object | None = None,
        *,
        violation_code: ViolationCode | None = None,
        violation_message: str = "Python workflow preflight denied the tool call",
    ) -> dict[str, object]:
        observed_state = dict(state) | start_update
        observed_state.update(update)
        _trace_intent(
            observed_state,  # type: ignore[arg-type]
            event=TraceEvent.INTENT,
            status=TraceStatus.RUNNING,
        )
        failure = update.get("failure")
        if outcome is not None or failure is not None:
            decision = outcome.decision if hasattr(outcome, "decision") else None
            decision_status = (
                TraceStatus.DENIED
                if decision is PreflightDecision.DENY
                else TraceStatus.FAILED
                if failure is not None
                else TraceStatus.RUNNING
            )
            _trace_intent(
                observed_state,  # type: ignore[arg-type]
                event=TraceEvent.DECISION,
                status=decision_status,
                failure=_trace_failure(failure),
                decision=decision,
            )
        if violation_code is not None:
            _trace_safety_violation(
                observed_state,  # type: ignore[arg-type]
                violation_code,
                message=violation_message,
            )
        request = update.get("approval_request")
        if isinstance(request, ApprovalRequest):
            _trace_approval_interrupt(observed_state, request)  # type: ignore[arg-type]
        return start_update | update

    def trace_terminal(state: ToolUseState) -> dict[str, object]:
        if trace_recorder is None:
            return {}
        ids = _trace_ids(state)
        if ids is None:
            return {}
        trace_id, agent_run_id, step_id = ids
        failure = state.get("failure")
        if isinstance(failure, ToolFailure):
            if failure.code is ToolFailureCode.HUMAN_REJECTED:
                status = TraceStatus.REJECTED
            elif failure.code in {
                ToolFailureCode.PYTHON_PREFLIGHT_DENIED,
                ToolFailureCode.JAVA_AUTHORIZATION_DENIED,
            }:
                status = TraceStatus.DENIED
            else:
                status = TraceStatus.FAILED
        elif state.get("status") is ToolUseStatus.CONTINUE:
            status = TraceStatus.SUCCESS
        else:
            status = TraceStatus.FAILED
        trace_failure = _trace_failure(failure)
        parent = trace_parent("agent_run", agent_run_id, IdentityAuthority.PYTHON)
        observe(
            trace_recorder,
            lambda: AgentStep(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                step_type="tool_use",
                parent_identity=parent,
                workflow_id=state.get("workflow_id"),
                thread_id=state.get("workflow_id"),
                project_id=state.get("project_id"),
                event=TraceEvent.TERMINAL,
                status=status,
                failure=trace_failure,
            ),
        )
        observe(
            trace_recorder,
            lambda: AgentRun(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                workflow_id=state.get("workflow_id"),
                thread_id=state.get("workflow_id"),
                project_id=state.get("project_id"),
                event=TraceEvent.TERMINAL,
                status=status,
                failure=trace_failure,
            ),
        )
        return {}

    def preflight_tool(state: ToolUseState, config: RunnableConfig) -> dict[str, object]:
        start_update = _trace_start(state)
        calls_used = _validate_calls_used(state["tool_calls_used"])
        if calls_used >= max_tool_calls:
            return _trace_preflight_result(
                state,
                start_update,
                _failure(
                    ToolFailureCode.TOOL_CALL_LIMIT_EXCEEDED,
                    "tool call budget exhausted",
                    calls_used=calls_used,
                ),
            )
        try:
            router.validate(state["intent"], state["tool_call"])
        except ToolCatalogError as exc:
            if preflight_guard is not None:
                rejected = preflight_guard.evaluate(state["intent"], state["tool_call"])
                if rejected.decision is PreflightDecision.DENY:
                    update = {
                        "tool_risk": rejected.risk,
                        "preflight_decision": rejected.decision,
                    } | _failure(
                        ToolFailureCode.PYTHON_PREFLIGHT_DENIED,
                        "Python workflow preflight denied the tool call",
                        calls_used=calls_used,
                    )
                    return _trace_preflight_result(
                        state,
                        start_update,
                        update,
                        rejected,
                        violation_code=rejected.violation_code,
                    )
            return _trace_preflight_result(
                state,
                start_update,
                _failure(
                    ToolFailureCode.CONTRACT_OR_ROUTING_FAILURE,
                    str(exc),
                    calls_used=calls_used,
                ),
            )
        if preflight_guard is None:
            return _trace_preflight_result(
                state,
                start_update,
                {"failure": None},
            )

        outcome = preflight_guard.evaluate(state["intent"], state["tool_call"])
        updates: dict[str, object] = {
            "tool_risk": outcome.risk,
            "preflight_decision": outcome.decision,
            "failure": None,
        }
        if outcome.decision is PreflightDecision.DENY:
            return _trace_preflight_result(
                state,
                start_update,
                updates
                | _failure(
                    ToolFailureCode.PYTHON_PREFLIGHT_DENIED,
                    "Python workflow preflight denied the tool call",
                    calls_used=calls_used,
                ),
                outcome,
                violation_code=outcome.violation_code,
            )
        if outcome.decision is not PreflightDecision.REQUIRE_APPROVAL:
            return _trace_preflight_result(
                state,
                start_update,
                updates,
                outcome,
            )
        if checkpointer is None:
            return _trace_preflight_result(
                state,
                start_update,
                updates
                | _failure(
                    ToolFailureCode.APPROVAL_REQUIRED,
                    "tool call requires an interrupt-enabled checkpointer",
                    calls_used=calls_used,
                ),
                outcome,
            )
        request = _current_request(state, config)
        if request is None:
            return _trace_preflight_result(
                state,
                start_update,
                updates
                | _failure(
                    ToolFailureCode.WORKFLOW_IDENTITY_MISMATCH,
                    "workflow_id, project_id, and intent_id must match controlled context",
                    calls_used=calls_used,
                ),
                outcome,
            )
        approval_round = _validate_approval_round(state.get("approval_round", 0))
        if approval_round >= max_approval_rounds:
            return _trace_preflight_result(
                state,
                start_update,
                updates
                | {
                    "approval_round": approval_round,
                    "max_approval_rounds": max_approval_rounds,
                    "approval_request": None,
                }
                | _failure(
                    ToolFailureCode.APPROVAL_ROUND_LIMIT_EXCEEDED,
                    "approval round budget exhausted",
                    calls_used=calls_used,
                ),
                outcome,
            )
        return _trace_preflight_result(
            state,
            start_update,
            updates
            | {
                "approval_request": request,
                "approval_decision": None,
                "approval_consumed": False,
                "approval_round": approval_round + 1,
                "max_approval_rounds": max_approval_rounds,
                "status": ToolUseStatus.AWAITING_APPROVAL,
            },
            outcome,
        )

    def request_approval(
        state: ToolUseState,
        config: RunnableConfig,
    ) -> Command[Literal["preflight_tool", "execute_tool", "trace_terminal"]]:
        calls_used = _validate_calls_used(state["tool_calls_used"])
        stored_request = state.get("approval_request")
        current_request = _current_request(state, config)
        if (
            state.get("approval_consumed") is True
            or stored_request is None
            or current_request != stored_request
        ):
            return Command(
                update=_failure(
                    ToolFailureCode.STALE_APPROVAL,
                    "approval binding is stale or already consumed",
                    calls_used=calls_used,
                ),
                goto=_TRACE_TERMINAL_NODE,
            )

        raw_decision = interrupt(stored_request.model_dump(mode="json"))
        try:
            decision = ApprovalDecision.model_validate(raw_decision, strict=False)
        except ValidationError:
            return Command(
                update=_failure(
                    ToolFailureCode.APPROVAL_RESPONSE_INVALID,
                    "human approval response is invalid",
                    calls_used=calls_used,
                ),
                goto=_TRACE_TERMINAL_NODE,
            )
        if not stored_request.matches(decision):
            return Command(
                update=_failure(
                    ToolFailureCode.STALE_APPROVAL,
                    "human decision does not match the interrupted intent",
                    calls_used=calls_used,
                ),
                goto=_TRACE_TERMINAL_NODE,
            )
        _trace_approval_decision(state, decision)
        if decision.decision is ApprovalAction.REJECT:
            return Command(
                update=_failure(
                    ToolFailureCode.HUMAN_REJECTED,
                    "human rejected this exact tool intent",
                    calls_used=calls_used,
                )
                | {"approval_decision": decision, "approval_consumed": True},
                goto=_TRACE_TERMINAL_NODE,
            )
        if decision.decision is ApprovalAction.EDIT:
            assert decision.edited_arguments is not None
            try:
                edited_intent = ToolIntent(
                    tool_name=state["intent"].tool_name,
                    arguments=decision.edited_arguments,
                )
            except ValidationError:
                return Command(
                    update=_failure(
                        ToolFailureCode.CONTRACT_OR_ROUTING_FAILURE,
                        "edited arguments do not form a valid ToolIntent",
                        calls_used=calls_used,
                    ),
                    goto=_TRACE_TERMINAL_NODE,
                )
            edited_call = state["tool_call"].model_copy(
                update={"params": decision.edited_arguments}
            )
            return Command(
                update={
                    "intent": edited_intent,
                    "tool_call": edited_call,
                    "intent_id": new_intent_id(),
                    "approval_request": None,
                    "approval_decision": decision,
                    "approval_consumed": False,
                    "preflight_decision": None,
                    "failure": None,
                    "status": ToolUseStatus.PENDING,
                },
                goto=_PREFLIGHT_NODE,
            )

        try:
            router.validate(state["intent"], state["tool_call"])
        except ToolCatalogError as exc:
            return Command(
                update=_failure(
                    ToolFailureCode.CONTRACT_OR_ROUTING_FAILURE,
                    str(exc),
                    calls_used=calls_used,
                ),
                goto=_TRACE_TERMINAL_NODE,
            )
        assert preflight_guard is not None
        renewed = preflight_guard.evaluate(state["intent"], state["tool_call"])
        if renewed.decision is PreflightDecision.DENY:
            _trace_safety_violation(
                state,
                renewed.violation_code,
                message="Python workflow preflight denied the approved intent on resume",
            )
            return Command(
                update=_failure(
                    ToolFailureCode.PYTHON_PREFLIGHT_DENIED,
                    "Python workflow preflight denied the approved intent on resume",
                    calls_used=calls_used,
                ),
                goto=_TRACE_TERMINAL_NODE,
            )
        return Command(
            update={
                "tool_risk": renewed.risk,
                "preflight_decision": renewed.decision,
                "approval_decision": decision,
                "approval_consumed": True,
                "status": ToolUseStatus.PENDING,
                "failure": None,
            },
            goto=_EXECUTE_NODE,
        )

    async def execute_tool(state: ToolUseState) -> dict[str, object]:
        calls_used = _validate_calls_used(state["tool_calls_used"])

        def finish(update: dict[str, object]) -> dict[str, object]:
            _trace_tool_result(state, update)
            return update

        try:
            result = await asyncio.wait_for(
                router.route(state["intent"], state["tool_call"]),
                timeout=float(configured_timeout),
            )
        except (ToolCatalogError, ToolAdapterUnavailableError) as exc:
            return finish(
                _failure(
                    ToolFailureCode.CONTRACT_OR_ROUTING_FAILURE,
                    str(exc),
                    calls_used=calls_used,
                )
            )
        except ToolGatewayAuthenticationError:
            return finish(
                _failure(
                    ToolFailureCode.JAVA_AUTHENTICATION_FAILED,
                    "Java Tool Gateway rejected the credential",
                    calls_used=calls_used + 1,
                )
            )
        except ToolGatewayAuthorizationError:
            return finish(
                _failure(
                    ToolFailureCode.JAVA_AUTHORIZATION_DENIED,
                    "Java Tool Gateway denied project authorization",
                    calls_used=calls_used + 1,
                )
            )
        except ToolGatewayNotFoundError:
            return finish(
                _failure(
                    ToolFailureCode.JAVA_RESOURCE_NOT_FOUND,
                    "Java Tool Gateway resource was not found",
                    calls_used=calls_used + 1,
                )
            )
        except (ToolGatewayTimeoutError, TimeoutError):
            return finish(
                _failure(
                    ToolFailureCode.JAVA_TIMEOUT,
                    "Java Tool Gateway timed out",
                    calls_used=calls_used + 1,
                )
            )
        except ToolGatewayTransportError:
            return finish(
                _failure(
                    ToolFailureCode.JAVA_TRANSPORT_UNAVAILABLE,
                    "Java Tool Gateway was unavailable",
                    calls_used=calls_used + 1,
                )
            )
        except InvalidGatewayResultError:
            return finish(
                _failure(
                    ToolFailureCode.INVALID_GATEWAY_RESULT,
                    "Java Tool Gateway returned an invalid ToolResult",
                    calls_used=calls_used + 1,
                )
            )

        next_calls_used = calls_used + 1
        evidence = {
            "untrusted_evidence": result_evidence.from_tool_result(
                result,
                tool_call=state["tool_call"],
            )
        }
        if result.status == "SUCCESS":
            return finish(
                {
                    "tool_result": result,
                    "status": ToolUseStatus.CONTINUE,
                    "failure": None,
                    "tool_calls_used": next_calls_used,
                    "result_sanitized": result.sanitized,
                    "result_truncated": _is_truncated(result),
                }
                | evidence
            )
        failures = {
            "FORBIDDEN": (
                ToolFailureCode.JAVA_AUTHORIZATION_DENIED,
                "Java Tool Gateway denied the tool call",
            ),
            "FAILED": (
                ToolFailureCode.JAVA_EXECUTION_FAILED,
                "Java tool execution failed",
            ),
            "TIMEOUT": (
                ToolFailureCode.JAVA_TIMEOUT,
                "Java Tool Gateway reported a timeout",
            ),
            "RESULT_INVALID": (
                ToolFailureCode.INVALID_GATEWAY_RESULT,
                "Java Tool Gateway reported an invalid result",
            ),
        }
        code, message = failures.get(
            result.status,
            (
                ToolFailureCode.CONTRACT_OR_ROUTING_FAILURE,
                "Java Tool Gateway rejected the tool parameters",
            ),
        )
        return finish(
            _failure(
                code,
                message,
                calls_used=next_calls_used,
                result=result,
            )
            | evidence
        )

    builder = StateGraph(ToolUseState)
    builder.add_node(_PREFLIGHT_NODE, preflight_tool)
    builder.add_node(_APPROVAL_NODE, request_approval)
    builder.add_node(_EXECUTE_NODE, execute_tool)
    builder.add_node(_TRACE_TERMINAL_NODE, trace_terminal)
    builder.add_edge(START, _PREFLIGHT_NODE)
    builder.add_conditional_edges(
        _PREFLIGHT_NODE,
        _route_after_preflight,
        {
            "approval": _APPROVAL_NODE,
            "execute": _EXECUTE_NODE,
            "end": _TRACE_TERMINAL_NODE,
        },
    )
    builder.add_edge(_EXECUTE_NODE, _TRACE_TERMINAL_NODE)
    builder.add_edge(_TRACE_TERMINAL_NODE, END)
    return builder.compile(checkpointer=checkpointer)


__all__ = ["build_tool_use_graph"]
