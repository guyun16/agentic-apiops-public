"""Deterministic tests for the minimal LangGraph hello graph."""

from __future__ import annotations

from typing import cast

import pytest

from app.workflows.hello_graph import build_hello_graph, prepare, route_after_prepare
from app.workflows.state import APIOpsAgentState, WorkflowPhase, WorkflowRoute


def make_state(route: object, *, error: str | None = None) -> APIOpsAgentState:
    return {
        "trace_id": "hello-graph-test",
        "phase": WorkflowPhase.INITIAL,
        "route": cast(WorkflowRoute | None, route),
        "error": error,
    }


def test_graph_compiles_and_invokes() -> None:
    graph = build_hello_graph()

    result = graph.invoke(make_state(WorkflowRoute.READY))

    assert result["phase"] is WorkflowPhase.FINISHED


def test_ready_path_reaches_finished_terminal_phase() -> None:
    result = build_hello_graph().invoke(make_state(WorkflowRoute.READY))

    assert result == {
        "trace_id": "hello-graph-test",
        "phase": WorkflowPhase.FINISHED,
        "route": WorkflowRoute.READY,
        "error": None,
    }


def test_blocked_path_reaches_rejected_terminal_phase() -> None:
    result = build_hello_graph().invoke(
        make_state(WorkflowRoute.BLOCKED, error="precondition rejected")
    )

    assert result == {
        "trace_id": "hello-graph-test",
        "phase": WorkflowPhase.REJECTED,
        "route": WorkflowRoute.BLOCKED,
        "error": "precondition rejected",
    }


def test_prepare_returns_only_its_partial_phase_update() -> None:
    state = make_state(WorkflowRoute.READY, error="preserved")

    update = prepare(state)

    assert update == {"phase": WorkflowPhase.PREPARED}


@pytest.mark.parametrize(
    ("route", "expected"),
    [
        (WorkflowRoute.READY, WorkflowRoute.READY),
        (WorkflowRoute.BLOCKED, WorkflowRoute.BLOCKED),
    ],
)
def test_router_selects_each_route_deterministically(
    route: WorkflowRoute, expected: WorkflowRoute
) -> None:
    state = make_state(route)
    before = state.copy()

    assert route_after_prepare(state) is expected
    assert route_after_prepare(state) is expected
    assert state == before


@pytest.mark.parametrize("route", [None, "UNKNOWN", 123])
def test_router_explicitly_rejects_invalid_routes(route: object) -> None:
    state = make_state(route)

    with pytest.raises(ValueError, match="Unsupported workflow route"):
        route_after_prepare(state)


def test_graph_does_not_fail_open_for_invalid_route() -> None:
    with pytest.raises(ValueError, match="Unsupported workflow route"):
        build_hello_graph().invoke(make_state("UNKNOWN"))
