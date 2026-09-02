"""Deterministic tests for bounded retries and in-memory checkpoints."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.workflows.runtime_control import (
    build_bounded_cycle_graph,
    checkpoint_config,
    retry,
    route_after_validation,
)
from app.workflows.state import APIOpsAgentState, WorkflowPhase, WorkflowRoute


def make_state(
    max_attempts: int,
    *,
    trace_id: str = "runtime-control-test",
    error: str | None = None,
) -> APIOpsAgentState:
    return {
        "trace_id": trace_id,
        "phase": WorkflowPhase.INITIAL,
        "route": None,
        "error": error,
        "attempt_count": 0,
        "max_attempts": max_attempts,
    }


def test_initial_validation_success_uses_zero_retries() -> None:
    graph = build_bounded_cycle_graph(failures_before_success=0)

    result = graph.invoke(make_state(max_attempts=2))

    assert result["phase"] is WorkflowPhase.FINISHED
    assert result["route"] is WorkflowRoute.READY
    assert result["attempt_count"] == 0


def test_one_retry_then_success_increments_count_once() -> None:
    graph = build_bounded_cycle_graph(failures_before_success=1)

    result = graph.invoke(make_state(max_attempts=2))

    assert result["phase"] is WorkflowPhase.FINISHED
    assert result["route"] is WorkflowRoute.READY
    assert result["attempt_count"] == 1


def test_always_invalid_exhausts_exactly_two_retries_and_fails_stably() -> None:
    graph = build_bounded_cycle_graph(failures_before_success=None)

    result = graph.invoke(make_state(max_attempts=2))

    assert result["phase"] is WorkflowPhase.REJECTED
    assert result["route"] is WorkflowRoute.BLOCKED
    assert result["attempt_count"] == 2
    assert result["error"] == "validation failed after retry budget"


def test_zero_budget_does_not_enter_retry() -> None:
    graph = build_bounded_cycle_graph(failures_before_success=None)

    result = graph.invoke(make_state(max_attempts=0))

    assert result["phase"] is WorkflowPhase.REJECTED
    assert result["attempt_count"] == 0


def test_retry_node_returns_only_completed_attempt_update() -> None:
    state = make_state(max_attempts=2)
    before = state.copy()

    update = retry(state)

    assert update == {"attempt_count": 1}
    assert state == before


@pytest.mark.parametrize(
    ("route", "attempt_count", "max_attempts", "expected"),
    [
        (WorkflowRoute.READY, 0, 2, "finish"),
        (WorkflowRoute.BLOCKED, 0, 2, "retry"),
        (WorkflowRoute.BLOCKED, 2, 2, "reject"),
    ],
)
def test_router_is_pure_and_applies_budget_rule(
    route: WorkflowRoute,
    attempt_count: int,
    max_attempts: int,
    expected: str,
) -> None:
    state = make_state(max_attempts=max_attempts)
    state["route"] = route
    state["attempt_count"] = attempt_count
    before = state.copy()

    assert route_after_validation(state) == expected
    assert state == before


@pytest.mark.parametrize("route", [None, "UNKNOWN", 123])
def test_router_rejects_invalid_route_without_fail_open(route: object) -> None:
    state = make_state(max_attempts=2)
    state["route"] = route  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Unsupported validation route"):
        route_after_validation(state)


def test_checkpoint_snapshot_contains_runtime_state_for_thread_identity() -> None:
    saver = InMemorySaver()
    graph = build_bounded_cycle_graph(
        failures_before_success=None,
        checkpointer=saver,
    )
    config = checkpoint_config("execution-a")

    result = graph.invoke(make_state(max_attempts=2), config=config)
    snapshot = graph.get_state(config)
    saved_checkpoints = list(saver.list(config))

    assert snapshot.values == result
    assert snapshot.values["attempt_count"] == 2
    assert snapshot.config["configurable"]["thread_id"] == "execution-a"
    assert saved_checkpoints


def test_same_thread_reads_existing_checkpoint_context() -> None:
    saver = InMemorySaver()
    graph = build_bounded_cycle_graph(
        failures_before_success=1,
        checkpointer=saver,
    )
    config = checkpoint_config("execution-resume")

    graph.invoke(make_state(max_attempts=2), config=config)
    resumed_context = graph.get_state(config)

    assert resumed_context.values["attempt_count"] == 1
    assert resumed_context.values["phase"] is WorkflowPhase.FINISHED
    assert resumed_context.config["configurable"]["thread_id"] == "execution-resume"


def test_different_thread_identities_do_not_share_runtime_state() -> None:
    saver = InMemorySaver()
    graph = build_bounded_cycle_graph(
        failures_before_success=None,
        checkpointer=saver,
    )
    config_a = checkpoint_config("execution-a")
    config_b = checkpoint_config("execution-b")

    graph.invoke(make_state(2, trace_id="trace-a"), config=config_a)
    graph.invoke(make_state(0, trace_id="trace-b"), config=config_b)

    state_a = graph.get_state(config_a).values
    state_b = graph.get_state(config_b).values

    assert state_a["trace_id"] == "trace-a"
    assert state_a["attempt_count"] == 2
    assert state_a["max_attempts"] == 2
    assert state_b["trace_id"] == "trace-b"
    assert state_b["attempt_count"] == 0
    assert state_b["max_attempts"] == 0


def test_fail_once_resume_continues_from_checkpoint_without_restarting_prefix() -> None:
    saver = InMemorySaver()
    events: list[str] = []
    fail_condition = {"enabled": True}

    def prefix(state: APIOpsAgentState) -> dict[str, WorkflowPhase]:
        events.append("prefix")
        _ = state["trace_id"]
        return {"phase": WorkflowPhase.PREPARED}

    def fail_once(state: APIOpsAgentState) -> dict[str, WorkflowRoute]:
        events.append("fail_once")
        _ = state["phase"]
        if fail_condition["enabled"]:
            raise RuntimeError("deterministic fail-once")
        return {"route": WorkflowRoute.READY}

    def terminal(state: APIOpsAgentState) -> dict[str, WorkflowPhase]:
        events.append("terminal")
        _ = state["route"]
        return {"phase": WorkflowPhase.FINISHED}

    builder = StateGraph(APIOpsAgentState)
    builder.add_node("prefix", prefix)
    builder.add_node("fail_once", fail_once)
    builder.add_node("terminal", terminal)
    builder.add_edge(START, "prefix")
    builder.add_edge("prefix", "fail_once")
    builder.add_edge("fail_once", "terminal")
    builder.add_edge("terminal", END)
    graph = builder.compile(checkpointer=saver)
    config = checkpoint_config("execution-fail-once")

    with pytest.raises(RuntimeError, match="deterministic fail-once"):
        graph.invoke(make_state(max_attempts=0, trace_id="resume-trace"), config=config)

    before_resume = graph.get_state(config)
    assert events == ["prefix", "fail_once"]
    assert before_resume.next == ("fail_once",)
    assert before_resume.values["phase"] is WorkflowPhase.PREPARED
    assert before_resume.values["trace_id"] == "resume-trace"
    assert before_resume.values["attempt_count"] == 0
    assert before_resume.config["configurable"]["thread_id"] == "execution-fail-once"

    fail_condition["enabled"] = False
    resumed = graph.invoke(None, config=config)
    after_resume = graph.get_state(config)

    assert resumed["phase"] is WorkflowPhase.FINISHED
    assert resumed["route"] is WorkflowRoute.READY
    assert resumed["trace_id"] == "resume-trace"
    assert resumed["attempt_count"] == 0
    assert events == ["prefix", "fail_once", "fail_once", "terminal"]
    assert after_resume.next == ()
    assert after_resume.config["configurable"]["thread_id"] == "execution-fail-once"
