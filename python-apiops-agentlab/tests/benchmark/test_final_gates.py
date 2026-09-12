from __future__ import annotations

from pathlib import Path

import pytest

from app.benchmark import (
    FIXED_SUBSET_ID,
    FIXED_SUBSET_TASK_IDS,
    BenchmarkExecutionOutcome,
    BenchmarkRunner,
    BenchmarkTaskStatus,
    CollateralDamageStatus,
    TaskSuccessStatus,
    TaskSuccessSummary,
    collateral_record_for_task_ids,
    compare_fixed_subset_runs,
    evaluate_state_diff,
    evaluate_task_success,
    load_dataset,
    persist_fixed_subset_comparison,
    summarize_collateral_damage,
)
from app.evaluator import (
    EvaluationFacts,
    EvaluationResult,
    MetricName,
    MetricResult,
    MetricsCalculator,
    MetricStatus,
)


def _task(dataset, task_id: str):
    return next(task for task in dataset.tasks if task.benchmark_task_id == task_id)


def _truth(dataset, task):
    return next(
        truth
        for truth in dataset.ground_truths
        if truth.ground_truth_id == task.ground_truth_ref.ground_truth_id
        and truth.version == task.ground_truth_ref.version
    )


def _evaluation(task, truth, values: dict[MetricName, int | float | None]) -> EvaluationResult:
    metrics = []
    for metric_name in task.evaluation_spec.selected_metrics:
        value = values.get(metric_name)
        if value is None:
            metrics.append(
                MetricResult.unavailable(
                    metric_name,
                    MetricStatus.UNKNOWN,
                    "controlled test omission",
                )
            )
        else:
            metrics.append(MetricResult.measured(metric_name, value))
    return EvaluationResult(
        evaluation_id=f"evaluation:{task.benchmark_task_id}",
        case_id=f"case:{task.benchmark_task_id}",
        trace_id=f"trace:{task.benchmark_task_id}",
        agent_run_id=f"agent:{task.benchmark_task_id}",
        ground_truth_id=truth.ground_truth_id,
        ground_truth_version=truth.version,
        evaluator_version="rule-evaluator-v1",
        metrics=tuple(metrics),
    )


def _all_one(task, truth) -> EvaluationResult:
    return _evaluation(
        task,
        truth,
        {metric: 1 for metric in task.evaluation_spec.selected_metrics},
    )


@pytest.mark.anyio
async def test_execution_success_does_not_imply_task_success() -> None:
    dataset = load_dataset()
    task = _task(dataset, "bench_task_tool_allowed_rag_read")
    truth = _truth(dataset, task)

    class EmptyAdapter:
        async def execute(self, task, setup, *, trace_id, agent_run_id):
            return BenchmarkExecutionOutcome(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                facts=EvaluationFacts(),
            )

    result = await BenchmarkRunner(EmptyAdapter()).run_task(
        task,
        truth,
        evaluation_run_id="evaluation_run:task-success-separation",
    )
    assert result.status is BenchmarkTaskStatus.SUCCESS
    assert result.task_success is not None
    assert result.task_success.status is not TaskSuccessStatus.PASS


def test_category_specific_task_success_rules() -> None:
    dataset = load_dataset()

    generation = _task(dataset, "bench_task_golden_testcase_happy")
    generation_truth = _truth(dataset, generation)
    assert (
        evaluate_task_success(
            generation,
            generation_truth,
            _all_one(generation, generation_truth),
        ).status
        is TaskSuccessStatus.PASS
    )

    failure = _task(dataset, "bench_task_golden_failure_diagnosis")
    failure_truth = _truth(dataset, failure)
    diagnosis_values = {
        MetricName.TOOL_PRECISION: 1,
        MetricName.TOOL_RECALL: 1,
        MetricName.TOOL_EXACT_SET_MATCH: 1,
        MetricName.PARAMETER_ACCURACY: None,
        MetricName.EVIDENCE_HIT: 1,
        MetricName.DIAGNOSIS_ACCURACY: None,
    }
    assert (
        evaluate_task_success(
            failure,
            failure_truth,
            _evaluation(failure, failure_truth, diagnosis_values),
        ).status
        is TaskSuccessStatus.UNKNOWN
    )

    tool = _task(dataset, "bench_task_tool_allowed_rag_read")
    tool_truth = _truth(dataset, tool)
    assert evaluate_task_success(tool, tool_truth, _all_one(tool, tool_truth)).status is (
        TaskSuccessStatus.PASS
    )

    rag = _task(dataset, "bench_task_golden_rag_evidence")
    rag_truth = _truth(dataset, rag)
    assert evaluate_task_success(rag, rag_truth, _all_one(rag, rag_truth)).status is (
        TaskSuccessStatus.PASS
    )

    e2e = _task(dataset, "bench_task_e2e_generation_runner_success")
    e2e_truth = _truth(dataset, e2e)
    assert evaluate_task_success(e2e, e2e_truth, _all_one(e2e, e2e_truth)).status is (
        TaskSuccessStatus.PASS
    )


def test_zero_hit_and_wrong_project_use_distinct_structured_conditions() -> None:
    dataset = load_dataset()
    zero_hit = _task(dataset, "bench_task_rag_zero_hit")
    zero_truth = _truth(dataset, zero_hit)
    zero_values = {metric: 1 for metric in zero_hit.evaluation_spec.selected_metrics}
    assert (
        evaluate_task_success(
            zero_hit,
            zero_truth,
            _evaluation(zero_hit, zero_truth, zero_values),
        ).status
        is TaskSuccessStatus.PASS
    )

    wrong_project = _task(dataset, "bench_task_rag_wrong_project")
    wrong_truth = _truth(dataset, wrong_project)
    wrong_values = {metric: 1 for metric in wrong_project.evaluation_spec.selected_metrics}
    assert (
        evaluate_task_success(
            wrong_project,
            wrong_truth,
            _evaluation(wrong_project, wrong_truth, wrong_values),
        ).status
        is TaskSuccessStatus.PASS
    )


def test_task_success_summary_preserves_denominators_and_absence() -> None:
    from app.benchmark import TaskSuccessResult

    values = (
        TaskSuccessResult.from_conditions(()),
        TaskSuccessResult.unknown("controlled unknown"),
    )
    summary = TaskSuccessSummary.from_results(values)
    assert summary.task_count == 2
    assert summary.task_success_applicable == 0
    assert summary.task_success_unknown == 1
    assert summary.task_success_not_applicable == 1
    assert summary.task_success_rate is None


def test_collateral_damage_state_diff_is_deterministic() -> None:
    safe = evaluate_state_diff(
        scenario_id="tool-gateway-safe",
        source="controlled fixture",
        task_id="bench_task_tool_no_bypass",
        pre_state={"gatewayDecision": "UNSET", "protectedDataReturned": False},
        post_state={"gatewayDecision": "DENY", "protectedDataReturned": False},
        allowed_changes=("gatewayDecision",),
    )
    assert safe.collateral_damage_result is CollateralDamageStatus.PASS
    assert [change.path for change in safe.actual_changes] == ["gatewayDecision"]
    assert safe.unexpected_changes == ()

    damaged = evaluate_state_diff(
        scenario_id="tool-gateway-damage",
        source="controlled fixture",
        task_id="bench_task_tool_no_bypass",
        pre_state={"gatewayDecision": "UNSET", "protectedDataReturned": False},
        post_state={"gatewayDecision": "DENY", "protectedDataReturned": True},
        allowed_changes=("gatewayDecision",),
    )
    assert damaged.collateral_damage_result is CollateralDamageStatus.DAMAGE_DETECTED
    assert [change.path for change in damaged.unexpected_changes] == ["protectedDataReturned"]

    summary = summarize_collateral_damage((safe,), task_count=3)
    assert summary.applicable_count == 1
    assert summary.no_damage_count == 1
    assert summary.damage_count == 0
    assert summary.not_applicable_count == 2
    assert summary.collateral_damage_rate == 0.0


@pytest.mark.anyio
async def test_fixed_subset_comparison_ignores_runtime_identity(tmp_path: Path) -> None:
    dataset = load_dataset()

    class EmptyAdapter:
        async def execute(self, task, setup, *, trace_id, agent_run_id):
            return BenchmarkExecutionOutcome(trace_id=trace_id, agent_run_id=agent_run_id)

    runner = BenchmarkRunner(EmptyAdapter())
    run_a = await runner.run_batch(
        dataset,
        task_ids=FIXED_SUBSET_TASK_IDS,
        evaluation_run_id="evaluation_run:fixed-subset-a",
    )
    run_b = await runner.run_batch(
        dataset,
        task_ids=FIXED_SUBSET_TASK_IDS,
        evaluation_run_id="evaluation_run:fixed-subset-b",
    )
    comparison = compare_fixed_subset_runs(
        run_a,
        run_b,
        subset_id=FIXED_SUBSET_ID,
        config_digest_a="same-config-digest",
        config_digest_b="same-config-digest",
    )
    assert run_a.evaluation_run_id != run_b.evaluation_run_id
    assert comparison.task_ids_equal is True
    assert comparison.task_count_equal is True
    assert comparison.metric_schema_equal is True
    assert comparison.per_task_comparable is True
    assert comparison.aggregate_comparable is True
    assert comparison.deterministic_results_equal is True
    assert comparison.aggregate_equal is True
    assert comparison.observed_differences == ()
    path = persist_fixed_subset_comparison(comparison, tmp_path / "fixed-subset-rerun.json")
    assert path.is_file()


@pytest.mark.anyio
async def test_held_out_selection_and_aggregate_are_split_scoped() -> None:
    dataset = load_dataset()

    class EmptyAdapter:
        async def execute(self, task, setup, *, trace_id, agent_run_id):
            return BenchmarkExecutionOutcome(trace_id=trace_id, agent_run_id=agent_run_id)

    run = await BenchmarkRunner(EmptyAdapter()).run_batch(
        dataset,
        split="held_out",
        evaluation_run_id="evaluation_run:stage21-held-out-selection",
    )

    assert run.split.value == "held_out"
    assert len(run.selected_task_ids) == 10
    assert len(run.results) == 10
    assert {result.task_type.value for result in run.results} == {
        "TESTCASE_GENERATION",
        "FAILURE_DIAGNOSIS",
        "TOOL_SAFETY",
        "RAG_EVIDENCE_RETRIEVAL",
        "E2E_APIOPS",
    }
    evaluated = tuple(
        result.evaluation_result for result in run.results if result.evaluation_result
    )
    assert MetricsCalculator().calculate(evaluated).case_count == 10

    collateral = collateral_record_for_task_ids(run.selected_task_ids)
    assert collateral.summary.task_count == 10
    assert collateral.summary.not_applicable_count == 10
