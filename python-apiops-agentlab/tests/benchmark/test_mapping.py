from __future__ import annotations

import pytest

from app.benchmark import (
    CURRENT_JAVA_REPORT,
    BenchmarkMappingError,
    GroundTruthIdentityMismatchError,
    GroundTruthNotFoundError,
    GroundTruthVersionMismatchError,
    expected_tool_arguments_for_task,
    load_golden_ground_truths,
    load_golden_tasks,
    project_current_java_report,
    resolve_ground_truth,
    to_evaluation_case,
    validate_task_ground_truth_alignment,
)
from app.evaluator import ExpectedToolArguments, ParameterMatchPolicy
from app.evaluator.normalization import compare_parameters


def _task(task_id: str):
    return next(task for task in load_golden_tasks() if task.benchmark_task_id == task_id)


def _truth(truth_id: str):
    return next(truth for truth in load_golden_ground_truths() if truth.ground_truth_id == truth_id)


def test_task_ground_truth_maps_to_existing_evaluation_case() -> None:
    task = _task("bench_task_golden_failure_diagnosis")
    truth = resolve_ground_truth(task, load_golden_ground_truths())
    case = to_evaluation_case(
        task,
        truth,
        case_id="case-stage21-failure-diagnosis",
        trace_id="trace-stage21-1",
        agent_run_id="agent-run-stage21-1",
    )

    assert case.case_id != task.benchmark_task_id
    assert case.agent_run_id != task.benchmark_task_id
    assert case.ground_truth_id == task.ground_truth_ref.ground_truth_id
    assert case.ground_truth_version == task.ground_truth_ref.version
    assert case.applicable_metrics == task.evaluation_spec.selected_metrics


def test_ground_truth_identity_and_version_mismatches_fail_closed() -> None:
    task = _task("bench_task_golden_failure_diagnosis")
    truth = _truth("gt_stage21_failure_diagnosis")

    with pytest.raises(GroundTruthIdentityMismatchError):
        validate_task_ground_truth_alignment(
            task,
            truth.model_copy(update={"ground_truth_id": "gt-other"}),
        )
    with pytest.raises(GroundTruthVersionMismatchError):
        resolve_ground_truth(
            task,
            (truth.model_copy(update={"version": "v1"}),),
        )
    with pytest.raises(GroundTruthNotFoundError):
        resolve_ground_truth(task, ())


def test_current_java_report_is_projected_only_at_evaluation_boundary() -> None:
    task = _task("bench_task_golden_failure_diagnosis")
    truth = _truth("gt_stage21_failure_diagnosis")

    projected = project_current_java_report(truth, report_id="report:9876")

    assert truth.expected_evidence_ids == (CURRENT_JAVA_REPORT, "rag:orders-unique-index")
    assert projected.expected_evidence_ids == ("report:9876", "rag:orders-unique-index")
    assert projected.expected_diagnosis == truth.expected_diagnosis
    assert projected.expected_tools == truth.expected_tools
    assert projected.ground_truth_id == task.ground_truth_ref.ground_truth_id
    assert all(fact.value != CURRENT_JAVA_REPORT for fact in projected.expected_facts)

    with pytest.raises(BenchmarkMappingError):
        project_current_java_report(truth, report_id="fixture:report-701")

    unresolved = project_current_java_report(truth, report_id=None)
    assert unresolved.expected_evidence_ids == truth.expected_evidence_ids
    with pytest.raises(BenchmarkMappingError):
        project_current_java_report(truth, report_id=" ")


def test_expected_tool_calls_use_stage19_exact_and_subset_semantics() -> None:
    exact_task = _task("bench_task_golden_tool_safety")
    subset_task = _task("bench_task_golden_rag_evidence")
    exact = expected_tool_arguments_for_task(exact_task)[0]
    subset = expected_tool_arguments_for_task(subset_task)[0]

    assert isinstance(exact, ExpectedToolArguments)
    assert exact.match_policy is ParameterMatchPolicy.EXACT
    assert subset.match_policy is ParameterMatchPolicy.SUBSET
    assert exact.arguments == {
        "query": "project scope policy",
        "topK": 2,
        "targetProjectId": 42,
    }
    assert compare_parameters(exact, {"query": "project scope policy", "topK": 2}).score < 1
    assert (
        compare_parameters(
            exact,
            {"query": "project scope policy", "topK": 2, "targetProjectId": 7},
        ).score
        < 1
    )
    assert compare_parameters(exact, exact.arguments).score == 1
    assert (
        compare_parameters(
            exact,
            {**exact.arguments, "unexpected": "not allowed by EXACT"},
        ).score
        < 1
    )
    assert (
        compare_parameters(
            subset,
            {**subset.arguments, "retrievalTrace": "java-authority"},
        ).score
        == 1
    )


def test_benchmark_task_id_is_not_implicitly_reused_as_runtime_identity() -> None:
    task = _task("bench_task_golden_testcase_happy")
    truth = resolve_ground_truth(task, load_golden_ground_truths())

    with pytest.raises(ValueError):
        to_evaluation_case(
            task,
            truth,
            case_id=task.benchmark_task_id,
            trace_id="trace-stage21-2",
            agent_run_id="agent-run-stage21-2",
        )
