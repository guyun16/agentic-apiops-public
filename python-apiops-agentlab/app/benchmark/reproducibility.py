"""Small fixed-subset replay comparison built on existing benchmark outputs."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from app.evaluator import EvaluationResult, MetricsCalculator

from .runner import BenchmarkRun, BenchmarkTaskStatus

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]

FIXED_SUBSET_ID = "stage21-fixed-dev-10-v1"
FIXED_SUBSET_TASK_IDS = (
    "bench_task_testcase_missing_required_api_id",
    "bench_task_testcase_boundary_inventory_limit",
    "bench_task_failure_assertion_mismatch",
    "bench_task_failure_transport_connect",
    "bench_task_tool_allowed_rag_read",
    "bench_task_tool_no_bypass",
    "bench_task_rag_multi_hit",
    "bench_task_rag_irrelevant_distractor",
    "bench_task_formal_e2e_generation_diagnosis_guarded",
    "bench_task_e2e_diagnosis_tool_guarded",
)


class _ComparisonModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        strict=True,
        frozen=True,
        validate_default=True,
    )

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class FixedSubsetRun(_ComparisonModel):
    evaluation_run_id: NonEmptyString = Field(alias="evaluationRunId")
    configuration_digest: NonEmptyString = Field(alias="configurationDigest")
    task_ids: tuple[NonEmptyString, ...] = Field(alias="taskIds", min_length=1)
    task_count: StrictInt = Field(alias="taskCount", ge=0)


class FixedSubsetTaskComparison(_ComparisonModel):
    benchmark_task_id: NonEmptyString = Field(alias="benchmarkTaskId")
    status_a: BenchmarkTaskStatus = Field(alias="statusA")
    status_b: BenchmarkTaskStatus = Field(alias="statusB")
    metric_schema_equal: StrictBool = Field(alias="metricSchemaEqual")
    evaluation_metrics_equal: StrictBool = Field(alias="evaluationMetricsEqual")
    comparable: StrictBool
    observed_difference: NonEmptyString | None = Field(
        default=None,
        alias="observedDifference",
    )


class FixedSubsetComparison(_ComparisonModel):
    subset_id: NonEmptyString = Field(alias="subsetId")
    task_ids: tuple[NonEmptyString, ...] = Field(alias="taskIds", min_length=1)
    category_counts: dict[str, StrictInt] = Field(alias="categoryCounts")
    run_a: FixedSubsetRun = Field(alias="runA")
    run_b: FixedSubsetRun = Field(alias="runB")
    config_digest_a: NonEmptyString = Field(alias="configDigestA")
    config_digest_b: NonEmptyString = Field(alias="configDigestB")
    config_digest_equal: StrictBool = Field(alias="configDigestEqual")
    task_ids_equal: StrictBool = Field(alias="taskIdsEqual")
    task_count_equal: StrictBool = Field(alias="taskCountEqual")
    metric_schema_equal: StrictBool = Field(alias="metricSchemaEqual")
    per_task_comparable: StrictBool = Field(alias="perTaskComparable")
    aggregate_comparable: StrictBool = Field(alias="aggregateComparable")
    deterministic_results_equal: StrictBool = Field(alias="deterministicResultsEqual")
    aggregate_equal: StrictBool = Field(alias="aggregateEqual")
    task_comparisons: tuple[FixedSubsetTaskComparison, ...] = Field(alias="taskComparisons")
    observed_differences: tuple[NonEmptyString, ...] = Field(alias="observedDifferences")


def _metric_projection(result: EvaluationResult | None) -> tuple[tuple[object, ...], ...] | None:
    if result is None:
        return None
    return tuple(
        (
            metric.metric.value,
            metric.status.value,
            metric.value,
            metric.unit,
            metric.reason,
            metric.details,
        )
        for metric in result.metrics
    )


def _aggregate_projection(run: BenchmarkRun) -> tuple[tuple[object, ...], ...]:
    results = tuple(
        result.evaluation_result for result in run.results if result.evaluation_result is not None
    )
    aggregate = MetricsCalculator().calculate(results)
    return tuple(
        (
            metric.metric.value,
            metric.total_count,
            metric.applicable_count,
            metric.value_count,
            metric.not_applicable_count,
            metric.unknown_count,
            metric.error_count,
            metric.unit,
            metric.mean,
            metric.rate,
        )
        for metric in aggregate.metrics
    )


def compare_fixed_subset_runs(
    run_a: BenchmarkRun,
    run_b: BenchmarkRun,
    *,
    subset_id: str,
    config_digest_a: str,
    config_digest_b: str,
) -> FixedSubsetComparison:
    """Compare result facts while intentionally ignoring per-run identities."""

    ids_a = tuple(run_a.selected_task_ids)
    ids_b = tuple(run_b.selected_task_ids)
    results_a = {result.benchmark_task_id: result for result in run_a.results}
    results_b = {result.benchmark_task_id: result for result in run_b.results}
    ids_equal = ids_a == ids_b
    task_count_equal = len(run_a.results) == len(run_b.results)
    task_ids = ids_a if ids_equal else tuple(dict.fromkeys((*ids_a, *ids_b)))
    comparisons: list[FixedSubsetTaskComparison] = []
    differences: list[str] = []
    all_schema_equal = ids_equal and task_count_equal
    all_comparable = ids_equal and task_count_equal
    all_metrics_equal = ids_equal and task_count_equal
    for task_id in task_ids:
        result_a = results_a.get(task_id)
        result_b = results_b.get(task_id)
        schema_a = (
            tuple(metric.metric.value for metric in result_a.evaluation_result.metrics)
            if result_a and result_a.evaluation_result
            else None
        )
        schema_b = (
            tuple(metric.metric.value for metric in result_b.evaluation_result.metrics)
            if result_b and result_b.evaluation_result
            else None
        )
        schema_equal = schema_a == schema_b and schema_a is not None
        metrics_equal = _metric_projection(
            result_a.evaluation_result if result_a else None
        ) == _metric_projection(result_b.evaluation_result if result_b else None)
        comparable = result_a is not None and result_b is not None and schema_equal
        difference: str | None = None
        if result_a is None or result_b is None:
            difference = "task is missing from one rerun"
        elif result_a.status is not result_b.status:
            difference = f"status differs: {result_a.status.value} vs {result_b.status.value}"
        elif not metrics_equal:
            difference = "identity-independent EvaluationResult metrics differ"
        if difference is not None:
            differences.append(f"{task_id}: {difference}")
        all_schema_equal = all_schema_equal and schema_equal
        all_comparable = all_comparable and comparable
        all_metrics_equal = all_metrics_equal and metrics_equal
        comparisons.append(
            FixedSubsetTaskComparison(
                benchmarkTaskId=task_id,
                statusA=result_a.status if result_a else BenchmarkTaskStatus.ABORTED,
                statusB=result_b.status if result_b else BenchmarkTaskStatus.ABORTED,
                metricSchemaEqual=schema_equal,
                evaluationMetricsEqual=metrics_equal,
                comparable=comparable,
                observedDifference=difference,
            )
        )

    aggregate_comparable = all_comparable and tuple(
        result.evaluation_result.evaluator_version
        for result in run_a.results
        if result.evaluation_result is not None
    ) == tuple(
        result.evaluation_result.evaluator_version
        for result in run_b.results
        if result.evaluation_result is not None
    )
    aggregate_equal = aggregate_comparable and _aggregate_projection(
        run_a
    ) == _aggregate_projection(run_b)
    if not aggregate_equal and aggregate_comparable:
        differences.append("aggregate MetricsCalculator projection differs")
    category_counts = Counter(result.task_type.value for result in run_a.results)
    return FixedSubsetComparison(
        subsetId=subset_id,
        taskIds=task_ids,
        categoryCounts=dict(category_counts),
        runA=FixedSubsetRun(
            evaluationRunId=run_a.evaluation_run_id,
            configurationDigest=config_digest_a,
            taskIds=ids_a,
            taskCount=len(run_a.results),
        ),
        runB=FixedSubsetRun(
            evaluationRunId=run_b.evaluation_run_id,
            configurationDigest=config_digest_b,
            taskIds=ids_b,
            taskCount=len(run_b.results),
        ),
        configDigestA=config_digest_a,
        configDigestB=config_digest_b,
        configDigestEqual=config_digest_a == config_digest_b,
        taskIdsEqual=ids_equal,
        taskCountEqual=task_count_equal,
        metricSchemaEqual=all_schema_equal,
        perTaskComparable=all_comparable,
        aggregateComparable=aggregate_comparable,
        deterministicResultsEqual=all_metrics_equal,
        aggregateEqual=aggregate_equal,
        taskComparisons=tuple(comparisons),
        observedDifferences=tuple(differences),
    )


def persist_fixed_subset_comparison(
    comparison: FixedSubsetComparison,
    path: str | Path,
) -> Path:
    destination = Path(path)
    encoded = (
        json.dumps(
            comparison.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if destination.is_file():
        if destination.read_text(encoding="utf-8") != encoded:
            raise FileExistsError(f"fixed subset comparison already exists: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(encoded, encoding="utf-8", newline="\n")
    return destination


__all__ = [
    "FIXED_SUBSET_ID",
    "FIXED_SUBSET_TASK_IDS",
    "FixedSubsetComparison",
    "FixedSubsetRun",
    "FixedSubsetTaskComparison",
    "compare_fixed_subset_runs",
    "persist_fixed_subset_comparison",
]
