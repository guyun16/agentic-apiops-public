"""Bounded Stage 16 generation, validation, and single-repair workflow."""

from __future__ import annotations

from typing import Final, Literal

from langgraph.graph import END, START, StateGraph

from app.agents.testcase_generator import Candidate, GenerationFailure, TestCaseGenerator
from app.tracing import (
    AgentRun,
    AgentStep,
    IdentityAuthority,
    PromptIdentity,
    TraceEvent,
    TraceRecorder,
    TraceStatus,
    failure_detail,
    instrument_generator,
    new_identity,
    observe,
    trace_parent,
    trace_step_scope,
)
from app.workflows.candidate_validation import CandidateValidationResult, validate_candidate
from app.workflows.context_enrichment import ContextEnricher
from app.workflows.generation_context import GenerationContext
from app.workflows.state import (
    APIOpsAgentState,
    ContextEnrichmentStatus,
    TestCaseGenerationStatus,
    WorkflowPhase,
    WorkflowRoute,
)

GenerationDecision = Literal["validate", "end"]
ContextDecision = Literal["generate", "end"]
ValidationDecision = Literal["accept", "repair", "reject"]

_CONTEXT_NODE: Final = "context_enrichment"
_GENERATE_NODE: Final = "generate"
_VALIDATE_NODE: Final = "validate"
_REPAIR_NODE: Final = "repair"
_ACCEPT_NODE: Final = "accept"
_REJECT_NODE: Final = "reject"
_TRACE_START_NODE: Final = "trace_start"
_TRACE_TERMINAL_NODE: Final = "trace_terminal"


def _read_repair_budget(state: APIOpsAgentState) -> tuple[int, int]:
    attempts = state["repair_attempts"]
    maximum = state["max_repair_attempts"]
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
        raise ValueError("repair_attempts must be a non-negative integer")
    if maximum != 1 or isinstance(maximum, bool):
        raise ValueError("max_repair_attempts must be 1")
    if attempts > maximum:
        raise ValueError("repair_attempts cannot exceed max_repair_attempts")
    return attempts, maximum


def _require_context(state: APIOpsAgentState) -> GenerationContext:
    context = state["generation_context"]
    if context is None:
        raise ValueError("generation_context is required")
    return context


def _require_candidate(state: APIOpsAgentState) -> Candidate:
    candidate = state["candidate"]
    if candidate is None:
        raise RuntimeError("candidate is required")
    return candidate


def _require_validation(state: APIOpsAgentState) -> CandidateValidationResult:
    result = state["validation_result"]
    if result is None:
        raise RuntimeError("validation_result is required")
    return result


def route_after_generation(state: APIOpsAgentState) -> GenerationDecision:
    if state["generation_status"] is TestCaseGenerationStatus.GENERATION_FAILURE:
        return "end"
    return "validate"


def route_after_context(state: APIOpsAgentState) -> ContextDecision:
    status = state["context_status"]
    if status is ContextEnrichmentStatus.FAILED:
        return "end"
    if status in {ContextEnrichmentStatus.READY, ContextEnrichmentStatus.DEGRADED}:
        return "generate"
    raise RuntimeError("context enrichment did not produce a terminal status")


def route_after_validation(state: APIOpsAgentState) -> ValidationDecision:
    result = _require_validation(state)
    if result.valid:
        return "accept"
    attempts, maximum = _read_repair_budget(state)
    return "repair" if attempts < maximum else "reject"


def route_after_repair(state: APIOpsAgentState) -> GenerationDecision:
    if state["generation_status"] is TestCaseGenerationStatus.GENERATION_FAILURE:
        return "end"
    return "validate"


def accept_candidate(state: APIOpsAgentState) -> dict[str, object]:
    result = _require_validation(state)
    if not result.valid:
        raise RuntimeError("invalid candidate cannot be accepted")
    return {
        "phase": WorkflowPhase.FINISHED,
        "route": WorkflowRoute.READY,
        "generation_status": TestCaseGenerationStatus.ACCEPTED,
        "error": None,
    }


def reject_after_repair(state: APIOpsAgentState) -> dict[str, object]:
    result = _require_validation(state)
    attempts, maximum = _read_repair_budget(state)
    if result.valid or attempts < maximum:
        raise RuntimeError("repair rejection requires invalid exhausted state")
    return {
        "phase": WorkflowPhase.REJECTED,
        "route": WorkflowRoute.BLOCKED,
        "generation_status": TestCaseGenerationStatus.REPAIR_EXHAUSTED,
        "error": TestCaseGenerationStatus.REPAIR_EXHAUSTED.value,
    }


def build_testcase_generation_graph(
    generator: TestCaseGenerator,
    *,
    context_enricher: ContextEnricher | None = None,
    trace_recorder: TraceRecorder | None = None,
):
    """Compile the Stage 16 graph with one initial call and at most one repair."""

    traced_generator = instrument_generator(generator, trace_recorder)

    def start_trace(state: APIOpsAgentState) -> dict[str, object]:
        if trace_recorder is None:
            return {}
        trace_id = state.get("trace_id")
        if not isinstance(trace_id, str) or not trace_id:
            trace_id = new_identity("trace")
        agent_run_id = state.get("agent_run_id")
        if not isinstance(agent_run_id, str) or not agent_run_id:
            agent_run_id = new_identity("agent_run")
        observe(
            trace_recorder,
            lambda: AgentRun(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                project_id=state["project_id"],
                event=TraceEvent.START,
                status=TraceStatus.RUNNING,
            ),
        )
        return {"trace_id": trace_id, "agent_run_id": agent_run_id}

    def terminal_trace(state: APIOpsAgentState) -> dict[str, object]:
        if trace_recorder is None:
            return {}
        trace_id = state.get("trace_id")
        agent_run_id = state.get("agent_run_id")
        if not isinstance(trace_id, str) or not trace_id:
            return {}
        if not isinstance(agent_run_id, str) or not agent_run_id:
            return {}

        failure: object | None = None
        if state["phase"] is WorkflowPhase.FINISHED:
            status = TraceStatus.SUCCESS
        elif state["generation_status"] is TestCaseGenerationStatus.REPAIR_EXHAUSTED:
            status = TraceStatus.REJECTED
            failure = failure_detail(
                "REPAIR_EXHAUSTED",
                state.get("error") or "repair budget exhausted",
                code=TestCaseGenerationStatus.REPAIR_EXHAUSTED.value,
            )
        elif state["context_status"] is ContextEnrichmentStatus.FAILED:
            status = TraceStatus.FAILED
            failure = failure_detail(
                "CONTEXT_ENRICHMENT_FAILURE",
                state.get("context_error") or state.get("error") or "context enrichment failed",
                code="CONTEXT_ENRICHMENT_FAILED",
            )
        elif state["generation_status"] is TestCaseGenerationStatus.GENERATION_FAILURE:
            status = TraceStatus.FAILED
            failure = failure_detail(
                "GENERATION_FAILURE",
                state.get("error") or "generation failed",
                code=TestCaseGenerationStatus.GENERATION_FAILURE.value,
            )
        else:
            status = TraceStatus.REJECTED
            failure = failure_detail(
                "WORKFLOW_REJECTED",
                state.get("error") or "workflow rejected",
                code=state.get("error") or "WORKFLOW_REJECTED",
            )
        observe(
            trace_recorder,
            lambda: AgentRun(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                project_id=state["project_id"],
                event=TraceEvent.TERMINAL,
                status=status,
                failure=failure,
            ),
        )
        return {}

    def start_step(state: APIOpsAgentState, step_type: str) -> str | None:
        if trace_recorder is None:
            return None
        trace_id = state.get("trace_id")
        agent_run_id = state.get("agent_run_id")
        if not isinstance(trace_id, str) or not isinstance(agent_run_id, str):
            return None
        step_id = new_identity("agent_step")
        observe(
            trace_recorder,
            lambda: AgentStep(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                step_type=step_type,
                parent_identity=trace_parent(
                    "agent_run",
                    agent_run_id,
                    IdentityAuthority.PYTHON,
                ),
                project_id=state["project_id"],
                event=TraceEvent.START,
                status=TraceStatus.RUNNING,
            ),
        )
        return step_id

    def finish_step(
        state: APIOpsAgentState,
        step_id: str | None,
        *,
        status: TraceStatus,
        failure: object | None = None,
        step_type: str,
    ) -> None:
        if trace_recorder is None or step_id is None:
            return
        trace_id = state.get("trace_id")
        agent_run_id = state.get("agent_run_id")
        if not isinstance(trace_id, str) or not isinstance(agent_run_id, str):
            return
        observe(
            trace_recorder,
            lambda: AgentStep(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                agent_step_id=step_id,
                step_type=step_type,
                parent_identity=trace_parent(
                    "agent_run",
                    agent_run_id,
                    IdentityAuthority.PYTHON,
                ),
                project_id=state["project_id"],
                event=TraceEvent.TERMINAL,
                status=status,
                failure=failure,
            ),
        )

    async def enrich_context(state: APIOpsAgentState) -> dict[str, object]:
        step_id = start_step(state, _CONTEXT_NODE)
        context = _require_context(state)
        try:
            if context_enricher is None:
                update: dict[str, object] = {
                    "context_pack": None,
                    "context_status": ContextEnrichmentStatus.READY,
                    "context_error": None,
                }
            else:
                result = await context_enricher.enrich(
                    project_id=state["project_id"],
                    generation_context=context,
                )
                update = {
                    "context_pack": result.context_pack,
                    "context_status": result.status,
                    "context_error": result.error,
                }
                if result.status is ContextEnrichmentStatus.FAILED:
                    update.update(
                        phase=WorkflowPhase.REJECTED,
                        route=WorkflowRoute.BLOCKED,
                        error=result.error,
                    )
            finish_step(
                state,
                step_id,
                status=(
                    TraceStatus.FAILED
                    if update["context_status"] is ContextEnrichmentStatus.FAILED
                    else TraceStatus.SUCCESS
                ),
                failure=(
                    failure_detail(
                        "CONTEXT_ENRICHMENT_FAILURE",
                        update["context_error"] or "context enrichment failed",
                        code="CONTEXT_ENRICHMENT_FAILED",
                    )
                    if update["context_status"] is ContextEnrichmentStatus.FAILED
                    else None
                ),
                step_type=_CONTEXT_NODE,
            )
            return update
        except Exception as exc:
            finish_step(
                state,
                step_id,
                status=TraceStatus.FAILED,
                failure=failure_detail(
                    "CONTEXT_ENRICHMENT_FAILURE",
                    str(exc),
                    code=type(exc).__name__,
                    error_type=type(exc).__name__,
                ),
                step_type=_CONTEXT_NODE,
            )
            raise

    async def generate_candidate(state: APIOpsAgentState) -> dict[str, object]:
        _read_repair_budget(state)
        context = _require_context(state)
        step_id = start_step(state, _GENERATE_NODE)
        trace_id = state.get("trace_id")
        agent_run_id = state.get("agent_run_id")
        prompt = PromptIdentity(name="testcase_generate", version="v1")
        try:
            if (
                trace_recorder is not None
                and isinstance(trace_id, str)
                and isinstance(agent_run_id, str)
                and step_id is not None
            ):
                with trace_step_scope(
                    trace_recorder,
                    trace_id=trace_id,
                    agent_run_id=agent_run_id,
                    agent_step_id=step_id,
                    prompt=prompt,
                ):
                    candidate = await traced_generator.generate(
                        context,
                        project_id=state["project_id"],
                        context_pack=state["context_pack"],
                    )
            else:
                candidate = await traced_generator.generate(
                    context,
                    project_id=state["project_id"],
                    context_pack=state["context_pack"],
                )
        except GenerationFailure:
            finish_step(
                state,
                step_id,
                status=TraceStatus.FAILED,
                failure=failure_detail(
                    "GENERATION_FAILURE",
                    TestCaseGenerationStatus.GENERATION_FAILURE.value,
                    code=TestCaseGenerationStatus.GENERATION_FAILURE.value,
                ),
                step_type=_GENERATE_NODE,
            )
            return {
                "phase": WorkflowPhase.REJECTED,
                "route": WorkflowRoute.BLOCKED,
                "candidate": None,
                "validation_result": None,
                "generation_status": TestCaseGenerationStatus.GENERATION_FAILURE,
                "error": TestCaseGenerationStatus.GENERATION_FAILURE.value,
            }
        except Exception as exc:
            finish_step(
                state,
                step_id,
                status=TraceStatus.FAILED,
                failure=failure_detail(
                    "GENERATION_FAILURE",
                    str(exc),
                    code=type(exc).__name__,
                    error_type=type(exc).__name__,
                ),
                step_type=_GENERATE_NODE,
            )
            raise
        finish_step(
            state,
            step_id,
            status=TraceStatus.SUCCESS,
            step_type=_GENERATE_NODE,
        )
        return {
            "phase": WorkflowPhase.PREPARED,
            "route": None,
            "candidate": candidate,
            "validation_result": None,
            "generation_status": None,
            "error": None,
        }

    def validate(state: APIOpsAgentState) -> dict[str, object]:
        step_id = start_step(state, _VALIDATE_NODE)
        try:
            result = validate_candidate(
                _require_candidate(state),
                project_id=state["project_id"],
                generation_context=_require_context(state),
            )
        except Exception as exc:
            finish_step(
                state,
                step_id,
                status=TraceStatus.FAILED,
                failure=failure_detail(
                    "VALIDATION_FAILURE",
                    str(exc),
                    code=type(exc).__name__,
                    error_type=type(exc).__name__,
                ),
                step_type=_VALIDATE_NODE,
            )
            raise
        validation_failure = None
        if not result.valid:
            issue = result.issues[0] if result.issues else None
            validation_failure = failure_detail(
                "VALIDATION_FAILURE",
                "candidate validation failed" if issue is None else issue.message,
                code="VALIDATION_FAILED" if issue is None else issue.code,
            )
        finish_step(
            state,
            step_id,
            status=TraceStatus.FAILED if validation_failure is not None else TraceStatus.SUCCESS,
            failure=validation_failure,
            step_type=_VALIDATE_NODE,
        )
        return {
            "validation_result": result,
            "route": WorkflowRoute.READY if result.valid else WorkflowRoute.BLOCKED,
            "generation_status": (
                None if result.valid else TestCaseGenerationStatus.VALIDATION_FAILURE
            ),
        }

    async def repair_candidate(state: APIOpsAgentState) -> dict[str, object]:
        attempts, maximum = _read_repair_budget(state)
        if attempts >= maximum:
            raise RuntimeError("repair budget exhausted")
        result = _require_validation(state)
        if result.valid:
            raise RuntimeError("valid candidate cannot enter repair")
        step_id = start_step(state, _REPAIR_NODE)
        trace_id = state.get("trace_id")
        agent_run_id = state.get("agent_run_id")
        prompt = PromptIdentity(name="testcase_repair", version="v1")
        try:
            if (
                trace_recorder is not None
                and isinstance(trace_id, str)
                and isinstance(agent_run_id, str)
                and step_id is not None
            ):
                with trace_step_scope(
                    trace_recorder,
                    trace_id=trace_id,
                    agent_run_id=agent_run_id,
                    agent_step_id=step_id,
                    prompt=prompt,
                ):
                    candidate = await traced_generator.repair(
                        _require_context(state),
                        _require_candidate(state),
                        result.issues,
                        project_id=state["project_id"],
                        context_pack=state["context_pack"],
                    )
            else:
                candidate = await traced_generator.repair(
                    _require_context(state),
                    _require_candidate(state),
                    result.issues,
                    project_id=state["project_id"],
                    context_pack=state["context_pack"],
                )
        except GenerationFailure:
            finish_step(
                state,
                step_id,
                status=TraceStatus.FAILED,
                failure=failure_detail(
                    "REPAIR_FAILURE",
                    TestCaseGenerationStatus.GENERATION_FAILURE.value,
                    code=TestCaseGenerationStatus.GENERATION_FAILURE.value,
                ),
                step_type=_REPAIR_NODE,
            )
            return {
                "phase": WorkflowPhase.REJECTED,
                "route": WorkflowRoute.BLOCKED,
                "repair_attempts": attempts + 1,
                "generation_status": TestCaseGenerationStatus.GENERATION_FAILURE,
                "error": TestCaseGenerationStatus.GENERATION_FAILURE.value,
            }
        except Exception as exc:
            finish_step(
                state,
                step_id,
                status=TraceStatus.FAILED,
                failure=failure_detail(
                    "REPAIR_FAILURE",
                    str(exc),
                    code=type(exc).__name__,
                    error_type=type(exc).__name__,
                ),
                step_type=_REPAIR_NODE,
            )
            raise
        finish_step(
            state,
            step_id,
            status=TraceStatus.SUCCESS,
            step_type=_REPAIR_NODE,
        )
        return {
            "route": None,
            "candidate": candidate,
            "validation_result": None,
            "repair_attempts": attempts + 1,
            "generation_status": None,
            "error": None,
        }

    builder = StateGraph(APIOpsAgentState)
    builder.add_node(_TRACE_START_NODE, start_trace)
    builder.add_node(_TRACE_TERMINAL_NODE, terminal_trace)
    builder.add_node(_CONTEXT_NODE, enrich_context)
    builder.add_node(_GENERATE_NODE, generate_candidate)
    builder.add_node(_VALIDATE_NODE, validate)
    builder.add_node(_REPAIR_NODE, repair_candidate)
    builder.add_node(_ACCEPT_NODE, accept_candidate)
    builder.add_node(_REJECT_NODE, reject_after_repair)
    builder.add_edge(START, _TRACE_START_NODE)
    builder.add_edge(_TRACE_START_NODE, _CONTEXT_NODE)
    builder.add_conditional_edges(
        _CONTEXT_NODE,
        route_after_context,
        {"generate": _GENERATE_NODE, "end": _TRACE_TERMINAL_NODE},
    )
    builder.add_conditional_edges(
        _GENERATE_NODE,
        route_after_generation,
        {"validate": _VALIDATE_NODE, "end": _TRACE_TERMINAL_NODE},
    )
    builder.add_conditional_edges(
        _VALIDATE_NODE,
        route_after_validation,
        {
            "accept": _ACCEPT_NODE,
            "repair": _REPAIR_NODE,
            "reject": _REJECT_NODE,
        },
    )
    builder.add_conditional_edges(
        _REPAIR_NODE,
        route_after_repair,
        {"validate": _VALIDATE_NODE, "end": _TRACE_TERMINAL_NODE},
    )
    builder.add_edge(_ACCEPT_NODE, _TRACE_TERMINAL_NODE)
    builder.add_edge(_REJECT_NODE, _TRACE_TERMINAL_NODE)
    builder.add_edge(_TRACE_TERMINAL_NODE, END)
    return builder.compile()


__all__ = [
    "GenerationDecision",
    "ContextDecision",
    "ValidationDecision",
    "accept_candidate",
    "build_testcase_generation_graph",
    "reject_after_repair",
    "route_after_generation",
    "route_after_context",
    "route_after_repair",
    "route_after_validation",
]
