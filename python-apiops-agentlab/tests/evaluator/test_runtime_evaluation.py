from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.evaluator import MetricStatus
from app.services.runtime_evaluation import RuntimeEvaluationStore
from app.tracing import (
    AgentRun,
    Latency,
    ModelCall,
    ModelIdentity,
    PayloadDigest,
    PromptIdentity,
    TraceEvent,
    TraceStatus,
)

T0 = datetime(2026, 8, 29, 1, 0, tzinfo=UTC)


def lifecycle_records(agent_run_id: str = "agent_run:test") -> tuple[AgentRun, AgentRun]:
    return (
        AgentRun(
            trace_id="trace:test",
            agent_run_id=agent_run_id,
            timestamp=T0,
            event=TraceEvent.START,
            status=TraceStatus.RUNNING,
        ),
        AgentRun(
            trace_id="trace:test",
            agent_run_id=agent_run_id,
            timestamp=T0 + timedelta(seconds=2),
            event=TraceEvent.TERMINAL,
            status=TraceStatus.SUCCESS,
        ),
    )


def test_runtime_store_keeps_missing_facts_explicit() -> None:
    store = RuntimeEvaluationStore()
    store.begin(
        agent_run_id="agent_run:test",
        trace_id="trace:test",
        execution_type="DIAGNOSIS",
        provider="DeepSeek",
        model="deepseek-chat",
        started_at=T0,
    )
    store.update(
        agent_run_id="agent_run:test",
        status="COMPLETED",
        trace_records=lifecycle_records(),
    )

    detail = store.get_detail("agent_run:test")
    assert detail is not None
    assert detail.metrics["executionSuccess"].value == 1.0
    assert detail.metrics["validJson"].status is MetricStatus.NOT_APPLICABLE
    assert detail.metrics["totalTokens"].status is MetricStatus.NOT_APPLICABLE
    assert detail.metrics["cost"].status is MetricStatus.NOT_APPLICABLE
    assert detail.tool_counts.not_applicable == 1
    assert detail.safety_status is MetricStatus.UNKNOWN
    assert store.summary().tool.not_applicable == 1


def test_runtime_store_does_not_turn_missing_usage_into_zero() -> None:
    store = RuntimeEvaluationStore()
    store.begin(
        agent_run_id="agent_run:usage",
        trace_id="trace:usage",
        execution_type="TESTCASE_GENERATION",
        provider="DeepSeek",
        model="deepseek-chat",
        validation_applicable=True,
        started_at=T0,
    )
    start, terminal = lifecycle_records("agent_run:usage")
    model_call = ModelCall(
        trace_id="trace:usage",
        agent_run_id="agent_run:usage",
        timestamp=T0 + timedelta(seconds=1),
        event=TraceEvent.TERMINAL,
        status=TraceStatus.SUCCESS,
        model_call_id="model_call:usage",
        model_identity=ModelIdentity(provider="DeepSeek", model="deepseek-chat"),
        prompt=PromptIdentity(name="testcase_generate", version="v1"),
        model_input=PayloadDigest.from_value("bounded prompt"),
        latency=Latency(duration_ms=12.5),
    )
    store.update(
        agent_run_id="agent_run:usage",
        status="COMPLETED",
        trace_records=(start, model_call, terminal),
    )

    detail = store.get_detail("agent_run:usage")
    assert detail is not None
    assert detail.metrics["modelLatencyMs"].value == 12.5
    assert detail.metrics["promptTokens"].status is MetricStatus.UNKNOWN
    assert detail.metrics["completionTokens"].status is MetricStatus.UNKNOWN
    assert detail.metrics["totalTokens"].status is MetricStatus.UNKNOWN
    assert detail.metrics["cost"].status is MetricStatus.UNKNOWN
