from __future__ import annotations

import json

from app.benchmark import (
    BenchmarkExecutionMode,
    BenchmarkLifecycleStatus,
    BenchmarkTaskResult,
    BenchmarkTaskStatus,
    JsonBenchmarkResultStore,
    ToolResultObservation,
    project_tool_result_observations,
)
from app.benchmark.models import TaskType
from app.tracing import (
    EvidenceReference,
    RetrievalFact,
    RetrievalReference,
    ToolResultRecord,
    TraceEvent,
    TraceStatus,
    failure_detail,
)


def _tool_record(
    *,
    tool_name: str = "rag.search",
    status: str = "SUCCESS",
    trace_status: TraceStatus = TraceStatus.SUCCESS,
    tool_call_id: str = "java-tool-call-1",
    error_code: str | None = None,
    has_data: bool | None = True,
) -> ToolResultRecord:
    return ToolResultRecord(
        trace_id="trace-observe-1",
        agent_run_id="agent-observe-1",
        agent_step_id="agent-step-1",
        event=TraceEvent.RESULT,
        status=trace_status,
        failure=(
            failure_detail("JAVA_TOOL_FAILURE", "bounded failure", code=error_code or status)
            if trace_status is not TraceStatus.SUCCESS
            else None
        ),
        tool_name=tool_name,
        java_tool_call_id=tool_call_id,
        tool_result_status=status,
        java_error_code=error_code,
        has_data=has_data,
        result_summary="bounded result summary",
        sanitized=True,
        truncated=False,
    )


def _retrieval() -> RetrievalFact:
    return RetrievalFact(
        trace_id="trace-observe-1",
        agent_run_id="agent-observe-1",
        agent_step_id="agent-step-1",
        event=TraceEvent.FACT,
        status=TraceStatus.SUCCESS,
        retrieval_kind="JAVA_RAG_TOOL_RESULT",
        reference=RetrievalReference(
            rag_query_id="ragq-observe-1",
            evidence_references=(EvidenceReference(source_type="RUNBOOK", source_id="evidence-1"),),
        ),
        result_count=1,
    )


def test_non_success_java_result_is_projected_without_rag_identity() -> None:
    observations = project_tool_result_observations(
        (
            _tool_record(
                status="PARAM_INVALID",
                trace_status=TraceStatus.FAILED,
                error_code="PARAM_INVALID",
                has_data=False,
            ),
        )
    )

    assert observations == (
        ToolResultObservation(
            tool_call_id="java-tool-call-1",
            tool_name="rag.search",
            status="PARAM_INVALID",
            error_code="PARAM_INVALID",
            has_data=False,
            mapping_status="SKIPPED_NON_SUCCESS",
        ),
    )
    assert observations[0].rag_query_id is None


def test_successful_rag_result_projects_query_and_result_count() -> None:
    observations = project_tool_result_observations((_tool_record(), _retrieval()))

    assert observations[0].mapping_status == "SUCCESS"
    assert observations[0].rag_query_id == "ragq-observe-1"
    assert observations[0].result_count == 1


def test_successful_rag_result_without_retrieval_is_not_fabricated() -> None:
    observations = project_tool_result_observations(
        (_tool_record(),),
        mapping_status="VALIDATION_FAILED",
        mapping_error_code="RAG_RESULT_SCHEMA_INVALID",
    )

    assert observations[0].mapping_status == "VALIDATION_FAILED"
    assert observations[0].mapping_error_code == "RAG_RESULT_SCHEMA_INVALID"
    assert observations[0].rag_query_id is None
    assert observations[0].result_count is None


def test_non_rag_result_does_not_consume_retrieval_fact() -> None:
    observations = project_tool_result_observations(
        (_tool_record(tool_name="redis.read"), _retrieval())
    )

    assert observations[0].mapping_status == "NOT_APPLICABLE"
    assert observations[0].rag_query_id is None
    assert observations[0].result_count is None


def test_artifact_persists_only_minimal_tool_result_observation(tmp_path) -> None:
    observation = ToolResultObservation(
        tool_call_id="java-tool-call-safe",
        tool_name="rag.search",
        status="SUCCESS",
        has_data=True,
        rag_query_id="ragq-safe",
        result_count=2,
        mapping_status="SUCCESS",
    )
    result = BenchmarkTaskResult(
        evaluation_run_id="evaluation_run:observability",
        benchmark_task_id="bench_task_observability",
        task_type=TaskType.RAG_EVIDENCE_RETRIEVAL,
        status=BenchmarkTaskStatus.SUCCESS,
        execution_mode=BenchmarkExecutionMode.REAL_MODEL,
        agent_run_id="agent-run-observe",
        trace_id="trace-observe",
        case_id="case:observability",
        tool_result_observations=(observation,),
        setup_status=BenchmarkLifecycleStatus.SUCCESS,
        cleanup_status=BenchmarkLifecycleStatus.SUCCESS,
        duration_ms=1.0,
    )

    path = JsonBenchmarkResultStore(tmp_path / "results").persist_task(result)
    raw = json.loads(path.read_text(encoding="utf-8"))
    projected = raw["toolResultObservations"][0]

    assert projected["toolCallId"] == "java-tool-call-safe"
    assert projected["mappingStatus"] == "SUCCESS"
    assert "data" not in projected
    assert "secret" not in json.dumps(raw)
