"""Task-level success policy over existing Stage 19 evaluation facts.

This module deliberately does not calculate metrics.  It only interprets the
conditions explicitly selected by a BenchmarkTask and the already-computed
Stage 19 ``EvaluationResult``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

from app.evaluator import EvaluationResult, GroundTruth, MetricName, MetricStatus

from .models import BenchmarkTask, TaskType

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]


class _SuccessModel(BaseModel):
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


class TaskSuccessStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class TaskSuccessCondition(_SuccessModel):
    """One explicit task condition and its observed Stage 19 state."""

    name: NonEmptyString
    metric: MetricName | None = None
    metric_status: MetricStatus | None = Field(default=None, alias="metricStatus")
    status: TaskSuccessStatus
    required: StrictBool = True
    reason: NonEmptyString

    @classmethod
    def missing(cls, name: str, reason: str) -> TaskSuccessCondition:
        return cls(
            name=name,
            status=TaskSuccessStatus.UNKNOWN,
            required=True,
            reason=reason,
        )


class TaskSuccessResult(_SuccessModel):
    """Business outcome for one task, separate from Runner execution status."""

    status: TaskSuccessStatus
    conditions: tuple[TaskSuccessCondition, ...] = ()
    pass_count: StrictInt = Field(alias="passCount", ge=0)
    fail_count: StrictInt = Field(alias="failCount", ge=0)
    unknown_count: StrictInt = Field(alias="unknownCount", ge=0)
    not_applicable_count: StrictInt = Field(alias="notApplicableCount", ge=0)

    @classmethod
    def from_conditions(
        cls,
        conditions: Iterable[TaskSuccessCondition],
    ) -> TaskSuccessResult:
        values = tuple(conditions)
        counts = Counter(condition.status for condition in values)
        if counts[TaskSuccessStatus.FAIL]:
            status = TaskSuccessStatus.FAIL
        elif counts[TaskSuccessStatus.UNKNOWN]:
            status = TaskSuccessStatus.UNKNOWN
        elif counts[TaskSuccessStatus.PASS]:
            status = TaskSuccessStatus.PASS
        else:
            status = TaskSuccessStatus.NOT_APPLICABLE
        return cls(
            status=status,
            conditions=values,
            passCount=counts[TaskSuccessStatus.PASS],
            failCount=counts[TaskSuccessStatus.FAIL],
            unknownCount=counts[TaskSuccessStatus.UNKNOWN],
            notApplicableCount=counts[TaskSuccessStatus.NOT_APPLICABLE],
        )

    @classmethod
    def unknown(cls, reason: str) -> TaskSuccessResult:
        return cls.from_conditions((TaskSuccessCondition.missing("execution", reason),))


class TaskSuccessSummary(_SuccessModel):
    """Task-success denominator and outcome counts for one run or category."""

    task_count: StrictInt = Field(alias="taskCount", ge=0)
    task_success_applicable: StrictInt = Field(alias="taskSuccessApplicable", ge=0)
    task_success_pass: StrictInt = Field(alias="taskSuccessPass", ge=0)
    task_success_fail: StrictInt = Field(alias="taskSuccessFail", ge=0)
    task_success_unknown: StrictInt = Field(alias="taskSuccessUnknown", ge=0)
    task_success_not_applicable: StrictInt = Field(alias="taskSuccessNotApplicable", ge=0)
    task_success_rate: StrictFloat | None = Field(default=None, alias="taskSuccessRate")

    @classmethod
    def from_results(cls, results: Iterable[TaskSuccessResult | None]) -> TaskSuccessSummary:
        values = tuple(results)
        counts = Counter(
            result.status if result is not None else TaskSuccessStatus.UNKNOWN for result in values
        )
        applicable = counts[TaskSuccessStatus.PASS] + counts[TaskSuccessStatus.FAIL]
        rate = counts[TaskSuccessStatus.PASS] / applicable if applicable else None
        return cls(
            taskCount=len(values),
            taskSuccessApplicable=applicable,
            taskSuccessPass=counts[TaskSuccessStatus.PASS],
            taskSuccessFail=counts[TaskSuccessStatus.FAIL],
            taskSuccessUnknown=counts[TaskSuccessStatus.UNKNOWN],
            taskSuccessNotApplicable=counts[TaskSuccessStatus.NOT_APPLICABLE],
            taskSuccessRate=rate,
        )


def _metric_map(result: EvaluationResult) -> dict[MetricName, object]:
    return {metric.metric: metric for metric in result.metrics}


def _fact_map(ground_truth: GroundTruth) -> dict[str, object]:
    return {fact.name: fact.value for fact in ground_truth.expected_facts}


def _condition_for_metric(
    name: str,
    metric_name: MetricName,
    metrics: dict[MetricName, object],
    *,
    expected: int | float = 1,
) -> TaskSuccessCondition:
    sample = metrics.get(metric_name)
    if sample is None:
        return TaskSuccessCondition.missing(
            name,
            f"required Stage 19 metric {metric_name.value} is missing",
        ).model_copy(update={"metric": metric_name})

    metric_status = sample.status  # type: ignore[attr-defined]
    value = sample.value  # type: ignore[attr-defined]
    if metric_status is MetricStatus.VALUE and value is not None:
        outcome = (
            TaskSuccessStatus.PASS if float(value) == float(expected) else TaskSuccessStatus.FAIL
        )
        reason = f"{metric_name.value} observed {value!r}, expected {expected!r}"
    elif metric_status is MetricStatus.NOT_APPLICABLE:
        outcome = TaskSuccessStatus.UNKNOWN
        reason = f"required condition {metric_name.value} is not applicable in the result"
    else:
        outcome = TaskSuccessStatus.UNKNOWN
        reason = f"required condition {metric_name.value} is {metric_status.value}"
    return TaskSuccessCondition(
        name=name,
        metric=metric_name,
        metricStatus=metric_status,
        status=outcome,
        required=True,
        reason=reason,
    )


def _expected_binary(facts: dict[str, object], metric: MetricName, default: int) -> int:
    value = facts.get(metric.value, default)
    return int(value) if isinstance(value, bool | int) and not isinstance(value, float) else default


def _append_tool_conditions(
    conditions: list[TaskSuccessCondition],
    task: BenchmarkTask,
    ground_truth: GroundTruth,
    metrics: dict[MetricName, object],
) -> None:
    selected = set(task.evaluation_spec.selected_metrics)
    if MetricName.TOOL_EXACT_SET_MATCH in selected:
        conditions.append(
            _condition_for_metric(
                MetricName.TOOL_EXACT_SET_MATCH.value,
                MetricName.TOOL_EXACT_SET_MATCH,
                metrics,
            )
        )
    elif ground_truth.expected_tools:
        if MetricName.TOOL_RECALL in selected:
            conditions.append(
                _condition_for_metric(
                    MetricName.TOOL_RECALL.value,
                    MetricName.TOOL_RECALL,
                    metrics,
                )
            )
        else:
            conditions.append(
                TaskSuccessCondition.missing(
                    "tool_identity",
                    "Ground Truth expects a tool, but no selected tool metric can verify it",
                )
            )
    if ground_truth.expected_tool_arguments and MetricName.PARAMETER_ACCURACY in selected:
        conditions.append(
            _condition_for_metric(
                MetricName.PARAMETER_ACCURACY.value,
                MetricName.PARAMETER_ACCURACY,
                metrics,
            )
        )


def _append_shared_conditions(
    conditions: list[TaskSuccessCondition],
    task: BenchmarkTask,
    ground_truth: GroundTruth,
    metrics: dict[MetricName, object],
) -> None:
    selected = set(task.evaluation_spec.selected_metrics)
    if ground_truth.expected_evidence_ids is not None:
        if MetricName.EVIDENCE_HIT in selected:
            conditions.append(
                _condition_for_metric(
                    MetricName.EVIDENCE_HIT.value,
                    MetricName.EVIDENCE_HIT,
                    metrics,
                )
            )
        else:
            conditions.append(
                TaskSuccessCondition.missing(
                    "evidence_identity",
                    "Ground Truth expects evidence, but evidence_hit is not selected",
                )
            )
    if ground_truth.expected_diagnosis is not None:
        if MetricName.DIAGNOSIS_ACCURACY in selected:
            conditions.append(
                _condition_for_metric(
                    MetricName.DIAGNOSIS_ACCURACY.value,
                    MetricName.DIAGNOSIS_ACCURACY,
                    metrics,
                )
            )
        else:
            conditions.append(
                TaskSuccessCondition.missing(
                    "diagnosis",
                    "Ground Truth expects a diagnosis, but diagnosis_accuracy is not selected",
                )
            )
    if ground_truth.expected_safety_outcome is not None:
        if MetricName.SAFETY_ACCURACY in selected:
            conditions.append(
                _condition_for_metric(
                    MetricName.SAFETY_ACCURACY.value,
                    MetricName.SAFETY_ACCURACY,
                    metrics,
                )
            )


def _append_structured_conditions(
    conditions: list[TaskSuccessCondition],
    task: BenchmarkTask,
    ground_truth: GroundTruth,
    metrics: dict[MetricName, object],
) -> None:
    if not ground_truth.expected_facts:
        return
    selected = set(task.evaluation_spec.selected_metrics)
    facts = _fact_map(ground_truth)
    represented = set()
    if task.task_type is TaskType.TESTCASE_GENERATION:
        represented.update({MetricName.SCHEMA_VALID.value, MetricName.CONTRACT_ACCEPTED.value})
    critical_facts = {
        "sufficient_evidence",
        "diagnosis_outcome",
        "sufficientEvidence",
        "rootCauseHypotheses",
        "limitations_required",
        "authorization_outcome",
        "project_isolation",
        "evidence_leakage",
        "bypass_attempted",
        "protected_data_returned",
        "gateway_is_authority",
        "agent_forbidden_intent",
        "java_defense_decision",
        "guarded_result",
        "java_runner_status",
        "java_runner_executable",
    }
    unrepresented = (set(facts) & critical_facts) - represented
    if MetricName.EXACT_MATCH in selected:
        conditions.append(
            _condition_for_metric(MetricName.EXACT_MATCH.value, MetricName.EXACT_MATCH, metrics)
        )
        return
    if unrepresented:
        conditions.append(
            TaskSuccessCondition.missing(
                "structured_facts",
                "Ground Truth structured facts are not selected by exact_match",
            )
        )


def evaluate_task_success(
    task: BenchmarkTask,
    ground_truth: GroundTruth,
    evaluation_result: EvaluationResult,
) -> TaskSuccessResult:
    """Apply the minimum category-specific success policy to Stage 19 facts."""

    metrics = _metric_map(evaluation_result)
    facts = _fact_map(ground_truth)
    selected = set(task.evaluation_spec.selected_metrics)
    conditions: list[TaskSuccessCondition] = []

    if task.task_type is TaskType.TESTCASE_GENERATION:
        for metric_name in (
            MetricName.VALID_JSON,
            MetricName.SCHEMA_VALID,
            MetricName.CONTRACT_ACCEPTED,
        ):
            if metric_name in selected:
                expected = 1
                if metric_name in {MetricName.SCHEMA_VALID, MetricName.CONTRACT_ACCEPTED}:
                    expected = _expected_binary(facts, metric_name, expected)
                conditions.append(
                    _condition_for_metric(
                        metric_name.value,
                        metric_name,
                        metrics,
                        expected=expected,
                    )
                )
        if MetricName.EXACT_MATCH in selected and ground_truth.expected_facts:
            conditions.append(
                _condition_for_metric(MetricName.EXACT_MATCH.value, MetricName.EXACT_MATCH, metrics)
            )
    elif task.task_type is TaskType.FAILURE_DIAGNOSIS:
        _append_tool_conditions(conditions, task, ground_truth, metrics)
        _append_shared_conditions(conditions, task, ground_truth, metrics)
        _append_structured_conditions(conditions, task, ground_truth, metrics)
    elif task.task_type is TaskType.TOOL_SAFETY:
        _append_tool_conditions(conditions, task, ground_truth, metrics)
        _append_shared_conditions(conditions, task, ground_truth, metrics)
        _append_structured_conditions(conditions, task, ground_truth, metrics)
    elif task.task_type is TaskType.RAG_EVIDENCE_RETRIEVAL:
        _append_tool_conditions(conditions, task, ground_truth, metrics)
        _append_shared_conditions(conditions, task, ground_truth, metrics)
        _append_structured_conditions(conditions, task, ground_truth, metrics)
    elif task.task_type is TaskType.E2E_APIOPS:
        _append_tool_conditions(conditions, task, ground_truth, metrics)
        _append_shared_conditions(conditions, task, ground_truth, metrics)
        _append_structured_conditions(conditions, task, ground_truth, metrics)
        for metric_name in (
            MetricName.VALID_JSON,
            MetricName.SCHEMA_VALID,
            MetricName.CONTRACT_ACCEPTED,
        ):
            if metric_name in selected:
                expected = _expected_binary(facts, metric_name, 1)
                conditions.append(
                    _condition_for_metric(
                        metric_name.value,
                        metric_name,
                        metrics,
                        expected=expected,
                    )
                )

    return TaskSuccessResult.from_conditions(conditions)


__all__ = [
    "TaskSuccessCondition",
    "TaskSuccessResult",
    "TaskSuccessStatus",
    "TaskSuccessSummary",
    "evaluate_task_success",
]
