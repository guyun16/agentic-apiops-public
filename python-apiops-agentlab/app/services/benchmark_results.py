"""Read-only views over persisted Benchmark result artifacts.

This service deliberately stops at the artifact boundary.  It reads the
existing ``BenchmarkRun``, task-result, baseline, and reproducibility JSON
files; it never invokes the runner, loads a dataset, resolves Ground Truth,
or evaluates a task.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from app.benchmark.baseline import (
    BaselineConfiguration,
    BaselineRunRecord,
    ConfigurationValue,
    ReproducibilityRecord,
)
from app.benchmark.models import TaskType
from app.benchmark.runner import (
    BenchmarkExecutionMode,
    BenchmarkFailureStage,
    BenchmarkRun,
    BenchmarkTaskResult,
    BenchmarkTaskStatus,
)
from app.benchmark.success import (
    TaskSuccessResult,
    TaskSuccessStatus,
    TaskSuccessSummary,
)
from app.evaluator import (
    AggregatedMetric,
    AggregatedMetrics,
    EvaluationResult,
    MetricName,
    MetricResult,
    MetricsCalculator,
)


class BenchmarkResultStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


ViewerMetricState = Literal["VALUE", "NOT_APPLICABLE", "UNKNOWN", "ERROR", "MISSING"]


class _ViewerModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        strict=True,
        frozen=True,
        validate_default=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class BenchmarkMetricView(_ViewerModel):
    """One aggregate metric with explicit absence semantics."""

    metric: MetricName
    state: ViewerMetricState
    value: StrictFloat | None = None
    mean: StrictFloat | None = None
    rate: StrictFloat | None = None
    unit: StrictStr | None = None
    reason: StrictStr | None = None
    total_count: StrictInt | None = Field(default=None, alias="totalCount")
    applicable_count: StrictInt | None = Field(default=None, alias="applicableCount")
    value_count: StrictInt | None = Field(default=None, alias="valueCount")
    not_applicable_count: StrictInt | None = Field(default=None, alias="notApplicableCount")
    unknown_count: StrictInt | None = Field(default=None, alias="unknownCount")
    error_count: StrictInt | None = Field(default=None, alias="errorCount")


class BenchmarkTaskSuccessView(_ViewerModel):
    """Task-success counts copied from the persisted summary or task facts."""

    status: TaskSuccessStatus | None = None
    rate: StrictFloat | None = None
    pass_count: StrictInt | None = Field(default=None, alias="passCount")
    fail_count: StrictInt | None = Field(default=None, alias="failCount")
    unknown_count: StrictInt | None = Field(default=None, alias="unknownCount")
    not_applicable_count: StrictInt | None = Field(
        default=None,
        alias="notApplicableCount",
    )


class BenchmarkArtifactReferences(_ViewerModel):
    run: StrictStr | None = None
    baseline_run: StrictStr | None = Field(default=None, alias="baselineRun")
    baseline_config: StrictStr | None = Field(default=None, alias="baselineConfig")
    reproducibility: StrictStr | None = None
    evaluation_csv: StrictStr | None = Field(default=None, alias="evaluationCsv")
    baseline_report: StrictStr | None = Field(default=None, alias="baselineReport")
    failure_inventory: StrictStr | None = Field(default=None, alias="failureInventory")
    collateral_damage: StrictStr | None = Field(default=None, alias="collateralDamage")
    task_results: tuple[StrictStr, ...] = Field(default=(), alias="taskResults")


class BenchmarkTaskResultView(_ViewerModel):
    evaluation_run_id: StrictStr = Field(alias="evaluationRunId")
    benchmark_task_id: StrictStr = Field(alias="benchmarkTaskId")
    case_id: StrictStr = Field(alias="caseId")
    task_type: TaskType = Field(alias="taskType")
    status: BenchmarkTaskStatus
    execution_mode: BenchmarkExecutionMode = Field(alias="executionMode")
    failure_stage: BenchmarkFailureStage | None = Field(
        default=None,
        alias="failureStage",
    )
    failure_category: StrictStr | None = Field(default=None, alias="failureCategory")
    failure_code: StrictStr | None = Field(default=None, alias="failureCode")
    failure_reason: StrictStr | None = Field(default=None, alias="failureReason")
    evaluation_id: StrictStr | None = Field(default=None, alias="evaluationId")
    agent_run_id: StrictStr = Field(alias="agentRunId")
    trace_id: StrictStr = Field(alias="traceId")
    run_id: StrictInt | None = Field(default=None, alias="runId")
    report_id: StrictStr | None = Field(default=None, alias="reportId")
    duration_ms: StrictFloat | None = Field(default=None, alias="durationMs")
    model_latency_ms: StrictFloat | None = Field(default=None, alias="modelLatencyMs")
    prompt_tokens: StrictInt | None = Field(default=None, alias="promptTokens")
    completion_tokens: StrictInt | None = Field(default=None, alias="completionTokens")
    total_tokens: StrictInt | None = Field(default=None, alias="totalTokens")
    task_success: TaskSuccessResult | None = Field(default=None, alias="taskSuccess")
    metrics: tuple[MetricResult, ...] = ()
    artifact_ref: StrictStr | None = Field(default=None, alias="artifactRef")


class BenchmarkResultSummary(_ViewerModel):
    display_name: StrictStr = Field(alias="displayName")
    role: Literal["BASELINE", "IMPROVED", "CURRENT", "HISTORY"]
    display_order: StrictInt = Field(alias="displayOrder")
    evaluation_run_id: StrictStr = Field(alias="evaluationRunId")
    dataset_id: StrictStr = Field(alias="datasetId")
    dataset_version: StrictStr = Field(alias="datasetVersion")
    dataset_split: StrictStr | None = Field(default=None, alias="datasetSplit")
    task_schema_version: StrictStr = Field(alias="taskSchemaVersion")
    status: BenchmarkResultStatus
    selected_task_count: StrictInt = Field(alias="selectedTaskCount")
    executed_task_count: StrictInt = Field(alias="executedTaskCount")
    evaluated_task_count: StrictInt = Field(alias="evaluatedTaskCount")
    completed_task_count: StrictInt = Field(alias="completedTaskCount")
    failed_task_count: StrictInt = Field(alias="failedTaskCount")
    started_at: datetime = Field(alias="startedAt")
    completed_at: datetime = Field(alias="completedAt")
    model: ConfigurationValue
    prompt: tuple[ConfigurationValue, ...]
    evaluator: ConfigurationValue
    benchmark_config_version: StrictStr | None = Field(
        default=None,
        alias="benchmarkConfigVersion",
    )
    data_source: Literal["ARTIFACT"] = Field(default="ARTIFACT", alias="dataSource")


class BenchmarkResultDetail(BenchmarkResultSummary):
    aggregate_metrics: tuple[BenchmarkMetricView, ...] = Field(alias="aggregateMetrics")
    task_success: BenchmarkTaskSuccessView = Field(alias="taskSuccess")
    artifact_references: BenchmarkArtifactReferences = Field(alias="artifactReferences")


@dataclass(frozen=True, slots=True)
class _StoredRun:
    path: Path
    scenario_root: Path
    run: BenchmarkRun
    tasks: tuple[BenchmarkTaskResult, ...]
    task_artifact_refs: Mapping[str, str]
    baseline: BaselineRunRecord | None
    baseline_raw: Mapping[str, Any]
    configuration: BaselineConfiguration | None
    configuration_raw: Mapping[str, Any]
    reproducibility: ReproducibilityRecord | None
    aggregate: AggregatedMetrics | None
    task_success: TaskSuccessSummary | None
    display_name: str
    role: Literal["BASELINE", "IMPROVED", "CURRENT", "HISTORY"]
    display_order: int


@dataclass(frozen=True, slots=True)
class _Publication:
    evaluation_run_id: str
    display_name: str
    role: Literal["BASELINE", "IMPROVED", "CURRENT", "HISTORY"]
    artifact_location: Path
    display_order: int


def _default_artifact_roots() -> tuple[Path, ...]:
    service_file = Path(__file__).resolve()
    python_root = service_file.parents[2]
    repository_root = service_file.parents[3]
    configured = os.getenv("APIOPS_BENCHMARK_ARTIFACT_ROOTS", "")
    if configured:
        roots = tuple(Path(value).expanduser() for value in configured.split(os.pathsep) if value)
    else:
        roots = (repository_root / "artifacts", python_root / "artifacts")
    return tuple(root for root in roots if root.is_dir())


def _read_json(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _read_model(path: Path, model_type: type[BaseModel]) -> BaseModel | None:
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None


def _scenario_root(run_path: Path) -> Path:
    """Return the scenario root used by baseline artifact relative references."""

    # Persisted baseline references are rooted at ``<scenario>/results/...``.
    # A bare JsonBenchmarkResultStore run has no baseline references and still
    # resolves safely relative to its result directory.
    parents = run_path.parents
    return parents[2] if len(parents) > 2 else run_path.parent


def _resolve_reference(reference: str, scenario_root: Path, run_path: Path) -> Path | None:
    scenario = scenario_root.resolve()
    candidates = (
        scenario_root / reference,
        run_path.parent / reference,
        scenario_root / "results" / reference,
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_relative_to(scenario) and resolved.is_file():
            return resolved
    return None


def _load_tasks(
    run: BenchmarkRun,
    run_path: Path,
    scenario_root: Path,
    baseline_raw: Mapping[str, Any],
) -> tuple[tuple[BenchmarkTaskResult, ...], dict[str, str]]:
    persisted: dict[str, BenchmarkTaskResult] = {}
    artifact_refs: dict[str, str] = {}
    references = baseline_raw.get("taskResultArtifacts")
    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, str):
                continue
            task_path = _resolve_reference(reference, scenario_root, run_path)
            if task_path is None:
                continue
            task = _read_model(task_path, BenchmarkTaskResult)
            if isinstance(task, BenchmarkTaskResult):
                persisted[task.benchmark_task_id] = task
                artifact_refs.setdefault(task.benchmark_task_id, reference)

    # The run envelope remains the ordering and membership authority.  A task
    # artifact, when present, supplies the same persisted task without
    # rerunning any workflow.
    return (
        tuple(persisted.get(result.benchmark_task_id, result) for result in run.results),
        artifact_refs,
    )


def _configuration_value(
    parsed: BaselineConfiguration | None,
    raw: Mapping[str, Any],
    field_name: str,
) -> ConfigurationValue:
    if parsed is not None:
        value = getattr(parsed, field_name, None)
        if isinstance(value, ConfigurationValue):
            return value
    raw_value = raw.get(_camel_case(field_name))
    if isinstance(raw_value, dict):
        try:
            value = ConfigurationValue.model_validate(raw_value)
        except (TypeError, ValueError):
            value = None
        if isinstance(value, ConfigurationValue):
            return value
    return ConfigurationValue.unknown(
        source="benchmark artifact lookup",
        reason=f"{_camel_case(field_name)} is unavailable in baseline-config.json",
    )


def _camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def _configuration_version(
    parsed: BaselineConfiguration | None,
    raw: Mapping[str, Any],
) -> str | None:
    if parsed is not None:
        return parsed.benchmark_config_version
    value = raw.get("benchmarkConfigVersion")
    return value if isinstance(value, str) and value else None


def _aggregate_from_artifacts(
    baseline_raw: Mapping[str, Any],
    tasks: Sequence[BenchmarkTaskResult],
) -> AggregatedMetrics | None:
    raw_metrics = baseline_raw.get("overallMetrics")
    if isinstance(raw_metrics, dict):
        try:
            return AggregatedMetrics.model_validate(raw_metrics)
        except (TypeError, ValueError):
            pass

    evaluations = tuple(
        result.evaluation_result for result in tasks if result.evaluation_result is not None
    )
    if not evaluations:
        return None
    try:
        # This is only a projection of already-persisted EvaluationResult
        # values.  It does not load Ground Truth or execute an evaluator.
        return MetricsCalculator().calculate(evaluations)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _task_success_from_artifacts(
    baseline_raw: Mapping[str, Any],
    tasks: Sequence[BenchmarkTaskResult],
) -> TaskSuccessSummary | None:
    raw_success = baseline_raw.get("taskSuccess")
    if isinstance(raw_success, dict):
        try:
            return TaskSuccessSummary.model_validate(raw_success)
        except (TypeError, ValueError):
            pass
    if any(result.task_success is not None for result in tasks):
        return TaskSuccessSummary.from_results(result.task_success for result in tasks)
    return None


def _relative_ref(path: Path | None, scenario_root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(scenario_root.resolve()).as_posix()
    except ValueError:
        return path.name


def is_complete_full105(run: BenchmarkRun) -> bool:
    """Execution completeness, independent of success scores or model quality."""
    selected = set(run.selected_task_ids)
    actual = [task.benchmark_task_id for task in run.results]
    return (
        not run.aborted
        and len(run.selected_task_ids) == len(selected) == 105
        and len(actual) == len(set(actual)) == 105
        and set(actual) == selected
        and all(task.evaluation_run_id == run.evaluation_run_id for task in run.results)
    )


class BenchmarkArtifactStore:
    """Project only explicitly published Benchmark artifacts without writes."""

    def __init__(
        self,
        roots: Sequence[Path] | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self.roots = tuple(roots) if roots is not None else _default_artifact_roots()
        repository_root = Path(__file__).resolve().parents[3]
        self.manifest_path = (
            manifest_path
            if manifest_path is not None
            else repository_root / "artifacts" / "benchmark" / "portfolio-manifest.json"
        )

    def _publications(self) -> tuple[_Publication, ...]:
        raw = _read_json(self.manifest_path)
        if raw is None or raw.get("schemaVersion") != "apiops-bench-publication/v1":
            return ()
        repository_root = Path(__file__).resolve().parents[3]
        publications: list[_Publication] = []
        allowed_roots: list[Path] = []
        for root in self.roots:
            try:
                allowed_roots.append(root.resolve())
            except OSError:
                continue
        entries = raw.get("publications")
        if not isinstance(entries, list):
            return ()
        counts = Counter(
            entry["evaluationRunId"]
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("evaluationRunId"), str)
        )
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            run_id = entry.get("evaluationRunId")
            display_name = entry.get("displayName")
            role = entry.get("role")
            location = entry.get("artifactLocation")
            order = entry.get("displayOrder")
            if (
                not isinstance(run_id, str)
                or not run_id.strip()
                or not isinstance(display_name, str)
                or not display_name.strip()
                or not isinstance(role, str)
                or role not in {"BASELINE", "IMPROVED", "CURRENT", "HISTORY"}
                or not isinstance(location, str)
                or not location.strip()
                or "\x00" in location
                or isinstance(order, bool)
                or not isinstance(order, int)
            ):
                continue
            path = Path(location)
            if not path.is_absolute():
                path = repository_root / path
            try:
                path = path.resolve()
            except (OSError, ValueError, RuntimeError):
                continue
            if not any(path.is_relative_to(root) for root in allowed_roots):
                continue
            publications.append(_Publication(run_id, display_name, role, path, order))
        return tuple(
            sorted(
                (item for item in publications if counts[item.evaluation_run_id] == 1),
                key=lambda item: item.display_order,
            )
        )

    def _load(self, evaluation_run_id: str | None = None) -> tuple[_StoredRun, ...]:
        candidates: list[_StoredRun] = []
        seen_run_ids: set[str] = set()
        for publication in self._publications():
            if evaluation_run_id is not None and publication.evaluation_run_id != evaluation_run_id:
                continue
            run_path = publication.artifact_location
            try:
                resolved_path = run_path.resolve()
            except OSError:
                continue
            if not resolved_path.is_file() or publication.evaluation_run_id in seen_run_ids:
                continue
            run = _read_model(resolved_path, BenchmarkRun)
            if (
                not isinstance(run, BenchmarkRun)
                or run.evaluation_run_id != publication.evaluation_run_id
                or not is_complete_full105(run)
            ):
                continue
            seen_run_ids.add(run.evaluation_run_id)
            scenario_root = _scenario_root(resolved_path)
            baseline_path = resolved_path.parent / "baseline-run.json"
            config_path = resolved_path.parent / "baseline-config.json"
            reproducibility_path = resolved_path.parent / "reproducibility.json"
            baseline_raw = _read_json(baseline_path) or {}
            config_raw = _read_json(config_path) or {}
            baseline = _read_model(baseline_path, BaselineRunRecord)
            configuration = _read_model(config_path, BaselineConfiguration)
            reproducibility = _read_model(reproducibility_path, ReproducibilityRecord)
            tasks, artifact_refs = _load_tasks(run, resolved_path, scenario_root, baseline_raw)
            candidates.append(
                _StoredRun(
                    path=resolved_path,
                    scenario_root=scenario_root,
                    run=run,
                    tasks=tasks,
                    task_artifact_refs=artifact_refs,
                    baseline=baseline if isinstance(baseline, BaselineRunRecord) else None,
                    baseline_raw=baseline_raw,
                    configuration=(
                        configuration if isinstance(configuration, BaselineConfiguration) else None
                    ),
                    configuration_raw=config_raw,
                    reproducibility=(
                        reproducibility
                        if isinstance(reproducibility, ReproducibilityRecord)
                        else None
                    ),
                    aggregate=_aggregate_from_artifacts(baseline_raw, tasks),
                    task_success=_task_success_from_artifacts(baseline_raw, tasks),
                    display_name=publication.display_name,
                    role=publication.role,
                    display_order=publication.display_order,
                )
            )
        return tuple(sorted(candidates, key=lambda item: item.display_order))

    def list(self) -> list[BenchmarkResultSummary]:
        return [self._summary(item) for item in self._load()]

    def get(self, evaluation_run_id: str) -> BenchmarkResultDetail | None:
        item = next(
            (
                candidate
                for candidate in self._load(evaluation_run_id)
                if candidate.run.evaluation_run_id == evaluation_run_id
            ),
            None,
        )
        return self._detail(item) if item is not None else None

    def tasks(self, evaluation_run_id: str) -> list[BenchmarkTaskResultView] | None:
        item = next(
            (
                candidate
                for candidate in self._load(evaluation_run_id)
                if candidate.run.evaluation_run_id == evaluation_run_id
            ),
            None,
        )
        if item is None:
            return None
        return [self._task_view(item, task) for task in item.tasks]

    def _summary(self, item: _StoredRun) -> BenchmarkResultSummary:
        run = item.run
        completed = sum(task.status is BenchmarkTaskStatus.SUCCESS for task in item.tasks)
        failed = len(item.tasks) - completed
        return BenchmarkResultSummary(
            displayName=item.display_name,
            role=item.role,
            displayOrder=item.display_order,
            evaluationRunId=run.evaluation_run_id,
            datasetId=run.dataset_id,
            datasetVersion=run.dataset_version,
            datasetSplit=_dataset_split(item),
            taskSchemaVersion=run.task_schema_version,
            status=(
                BenchmarkResultStatus.FAILED if run.aborted else BenchmarkResultStatus.COMPLETED
            ),
            selectedTaskCount=len(run.selected_task_ids),
            executedTaskCount=len(item.tasks),
            evaluatedTaskCount=sum(task.evaluation_result is not None for task in item.tasks),
            completedTaskCount=completed,
            failedTaskCount=failed,
            startedAt=run.started_at,
            completedAt=run.completed_at,
            model=_configuration_value(
                item.configuration,
                item.configuration_raw,
                "model_identity",
            ),
            prompt=_prompt_values(item),
            evaluator=_configuration_value(
                item.configuration,
                item.configuration_raw,
                "evaluator_identity",
            ),
            benchmarkConfigVersion=_configuration_version(
                item.configuration,
                item.configuration_raw,
            ),
        )

    def _detail(self, item: _StoredRun) -> BenchmarkResultDetail:
        assert item is not None
        summary = self._summary(item)
        return BenchmarkResultDetail(
            **summary.model_dump(),
            aggregateMetrics=_metric_views(item.aggregate),
            taskSuccess=_task_success_view(item.task_success),
            artifactReferences=_artifact_references(item),
        )

    def _task_view(self, item: _StoredRun, result: BenchmarkTaskResult) -> BenchmarkTaskResultView:
        evaluation: EvaluationResult | None = result.evaluation_result
        return BenchmarkTaskResultView(
            evaluationRunId=result.evaluation_run_id,
            benchmarkTaskId=result.benchmark_task_id,
            caseId=result.case_id,
            taskType=result.task_type,
            status=result.status,
            executionMode=result.execution_mode,
            failureStage=result.failure_stage,
            failureCategory=result.failure_category,
            failureCode=result.failure_code,
            failureReason=_failure_reason(result),
            evaluationId=result.evaluation_id,
            agentRunId=result.agent_run_id,
            traceId=result.trace_id,
            runId=result.run_id,
            reportId=result.report_id,
            durationMs=float(result.duration_ms),
            modelLatencyMs=(
                float(result.model_latency_ms) if result.model_latency_ms is not None else None
            ),
            promptTokens=result.prompt_tokens,
            completionTokens=result.completion_tokens,
            totalTokens=result.total_tokens,
            taskSuccess=result.task_success,
            metrics=evaluation.metrics if evaluation is not None else (),
            artifactRef=_task_artifact_ref(item, result.benchmark_task_id),
        )


def _dataset_split(item: _StoredRun) -> str | None:
    raw = item.baseline_raw.get("datasetSplit")
    if isinstance(raw, str):
        return raw
    return item.run.split.value if item.run.split is not None else None


def _prompt_values(item: _StoredRun) -> tuple[ConfigurationValue, ...]:
    if item.configuration is not None:
        return item.configuration.prompt_identities
    raw = item.configuration_raw.get("promptIdentities")
    if isinstance(raw, list):
        parsed: list[ConfigurationValue] = []
        for value in raw:
            if not isinstance(value, dict):
                continue
            try:
                parsed.append(ConfigurationValue.model_validate(value))
            except (TypeError, ValueError):
                continue
        if parsed:
            return tuple(parsed)
    return (
        ConfigurationValue.unknown(
            source="benchmark artifact lookup",
            reason="promptIdentities is unavailable in baseline-config.json",
        ),
    )


def _metric_state(metric: AggregatedMetric) -> ViewerMetricState:
    if metric.value_count > 0:
        return "VALUE"
    if metric.error_count > 0:
        return "ERROR"
    if metric.unknown_count > 0:
        return "UNKNOWN"
    if metric.not_applicable_count > 0:
        return "NOT_APPLICABLE"
    return "MISSING"


def _metric_view(metric: AggregatedMetric) -> BenchmarkMetricView:
    state = _metric_state(metric)
    value = metric.rate if metric.rate is not None else metric.mean
    reason = None
    if state == "NOT_APPLICABLE":
        reason = "persisted aggregate contains no applicable samples"
    elif state == "UNKNOWN":
        reason = "persisted aggregate contains unknown samples and no value"
    elif state == "ERROR":
        reason = "persisted aggregate contains evaluation errors and no value"
    return BenchmarkMetricView(
        metric=metric.metric,
        state=state,
        value=float(value) if value is not None else None,
        mean=float(metric.mean) if metric.mean is not None else None,
        rate=float(metric.rate) if metric.rate is not None else None,
        unit=metric.unit,
        reason=reason,
        totalCount=metric.total_count,
        applicableCount=metric.applicable_count,
        valueCount=metric.value_count,
        notApplicableCount=metric.not_applicable_count,
        unknownCount=metric.unknown_count,
        errorCount=metric.error_count,
    )


def _metric_views(aggregate: AggregatedMetrics | None) -> tuple[BenchmarkMetricView, ...]:
    by_name = {metric.metric: metric for metric in aggregate.metrics} if aggregate else {}
    views: list[BenchmarkMetricView] = []
    for metric_name in MetricName:
        metric = by_name.get(metric_name)
        if metric_name is MetricName.DIAGNOSIS_CONTRACT and metric is None:
            continue  # A new optional metric must not alter historical artifact views.
        if metric is None:
            views.append(
                BenchmarkMetricView(
                    metric=metric_name,
                    state="MISSING",
                    reason="metric is not present in the persisted aggregate artifact",
                )
            )
        else:
            views.append(_metric_view(metric))
    return tuple(views)


def _task_success_view(summary: TaskSuccessSummary | None) -> BenchmarkTaskSuccessView:
    if summary is None:
        return BenchmarkTaskSuccessView()
    return BenchmarkTaskSuccessView(
        rate=(float(summary.task_success_rate) if summary.task_success_rate is not None else None),
        passCount=summary.task_success_pass,
        failCount=summary.task_success_fail,
        unknownCount=summary.task_success_unknown,
        notApplicableCount=summary.task_success_not_applicable,
    )


def _failure_reason(result: BenchmarkTaskResult) -> str | None:
    if result.error_summary:
        return result.error_summary
    parts = [part for part in (result.failure_category, result.failure_code) if part]
    if parts:
        return " · ".join(parts)
    if result.task_success is not None:
        failed = tuple(
            condition.reason
            for condition in result.task_success.conditions
            if condition.status is TaskSuccessStatus.FAIL
        )
        if failed:
            return " · ".join(failed)
    return None


def _task_artifact_ref(item: _StoredRun, task_id: str) -> str | None:
    return item.task_artifact_refs.get(task_id)


def _artifact_references(item: _StoredRun) -> BenchmarkArtifactReferences:
    raw = item.baseline_raw
    repro_raw = _read_json(item.path.parent / "reproducibility.json") or {}
    task_results = raw.get("taskResultArtifacts")
    task_refs = (
        tuple(value for value in task_results if isinstance(value, str))
        if isinstance(task_results, list)
        else ()
    )
    return BenchmarkArtifactReferences(
        run=_string_or_relative(raw.get("runArtifact"), item.path, item.scenario_root),
        baselineRun=_relative_ref(item.path.parent / "baseline-run.json", item.scenario_root),
        baselineConfig=_relative_ref(item.path.parent / "baseline-config.json", item.scenario_root),
        reproducibility=_relative_ref(
            item.path.parent / "reproducibility.json",
            item.scenario_root,
        ),
        evaluationCsv=_string_or_relative(
            repro_raw.get("evaluationCsvArtifact"),
            item.path,
            item.scenario_root,
        ),
        baselineReport=_string_or_relative(
            repro_raw.get("baselineReportArtifact"),
            item.path,
            item.scenario_root,
        ),
        failureInventory=_string_or_relative(
            raw.get("failureInventoryArtifact"),
            item.path,
            item.scenario_root,
        ),
        collateralDamage=_string_or_relative(
            raw.get("collateralDamageArtifact"),
            item.path,
            item.scenario_root,
        ),
        taskResults=task_refs,
    )


def _string_or_relative(value: object, fallback: Path, scenario_root: Path) -> str | None:
    if isinstance(value, str) and value:
        return value
    return _relative_ref(fallback, scenario_root)


__all__ = [
    "BenchmarkArtifactReferences",
    "BenchmarkArtifactStore",
    "BenchmarkMetricView",
    "BenchmarkResultDetail",
    "BenchmarkResultStatus",
    "BenchmarkResultSummary",
    "BenchmarkTaskResultView",
    "BenchmarkTaskSuccessView",
]
