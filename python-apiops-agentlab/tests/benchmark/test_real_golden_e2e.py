from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from app.benchmark import (
    BenchmarkExecutionOutcome,
    BenchmarkRunner,
    BenchmarkTaskStatus,
    CallableStage20WorkflowAdapter,
    JavaResourceReference,
    JsonBenchmarkResultStore,
    LiteralSetup,
    PythonFixtureReference,
    load_golden_tasks,
)
from app.evaluator import (
    EvaluationFacts,
    MetricName,
    MetricStatus,
    ObservedToolArguments,
    SafetyOutcome,
    StructuredFact,
    ValidityFacts,
)
from app.tracing import (
    EvidenceReference,
    JavaRunReferenceFact,
    RetrievalFact,
    RetrievalReference,
    ToolResultRecord,
    TraceEvent,
    TraceStatus,
    failure_detail,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
JAVA_PROJECT = REPOSITORY_ROOT / "java-apiops-platform"
_CORRELATION = re.compile(
    r"STAGE20_CROSS_PROCESS_CORRELATION "
    r"traceId=(?P<trace_id>\S+) "
    r"agentRunId=(?P<agent_run_id>\S+) "
    r"agentStepId=(?P<agent_step_id>\S+) "
    r"runId=(?P<run_id>\d+) "
    r"reportId=(?P<report_id>\S+) "
    r"toolCallId=(?P<tool_call_id>\S+) "
    r"toolName=(?P<tool_name>\S+) "
    r"status=(?P<tool_status>\S+) "
    r"ragQueryId=(?P<rag_query_id>\S+)"
)


def _metric(result: object, name: MetricName):
    return next(item for item in result.metrics if item.metric is name)  # type: ignore[attr-defined]


def _run_existing_diagnosis_cross_process_test() -> dict[str, str | int]:
    command = [
        str(JAVA_PROJECT / ("mvnw.cmd" if os.name == "nt" else "mvnw")),
        "-pl",
        "apiops-web",
        "-am",
        "-Dtest=Stage20DiagnosisToolAuditCrossProcessE2ETest",
        "-Dsurefire.failIfNoSpecifiedTests=false",
        "test",
    ]
    completed = subprocess.run(
        command,
        cwd=JAVA_PROJECT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0:
        pytest.fail(
            "existing Stage 20 real cross-process test failed; no fake fallback is allowed:\n"
            + output[-12_000:]
        )
    match = _CORRELATION.search(output)
    if match is None:
        pytest.fail("existing Stage 20 test returned no Java/Python correlation evidence")
    values: dict[str, str | int] = match.groupdict()
    values["run_id"] = int(values["run_id"])
    return values


def _run_existing_java_test(
    selector: str,
    *,
    environment: dict[str, str] | None = None,
    timeout: int = 240,
) -> str:
    """Invoke one existing Java test boundary; never fall back to fixture-only facts."""

    command = [
        str(JAVA_PROJECT / ("mvnw.cmd" if os.name == "nt" else "mvnw")),
        "-pl",
        "apiops-web",
        "-am",
        f"-Dtest={selector}",
        "-Dsurefire.failIfNoSpecifiedTests=false",
        "test",
    ]
    inherited = os.environ.copy()
    for key, value in (environment or {}).items():
        if value is None:
            inherited.pop(key, None)
        else:
            inherited[key] = value
    completed = subprocess.run(
        command,
        cwd=JAVA_PROJECT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env=inherited,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0:
        raise RuntimeError(
            f"existing Java Stage 20 test {selector} failed with exit code "
            f"{completed.returncode}:\n{output[-12_000:]}"
        )
    return output


def _json_marker(output: str, marker: str) -> dict[str, object]:
    match = re.search(rf"{re.escape(marker)} (?P<payload>\{{[^\r\n]+\}})", output)
    if match is None:
        raise RuntimeError(f"Java test output did not contain {marker}")
    payload = json.loads(match.group("payload"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Java marker {marker} did not contain a JSON object")
    return payload


def _required_payload_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"live Stage 20 payload is missing {key}")
    return value


def _payload_identity(payload: dict[str, object]) -> dict[str, object]:
    identity = payload.get("identity")
    return identity if isinstance(identity, dict) else payload


def _payload_tool_arguments(payload: dict[str, object]) -> dict[str, object]:
    arguments = payload.get("toolArguments")
    if not isinstance(arguments, dict):
        tool = payload.get("tool")
        arguments = tool.get("arguments") if isinstance(tool, dict) else None
    if not isinstance(arguments, dict):
        raise RuntimeError("live Stage 20 payload is missing observed tool arguments")
    return arguments


def _payload_evidence_ids(payload: dict[str, object]) -> tuple[str, ...]:
    evidence = payload.get("evidenceIds")
    if not isinstance(evidence, list):
        tool = payload.get("tool")
        evidence = tool.get("evidenceIds") if isinstance(tool, dict) else None
    if not isinstance(evidence, list):
        return ()
    return tuple(value for value in evidence if isinstance(value, str) and value)


def _live_tool_records(
    payload: dict[str, object],
    *,
    status: TraceStatus,
) -> tuple[ToolResultRecord, RetrievalFact | None]:
    identity = _payload_identity(payload)
    trace_id = _required_payload_text(identity, "traceId")
    agent_run_id = _required_payload_text(identity, "agentRunId")
    tool_call_id = (
        _required_payload_text(
            payload,
            "toolCallId",
        )
        if "toolCallId" in payload
        else _required_payload_text(identity, "toolCallId")
    )
    tool_name = payload.get("toolName")
    if not isinstance(tool_name, str):
        tool = payload.get("tool")
        tool_name = tool.get("name") if isinstance(tool, dict) else None
    if not isinstance(tool_name, str) or not tool_name:
        raise RuntimeError("live Stage 20 payload is missing tool name")
    failure = (
        failure_detail(
            "JAVA_AUTHORIZATION_DENIED",
            "Java Tool Gateway returned the live authorization decision",
            code="JAVA_AUTHORIZATION_DENIED",
        )
        if status is TraceStatus.DENIED
        else None
    )
    tool_record = ToolResultRecord(
        trace_id=trace_id,
        agent_run_id=agent_run_id,
        agent_step_id=(
            payload.get("agentStepId") if isinstance(payload.get("agentStepId"), str) else None
        ),
        sequence=1,
        project_id=(
            payload.get("projectId") if isinstance(payload.get("projectId"), int) else None
        ),
        event=TraceEvent.RESULT,
        status=status,
        tool_name=tool_name,
        java_tool_call_id=tool_call_id,
        result_summary="Java ToolResult identity and status from an existing live boundary",
        sanitized=True,
        truncated=False,
        failure=failure,
    )
    rag_query_id = payload.get("ragQueryId")
    if not isinstance(rag_query_id, str):
        tool = payload.get("tool")
        rag_query_id = tool.get("ragQueryId") if isinstance(tool, dict) else None
    if not isinstance(rag_query_id, str) or not rag_query_id:
        return tool_record, None
    identity_run_id = identity.get("runId")
    report_id = identity.get("reportId")
    run_id = identity_run_id if isinstance(identity_run_id, int) else None
    report_value = report_id if isinstance(report_id, str) else None
    evidence_references = tuple(
        EvidenceReference(source_type="JAVA_RAG", source_id=evidence_id)
        for evidence_id in _payload_evidence_ids(payload)
    )
    retrieval = RetrievalFact(
        trace_id=trace_id,
        agent_run_id=agent_run_id,
        agent_step_id=tool_record.agent_step_id,
        sequence=2,
        project_id=tool_record.project_id,
        event=TraceEvent.FACT,
        status=TraceStatus.SUCCESS,
        retrieval_kind="JAVA_RAG_TOOL_RESULT",
        reference=RetrievalReference(
            rag_query_id=rag_query_id,
            run_id=run_id,
            report_id=report_value,
            evidence_references=evidence_references,
        ),
        result_count=len(evidence_references),
    )
    return tool_record, retrieval


def _live_outcome_from_tool_payload(
    payload: dict[str, object],
    *,
    status: TraceStatus,
    safety_outcome: SafetyOutcome | None = None,
    authority_reference: str,
    structured_facts: tuple[StructuredFact, ...] = (),
) -> BenchmarkExecutionOutcome:
    identity = _payload_identity(payload)
    trace_id = _required_payload_text(identity, "traceId")
    agent_run_id = _required_payload_text(identity, "agentRunId")
    tool_record, retrieval = _live_tool_records(payload, status=status)
    tool_call_id = (
        _required_payload_text(
            payload,
            "toolCallId",
        )
        if "toolCallId" in payload
        else _required_payload_text(identity, "toolCallId")
    )
    arguments = _payload_tool_arguments(payload)
    evidence_ids = _payload_evidence_ids(payload)
    evidence_value = evidence_ids or None
    facts = EvaluationFacts(
        tool_arguments=(
            ObservedToolArguments(tool_name=tool_record.tool_name, arguments=arguments),
        ),
        evidence_ids=evidence_value,
        safety_outcome=safety_outcome,
        structured_facts=structured_facts,
    )
    records: list[object] = [tool_record]
    identity_run_id = identity.get("runId")
    report_id = identity.get("reportId")
    run_id = identity_run_id if isinstance(identity_run_id, int) else None
    report_value = report_id if isinstance(report_id, str) else None
    batch_id = identity.get("batchId")
    task_id = identity.get("taskId")
    if (
        isinstance(batch_id, str)
        and isinstance(task_id, int)
        and isinstance(run_id, int)
        and isinstance(report_value, str)
    ):
        live_records: list[object] = [
            JavaRunReferenceFact(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                sequence=index,
                project_id=(
                    payload.get("projectId") if isinstance(payload.get("projectId"), int) else None
                ),
                event=TraceEvent.FACT,
                status=TraceStatus.SUCCESS,
                reference_stage=stage,
                java_batch_id=batch_id,
                java_task_id=task_id,
                java_run_id=run_id,
                java_status=(
                    payload.get("runner", {}).get("terminalStatus")
                    if isinstance(payload.get("runner"), dict)
                    else None
                ),
            )
            for index, stage in enumerate(
                ("SUBMIT_ACCEPTED", "TERMINAL_OBSERVED", "REPORT_READ"),
                start=1,
            )
        ]
        live_records.append(tool_record.model_copy(update={"sequence": 4}))
        if retrieval is not None:
            live_records.append(retrieval.model_copy(update={"sequence": 5}))
        records = live_records
    return BenchmarkExecutionOutcome(
        trace_id=trace_id,
        agent_run_id=agent_run_id,
        facts=facts,
        trace_records=tuple(records),
        run_id=run_id,
        report_id=report_value,
        tool_call_ids=(tool_call_id,),
        rag_query_ids=(
            (retrieval.reference.rag_query_id,)
            if retrieval is not None and retrieval.reference.rag_query_id is not None
            else ()
        ),
        authority_references=(authority_reference,),
    )


async def _live_golden_outcome(
    task,
    setup,
    *,
    trace_id: str,
    agent_run_id: str,
) -> BenchmarkExecutionOutcome:
    """Route each checked-in Golden Task to an existing live Java/Python test path."""

    del setup, trace_id, agent_run_id
    task_id = task.benchmark_task_id
    if task_id == "bench_task_golden_testcase_happy":
        fixture = next(
            entry
            for entry in task.initial_state.entries
            if isinstance(entry, PythonFixtureReference) and entry.key == "candidateFixture"
        )
        fixture_path = (REPOSITORY_ROOT / fixture.ref).resolve()
        if not fixture_path.is_file():
            raise RuntimeError(f"Golden generation fixture is missing: {fixture.ref}")
        output = await asyncio.to_thread(
            _run_existing_java_test,
            "Stage21GenerationCrossProcessE2ETest",
            environment={"STAGE21_CANDIDATE_FIXTURE": str(fixture_path)},
        )
        payload = _json_marker(output, "STAGE21_GENERATION_CORRELATION")
        identity = _payload_identity(payload)
        return BenchmarkExecutionOutcome(
            trace_id=_required_payload_text(identity, "traceId"),
            agent_run_id=_required_payload_text(identity, "agentRunId"),
            facts=EvaluationFacts(
                validity=ValidityFacts(
                    valid_json=True,
                    schema_valid=True,
                    contract_accepted=True,
                ),
                structured_facts=(
                    StructuredFact(name="task_strategy", value="HAPPY_PATH"),
                    StructuredFact(name="java_runner_executable", value=False),
                ),
            ),
            authority_references=(
                "java://metadata/project-41/api-api-1",
                "python://stage16-generation-graph",
            ),
        )

    if task_id == "bench_task_golden_failure_diagnosis":
        output = await asyncio.to_thread(
            _run_existing_java_test,
            "Stage20DiagnosisToolAuditCrossProcessE2ETest",
            environment={
                "STAGE20_TOOL_QUERY": "duplicate key orders unique index",
                "STAGE20_TOOL_TOP_K": "2",
            },
        )
        payload = _json_marker(output, "STAGE21_DIAGNOSIS_CORRELATION")
        return _live_outcome_from_tool_payload(
            payload,
            status=TraceStatus.SUCCESS,
            authority_reference="java://stage20/diagnosis-tool-audit",
        )

    if task_id == "bench_task_golden_rag_evidence":
        output = await asyncio.to_thread(
            _run_existing_java_test,
            "Stage20DiagnosisToolAuditCrossProcessE2ETest",
            environment={
                "STAGE20_TOOL_QUERY": "orders create failure",
                "STAGE20_TOOL_TOP_K": "2",
            },
        )
        payload = _json_marker(output, "STAGE21_DIAGNOSIS_CORRELATION")
        return _live_outcome_from_tool_payload(
            payload,
            status=TraceStatus.SUCCESS,
            authority_reference="java://stage20/diagnosis-tool-audit/rag",
        )

    if task_id == "bench_task_golden_tool_safety":
        output = await asyncio.to_thread(
            _run_existing_java_test,
            "Stage20FailureCrossProcessE2ETest#realUnauthorizedProjectReturnsJavaForbiddenAndNoFallback",
            environment={
                "STAGE20_FAILURE_MODE": "PROJECT_403",
                "STAGE20_TOOL_QUERY": "project scope policy",
                "STAGE20_TOOL_TOP_K": "2",
            },
        )
        payload = _json_marker(output, "STAGE21_TOOL_SAFETY_CORRELATION")
        return _live_outcome_from_tool_payload(
            payload,
            status=TraceStatus.DENIED,
            safety_outcome=SafetyOutcome.JAVA_DENIED,
            authority_reference="java://stage20/tool-gateway/authorization-deny",
            structured_facts=(
                StructuredFact(name="agent_forbidden_intent", value=True),
                StructuredFact(name="java_defense_decision", value="DENY"),
            ),
        )

    if task_id == "bench_task_golden_e2e_apiops":
        output = await asyncio.to_thread(
            _run_existing_java_test,
            "Stage20FinalAcceptanceCrossProcessE2ETest",
            environment={
                "STAGE20_TOOL_QUERY": "orders create failure",
                "STAGE20_TOOL_TOP_K": "2",
            },
        )
        payload = _json_marker(output, "STAGE21_FINAL_CORRELATION")
        tool = payload.get("tool")
        tool_status = tool.get("status") if isinstance(tool, dict) else None
        if tool_status != "SUCCESS":
            raise RuntimeError("Stage 20 Final Acceptance did not return a successful ToolResult")
        return _live_outcome_from_tool_payload(
            payload,
            status=TraceStatus.SUCCESS,
            safety_outcome=SafetyOutcome.SAFE,
            authority_reference="java://stage20/final-acceptance",
            structured_facts=(
                StructuredFact(name="java_runner_status", value="SUCCESS"),
                StructuredFact(name="java_runner_executable", value=True),
            ),
        )

    raise RuntimeError(f"no live Stage 20 mapping exists for Golden Task {task_id}")


async def _deterministic_golden_outcome(
    task,
    setup,
    *,
    trace_id: str,
    agent_run_id: str,
) -> BenchmarkExecutionOutcome:
    """Exercise the standalone Golden batch envelope without Java-owned facts."""

    del task, setup
    return BenchmarkExecutionOutcome(trace_id=trace_id, agent_run_id=agent_run_id)


def _real_diagnosis_outcome(
    task,
    setup,
    *,
    trace_id: str,
    agent_run_id: str,
) -> BenchmarkExecutionOutcome:
    del setup, trace_id, agent_run_id
    project_id = next(
        entry.value
        for entry in task.initial_state.entries
        if isinstance(entry, LiteralSetup) and entry.key == "projectId"
    )
    report_ref = next(
        entry.ref
        for entry in task.initial_state.entries
        if isinstance(entry, JavaResourceReference) and entry.key == "testReport"
    )
    assert project_id == 41

    runtime = _run_existing_diagnosis_cross_process_test()
    _real_diagnosis_outcome.last_runtime = runtime  # type: ignore[attr-defined]
    run_id = runtime["run_id"]
    assert isinstance(run_id, int)
    assert report_ref == "java://test-report/project-41/stage21-initial/golden-failure"
    assert runtime["report_id"] == f"report:{run_id}"
    assert runtime["tool_status"] == "SUCCESS"

    tool_result = ToolResultRecord(
        trace_id=runtime["trace_id"],
        agent_run_id=runtime["agent_run_id"],
        agent_step_id=runtime["agent_step_id"],
        sequence=1,
        status=TraceStatus.SUCCESS,
        tool_name=runtime["tool_name"],
        java_tool_call_id=runtime["tool_call_id"],
        result_summary="Java ToolResult identity from the existing cross-process E2E",
        sanitized=True,
        truncated=False,
    )
    retrieval = RetrievalFact(
        trace_id=runtime["trace_id"],
        agent_run_id=runtime["agent_run_id"],
        agent_step_id=runtime["agent_step_id"],
        sequence=2,
        status=TraceStatus.SUCCESS,
        retrieval_kind="evidence",
        reference=RetrievalReference(rag_query_id=runtime["rag_query_id"]),
    )
    facts = EvaluationFacts(
        structured_facts=(
            StructuredFact(name="java_run_id", value=run_id),
            StructuredFact(name="java_report_id", value=runtime["report_id"]),
            StructuredFact(name="java_tool_call_id", value=runtime["tool_call_id"]),
            StructuredFact(name="java_rag_query_id", value=runtime["rag_query_id"]),
        )
    )
    return BenchmarkExecutionOutcome(
        trace_id=runtime["trace_id"],
        agent_run_id=runtime["agent_run_id"],
        facts=facts,
        trace_records=(tool_result, retrieval),
        run_id=run_id,
        report_id=runtime["report_id"],
        tool_call_ids=(runtime["tool_call_id"],),
        rag_query_ids=(runtime["rag_query_id"],),
    )


@pytest.mark.anyio
async def test_failure_diagnosis_golden_task_executes_real_stage20_and_stage19(
    tmp_path: Path,
) -> None:
    task = next(
        task
        for task in load_golden_tasks()
        if task.benchmark_task_id == "bench_task_golden_failure_diagnosis"
    )
    store = JsonBenchmarkResultStore(tmp_path / "results")
    run = await BenchmarkRunner(
        CallableStage20WorkflowAdapter(_real_diagnosis_outcome),
        result_store=store,
    ).run_dataset(
        golden_only=True,
        task_ids=(task.benchmark_task_id,),
        evaluation_run_id="evaluation_run:stage21-real",
    )
    assert run.selected_task_ids == (task.benchmark_task_id,)
    result = run.results[0]

    assert task.benchmark_task_id == "bench_task_golden_failure_diagnosis"
    assert result.status is BenchmarkTaskStatus.SUCCESS
    assert result.evaluation_id is not None
    assert result.evaluation_id.startswith("evaluation:")
    assert result.run_id is not None
    assert result.report_id == f"report:{result.run_id}"
    assert len(result.tool_call_ids) == 1
    assert len(result.rag_query_ids) == 1
    assert result.evaluation_result is not None
    assert result.evaluation_result.ground_truth_id == "gt_stage21_failure_diagnosis"
    assert result.evaluation_result.ground_truth_version == "v3"
    assert _metric(result.evaluation_result, MetricName.TOOL_EXACT_SET_MATCH).value == 1
    assert _metric(result.evaluation_result, MetricName.TOOL_PRECISION).value == 1
    assert _metric(result.evaluation_result, MetricName.TOOL_RECALL).value == 1
    assert (
        _metric(result.evaluation_result, MetricName.PARAMETER_ACCURACY).status
        is MetricStatus.UNKNOWN
    )
    assert _metric(result.evaluation_result, MetricName.EVIDENCE_HIT).value == 0
    assert (
        _metric(result.evaluation_result, MetricName.DIAGNOSIS_ACCURACY).status
        is MetricStatus.UNKNOWN
    )
    assert store.task_path(result.evaluation_run_id, result.benchmark_task_id).is_file()

    runtime = _real_diagnosis_outcome.last_runtime  # type: ignore[attr-defined]

    print(
        "STAGE21_REAL_GOLDEN_EVALUATION "
        + json.dumps(
            {
                "benchmarkTaskId": task.benchmark_task_id,
                "selectedTaskCount": len(run.selected_task_ids),
                "executedTaskCount": len(run.results),
                "evaluationRunId": run.evaluation_run_id,
                "groundTruthId": result.evaluation_result.ground_truth_id,
                "groundTruthVersion": result.evaluation_result.ground_truth_version,
                "agentRunId": result.agent_run_id,
                "agentStepId": runtime["agent_step_id"],
                "traceId": result.trace_id,
                "runId": result.run_id,
                "reportId": result.report_id,
                "toolCallId": result.tool_call_ids[0],
                "ragQueryId": result.rag_query_ids[0],
                "evaluationId": result.evaluation_id,
                "artifactWritten": store.task_path(
                    result.evaluation_run_id,
                    result.benchmark_task_id,
                ).is_file(),
                "metrics": {
                    name.value: {
                        "status": _metric(result.evaluation_result, name).status.value,
                        "value": _metric(result.evaluation_result, name).value,
                    }
                    for name in (
                        MetricName.TOOL_EXACT_SET_MATCH,
                        MetricName.PARAMETER_ACCURACY,
                        MetricName.EVIDENCE_HIT,
                        MetricName.DIAGNOSIS_ACCURACY,
                    )
                },
            },
            sort_keys=True,
        )
    )


@pytest.mark.anyio
async def test_all_five_golden_tasks_execute_one_deterministic_batch(
    tmp_path: Path,
) -> None:
    """Run the five Golden Tasks through one standalone deterministic batch.

    This Python test does not own the Java Spring/JWT lifecycle and therefore does
    not assert ``STAGE21_FINAL_CORRELATION``.  That marker remains covered by the
    Java-owned Stage20FinalAcceptanceCrossProcessE2ETest.
    """

    expected_ids = (
        "bench_task_golden_e2e_apiops",
        "bench_task_golden_failure_diagnosis",
        "bench_task_golden_rag_evidence",
        "bench_task_golden_testcase_happy",
        "bench_task_golden_tool_safety",
    )
    store = JsonBenchmarkResultStore(tmp_path / "deterministic-golden-results")
    run = await BenchmarkRunner(
        CallableStage20WorkflowAdapter(_deterministic_golden_outcome),
        result_store=store,
    ).run_dataset(
        golden_only=True,
        evaluation_run_id="evaluation_run:stage21-deterministic-golden-batch",
    )

    assert run.selected_task_ids == expected_ids
    assert len(run.results) == 5
    assert all(result.status is BenchmarkTaskStatus.SUCCESS for result in run.results)
    assert all(result.evaluation_result is not None for result in run.results)
    assert all(result.setup_status.value == "SUCCESS" for result in run.results)
    assert all(result.cleanup_status.value == "SUCCESS" for result in run.results)
    assert all(
        store.task_path(run.evaluation_run_id, task_id).is_file() for task_id in expected_ids
    )
    run_path = store.task_path(run.evaluation_run_id, "_baseline").parent / "run.json"
    assert run_path.is_file()

    by_id = {result.benchmark_task_id: result for result in run.results}
    assert all(result.run_id is None for result in by_id.values())
    assert all(result.report_id is None for result in by_id.values())
    assert all(result.tool_call_ids == () for result in by_id.values())
    assert all(result.rag_query_ids == () for result in by_id.values())

    print(
        "STAGE21_DETERMINISTIC_GOLDEN_BATCH "
        + json.dumps(
            {
                "selected": len(run.selected_task_ids),
                "executed": len(run.results),
                "executionMode": "DETERMINISTIC",
                "evaluationRunId": run.evaluation_run_id,
                "taskStatuses": {
                    result.benchmark_task_id: result.status.value for result in run.results
                },
                "identities": {
                    result.benchmark_task_id: {
                        "agentRunId": result.agent_run_id,
                        "traceId": result.trace_id,
                        "runId": result.run_id,
                        "reportId": result.report_id,
                        "toolCallIds": result.tool_call_ids,
                        "ragQueryIds": result.rag_query_ids,
                        "evaluationId": result.evaluation_id,
                    }
                    for result in run.results
                },
                "artifacts": [
                    str(store.task_path(run.evaluation_run_id, task_id)) for task_id in expected_ids
                ],
                "runArtifact": str(run_path),
            },
            sort_keys=True,
        )
    )
