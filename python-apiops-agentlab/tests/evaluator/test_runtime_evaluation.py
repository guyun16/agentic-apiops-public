from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.evaluator import (
    EvaluationCase,
    EvaluationFacts,
    GroundTruth,
    JudgeConfiguration,
    JudgeDimension,
    JudgeResult,
    JudgeRubric,
    MetricName,
    MetricStatus,
    ValidityFacts,
)
from app.services.runtime_evaluation import RuntimeEvaluationStore, RuntimeValidationFacts
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


def test_runtime_store_reopens_sqlite_with_list_and_detail(tmp_path: Path) -> None:
    database_path = tmp_path / "agentlab-runtime.sqlite3"
    first = RuntimeEvaluationStore(database_path)
    first.begin(
        agent_run_id="agent_run:restart",
        trace_id="trace:restart",
        execution_type="TESTCASE_GENERATION",
        provider="DeepSeek",
        model="deepseek-chat",
        project_id=41,
        run_id=701,
        validation_applicable=True,
        started_at=T0,
    )
    first.update(
        agent_run_id="agent_run:restart",
        status="COMPLETED",
        trace_records=lifecycle_records("agent_run:restart"),
        validation=RuntimeValidationFacts(True, True, True),
        finished_at=T0 + timedelta(seconds=2),
    )
    first.close()

    second = RuntimeEvaluationStore(database_path)
    detail = second.get_detail("agent_run:restart")

    assert [item.agent_run_id for item in second.list_runs(project_id=41)] == ["agent_run:restart"]
    assert detail is not None
    assert detail.status == "COMPLETED"
    assert detail.metrics["validJson"].value == 1.0
    assert detail.metrics["wallClockLatencyMs"].value == 2000.0
    assert detail.evaluation_result is None
    assert detail.judge_results == ()
    second.close()


def test_agent_run_identity_keeps_only_latest_projection(tmp_path: Path) -> None:
    store = RuntimeEvaluationStore(tmp_path / "agentlab-runtime.sqlite3")
    store.begin(
        agent_run_id="agent_run:current",
        trace_id="trace:first",
        execution_type="DIAGNOSIS",
        provider="DeepSeek",
        model="first-model",
        started_at=T0,
    )
    store.begin(
        agent_run_id="agent_run:current",
        trace_id="trace:latest",
        execution_type="TESTCASE_GENERATION",
        provider="DeepSeek",
        model="latest-model",
        validation_applicable=True,
        started_at=T0 + timedelta(seconds=1),
    )

    detail = store.get_detail("agent_run:current")

    assert len(store.list_runs()) == 1
    assert detail is not None
    assert detail.trace_id == "trace:latest"
    assert detail.model == "latest-model"
    store.close()


def test_formal_stage19_result_and_existing_judge_result_survive_reopen(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "agentlab-runtime.sqlite3"
    store = RuntimeEvaluationStore(database_path)
    store.begin(
        agent_run_id="agent_run:formal",
        trace_id="trace:formal",
        execution_type="DIAGNOSIS",
        provider="DeepSeek",
        model="deepseek-chat",
        project_id=41,
        started_at=T0,
    )
    case = EvaluationCase(
        case_id="case:formal",
        trace_id="trace:formal",
        agent_run_id="agent_run:formal",
        ground_truth_id="gt:formal",
        ground_truth_version="v1",
        facts=EvaluationFacts(validity=ValidityFacts(valid_json=True)),
        applicable_metrics=(MetricName.VALID_JSON,),
    )
    truth = GroundTruth(ground_truth_id="gt:formal", version="v1")
    configuration = JudgeConfiguration(
        rubric=JudgeRubric(
            rubric_id="diagnosis-quality",
            version="v1",
            dimension=JudgeDimension.DIAGNOSIS_QUALITY,
            criteria=("Use the supplied reference.",),
        ),
        prompt=PromptIdentity(name="judge", version="v1"),
        model_identity=ModelIdentity(
            provider="judge-provider",
            model="judge-model",
            version="judge-v1",
        ),
    )
    judge = JudgeResult(
        judge_result_id="judge_result:formal",
        judge_case_id="judge_case:formal",
        trace_id=case.trace_id,
        agent_run_id=case.agent_run_id,
        dimension=JudgeDimension.DIAGNOSIS_QUALITY,
        score=0.8,
        reason="The supplied diagnosis is supported by the reference.",
        configuration=configuration,
    )

    result = store.evaluate_and_persist(
        case=case,
        ground_truth=truth,
        trace_records=(),
        judge_results=(judge,),
    )
    store.close()

    reopened = RuntimeEvaluationStore(database_path)
    detail = reopened.get_detail(case.agent_run_id)

    assert result.metrics[0].metric is MetricName.VALID_JSON
    assert result.metrics[0].value == 1
    assert all(metric.status is MetricStatus.NOT_APPLICABLE for metric in result.metrics[1:])
    assert detail is not None
    assert detail.evaluation_result == result
    assert detail.judge_results == (judge,)
    assert detail.judge_results[0].configuration.model_identity.version == "judge-v1"
    reopened.close()
