"""Minimal LangGraph StateGraph spike for the Python workflow boundary."""

from __future__ import annotations

from typing import Final

from langgraph.graph import END, START, StateGraph

from app.workflows.state import APIOpsAgentState, WorkflowPhase, WorkflowRoute

_PREPARE_NODE: Final = "prepare"
_FINISH_NODE: Final = "finish"
_REJECT_NODE: Final = "reject"


def prepare(state: APIOpsAgentState) -> dict[str, WorkflowPhase]:
    """Mark the workflow as prepared without changing routing or error state."""

    _ = state["phase"]
    return {"phase": WorkflowPhase.PREPARED}


def route_after_prepare(state: APIOpsAgentState) -> WorkflowRoute:
    """Select the next branch from the existing route without mutating state."""

    route = state["route"]
    if route is WorkflowRoute.READY:
        return WorkflowRoute.READY
    if route is WorkflowRoute.BLOCKED:
        return WorkflowRoute.BLOCKED
    raise ValueError(f"Unsupported workflow route: {route!r}")


def finish(state: APIOpsAgentState) -> dict[str, WorkflowPhase]:
    """Mark the successful terminal phase."""

    _ = state["phase"]
    return {"phase": WorkflowPhase.FINISHED}


def reject(state: APIOpsAgentState) -> dict[str, WorkflowPhase | str]:
    """Mark the blocked terminal phase and preserve or set a controlled error."""

    error = state["error"] or "workflow blocked"
    return {"phase": WorkflowPhase.REJECTED, "error": error}


def build_hello_graph():
    """Build and compile the minimal deterministic workflow graph."""

    builder = StateGraph(APIOpsAgentState)
    builder.add_node(_PREPARE_NODE, prepare)
    builder.add_node(_FINISH_NODE, finish)
    builder.add_node(_REJECT_NODE, reject)
    builder.add_edge(START, _PREPARE_NODE)
    builder.add_conditional_edges(
        _PREPARE_NODE,
        route_after_prepare,
        {
            WorkflowRoute.READY: _FINISH_NODE,
            WorkflowRoute.BLOCKED: _REJECT_NODE,
        },
    )
    builder.add_edge(_FINISH_NODE, END)
    builder.add_edge(_REJECT_NODE, END)
    return builder.compile()


__all__ = [
    "build_hello_graph",
    "finish",
    "prepare",
    "reject",
    "route_after_prepare",
]
