"""Pandas/CSV/Markdown views over existing Stage 19 evaluation results."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator

from app.evaluator import (
    AggregatedMetric,
    EvaluationResult,
    JudgeResult,
    MetricName,
    MetricsCalculator,
    MetricStatus,
)

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]
MISSING_METRIC_STATE = "MISSING"

_IDENTITY_COLUMNS = (
    "evaluation_id",
    "case_id",
    "trace_id",
    "agent_run_id",
    "ground_truth_id",
    "ground_truth_version",
    "evaluator_version",
)
_METRIC_SUFFIXES = ("state", "value", "unit", "reason")
_FAILURE_SIGNAL_METRICS = {
    MetricName.VALID_JSON,
    MetricName.SCHEMA_VALID,
    MetricName.CONTRACT_ACCEPTED,
    MetricName.EXACT_MATCH,
    MetricName.TOOL_PRECISION,
    MetricName.TOOL_RECALL,
    MetricName.TOOL_EXACT_SET_MATCH,
    MetricName.PARAMETER_ACCURACY,
    MetricName.EVIDENCE_HIT,
    MetricName.DIAGNOSIS_ACCURACY,
    MetricName.SAFETY_ACCURACY,
}
_METRIC_DEFINITIONS = {
    MetricName.VALID_JSON: "Authority fact that JSON syntax parsed successfully.",
    MetricName.SCHEMA_VALID: "Authority fact that the shared schema accepted the value.",
    MetricName.CONTRACT_ACCEPTED: "Existing Validator/semantic contract acceptance fact.",
    MetricName.EXACT_MATCH: "Deterministic equality under explicitly allowed normalization.",
    MetricName.TOOL_PRECISION: "Expected/actual tool intersection divided by actual tools.",
    MetricName.TOOL_RECALL: "Expected/actual tool intersection divided by expected tools.",
    MetricName.TOOL_EXACT_SET_MATCH: "One only when expected and actual tool sets are equal.",
    MetricName.PARAMETER_ACCURACY: "Existing exact/subset parameter comparison score.",
    MetricName.EVIDENCE_HIT: "Expected evidence IDs retrieved divided by expected evidence IDs.",
    MetricName.DIAGNOSIS_ACCURACY: "Frozen diagnosis label or acceptable-alternative match.",
    MetricName.SAFETY_ACCURACY: "Observed safety outcome compared with the expected outcome.",
    MetricName.WALL_CLOCK_LATENCY_MS: "AgentRun start-to-terminal elapsed time.",
    MetricName.MODEL_LATENCY_MS: "Sum of recorded model-call durations.",
    MetricName.TOOL_LATENCY_MS: "Sum of recorded tool durations when available.",
    MetricName.HUMAN_WAIT_MS: "Paired approval interrupt-to-resume wait time.",
    MetricName.ACTIVE_EXECUTION_MS: "Wall-clock latency less complete human waits.",
    MetricName.PROMPT_TOKENS: "Provider-reported prompt tokens only.",
    MetricName.COMPLETION_TOKENS: "Provider-reported completion tokens only.",
    MetricName.TOTAL_TOKENS: "Provider-reported total tokens only.",
    MetricName.COST: "Cost computed only from known usage and versioned injected pricing.",
}


class _ReportModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        validate_default=True,
    )


class ReportMetadata(_ReportModel):
    """Explicit reproducibility metadata; generation time is never guessed."""

    report_id: NonEmptyString
    run_label: NonEmptyString
    generated_at: datetime
    dataset_id: NonEmptyString
    dataset_version: NonEmptyString
    evaluation_config_version: NonEmptyString
    source_revision: NonEmptyString | None = None

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value


class ComparisonRun(_ReportModel):
    """One observed run and its explicit configuration description."""

    label: NonEmptyString
    configuration: tuple[NonEmptyString, ...] = Field(min_length=1)
    results: tuple[EvaluationResult, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_must_be_unique(self) -> ComparisonRun:
        case_ids = [result.case_id for result in self.results]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("comparison run case_id values must be unique")
        return self


class ReportArtifacts(_ReportModel):
    evaluation_csv: Path
    evaluation_report: Path
    ablation_report: Path


def _columns() -> list[str]:
    columns = list(_IDENTITY_COLUMNS)
    for metric in MetricName:
        columns.extend(f"{metric.value}__{suffix}" for suffix in _METRIC_SUFFIXES)
    return columns


def evaluation_results_to_dataframe(results: Sequence[EvaluationResult]) -> pd.DataFrame:
    """Return one row per case without collapsing unavailable values to zero."""

    rows: list[dict[str, object]] = []
    for result in results:
        row: dict[str, object] = {column: getattr(result, column) for column in _IDENTITY_COLUMNS}
        samples = {sample.metric: sample for sample in result.metrics}
        for metric in MetricName:
            prefix = metric.value
            sample = samples.get(metric)
            if sample is None:
                row[f"{prefix}__state"] = MISSING_METRIC_STATE
                row[f"{prefix}__value"] = pd.NA
                row[f"{prefix}__unit"] = pd.NA
                row[f"{prefix}__reason"] = pd.NA
                continue
            row[f"{prefix}__state"] = sample.status.value
            row[f"{prefix}__value"] = sample.value if sample.status is MetricStatus.VALUE else pd.NA
            row[f"{prefix}__unit"] = sample.unit if sample.unit is not None else pd.NA
            row[f"{prefix}__reason"] = sample.reason if sample.reason is not None else pd.NA
        rows.append(row)

    frame = pd.DataFrame(rows, columns=_columns())
    for column in _IDENTITY_COLUMNS:
        frame[column] = frame[column].astype("string")
    for metric in MetricName:
        prefix = metric.value
        for suffix in ("state", "unit", "reason"):
            column = f"{prefix}__{suffix}"
            frame[column] = frame[column].astype("string")
        value_column = f"{prefix}__value"
        frame[value_column] = pd.to_numeric(frame[value_column], errors="coerce").astype("Float64")
    return frame


def export_evaluation_csv(
    results: Sequence[EvaluationResult],
    path: str | Path,
) -> Path:
    """Write a stable case-level CSV view of existing EvaluationResults."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    evaluation_results_to_dataframe(results).to_csv(
        destination,
        index=False,
        na_rep="",
        lineterminator="\n",
    )
    return destination


def read_evaluation_csv(path: str | Path) -> pd.DataFrame:
    """Read back the case-level CSV and restore nullable report dtypes."""

    frame = pd.read_csv(path, keep_default_na=True)
    missing_columns = set(_columns()) - set(frame.columns)
    if missing_columns:
        raise ValueError(f"evaluation CSV is missing columns: {sorted(missing_columns)}")
    frame = frame.loc[:, _columns()]
    for column in _IDENTITY_COLUMNS:
        frame[column] = frame[column].astype("string")
    for metric in MetricName:
        prefix = metric.value
        for suffix in ("state", "unit", "reason"):
            column = f"{prefix}__{suffix}"
            frame[column] = frame[column].astype("string")
        value_column = f"{prefix}__value"
        frame[value_column] = pd.to_numeric(frame[value_column], errors="coerce").astype("Float64")
    return frame


def _escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _display_number(value: float | None) -> str:
    return "UNKNOWN" if value is None else f"{value:.6g}"


def _metric_map(metrics: Sequence[AggregatedMetric]) -> dict[MetricName, AggregatedMetric]:
    return {metric.metric: metric for metric in metrics}


def _failure_rows(results: Sequence[EvaluationResult]) -> list[tuple[str, str, str, str]]:
    failures: list[tuple[str, str, str, str]] = []
    for result in results:
        for sample in result.metrics:
            is_zero_score = (
                sample.metric in _FAILURE_SIGNAL_METRICS
                and sample.status is MetricStatus.VALUE
                and sample.value == 0
            )
            if sample.status is MetricStatus.ERROR or is_zero_score:
                failures.append(
                    (
                        result.case_id,
                        sample.metric.value,
                        sample.status.value,
                        sample.reason or "No reason recorded.",
                    )
                )
    return failures


def render_evaluation_report(
    results: Sequence[EvaluationResult],
    metadata: ReportMetadata,
    *,
    judge_results: Sequence[JudgeResult] = (),
    limitations: Sequence[str] = (),
) -> str:
    """Render one run using MetricsCalculator as the aggregation authority."""

    aggregate = MetricsCalculator().calculate(results)
    lines = [
        f"# Evaluation Report: {_escape(metadata.run_label)}",
        "",
        "## Evaluation setup",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Report ID | {_escape(metadata.report_id)} |",
        f"| Dataset | {_escape(metadata.dataset_id)} @ {_escape(metadata.dataset_version)} |",
        f"| Evaluation config | {_escape(metadata.evaluation_config_version)} |",
        f"| Generated at | {_escape(metadata.generated_at.isoformat())} |",
        f"| Source revision | {_escape(metadata.source_revision or 'UNKNOWN')} |",
        "",
        "The report consumes existing EvaluationResult and JudgeResult facts. It does not rerun "
        "the Evaluator or redefine metric formulas.",
        "",
        "## Sample counts and denominator context",
        "",
        f"Case count: **{aggregate.case_count}**. VALUE samples form known-value means/rates; "
        "NOT_APPLICABLE is excluded, while UNKNOWN and ERROR remain visible but carry no value.",
        "",
        "| Metric | Total facts | Applicable | Known values | N/A | UNKNOWN | ERROR | MISSING |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for metric in aggregate.metrics:
        lines.append(
            f"| {metric.metric.value} | {metric.total_count} | {metric.applicable_count} | "
            f"{metric.value_count} | {metric.not_applicable_count} | {metric.unknown_count} | "
            f"{metric.error_count} | {aggregate.case_count - metric.total_count} |"
        )

    lines.extend(
        [
            "",
            "## Metric definitions",
            "",
            "| Metric | Definition |",
            "| --- | --- |",
        ]
    )
    for metric in aggregate.metrics:
        lines.append(f"| {metric.metric.value} | {_METRIC_DEFINITIONS[metric.metric]} |")

    lines.extend(
        [
            "",
            "## Results",
            "",
            "| Metric | Rate | Mean | Unit |",
            "| --- | ---: | ---: | --- |",
        ]
    )
    for metric in aggregate.metrics:
        lines.append(
            f"| {metric.metric.value} | {_display_number(metric.rate)} | "
            f"{_display_number(metric.mean)} | {_escape(metric.unit or 'N/A')} |"
        )

    lines.extend(["", "## Failure cases", ""])
    failures = _failure_rows(results)
    if failures:
        lines.extend(
            [
                "| Case | Metric | State | Recorded reason |",
                "| --- | --- | --- | --- |",
            ]
        )
        for case_id, metric, state, reason in failures:
            lines.append(
                f"| {_escape(case_id)} | {_escape(metric)} | {_escape(state)} | {_escape(reason)} |"
            )
    else:
        lines.append("No zero-valued deterministic quality metric or evaluator ERROR was recorded.")

    selected = _metric_map(aggregate.metrics)
    lines.extend(
        [
            "",
            "## Cost and latency",
            "",
            "| Metric | Known mean | Known samples | UNKNOWN | MISSING |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for name in (
        MetricName.WALL_CLOCK_LATENCY_MS,
        MetricName.MODEL_LATENCY_MS,
        MetricName.TOOL_LATENCY_MS,
        MetricName.HUMAN_WAIT_MS,
        MetricName.ACTIVE_EXECUTION_MS,
        MetricName.TOTAL_TOKENS,
        MetricName.COST,
    ):
        metric = selected.get(name)
        if metric is None:
            lines.append(f"| {name.value} | MISSING | 0 | 0 | {aggregate.case_count} |")
        else:
            lines.append(
                f"| {name.value} | {_display_number(metric.mean)} | {metric.value_count} | "
                f"{metric.unknown_count} | {aggregate.case_count - metric.total_count} |"
            )

    lines.extend(["", "## Safety observations", ""])
    safety = selected.get(MetricName.SAFETY_ACCURACY)
    if safety is None:
        lines.append("Safety metric is MISSING from this report input.")
    else:
        lines.append(
            f"Known safety mean: **{_display_number(safety.mean)}** from "
            f"**{safety.value_count}** known samples; UNKNOWN: **{safety.unknown_count}**; "
            f"ERROR: **{safety.error_count}**. This is an evaluation observation, not authority."
        )

    lines.extend(["", "## Model-based observations", ""])
    if judge_results:
        lines.extend(
            [
                "| Judge case | Dimension | Score | Rubric | Prompt | Model |",
                "| --- | --- | ---: | --- | --- | --- |",
            ]
        )
        for result in judge_results:
            config = result.configuration
            model = config.model_identity
            lines.append(
                f"| {_escape(result.judge_case_id)} | {result.dimension.value} | "
                f"{_display_number(result.score)} | {_escape(config.rubric.rubric_id)}@"
                f"{_escape(config.rubric.version)} | {_escape(config.prompt.name)}@"
                f"{_escape(config.prompt.version)} | {_escape(model.provider)}/"
                f"{_escape(model.model)}@{_escape(model.version)} |"
            )
    else:
        lines.append("No JudgeResult was supplied; no model-based score is inferred.")

    evaluator_versions = sorted({result.evaluator_version for result in results})
    truth_versions = sorted(
        {f"{result.ground_truth_id}@{result.ground_truth_version}" for result in results}
    )
    lines.extend(
        [
            "",
            "## Reproducibility metadata",
            "",
            f"- Evaluator versions: {', '.join(evaluator_versions) or 'MISSING'}",
            f"- Ground Truth identities: {', '.join(truth_versions) or 'MISSING'}",
            f"- Dataset: {metadata.dataset_id}@{metadata.dataset_version}",
            f"- Evaluation configuration: {metadata.evaluation_config_version}",
            f"- Source revision: {metadata.source_revision or 'UNKNOWN'}",
            "",
            "## Limitations",
            "",
        ]
    )
    effective_limitations = tuple(limitations) or (
        "This report is descriptive and limited to the supplied cases.",
    )
    lines.extend(f"- {_escape(item)}" for item in effective_limitations)
    return "\n".join(lines) + "\n"


def _aggregate_value(metric: AggregatedMetric | None) -> float | None:
    if metric is None:
        return None
    return metric.rate if metric.rate is not None else metric.mean


def render_ablation_report(
    run_a: ComparisonRun,
    run_b: ComparisonRun,
    selected_metrics: Sequence[MetricName],
    *,
    limitations: Sequence[str] = (),
) -> str:
    """Render a minimal observational A/B comparison over matched cases."""

    if not selected_metrics:
        raise ValueError("comparison requires at least one selected metric")
    if len(selected_metrics) != len(set(selected_metrics)):
        raise ValueError("selected_metrics must be unique")
    cases_a = {result.case_id for result in run_a.results}
    cases_b = {result.case_id for result in run_b.results}
    if cases_a != cases_b:
        raise ValueError("comparison runs must contain the same case_id values")

    aggregate_a = _metric_map(MetricsCalculator().calculate(run_a.results).metrics)
    aggregate_b = _metric_map(MetricsCalculator().calculate(run_b.results).metrics)
    lines = [
        "# Minimal Run A / Run B Comparison",
        "",
        "This report describes observed differences on the same fixed cases. It does not claim "
        "that a configuration difference caused a metric change.",
        "",
        "## Evaluation setup",
        "",
        f"- Matched case count: {len(cases_a)}",
        f"- Run A: {_escape(run_a.label)}",
        f"- Run B: {_escape(run_b.label)}",
        "",
        "## Configuration difference",
        "",
        "| Run | Configuration |",
        "| --- | --- |",
        f"| A | {_escape('; '.join(run_a.configuration))} |",
        f"| B | {_escape('; '.join(run_b.configuration))} |",
        "",
        "## Selected metric observations",
        "",
        "| Metric | Run A | Run B | Delta (B - A) | A known | B known |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in selected_metrics:
        metric_a = aggregate_a.get(name)
        metric_b = aggregate_b.get(name)
        value_a = _aggregate_value(metric_a)
        value_b = _aggregate_value(metric_b)
        delta = value_b - value_a if value_a is not None and value_b is not None else None
        lines.append(
            f"| {name.value} | {_display_number(value_a)} | {_display_number(value_b)} | "
            f"{_display_number(delta)} | {metric_a.value_count if metric_a else 0} | "
            f"{metric_b.value_count if metric_b else 0} |"
        )

    lines.extend(["", "## Limitations", ""])
    fixed_limitations = (
        "Observed deltas are descriptive and are not evidence of causal improvement.",
        "This is a small matched-case comparison, not a randomized or formal multi-group ablation.",
        "A missing or unknown aggregate remains UNKNOWN; it is never replaced with zero.",
    )
    lines.extend(f"- {_escape(item)}" for item in (*fixed_limitations, *limitations))
    return "\n".join(lines) + "\n"


def generate_report_bundle(
    output_dir: str | Path,
    *,
    primary_run: ComparisonRun,
    comparison_run: ComparisonRun,
    metadata: ReportMetadata,
    selected_metrics: Sequence[MetricName],
    judge_results: Sequence[JudgeResult] = (),
    limitations: Sequence[str] = (),
) -> ReportArtifacts:
    """Generate the three Stage 19.5 artifacts from existing typed facts."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = export_evaluation_csv(
        primary_run.results,
        destination / "evaluation_result.csv",
    )
    evaluation_path = destination / "evaluation_report.md"
    evaluation_path.write_text(
        render_evaluation_report(
            primary_run.results,
            metadata,
            judge_results=judge_results,
            limitations=limitations,
        ),
        encoding="utf-8",
        newline="\n",
    )
    ablation_path = destination / "ablation_report.md"
    ablation_path.write_text(
        render_ablation_report(
            comparison_run,
            primary_run,
            selected_metrics,
            limitations=limitations,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return ReportArtifacts(
        evaluation_csv=csv_path,
        evaluation_report=evaluation_path,
        ablation_report=ablation_path,
    )


__all__ = [
    "MISSING_METRIC_STATE",
    "ComparisonRun",
    "ReportArtifacts",
    "ReportMetadata",
    "evaluation_results_to_dataframe",
    "export_evaluation_csv",
    "generate_report_bundle",
    "read_evaluation_csv",
    "render_ablation_report",
    "render_evaluation_report",
]
