from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.benchmark.models import DatasetSplit, TaskType
from app.benchmark.outcome_v2 import (
    OutcomeAuthority,
    OutcomeMode,
    OutcomePolicy,
    OutcomePolicyError,
    OutcomePolicyTask,
    ToolRequirement,
    V2OutcomeStatus,
    load_outcome_policy,
    project_outcome_v2,
)
from app.benchmark.runner import (
    BenchmarkLifecycleStatus,
    BenchmarkRun,
    BenchmarkRunPolicy,
    BenchmarkTaskResult,
    BenchmarkTaskStatus,
    FormalEvidenceSnapshot,
    ToolResultObservation,
)
from app.benchmark.success import TaskSuccessResult, TaskSuccessStatus
from app.evaluator import (
    EvaluationResult,
    MetricName,
    MetricResult,
    MetricStatus,
    StructuredFact,
)

POLICY_PATH = Path(__file__).parent / "fixtures" / "stage21-outcome-policy-v2.json"


@pytest.mark.parametrize(
    ("authority", "metric_value", "expected"),
    [
        ("missing", 1, V2OutcomeStatus.UNKNOWN),
        ("missing", 0, V2OutcomeStatus.FAIL),
        ("schema", 1, V2OutcomeStatus.PASS),
        ("wrong_schema", 1, V2OutcomeStatus.FAIL),
        ("schema", 0, V2OutcomeStatus.FAIL),
        ("runner", 1, V2OutcomeStatus.PASS),
        ("wrong_runner", 1, V2OutcomeStatus.FAIL),
        ("untrusted_schema", 1, V2OutcomeStatus.UNKNOWN),
        ("missing_snapshot", 1, V2OutcomeStatus.UNKNOWN),
    ],
)
def test_guessed_business_code_cannot_close_authority_gap(authority, metric_value, expected):
    task_id = "arbitrary_business_code_generation"
    facts = {"expected_error_code": "ASSERTED_CODE"}
    if "schema" in authority:
        facts.update(
            {
                "metadata_authority": "JAVA_OPENAPI_BASELINE"
                if authority != "untrusted_schema"
                else "PYTHON_FIXTURE",
                "response_code_contract_authority": "JAVA_RESPONSE_SCHEMA",
                "response_code_contract_values": [
                    "OTHER_CODE" if authority == "wrong_schema" else "ASSERTED_CODE"
                ],
            }
        )
    if authority in {"runner", "wrong_runner", "missing_snapshot"}:
        facts.update(
            {
                "report_authority": "JAVA_TEST_REPORT",
                "response_snapshot_present": authority != "missing_snapshot",
                "java_runner_business_outcome": "OTHER_CODE"
                if authority == "wrong_runner"
                else "ASSERTED_CODE",
            }
        )
    result = _minimal_result(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (MetricResult.measured(MetricName.EXACT_MATCH, metric_value),),
    ).model_copy(
        update={
            "formal_evidence": FormalEvidenceSnapshot(
                normalizedEvaluationFacts={
                    "structured_facts": [
                        {"name": name, "value": value} for name, value in facts.items()
                    ]
                },
            )
        }
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (MetricName.EXACT_MATCH,),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
    )
    projected = project_outcome_v2(_single_task_run(result), policy).tasks[0]
    assert projected.v2_status is expected


def _minimal_result(
    task_id: str,
    task_type: TaskType,
    metrics: tuple[MetricResult, ...],
    *,
    tool_call_ids: tuple[str, ...] = (),
    tool_result_observations: tuple[ToolResultObservation, ...] = (),
    task_success: TaskSuccessResult | None = None,
) -> BenchmarkTaskResult:
    evaluation = EvaluationResult(
        evaluation_id="evaluation-1",
        case_id="case-1",
        trace_id="trace-1",
        agent_run_id="agent-1",
        ground_truth_id="gt-1",
        ground_truth_version="v1",
        evaluator_version="stage19-test",
        metrics=metrics,
    )
    return BenchmarkTaskResult(
        evaluationRunId="run-1",
        benchmarkTaskId=task_id,
        taskType=task_type,
        status=BenchmarkTaskStatus.SUCCESS,
        agentRunId="agent-1",
        traceId="trace-1",
        toolCallIds=tool_call_ids,
        toolResultObservations=tool_result_observations,
        caseId="case-1",
        evaluationResult=evaluation,
        taskSuccess=task_success,
        setupStatus=BenchmarkLifecycleStatus.SUCCESS,
        cleanupStatus=BenchmarkLifecycleStatus.SUCCESS,
        durationMs=1.0,
    )


def _single_task_policy(
    task_id: str,
    task_type: TaskType,
    metrics: tuple[MetricName, ...],
    *,
    authority: OutcomeAuthority = OutcomeAuthority.SUPPORTED_BY_EXISTING_FACTS,
    tool_name: str | None = None,
    requirement: str = "REQUIRED",
    scenario: str = "unit test",
    expected_metric_values: dict[MetricName, int] | None = None,
) -> OutcomePolicy:
    tools = ()
    if tool_name is not None:
        tools = (
            {
                "toolName": tool_name,
                "requirement": ToolRequirement(requirement),
                "reason": "unit test requirement",
            },
        )
    task = OutcomePolicyTask(
        benchmarkTaskId=task_id,
        taskType=task_type,
        split=DatasetSplit.DEV,
        scenario=scenario,
        outcomeAuthority=authority,
        outcomeMetrics=metrics,
        expectedMetricValues=expected_metric_values or {},
        outcomeMode=OutcomeMode.ALL,
        toolRequirements=tools,
    )
    return OutcomePolicy(
        policyVersion="stage21-outcome-v2-test",
        datasetId="dataset-test",
        datasetVersion="v1",
        taskSchemaVersion="0.2.0",
        tasks=(task,),
    )


def _single_task_run(result: BenchmarkTaskResult) -> BenchmarkRun:
    return BenchmarkRun(
        evaluationRunId="run-1",
        datasetId="dataset-test",
        datasetVersion="v1",
        taskSchemaVersion="0.2.0",
        selectedTaskIds=(result.benchmark_task_id,),
        results=(result,),
        startedAt=datetime.now(UTC),
        completedAt=datetime.now(UTC),
        policy=BenchmarkRunPolicy(),
    )


def test_partial_projection_contains_only_persisted_results() -> None:
    task_id = "bench_task_partial_projection_present"
    missing_task_id = "bench_task_partial_projection_missing"
    result = _minimal_result(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (MetricResult.measured(MetricName.CONTRACT_ACCEPTED, 1),),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (MetricName.CONTRACT_ACCEPTED,),
    )
    missing_task = OutcomePolicyTask(
        benchmarkTaskId=missing_task_id,
        taskType=TaskType.TESTCASE_GENERATION,
        split=DatasetSplit.DEV,
        scenario="not selected by the bounded live gate",
        outcomeAuthority=OutcomeAuthority.SUPPORTED_BY_EXISTING_FACTS,
        outcomeMetrics=(MetricName.CONTRACT_ACCEPTED,),
        outcomeMode=OutcomeMode.ALL,
    )
    partial_policy = policy.model_copy(update={"tasks": (*policy.tasks, missing_task)})

    projection = project_outcome_v2(
        _single_task_run(result),
        partial_policy,
        require_full_dataset=False,
    )

    assert [task.benchmark_task_id for task in projection.tasks] == [task_id]
    assert projection.v2_status_counts == {"PASS": 1}


def test_policy_sidecar_is_complete_and_dataset_aligned() -> None:
    policy = load_outcome_policy(POLICY_PATH)

    assert policy.policy_version == "stage21-outcome-v2-v2"
    assert len(policy.tasks) == 105
    assert len(policy.task_by_id) == 105
    assert (
        sum(
            requirement.requirement.value == "REQUIRED"
            for task in policy.tasks
            for requirement in task.tool_requirements
        )
        == 41
    )
    assert (
        sum(
            requirement.requirement.value == "OPTIONAL"
            for task in policy.tasks
            for requirement in task.tool_requirements
        )
        == 18
    )
    assert sum(bool(task.expected_metric_values) for task in policy.tasks) == 10


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("missing", "missing task policy"),
        ("duplicate", "duplicate benchmarkTaskId"),
        ("unknown", "unknown task policy"),
        ("dataset", "dataset mismatch"),
        ("metric", "unknown metric"),
    ),
)
def test_policy_loader_fails_closed(tmp_path: Path, mutation: str, message: str) -> None:
    raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if mutation == "missing":
        raw["tasks"].pop()
    elif mutation == "duplicate":
        raw["tasks"].append(raw["tasks"][0])
    elif mutation == "unknown":
        unknown = dict(raw["tasks"][0])
        unknown["benchmarkTaskId"] = "bench_task_unknown"
        raw["tasks"].append(unknown)
    elif mutation == "dataset":
        raw["datasetVersion"] = "not-the-dataset"
    else:
        raw["tasks"][0]["outcomeMetrics"] = ["not_a_metric"]

    candidate = tmp_path / "policy.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(OutcomePolicyError, match=message):
        load_outcome_policy(candidate)


def test_policy_rejects_polarity_override_for_semantic_score() -> None:
    with pytest.raises(ValueError, match="limited to schema/contract polarity metrics"):
        OutcomePolicyTask(
            benchmarkTaskId="bench_task_invalid_polarity_unit",
            taskType=TaskType.TESTCASE_GENERATION,
            split=DatasetSplit.DEV,
            scenario="invalid override",
            outcomeAuthority=OutcomeAuthority.SUPPORTED_BY_EXISTING_FACTS,
            outcomeMetrics=(MetricName.EXACT_MATCH,),
            expectedMetricValues={MetricName.EXACT_MATCH: 0},
            outcomeMode=OutcomeMode.ALL,
        )


def test_failure_diagnosis_outcome_does_not_require_evidence_hit() -> None:
    task_id = "bench_task_failure_diagnosis_unit"
    result = _minimal_result(
        task_id,
        TaskType.FAILURE_DIAGNOSIS,
        (
            MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 1),
            MetricResult.measured(MetricName.EVIDENCE_HIT, 0),
        ),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.FAILURE_DIAGNOSIS,
        (MetricName.DIAGNOSIS_ACCURACY,),
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.PASS
    assert projection.outcome_accuracy.value == 1.0


def test_diagnosis_correct_optional_rag_not_called_is_outcome_pass() -> None:
    task_id = "bench_task_diagnosis_optional_rag_unit"
    result = _minimal_result(
        task_id,
        TaskType.FAILURE_DIAGNOSIS,
        (MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 1),),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.FAILURE_DIAGNOSIS,
        (MetricName.DIAGNOSIS_ACCURACY,),
        tool_name="rag.search",
        requirement="OPTIONAL",
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.PASS
    assert projection.tasks[0].tool_requirements[0].invoked is False
    assert projection.optional_tool_invocation_count == 0


def test_diagnosis_correct_evidence_failure_is_diagnostic_only_when_not_required() -> None:
    task_id = "bench_task_diagnosis_non_evidence_unit"
    result = _minimal_result(
        task_id,
        TaskType.FAILURE_DIAGNOSIS,
        (
            MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 1),
            MetricResult.measured(MetricName.EVIDENCE_HIT, 0),
        ),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.FAILURE_DIAGNOSIS,
        (MetricName.DIAGNOSIS_ACCURACY,),
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.PASS
    evidence = next(
        item
        for item in projection.tasks[0].diagnostic_metrics
        if item.metric is MetricName.EVIDENCE_HIT
    )
    assert evidence.value == 0


def test_diagnosis_explicit_evidence_without_retrieval_authority_cannot_pass() -> None:
    task_id = "bench_task_diagnosis_required_evidence_unit"
    result = _minimal_result(
        task_id,
        TaskType.FAILURE_DIAGNOSIS,
        (
            MetricResult.measured(MetricName.DIAGNOSIS_ACCURACY, 1),
            MetricResult.unavailable(
                MetricName.EVIDENCE_HIT,
                MetricStatus.UNKNOWN,
                "no retrieved evidence identity fact is available",
            ),
        ),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.FAILURE_DIAGNOSIS,
        (MetricName.DIAGNOSIS_ACCURACY, MetricName.EVIDENCE_HIT),
        tool_name="rag.search",
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.UNKNOWN
    assert projection.required_tool_miss_count == 1


def test_generation_valid_schema_but_wrong_semantics_is_fail() -> None:
    task_id = "bench_task_generation_semantic_mismatch_unit"
    result = _minimal_result(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (
            MetricResult.measured(MetricName.VALID_JSON, 1),
            MetricResult.measured(MetricName.SCHEMA_VALID, 1),
            MetricResult.measured(MetricName.CONTRACT_ACCEPTED, 1),
            MetricResult.measured(MetricName.EXACT_MATCH, 0),
        ),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (
            MetricName.VALID_JSON,
            MetricName.SCHEMA_VALID,
            MetricName.CONTRACT_ACCEPTED,
            MetricName.EXACT_MATCH,
        ),
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.FAIL


def test_generation_deterministic_facts_and_existing_judge_prove_pass() -> None:
    task_id = "bench_task_generation_deterministic_judge_unit"
    result = _minimal_result(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (
            MetricResult.measured(MetricName.VALID_JSON, 1),
            MetricResult.measured(MetricName.SCHEMA_VALID, 1),
            MetricResult.measured(MetricName.CONTRACT_ACCEPTED, 1),
            MetricResult.measured(MetricName.EXACT_MATCH, 1),
        ),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (
            MetricName.VALID_JSON,
            MetricName.SCHEMA_VALID,
            MetricName.CONTRACT_ACCEPTED,
            MetricName.EXACT_MATCH,
        ),
        scenario="deterministic validator plus existing Stage19 Judge",
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.PASS


def test_negative_generation_expected_invalid_and_actual_invalid_is_pass() -> None:
    task_id = "bench_task_generation_negative_polarity_unit"
    result = _minimal_result(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (
            MetricResult.measured(MetricName.VALID_JSON, 1),
            MetricResult.measured(MetricName.SCHEMA_VALID, 0),
            MetricResult.measured(MetricName.CONTRACT_ACCEPTED, 0),
            MetricResult.measured(MetricName.EXACT_MATCH, 1),
        ),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (
            MetricName.VALID_JSON,
            MetricName.SCHEMA_VALID,
            MetricName.CONTRACT_ACCEPTED,
            MetricName.EXACT_MATCH,
        ),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
        expected_metric_values={
            MetricName.SCHEMA_VALID: 0,
            MetricName.CONTRACT_ACCEPTED: 0,
        },
    )

    task = project_outcome_v2(_single_task_run(result), policy).tasks[0]

    assert task.v2_status is V2OutcomeStatus.PASS
    assert task.outcome_authority is OutcomeAuthority.SUPPORTED_BY_EXISTING_FACTS
    assert task.outcome_authority_gap is False
    assert (
        next(
            item for item in task.outcome_metrics if item.metric is MetricName.SCHEMA_VALID
        ).expected_value
        == 0
    )


def test_negative_generation_that_is_accepted_is_fail() -> None:
    task_id = "bench_task_generation_negative_accepted_unit"
    result = _minimal_result(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (
            MetricResult.measured(MetricName.VALID_JSON, 1),
            MetricResult.measured(MetricName.SCHEMA_VALID, 1),
            MetricResult.measured(MetricName.CONTRACT_ACCEPTED, 1),
            MetricResult.measured(MetricName.EXACT_MATCH, 0),
        ),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (
            MetricName.VALID_JSON,
            MetricName.SCHEMA_VALID,
            MetricName.CONTRACT_ACCEPTED,
            MetricName.EXACT_MATCH,
        ),
        expected_metric_values={
            MetricName.SCHEMA_VALID: 0,
            MetricName.CONTRACT_ACCEPTED: 0,
        },
    )

    assert (
        project_outcome_v2(_single_task_run(result), policy).tasks[0].v2_status
        is V2OutcomeStatus.FAIL
    )


def test_fractional_exact_match_is_decisive_fail_not_unknown() -> None:
    task_id = "bench_task_generation_partial_mismatch_unit"
    result = _minimal_result(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (MetricResult.measured(MetricName.EXACT_MATCH, 0.75),),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (MetricName.EXACT_MATCH,),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
    )

    task = project_outcome_v2(_single_task_run(result), policy).tasks[0]

    assert task.v2_status is V2OutcomeStatus.FAIL
    assert task.outcome_authority_gap is False


def test_authority_gap_preserves_decisive_outcome_failure() -> None:
    task_id = "bench_task_authority_gap_failure_unit"
    result = _minimal_result(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (MetricResult.measured(MetricName.CONTRACT_ACCEPTED, 0),),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (MetricName.CONTRACT_ACCEPTED,),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.FAIL
    assert projection.tasks[0].outcome_authority_gap is True


def test_observed_insufficient_evidence_result_closes_stale_authority_gap() -> None:
    task_id = "bench_task_failure_insufficient_missing"
    result = _minimal_result(
        task_id,
        TaskType.FAILURE_DIAGNOSIS,
        (MetricResult.measured(MetricName.EXACT_MATCH, 1),),
    ).model_copy(
        update={
            "formal_evidence": FormalEvidenceSnapshot(
                normalizedEvaluationFacts={
                    "structured_facts": [
                        {"name": "diagnosis_outcome", "value": "INSUFFICIENT_EVIDENCE"},
                        {"name": "sufficient_evidence", "value": False},
                        {"name": "rootCauseHypotheses", "value": []},
                    ]
                }
            )
        }
    )
    policy = _single_task_policy(
        task_id,
        TaskType.FAILURE_DIAGNOSIS,
        (MetricName.EXACT_MATCH,),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
        scenario="INSUFFICIENT_EVIDENCE",
    )

    task = project_outcome_v2(_single_task_run(result), policy).tasks[0]

    assert task.v2_status is V2OutcomeStatus.PASS
    assert task.outcome_authority is OutcomeAuthority.SUPPORTED_BY_EXISTING_FACTS
    assert task.outcome_authority_gap is False


def test_claimed_insufficient_evidence_without_explicit_sufficiency_fact_stays_unknown() -> None:
    task_id = "bench_task_failure_insufficient_unproven_unit"
    result = _minimal_result(
        task_id,
        TaskType.FAILURE_DIAGNOSIS,
        (MetricResult.measured(MetricName.EXACT_MATCH, 1),),
    ).model_copy(
        update={
            "formal_evidence": FormalEvidenceSnapshot(
                normalizedEvaluationFacts={
                    "structured_facts": [
                        {"name": "diagnosis_outcome", "value": "INSUFFICIENT_EVIDENCE"},
                    ]
                }
            )
        }
    )
    policy = _single_task_policy(
        task_id,
        TaskType.FAILURE_DIAGNOSIS,
        (MetricName.EXACT_MATCH,),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
        scenario="INSUFFICIENT_EVIDENCE",
    )

    task = project_outcome_v2(_single_task_run(result), policy).tasks[0]

    assert task.v2_status is V2OutcomeStatus.UNKNOWN
    assert task.outcome_authority_gap is True


def test_new_java_terminal_safety_facts_close_historical_authority_gap() -> None:
    task_id = "bench_task_live_allowed_tool_authority_unit"
    tool_result = ToolResultObservation(
        toolCallId="java-call-1",
        toolName="redis.read",
        status="SUCCESS",
        hasData=True,
        mappingStatus="NOT_APPLICABLE",
    )
    result = _minimal_result(
        task_id,
        TaskType.TOOL_SAFETY,
        (MetricResult.measured(MetricName.SAFETY_ACCURACY, 1),),
        tool_call_ids=("java-call-1",),
        tool_result_observations=(tool_result,),
    ).model_copy(
        update={
            "formal_evidence": FormalEvidenceSnapshot(
                terminalDecisionFacts=(
                    StructuredFact(name="safety_outcome", value="SAFE"),
                    StructuredFact(name="safety_terminal_decision", value="SAFE"),
                    StructuredFact(
                        name="safety_decision_authority",
                        value="JAVA_TOOL_GATEWAY",
                    ),
                ),
                toolResultMappings=(tool_result,),
            )
        }
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TOOL_SAFETY,
        (MetricName.SAFETY_ACCURACY,),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
        tool_name="redis.read",
    )

    projected = project_outcome_v2(_single_task_run(result), policy).tasks[0]

    assert projected.v2_status is V2OutcomeStatus.PASS
    assert projected.outcome_authority is OutcomeAuthority.SUPPORTED_BY_EXISTING_FACTS
    assert projected.outcome_authority_gap is False


def test_claimed_java_safety_authority_without_tool_result_stays_unknown() -> None:
    task_id = "bench_task_unproven_allowed_tool_authority_unit"
    result = _minimal_result(
        task_id,
        TaskType.TOOL_SAFETY,
        (MetricResult.measured(MetricName.SAFETY_ACCURACY, 1),),
    ).model_copy(
        update={
            "formal_evidence": FormalEvidenceSnapshot(
                terminalDecisionFacts=(
                    StructuredFact(name="safety_outcome", value="SAFE"),
                    StructuredFact(name="safety_terminal_decision", value="SAFE"),
                    StructuredFact(
                        name="safety_decision_authority",
                        value="JAVA_TOOL_GATEWAY",
                    ),
                )
            )
        }
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TOOL_SAFETY,
        (MetricName.SAFETY_ACCURACY,),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
        tool_name="redis.read",
    )

    projected = project_outcome_v2(_single_task_run(result), policy).tasks[0]

    assert projected.v2_status is V2OutcomeStatus.UNKNOWN
    assert projected.outcome_authority_gap is True


def test_java_runner_e2e_facts_close_historical_authority_gap() -> None:
    task_id = "bench_task_e2e_java_authority_unit"
    result = _minimal_result(
        task_id,
        TaskType.E2E_APIOPS,
        (MetricResult.measured(MetricName.EXACT_MATCH, 1),),
    ).model_copy(
        update={
            "formal_evidence": FormalEvidenceSnapshot(
                normalizedEvaluationFacts={
                    "structured_facts": [
                        {"name": "contract_accepted", "value": True},
                        {
                            "name": "metadata_authority",
                            "value": "JAVA_OPENAPI_BASELINE",
                        },
                        {"name": "report_authority", "value": "JAVA_TEST_REPORT"},
                        {"name": "java_runner_status", "value": "SUCCESS"},
                        {"name": "runner_status", "value": "SUCCESS"},
                        {"name": "response_snapshot_present", "value": True},
                    ]
                }
            )
        }
    )
    policy = _single_task_policy(
        task_id,
        TaskType.E2E_APIOPS,
        (MetricName.EXACT_MATCH,),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
    )

    projected = project_outcome_v2(_single_task_run(result), policy).tasks[0]

    assert projected.v2_status is V2OutcomeStatus.PASS
    assert projected.outcome_authority is OutcomeAuthority.SUPPORTED_BY_EXISTING_FACTS
    assert projected.outcome_authority_gap is False


def test_e2e_claim_without_java_report_authority_stays_unknown() -> None:
    task_id = "bench_task_e2e_unproven_authority_unit"
    result = _minimal_result(
        task_id,
        TaskType.E2E_APIOPS,
        (MetricResult.measured(MetricName.EXACT_MATCH, 1),),
    ).model_copy(
        update={
            "formal_evidence": FormalEvidenceSnapshot(
                normalizedEvaluationFacts={
                    "structured_facts": [
                        {"name": "contract_accepted", "value": True},
                        {
                            "name": "metadata_authority",
                            "value": "JAVA_OPENAPI_BASELINE",
                        },
                        {"name": "java_runner_status", "value": "SUCCESS"},
                        {"name": "runner_status", "value": "SUCCESS"},
                        {"name": "response_snapshot_present", "value": True},
                    ]
                }
            )
        }
    )
    policy = _single_task_policy(
        task_id,
        TaskType.E2E_APIOPS,
        (MetricName.EXACT_MATCH,),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
    )

    projected = project_outcome_v2(_single_task_run(result), policy).tasks[0]

    assert projected.v2_status is V2OutcomeStatus.UNKNOWN
    assert projected.outcome_authority_gap is True


@pytest.mark.parametrize("exact_value", [0, 1])
def test_guarded_e2e_uses_existing_exact_authority_closure(exact_value: int) -> None:
    task_id = "arbitrary_guarded_e2e_contract"
    result = _minimal_result(
        task_id,
        TaskType.E2E_APIOPS,
        (
            MetricResult.measured(MetricName.EXACT_MATCH, exact_value),
            MetricResult.measured(MetricName.SAFETY_ACCURACY, 1),
        ),
        tool_call_ids=("java-denied-call",),
        tool_result_observations=(
            ToolResultObservation(
                toolCallId="java-denied-call",
                toolName="rag.search",
                status="FORBIDDEN",
                hasData=False,
                errorCode="FORBIDDEN",
                mappingStatus="SKIPPED_NON_SUCCESS",
            ),
        ),
    ).model_copy(
        update={
            "formal_evidence": FormalEvidenceSnapshot(
                normalizedEvaluationFacts={
                    "structured_facts": [
                        {"name": "contract_accepted", "value": True},
                        {"name": "metadata_authority", "value": "JAVA_OPENAPI_BASELINE"},
                        {"name": "report_authority", "value": "JAVA_TEST_REPORT"},
                        {"name": "java_runner_status", "value": "SUCCESS"},
                        {"name": "runner_status", "value": "SUCCESS"},
                        {"name": "response_snapshot_present", "value": True},
                        {"name": "guarded_result", "value": exact_value == 1},
                        {"name": "java_defense_decision", "value": "DENY"},
                    ]
                },
            )
        }
    )
    policy = _single_task_policy(
        task_id,
        TaskType.E2E_APIOPS,
        (MetricName.EXACT_MATCH, MetricName.SAFETY_ACCURACY),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
        tool_name="rag.search",
    )

    projected = project_outcome_v2(_single_task_run(result), policy).tasks[0]

    assert projected.v2_status is (V2OutcomeStatus.PASS if exact_value else V2OutcomeStatus.FAIL)
    assert projected.outcome_authority_gap is False


@pytest.mark.parametrize(
    "broken",
    [
        None,
        "no_call",
        "mapping_failed",
        "nonempty",
        "unknown_leakage",
        "missing_count",
        "duplicate",
        "wrong_metric",
        "wrong_id",
        "no_data",
    ],
)
def test_java_zero_hit_facts_close_only_proven_authority_gap(broken: str | None) -> None:
    task_id = "bench_task_arbitrary_zero_hit_authority_unit"
    observation = ToolResultObservation(
        toolCallId="java-zero",
        toolName="rag.search",
        status="SUCCESS",
        hasData=True,
        resultCount=0,
        mappingStatus="SUCCESS",
    )
    facts = {
        "tool_status": "SUCCESS",
        "authorization_outcome": "AUTHORIZED",
        "result_count": 0,
        "evidence_leakage": False,
        "evidence_ids": [],
    }
    if broken == "unknown_leakage":
        facts.pop("evidence_leakage")
    elif broken == "missing_count":
        facts.pop("result_count")
    elif broken == "mapping_failed":
        observation = observation.model_copy(update={"mapping_status": "VALIDATION_FAILED"})
    elif broken == "nonempty":
        observation = observation.model_copy(update={"result_count": 1})
    elif broken == "no_data":
        observation = observation.model_copy(update={"has_data": False})
    observations = () if broken == "no_call" else (observation,)
    if broken == "duplicate":
        observations = (observation, observation.model_copy(update={"tool_call_id": "second"}))
    result = _minimal_result(
        task_id,
        TaskType.RAG_EVIDENCE_RETRIEVAL,
        (MetricResult.measured(MetricName.EXACT_MATCH, 0 if broken == "wrong_metric" else 1),),
        tool_call_ids=("wrong" if broken == "wrong_id" else "java-zero",),
        tool_result_observations=observations,
    ).model_copy(
        update={
            "formal_evidence": FormalEvidenceSnapshot(
                normalizedEvaluationFacts={
                    "structured_facts": [
                        {"name": name, "value": value} for name, value in facts.items()
                    ]
                },
            )
        }
    )
    policy = _single_task_policy(
        task_id,
        TaskType.RAG_EVIDENCE_RETRIEVAL,
        (MetricName.EXACT_MATCH,),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
    )
    projected = project_outcome_v2(_single_task_run(result), policy).tasks[0]
    expected = (
        V2OutcomeStatus.PASS
        if broken is None
        else V2OutcomeStatus.FAIL
        if broken == "wrong_metric"
        else V2OutcomeStatus.UNKNOWN
    )
    assert projected.v2_status is expected


def test_pure_rag_wrong_evidence_is_fail() -> None:
    task_id = "bench_task_rag_wrong_evidence_unit"
    observation = ToolResultObservation(
        toolCallId="rag-call-1",
        toolName="rag.search",
        status="SUCCESS",
        resultCount=1,
        mappingStatus="SUCCESS",
    )
    result = _minimal_result(
        task_id,
        TaskType.RAG_EVIDENCE_RETRIEVAL,
        (MetricResult.measured(MetricName.EVIDENCE_HIT, 0),),
        tool_result_observations=(observation,),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.RAG_EVIDENCE_RETRIEVAL,
        (MetricName.EVIDENCE_HIT,),
        tool_name="rag.search",
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.FAIL
    assert projection.tasks[0].tool_requirements[0].invoked is True


def test_pure_rag_without_retrieval_authority_is_unknown() -> None:
    task_id = "bench_task_rag_missing_authority_unit"
    result = _minimal_result(
        task_id,
        TaskType.RAG_EVIDENCE_RETRIEVAL,
        (
            MetricResult.unavailable(
                MetricName.EVIDENCE_HIT,
                MetricStatus.UNKNOWN,
                "retrieval authority unavailable",
            ),
        ),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.RAG_EVIDENCE_RETRIEVAL,
        (MetricName.EVIDENCE_HIT,),
        tool_name="rag.search",
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.UNKNOWN
    assert projection.required_tool_miss_count == 1


def test_safe_task_with_authoritative_no_side_effect_result_passes() -> None:
    task_id = "bench_task_safe_result_unit"
    result = _minimal_result(
        task_id,
        TaskType.TOOL_SAFETY,
        (MetricResult.measured(MetricName.SAFETY_ACCURACY, 1),),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TOOL_SAFETY,
        (MetricName.SAFETY_ACCURACY,),
        scenario="safe result only",
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.PASS


def test_explicit_java_deny_without_real_deny_authority_cannot_pass() -> None:
    task_id = "bench_task_java_deny_without_authority_unit"
    result = _minimal_result(
        task_id,
        TaskType.TOOL_SAFETY,
        (
            MetricResult.unavailable(
                MetricName.SAFETY_ACCURACY,
                MetricStatus.UNKNOWN,
                "Java DENY authority was not observed",
            ),
        ),
        tool_call_ids=("python-only-call-id",),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TOOL_SAFETY,
        (MetricName.SAFETY_ACCURACY,),
        tool_name="rag.search",
        scenario="explicit Java DENY",
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.UNKNOWN


def test_unsafe_side_effect_is_fail() -> None:
    task_id = "bench_task_unsafe_side_effect_unit"
    result = _minimal_result(
        task_id,
        TaskType.TOOL_SAFETY,
        (MetricResult.measured(MetricName.SAFETY_ACCURACY, 0),),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TOOL_SAFETY,
        (MetricName.SAFETY_ACCURACY,),
        scenario="destructive side effect",
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.FAIL


def test_e2e_business_pass_ignores_noncritical_tool_sequence() -> None:
    task_id = "bench_task_e2e_business_target_unit"
    result = _minimal_result(
        task_id,
        TaskType.E2E_APIOPS,
        (MetricResult.measured(MetricName.EXACT_MATCH, 1),),
        task_success=TaskSuccessResult(
            status=TaskSuccessStatus.PASS,
            passCount=1,
            failCount=0,
            unknownCount=0,
            notApplicableCount=0,
        ),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.E2E_APIOPS,
        (MetricName.EXACT_MATCH,),
        tool_name="rag.search",
        requirement="OPTIONAL",
        scenario="final business target",
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.PASS
    assert projection.tasks[0].v1_status is TaskSuccessStatus.PASS
    assert projection.optional_tool_invocation_count == 0


def test_authority_gap_projects_unknown_without_guessing() -> None:
    task_id = "bench_task_authority_gap_unit"
    result = _minimal_result(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (MetricResult.measured(MetricName.CONTRACT_ACCEPTED, 1),),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.TESTCASE_GENERATION,
        (MetricName.CONTRACT_ACCEPTED,),
        authority=OutcomeAuthority.OUTCOME_AUTHORITY_GAP,
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    assert projection.tasks[0].v2_status is V2OutcomeStatus.UNKNOWN
    assert projection.outcome_accuracy.denominator == 0
    assert projection.outcome_accuracy.unknown_count == 1


def test_single_required_tool_call_id_counts_as_invocation() -> None:
    task_id = "bench_task_required_tool_unit"
    result = _minimal_result(
        task_id,
        TaskType.RAG_EVIDENCE_RETRIEVAL,
        (MetricResult.measured(MetricName.EVIDENCE_HIT, 1),),
        tool_call_ids=("tool-call-1",),
    )
    policy = _single_task_policy(
        task_id,
        TaskType.RAG_EVIDENCE_RETRIEVAL,
        (MetricName.EVIDENCE_HIT,),
        tool_name="rag.search",
    )

    projection = project_outcome_v2(_single_task_run(result), policy)

    requirement = projection.tasks[0].tool_requirements[0]
    assert requirement.invoked is True
    assert requirement.observed_tool_call_ids == ("tool-call-1",)
    assert projection.required_tool_miss_count == 0
