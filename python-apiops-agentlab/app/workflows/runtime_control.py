"""Deterministic bounded-cycle and in-memory checkpoint experiment."""

from __future__ import annotations

from typing import Final, Literal

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.workflows.hello_graph import finish, prepare
from app.workflows.state import APIOpsAgentState, WorkflowPhase, WorkflowRoute

CycleDecision = Literal["finish", "retry", "reject"]

_PREPARE_NODE: Final = "prepare"
_VALIDATE_NODE: Final = "validate"
_RETRY_NODE: Final = "retry"
_FINISH_NODE: Final = "finish"
_REJECT_NODE: Final = "reject"


def _read_budget(state: APIOpsAgentState) -> tuple[int, int]:
    attempt_count = state["attempt_count"]
    max_attempts = state["max_attempts"]
    if isinstance(attempt_count, bool) or not isinstance(attempt_count, int):
        raise ValueError("attempt_count must be a non-negative integer")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise ValueError("max_attempts must be a non-negative integer")
    if attempt_count < 0 or max_attempts < 0:
        raise ValueError("attempt_count and max_attempts must be non-negative")
    return attempt_count, max_attempts


def _validate_scenario(failures_before_success: int | None) -> None:
    if failures_before_success is not None and failures_before_success < 0:
        raise ValueError("failures_before_success must be non-negative or None")


def route_after_validation(state: APIOpsAgentState) -> CycleDecision:
    """Choose the next branch from validation outcome and the current budget."""

    route = state["route"]
    attempt_count, max_attempts = _read_budget(state)
    if route is WorkflowRoute.READY:
        return "finish"
    if route is WorkflowRoute.BLOCKED and attempt_count < max_attempts:
        return "retry"
    if route is WorkflowRoute.BLOCKED:
        return "reject"
    raise ValueError(f"Unsupported validation route: {route!r}")


def retry(state: APIOpsAgentState) -> dict[str, int]:
    """Complete one deterministic retry-style attempt and increment its count."""

    attempt_count, max_attempts = _read_budget(state)
    if attempt_count >= max_attempts:
        raise RuntimeError("retry budget exhausted")
    return {"attempt_count": attempt_count + 1}


def reject_after_budget(state: APIOpsAgentState) -> dict[str, WorkflowPhase | str]:
    """Produce a stable failure terminal update after the retry budget is exhausted."""

    _ = state["attempt_count"]
    error = state["error"] or "validation failed after retry budget"
    return {"phase": WorkflowPhase.REJECTED, "error": error}


def checkpoint_config(thread_id: str) -> dict[str, dict[str, str]]:
    """Build the explicit LangGraph execution identity configuration."""

    if not thread_id:
        raise ValueError("thread_id must be non-empty")
    return {"configurable": {"thread_id": thread_id}}


def build_bounded_cycle_graph(
    *,
    failures_before_success: int | None,
    checkpointer: InMemorySaver | None = None,
):
    """Build a deterministic validation/retry graph with an optional in-memory saver.

    ``failures_before_success=None`` models an always-invalid validation scenario.
    Otherwise, validation becomes successful after that many completed retries.
    """

    _validate_scenario(failures_before_success)

    def validate(state: APIOpsAgentState) -> dict[str, WorkflowRoute]:
        attempt_count, _ = _read_budget(state)
        if failures_before_success is not None and attempt_count >= failures_before_success:
            return {"route": WorkflowRoute.READY}
        return {"route": WorkflowRoute.BLOCKED}

    builder = StateGraph(APIOpsAgentState)
    builder.add_node(_PREPARE_NODE, prepare)
    builder.add_node(_VALIDATE_NODE, validate)
    builder.add_node(_RETRY_NODE, retry)
    builder.add_node(_FINISH_NODE, finish)
    builder.add_node(_REJECT_NODE, reject_after_budget)
    builder.add_edge(START, _PREPARE_NODE)
    builder.add_edge(_PREPARE_NODE, _VALIDATE_NODE)
    builder.add_conditional_edges(
        _VALIDATE_NODE,
        route_after_validation,
        {
            "finish": _FINISH_NODE,
            "retry": _RETRY_NODE,
            "reject": _REJECT_NODE,
        },
    )
    builder.add_edge(_RETRY_NODE, _VALIDATE_NODE)
    builder.add_edge(_FINISH_NODE, END)
    builder.add_edge(_REJECT_NODE, END)
    return builder.compile(checkpointer=checkpointer)


__all__ = [
    "CycleDecision",
    "build_bounded_cycle_graph",
    "checkpoint_config",
    "reject_after_budget",
    "retry",
    "route_after_validation",
]
