"""Stage 21.5 baseline records over the existing benchmark and report boundaries.

This module deliberately stays on the outside of :mod:`app.benchmark.runner`:
the runner executes tasks and persists its existing ``BenchmarkRun`` envelope;
this module only snapshots configuration, projects existing evaluation facts
into a failure inventory, and renders a baseline view through Stage 19's
reporting functions.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from app.evaluator import (
    AggregatedMetrics,
    EvaluationResult,
    MetricResult,
    MetricsCalculator,
    MetricStatus,
)
from app.reports.reporting import (
    _FAILURE_SIGNAL_METRICS,
    ReportMetadata,
    export_evaluation_csv,
    render_evaluation_report,
)
from app.schemas.testcase_dsl import JsonValue

from .collateral import CollateralDamageRecord, collateral_record_for_task_ids
from .dataset import BenchmarkDataset, load_dataset
from .models import DatasetSplit, TaskType
from .runner import (
    BenchmarkFailureStage,
    BenchmarkRun,
    BenchmarkRunner,
    BenchmarkTaskResult,
    BenchmarkTaskStatus,
    JsonBenchmarkResultStore,
    preflight_artifact_paths,
    select_dataset_tasks,
)
from .success import TaskSuccessSummary

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]


class _BaselineModel(BaseModel):
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


class MetadataAvailability(StrEnum):
    """Whether a reproducibility value was observed by the caller."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class ConfigurationValue(_BaselineModel):
    """A value with an explicit absence state instead of an invented default."""

    value: JsonValue | None = None
    availability: MetadataAvailability
    source: NonEmptyString
    reason: NonEmptyString | None = None

    @model_validator(mode="after")
    def availability_and_value_must_agree(self) -> ConfigurationValue:
        has_value = self.value is not None
        if self.availability is MetadataAvailability.AVAILABLE and not has_value:
            raise ValueError("AVAILABLE configuration metadata requires value")
        if self.availability is not MetadataAvailability.AVAILABLE and has_value:
            raise ValueError("unavailable configuration metadata must not carry value")
        if self.availability is not MetadataAvailability.AVAILABLE and self.reason is None:
            raise ValueError("unavailable configuration metadata requires reason")
        return self

    @classmethod
    def available(cls, value: JsonValue, *, source: str) -> ConfigurationValue:
        return cls(value=value, availability=MetadataAvailability.AVAILABLE, source=source)

    @classmethod
    def unavailable(cls, *, source: str, reason: str) -> ConfigurationValue:
        return cls(
            availability=MetadataAvailability.UNAVAILABLE,
            source=source,
            reason=reason,
        )

    @classmethod
    def unknown(cls, *, source: str, reason: str) -> ConfigurationValue:
        return cls(
            availability=MetadataAvailability.UNKNOWN,
            source=source,
            reason=reason,
        )


class BaselineConfiguration(_BaselineModel):
    """Serializable configuration snapshot for one formal baseline run.

    ``evaluationRunId`` remains the runner's batch identity.  This snapshot
    does not introduce a second runtime ``benchmarkRunId``; serialized baseline
    records may call the same value ``benchmarkRunId`` for readability.
    """

    baseline_config_id: NonEmptyString = Field(alias="baselineConfigId")
    dataset_id: NonEmptyString = Field(alias="datasetId")
    dataset_version: NonEmptyString = Field(alias="datasetVersion")
    dataset_split: Literal["all", "dev", "held_out"] = Field(alias="datasetSplit")
    task_schema_version: NonEmptyString = Field(alias="taskSchemaVersion")
    model_identity: ConfigurationValue = Field(alias="modelIdentity")
    model_parameters: ConfigurationValue = Field(alias="modelParameters")
    prompt_identities: tuple[ConfigurationValue, ...] = Field(
        alias="promptIdentities",
        min_length=1,
    )
    workflow_identity: ConfigurationValue = Field(alias="workflowIdentity")
    tool_catalog_identity: ConfigurationValue = Field(alias="toolCatalogIdentity")
    evaluator_identity: ConfigurationValue = Field(alias="evaluatorIdentity")
    benchmark_config_version: NonEmptyString = Field(alias="benchmarkConfigVersion")
    application_identity: ConfigurationValue = Field(alias="applicationIdentity")
    java_runtime_version: ConfigurationValue = Field(alias="javaRuntimeVersion")
    python_runtime_version: ConfigurationValue = Field(alias="pythonRuntimeVersion")
    execution_timestamp: datetime = Field(alias="executionTimestamp")

    @field_validator("execution_timestamp")
    @classmethod
    def execution_timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("execution_timestamp must be timezone-aware")
        return value

    @property
    def configuration_digest(self) -> str:
        """Stable content digest excluding the per-run capture timestamp."""

        payload = dict(self.model_dump(mode="json"))
        payload.pop("executionTimestamp", None)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class FailureInventoryItem(_BaselineModel):
    """A failure projection linked back to existing task/evaluation artifacts."""

    benchmark_task_id: NonEmptyString = Field(alias="benchmarkTaskId")
    task_type: TaskType = Field(alias="taskType")
    task_status: BenchmarkTaskStatus = Field(alias="taskStatus")
    failure_stage: BenchmarkFailureStage | None = Field(default=None, alias="failureStage")
    failure_category: NonEmptyString | None = Field(default=None, alias="failureCategory")
    failure_code: NonEmptyString | None = Field(default=None, alias="failureCode")
    case_id: NonEmptyString = Field(alias="caseId")
    evaluation_id: NonEmptyString | None = Field(default=None, alias="evaluationId")
    evaluation_failure_metrics: tuple[MetricResult, ...] = Field(
        default=(),
        alias="evaluationFailureMetrics",
    )
    agent_run_id: NonEmptyString = Field(alias="agentRunId")
    trace_id: NonEmptyString = Field(alias="traceId")
    run_id: StrictInt | None = Field(default=None, alias="runId")
    report_id: NonEmptyString | None = Field(default=None, alias="reportId")
    tool_call_ids: tuple[NonEmptyString, ...] = Field(default=(), alias="toolCallIds")
    rag_query_ids: tuple[NonEmptyString, ...] = Field(default=(), alias="ragQueryIds")
    artifact_ref: NonEmptyString = Field(alias="artifactRef")

    @model_validator(mode="after")
    def failure_must_have_signal(self) -> FailureInventoryItem:
        if self.task_status is BenchmarkTaskStatus.SUCCESS:
            raise ValueError("failure inventory must contain only non-success task results")
        return self


class FailureInventory(_BaselineModel):
    """Failure facts from task envelopes and existing metric results."""

    benchmark_run_id: NonEmptyString = Field(alias="benchmarkRunId")
    failure_count: StrictInt = Field(alias="failureCount", ge=0)
    items: tuple[FailureInventoryItem, ...]

    @model_validator(mode="after")
    def count_must_match_items(self) -> FailureInventory:
        if self.failure_count != len(self.items):
            raise ValueError("failureCount must equal the number of inventory items")
        return self


class CategoryBaselineMetrics(_BaselineModel):
    category: TaskType
    task_count: StrictInt = Field(alias="taskCount", ge=0)
    evaluated_task_count: StrictInt = Field(alias="evaluatedTaskCount", ge=0)
    failure_task_count: StrictInt = Field(alias="failureTaskCount", ge=0)
    metrics: AggregatedMetrics
    task_success: TaskSuccessSummary = Field(alias="taskSuccess")


class BaselineRunRecord(_BaselineModel):
    """Formal baseline summary; metric values remain Stage 19 aggregates."""

    benchmark_run_id: NonEmptyString = Field(alias="benchmarkRunId")
    baseline_config_id: NonEmptyString = Field(alias="baselineConfigId")
    dataset_id: NonEmptyString = Field(alias="datasetId")
    dataset_version: NonEmptyString = Field(alias="datasetVersion")
    dataset_split: Literal["all", "dev", "held_out"] = Field(alias="datasetSplit")
    selected_task_count: StrictInt = Field(alias="selectedTaskCount", ge=0)
    executed_task_count: StrictInt = Field(alias="executedTaskCount", ge=0)
    evaluated_task_count: StrictInt = Field(alias="evaluatedTaskCount", ge=0)
    successful_task_count: StrictInt = Field(alias="successfulTaskCount", ge=0)
    failure_task_count: StrictInt = Field(alias="failureTaskCount", ge=0)
    overall_metrics: AggregatedMetrics = Field(alias="overallMetrics")
    category_metrics: tuple[CategoryBaselineMetrics, ...] = Field(alias="categoryMetrics")
    task_success: TaskSuccessSummary = Field(alias="taskSuccess")
    collateral_damage: CollateralDamageRecord = Field(alias="collateralDamage")
    task_result_artifacts: tuple[NonEmptyString, ...] = Field(
        alias="taskResultArtifacts",
        min_length=1,
    )
    run_artifact: NonEmptyString = Field(alias="runArtifact")
    failure_inventory_artifact: NonEmptyString = Field(alias="failureInventoryArtifact")
    reproducibility_artifact: NonEmptyString = Field(alias="reproducibilityArtifact")


class ReproducibilityRecord(_BaselineModel):
    """The complete run/config/artifact linkage needed for later replay."""

    benchmark_run_id: NonEmptyString = Field(alias="benchmarkRunId")
    baseline_config_id: NonEmptyString = Field(alias="baselineConfigId")
    configuration_digest: NonEmptyString = Field(alias="configurationDigest")
    configuration: BaselineConfiguration
    selected_task_count: StrictInt = Field(alias="selectedTaskCount", ge=0)
    executed_task_count: StrictInt = Field(alias="executedTaskCount", ge=0)
    task_result_artifacts: tuple[NonEmptyString, ...] = Field(
        alias="taskResultArtifacts",
        min_length=1,
    )
    run_artifact: NonEmptyString = Field(alias="runArtifact")
    baseline_run_artifact: NonEmptyString = Field(alias="baselineRunArtifact")
    failure_inventory_artifact: NonEmptyString = Field(alias="failureInventoryArtifact")
    evaluation_csv_artifact: NonEmptyString = Field(alias="evaluationCsvArtifact")
    baseline_report_artifact: NonEmptyString = Field(alias="baselineReportArtifact")
    collateral_damage_artifact: NonEmptyString = Field(alias="collateralDamageArtifact")


@dataclass(frozen=True, slots=True)
class BaselineArtifacts:
    """Filesystem locations written for one baseline run."""

    root: Path
    baseline_config: Path
    baseline_run: Path
    failure_inventory: Path
    reproducibility: Path
    evaluation_csv: Path
    baseline_report: Path
    collateral_damage: Path
    run: Path
    task_results: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class FormalBaselineResult:
    """In-memory result returned after execution and artifact persistence."""

    run: BenchmarkRun
    configuration: BaselineConfiguration
    overall_metrics: AggregatedMetrics
    category_metrics: tuple[CategoryBaselineMetrics, ...]
    task_success: TaskSuccessSummary
    collateral_damage: CollateralDamageRecord
    failure_inventory: FailureInventory
    baseline_record: BaselineRunRecord
    reproducibility: ReproducibilityRecord
    artifacts: BaselineArtifacts


def plan_baseline_artifact_paths(
    output_dir: str | Path,
    evaluation_run_id: str,
    task_ids: Iterable[str],
    *,
    result_store: JsonBenchmarkResultStore | None = None,
) -> list[tuple[str, Path]]:
    """Plan every artifact written by one provider-neutral baseline run."""

    destination = Path(output_dir).resolve()
    store = result_store or JsonBenchmarkResultStore(destination / "results")
    run_dir = store.task_path(evaluation_run_id, "_baseline").parent
    paths = [
        ("baseline:run", run_dir / "run.json"),
        ("baseline:baseline-config", run_dir / "baseline-config.json"),
        ("baseline:baseline-run", run_dir / "baseline-run.json"),
        ("baseline:failure-inventory", run_dir / "failure-inventory.json"),
        ("baseline:reproducibility", run_dir / "reproducibility.json"),
        ("baseline:evaluation-csv", run_dir / "evaluation_result.csv"),
        ("baseline:baseline-report", run_dir / "baseline-report.md"),
        ("baseline:collateral-damage", run_dir / "collateral-damage.json"),
    ]
    paths.extend(
        (
            f"baseline:task:{index:03d}:{task_id}",
            store.task_path(evaluation_run_id, task_id),
        )
        for index, task_id in enumerate(task_ids, start=1)
    )
    return paths


def capture_python_runtime() -> ConfigurationValue:
    """Capture only the Python runtime facts available in this process."""

    return ConfigurationValue.available(
        f"{platform.python_implementation()} {platform.python_version()}",
        source="platform.python_version",
    )


def capture_git_revision(repository_root: Path) -> ConfigurationValue:
    """Capture a read-only application revision without requiring git metadata."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ConfigurationValue.unavailable(
            source="git rev-parse HEAD",
            reason="git revision could not be read",
        )
    revision = completed.stdout.strip()
    if completed.returncode != 0 or not revision:
        return ConfigurationValue.unavailable(
            source="git rev-parse HEAD",
            reason="git revision is unavailable",
        )
    return ConfigurationValue.available(revision, source="git rev-parse HEAD")


def unavailable_java_runtime(
    *, reason: str = "Java runtime was not emitted by the current Python boundary"
) -> ConfigurationValue:
    """Make the absence of a Java runtime fact explicit rather than guessing it."""

    return ConfigurationValue.unavailable(source="Stage20 runtime context", reason=reason)


def _effective_split(split: DatasetSplit | str | None) -> Literal["all", "dev", "held_out"]:
    if split is None:
        return "all"
    effective = DatasetSplit(split) if isinstance(split, str) else split
    if effective is DatasetSplit.DEV:
        return "dev"
    if effective is DatasetSplit.HELD_OUT:
        return "held_out"
    raise ValueError("baseline split must be DEV, HELD_OUT, or omitted")


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_immutable_json(path: Path, value: object) -> None:
    text = _json_text(value)
    if path.is_file():
        if path.read_text(encoding="utf-8") != text:
            raise FileExistsError(
                f"baseline artifact already exists with different content: {path}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_immutable_text(path: Path, text: str) -> None:
    if not text.endswith("\n"):
        text += "\n"
    if path.is_file():
        if path.read_text(encoding="utf-8") != text:
            raise FileExistsError(
                f"baseline artifact already exists with different content: {path}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _export_immutable_csv(results: Sequence[EvaluationResult], path: Path) -> None:
    """Use the existing CSV exporter while preventing silent replacement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        export_evaluation_csv(results, path)
        return

    with tempfile.NamedTemporaryFile(
        mode="w+b",
        prefix=f"{path.stem}-",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as handle:
        candidate = Path(handle.name)
    try:
        export_evaluation_csv(results, candidate)
        if path.read_bytes() != candidate.read_bytes():
            raise FileExistsError(
                f"baseline artifact already exists with different content: {path}"
            )
    finally:
        candidate.unlink(missing_ok=True)


def _relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _failure_metrics(result: BenchmarkTaskResult) -> tuple[MetricResult, ...]:
    evaluation = result.evaluation_result
    if evaluation is None:
        return ()
    return tuple(
        sample
        for sample in evaluation.metrics
        if sample.status is MetricStatus.ERROR
        or (
            sample.metric in _FAILURE_SIGNAL_METRICS
            and sample.status is MetricStatus.VALUE
            and sample.value == 0
        )
    )


def _build_failure_inventory(
    run: BenchmarkRun,
    artifact_refs: Mapping[str, str],
) -> FailureInventory:
    items: list[FailureInventoryItem] = []
    for result in run.results:
        if result.status is BenchmarkTaskStatus.SUCCESS:
            continue
        metric_failures = _failure_metrics(result)
        items.append(
            FailureInventoryItem(
                benchmarkTaskId=result.benchmark_task_id,
                taskType=result.task_type,
                taskStatus=result.status,
                failureStage=result.failure_stage,
                failureCategory=result.failure_category,
                failureCode=result.failure_code,
                caseId=result.case_id,
                evaluationId=result.evaluation_id,
                evaluationFailureMetrics=metric_failures,
                agentRunId=result.agent_run_id,
                traceId=result.trace_id,
                runId=result.run_id,
                reportId=result.report_id,
                toolCallIds=result.tool_call_ids,
                ragQueryIds=result.rag_query_ids,
                artifactRef=artifact_refs[result.benchmark_task_id],
            )
        )
    return FailureInventory(
        benchmarkRunId=run.evaluation_run_id,
        failureCount=len(items),
        items=tuple(items),
    )


def _category_metrics(
    run: BenchmarkRun,
    failure_inventory: FailureInventory,
) -> tuple[CategoryBaselineMetrics, ...]:
    by_category: dict[TaskType, list[BenchmarkTaskResult]] = {category: [] for category in TaskType}
    for result in run.results:
        by_category[result.task_type].append(result)
    failed_ids = {item.benchmark_task_id for item in failure_inventory.items}
    categories: list[CategoryBaselineMetrics] = []
    for category in TaskType:
        task_results = by_category[category]
        evaluated = tuple(
            result.evaluation_result
            for result in task_results
            if result.evaluation_result is not None
        )
        categories.append(
            CategoryBaselineMetrics(
                category=category,
                taskCount=len(task_results),
                evaluatedTaskCount=len(evaluated),
                failureTaskCount=sum(
                    result.benchmark_task_id in failed_ids for result in task_results
                ),
                metrics=MetricsCalculator().calculate(evaluated),
                taskSuccess=TaskSuccessSummary.from_results(
                    result.task_success for result in task_results
                ),
            )
        )
    return tuple(categories)


def _metric_value(metric: object | None) -> str:
    if metric is None:
        return "MISSING"
    rate = getattr(metric, "rate", None)
    mean = getattr(metric, "mean", None)
    if rate is not None:
        return f"rate={rate:.6g}"
    if mean is not None:
        return f"mean={mean:.6g}"
    return (
        f"N/A={getattr(metric, 'not_applicable_count', 0)}, "
        f"UNKNOWN={getattr(metric, 'unknown_count', 0)}, "
        f"ERROR={getattr(metric, 'error_count', 0)}"
    )


def _md_value(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _configuration_value_text(value: ConfigurationValue) -> str:
    if value.availability is not MetadataAvailability.AVAILABLE:
        return value.availability.value
    return json.dumps(value.value, ensure_ascii=False, sort_keys=True)


def _render_baseline_report(
    run: BenchmarkRun,
    configuration: BaselineConfiguration,
    category_metrics: Sequence[CategoryBaselineMetrics],
    failure_inventory: FailureInventory,
    artifact_refs: Mapping[str, str],
    task_success: TaskSuccessSummary,
    collateral_damage: CollateralDamageRecord,
) -> str:
    source_revision = (
        configuration.application_identity.value
        if configuration.application_identity.availability is MetadataAvailability.AVAILABLE
        and isinstance(configuration.application_identity.value, str)
        else None
    )
    evaluation_results = tuple(
        result.evaluation_result for result in run.results if result.evaluation_result is not None
    )
    task_success_rate = _md_value(
        task_success.task_success_rate if task_success.task_success_rate is not None else "UNKNOWN"
    )
    collateral_rate = _md_value(
        collateral_damage.summary.collateral_damage_rate
        if collateral_damage.summary.collateral_damage_rate is not None
        else "UNKNOWN"
    )
    is_real_model = (
        configuration.model_identity.availability is MetadataAvailability.AVAILABLE
        and isinstance(configuration.model_identity.value, dict)
        and bool(configuration.model_identity.value.get("provider"))
    )
    report_title = "Real-Model Baseline" if is_real_model else "Formal Benchmark Baseline"
    metadata = ReportMetadata(
        report_id=f"baseline:{run.evaluation_run_id}",
        run_label=f"{report_title} {configuration.baseline_config_id}",
        generated_at=configuration.execution_timestamp,
        dataset_id=configuration.dataset_id,
        dataset_version=configuration.dataset_version,
        evaluation_config_version=configuration.benchmark_config_version,
        source_revision=source_revision,
    )
    delegated_report = render_evaluation_report(
        evaluation_results,
        metadata,
        limitations=(
            "This is a descriptive baseline over the selected task results.",
            "Unknown and not-applicable runtime metadata is retained; no zero is inferred "
            "for missing token or cost facts.",
            "Collateral damage is not inferred because no Stage 19 "
            "collateral-damage evaluator exists.",
        ),
    )
    lines = [
        f"# {report_title}",
        "",
        "This artifact records one baseline execution through the existing "
        "BenchmarkRunner and Stage 19 EvaluationResult/reporting boundaries.",
        "",
        "## Baseline identity",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Benchmark run (existing evaluationRunId) | {_md_value(run.evaluation_run_id)} |",
        f"| Baseline config | {_md_value(configuration.baseline_config_id)} |",
        f"| Configuration digest | {_md_value(configuration.configuration_digest)} |",
        f"| Model identity | "
        f"{_md_value(_configuration_value_text(configuration.model_identity))} |",
        f"| Model parameters | "
        f"{_md_value(_configuration_value_text(configuration.model_parameters))} |",
        f"| Prompt identities | "
        f"{_md_value(_configuration_value_text(configuration.prompt_identities[0]))} |",
        f"| Workflow identity | "
        f"{_md_value(_configuration_value_text(configuration.workflow_identity))} |",
        f"| Dataset | {_md_value(configuration.dataset_id)} @ "
        f"{_md_value(configuration.dataset_version)} |",
        f"| Split | {_md_value(configuration.dataset_split)} |",
        f"| Selected tasks | {len(run.selected_task_ids)} |",
        f"| Executed tasks | {len(run.results)} |",
        f"| Evaluated tasks | {len(evaluation_results)} |",
        f"| Task failures / evaluation failure signals | {failure_inventory.failure_count} |",
        f"| Execution status SUCCESS | "
        f"{sum(result.status is BenchmarkTaskStatus.SUCCESS for result in run.results)} |",
        f"| Task Success PASS / FAIL / UNKNOWN / N/A | {task_success.task_success_pass} / "
        f"{task_success.task_success_fail} / {task_success.task_success_unknown} / "
        f"{task_success.task_success_not_applicable} |",
        f"| Task Success Rate (PASS / applicable) | {task_success_rate} |",
        "",
        "## Category metrics",
        "",
        "The rows below are projections of ``MetricsCalculator`` results; they do not "
        "redefine a metric formula.",
        "",
        "| Category | Tasks | Evaluated | Failure tasks | Metric | Existing aggregate |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for category in category_metrics:
        if not category.metrics.metrics:
            lines.append(
                f"| {_md_value(category.category.value)} | {category.task_count} | "
                f"{category.evaluated_task_count} | {category.failure_task_count} | — | MISSING |"
            )
            continue
        for metric in category.metrics.metrics:
            lines.append(
                f"| {_md_value(category.category.value)} | {category.task_count} | "
                f"{category.evaluated_task_count} | {category.failure_task_count} | "
                f"{_md_value(metric.metric.value)} | {_md_value(_metric_value(metric))} |"
            )

    lines.extend(
        [
            "",
            "## Task Success by category",
            "",
            "Task Success is a category-specific interpretation of existing "
            "EvaluationResult conditions. It is not BenchmarkTaskResult.status.",
            "",
            "| Category | Tasks | Applicable | PASS | FAIL | UNKNOWN | N/A | Rate |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for category in category_metrics:
        summary = category.task_success
        summary_rate = _md_value(
            summary.task_success_rate if summary.task_success_rate is not None else "UNKNOWN"
        )
        lines.append(
            f"| {_md_value(category.category.value)} | {summary.task_count} | "
            f"{summary.task_success_applicable} | {summary.task_success_pass} | "
            f"{summary.task_success_fail} | {summary.task_success_unknown} | "
            f"{summary.task_success_not_applicable} | "
            f"{summary_rate} |"
        )

    lines.extend(["", "## Failure inventory", ""])
    if not failure_inventory.items:
        lines.append(
            "No task-status failure or existing deterministic evaluation failure signal "
            "was recorded."
        )
    else:
        lines.extend(
            [
                "| Task | Category | Status | Stage | Category/code | Evaluation | Artifact |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in failure_inventory.items:
            classification = (
                "/".join(part for part in (item.failure_category, item.failure_code) if part)
                or "metric signal"
            )
            lines.append(
                f"| {_md_value(item.benchmark_task_id)} | {_md_value(item.task_type.value)} | "
                f"{_md_value(item.task_status.value)} | {_md_value(item.failure_stage or 'N/A')} | "
                f"{_md_value(classification)} | {_md_value(item.evaluation_id or 'N/A')} | "
                f"{_md_value(artifact_refs[item.benchmark_task_id])} |"
            )

    lines.extend(
        [
            "",
            "## Safety and collateral-damage boundary",
            "",
            "Safety is reported only through existing Stage 19 ``safety_accuracy`` facts "
            "and authority references.",
            "Collateral Damage is not a baseline metric here in Stage 19. This baseline "
            "records only the separate deterministic state-diff acceptance evidence.",
            f"Collateral Damage applicable/no-damage/damage/UNKNOWN/N/A = "
            f"{collateral_damage.summary.applicable_count}/"
            f"{collateral_damage.summary.no_damage_count}/"
            f"{collateral_damage.summary.damage_count}/"
            f"{collateral_damage.summary.unknown_count}/"
            f"{collateral_damage.summary.not_applicable_count}; "
            f"rate={collateral_rate}.",
            "The pre-state, post-state, allowed paths, and normalized diff are in "
            "collateral-damage.json; no LLM Judge decides state damage.",
            "",
            "## Existing Evaluation report",
            "",
            delegated_report.rstrip("\n"),
        ]
    )
    return "\n".join(lines) + "\n"


def _artifact_paths(
    run: BenchmarkRun,
    result_store: JsonBenchmarkResultStore,
    output_dir: Path,
) -> BaselineArtifacts:
    root = output_dir.resolve()
    run_dir = result_store.task_path(run.evaluation_run_id, "_baseline").parent
    task_results = tuple(
        result_store.task_path(run.evaluation_run_id, result.benchmark_task_id)
        for result in run.results
    )
    return BaselineArtifacts(
        root=root,
        baseline_config=run_dir / "baseline-config.json",
        baseline_run=run_dir / "baseline-run.json",
        failure_inventory=run_dir / "failure-inventory.json",
        reproducibility=run_dir / "reproducibility.json",
        evaluation_csv=run_dir / "evaluation_result.csv",
        baseline_report=run_dir / "baseline-report.md",
        collateral_damage=run_dir / "collateral-damage.json",
        run=run_dir / "run.json",
        task_results=task_results,
    )


def _ensure_runner_artifacts(
    run: BenchmarkRun,
    result_store: JsonBenchmarkResultStore,
    artifacts: BaselineArtifacts,
) -> None:
    for result, path in zip(run.results, artifacts.task_results, strict=True):
        if not path.is_file():
            result_store.persist_task(result)
    if not artifacts.run.is_file():
        result_store.persist_run(run)


def _assert_existing_config_matches(path: Path, configuration: BaselineConfiguration) -> None:
    if not path.is_file():
        return
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FileExistsError(f"baseline config artifact is not readable: {path}") from exc
    if existing != configuration.model_dump(mode="json"):
        raise FileExistsError(
            f"baseline run identity already has a different configuration: {path}"
        )


def persist_baseline_artifacts(
    run: BenchmarkRun,
    dataset: BenchmarkDataset,
    configuration: BaselineConfiguration,
    *,
    output_dir: str | Path,
    result_store: JsonBenchmarkResultStore | None = None,
) -> FormalBaselineResult:
    """Persist a baseline view without changing the supplied execution facts."""

    destination = Path(output_dir).resolve()
    store = result_store or JsonBenchmarkResultStore(destination / "results")
    preflight_artifact_paths(
        plan_baseline_artifact_paths(
            destination,
            run.evaluation_run_id,
            (result.benchmark_task_id for result in run.results),
            result_store=store,
        )
    )
    artifacts = _artifact_paths(run, store, destination)
    _assert_existing_config_matches(artifacts.baseline_config, configuration)
    if run.dataset_id != dataset.manifest.dataset_id:
        raise ValueError("baseline run dataset ID does not match loaded dataset")
    if run.dataset_version != dataset.manifest.dataset_version:
        raise ValueError("baseline run dataset version does not match loaded dataset")
    if (
        configuration.dataset_id != run.dataset_id
        or configuration.dataset_version != run.dataset_version
    ):
        raise ValueError("baseline configuration does not match executed dataset")
    expected_split = _effective_split(run.split)
    if configuration.dataset_split != expected_split:
        raise ValueError("baseline configuration split does not match executed run")
    if configuration.task_schema_version != run.task_schema_version:
        raise ValueError("baseline configuration task schema version does not match run")

    _ensure_runner_artifacts(run, store, artifacts)
    artifact_refs = {
        result.benchmark_task_id: _relative_path(path, destination)
        for result, path in zip(run.results, artifacts.task_results, strict=True)
    }
    run_ref = _relative_path(artifacts.run, destination)
    evaluation_results = tuple(
        result.evaluation_result for result in run.results if result.evaluation_result is not None
    )
    overall_metrics = MetricsCalculator().calculate(evaluation_results)
    failure_inventory = _build_failure_inventory(run, artifact_refs)
    category_metrics = _category_metrics(run, failure_inventory)
    task_success = TaskSuccessSummary.from_results(result.task_success for result in run.results)
    collateral_damage = collateral_record_for_task_ids(run.selected_task_ids)
    task_result_refs = tuple(artifact_refs[result.benchmark_task_id] for result in run.results)
    baseline_ref = _relative_path(artifacts.baseline_run, destination)
    failure_ref = _relative_path(artifacts.failure_inventory, destination)
    reproducibility_ref = _relative_path(artifacts.reproducibility, destination)
    csv_ref = _relative_path(artifacts.evaluation_csv, destination)
    report_ref = _relative_path(artifacts.baseline_report, destination)
    baseline_record = BaselineRunRecord(
        benchmarkRunId=run.evaluation_run_id,
        baselineConfigId=configuration.baseline_config_id,
        datasetId=run.dataset_id,
        datasetVersion=run.dataset_version,
        datasetSplit=configuration.dataset_split,
        selectedTaskCount=len(run.selected_task_ids),
        executedTaskCount=len(run.results),
        evaluatedTaskCount=len(evaluation_results),
        successfulTaskCount=sum(
            result.status is BenchmarkTaskStatus.SUCCESS for result in run.results
        ),
        failureTaskCount=failure_inventory.failure_count,
        overallMetrics=overall_metrics,
        categoryMetrics=category_metrics,
        taskSuccess=task_success,
        collateralDamage=collateral_damage,
        taskResultArtifacts=task_result_refs,
        runArtifact=run_ref,
        failureInventoryArtifact=failure_ref,
        reproducibilityArtifact=reproducibility_ref,
    )
    reproducibility = ReproducibilityRecord(
        benchmarkRunId=run.evaluation_run_id,
        baselineConfigId=configuration.baseline_config_id,
        configurationDigest=configuration.configuration_digest,
        configuration=configuration,
        selectedTaskCount=len(run.selected_task_ids),
        executedTaskCount=len(run.results),
        taskResultArtifacts=task_result_refs,
        runArtifact=run_ref,
        baselineRunArtifact=baseline_ref,
        failureInventoryArtifact=failure_ref,
        evaluationCsvArtifact=csv_ref,
        baselineReportArtifact=report_ref,
        collateralDamageArtifact=_relative_path(artifacts.collateral_damage, destination),
    )
    report = _render_baseline_report(
        run,
        configuration,
        category_metrics,
        failure_inventory,
        artifact_refs,
        task_success,
        collateral_damage,
    )
    _write_immutable_json(artifacts.baseline_config, configuration.model_dump(mode="json"))
    _write_immutable_json(artifacts.failure_inventory, failure_inventory.model_dump(mode="json"))
    _write_immutable_json(artifacts.reproducibility, reproducibility.model_dump(mode="json"))
    _write_immutable_json(artifacts.baseline_run, baseline_record.model_dump(mode="json"))
    _write_immutable_json(artifacts.collateral_damage, collateral_damage.model_dump(mode="json"))
    _export_immutable_csv(evaluation_results, artifacts.evaluation_csv)
    _write_immutable_text(artifacts.baseline_report, report)
    return FormalBaselineResult(
        run=run,
        configuration=configuration,
        overall_metrics=overall_metrics,
        category_metrics=category_metrics,
        task_success=task_success,
        collateral_damage=collateral_damage,
        failure_inventory=failure_inventory,
        baseline_record=baseline_record,
        reproducibility=reproducibility,
        artifacts=artifacts,
    )


async def run_formal_baseline(
    runner: BenchmarkRunner,
    configuration: BaselineConfiguration,
    *,
    evaluation_run_id: str,
    output_dir: str | Path,
    manifest_path: Path | None = None,
    split: DatasetSplit | str | None = None,
    category: TaskType | str | None = None,
    task_ids: Iterable[str] = (),
    golden_only: bool = False,
) -> FormalBaselineResult:
    """Run the active Dataset through the existing Runner, then persist baseline views."""

    if not evaluation_run_id.strip():
        raise ValueError("evaluation_run_id must not be empty")
    dataset = load_dataset(manifest_path)
    requested_split = _effective_split(split)
    if configuration.dataset_id != dataset.manifest.dataset_id:
        raise ValueError("baseline configuration dataset ID does not match manifest")
    if configuration.dataset_version != dataset.manifest.dataset_version:
        raise ValueError("baseline configuration dataset version does not match manifest")
    if configuration.task_schema_version != dataset.manifest.task_schema_version:
        raise ValueError("baseline configuration task schema version does not match manifest")
    if configuration.dataset_split != requested_split:
        raise ValueError("baseline configuration split does not match requested selection")

    destination = Path(output_dir).resolve()
    store = JsonBenchmarkResultStore(destination / "results")
    requested_task_ids = tuple(task_ids)
    selected_pairs = select_dataset_tasks(
        dataset,
        split=split,
        category=category,
        task_ids=requested_task_ids,
        golden_only=golden_only,
    )
    preflight_artifact_paths(
        plan_baseline_artifact_paths(
            destination,
            evaluation_run_id,
            (task.benchmark_task_id for task, _ in selected_pairs),
            result_store=store,
        )
    )
    baseline_config_path = (
        store.task_path(evaluation_run_id, "_baseline").parent / "baseline-config.json"
    )
    _assert_existing_config_matches(baseline_config_path, configuration)
    run = await runner.run_dataset(
        manifest_path,
        evaluation_run_id=evaluation_run_id,
        split=split,
        category=category,
        task_ids=requested_task_ids,
        golden_only=golden_only,
        result_store=store,
    )
    return persist_baseline_artifacts(
        run,
        dataset,
        configuration,
        output_dir=destination,
        result_store=store,
    )


__all__ = [
    "BaselineArtifacts",
    "BaselineConfiguration",
    "BaselineRunRecord",
    "CategoryBaselineMetrics",
    "ConfigurationValue",
    "FailureInventory",
    "FailureInventoryItem",
    "FormalBaselineResult",
    "MetadataAvailability",
    "ReproducibilityRecord",
    "capture_git_revision",
    "capture_python_runtime",
    "persist_baseline_artifacts",
    "plan_baseline_artifact_paths",
    "run_formal_baseline",
    "unavailable_java_runtime",
]
