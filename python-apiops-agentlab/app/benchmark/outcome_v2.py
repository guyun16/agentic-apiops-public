"""Stage 21 Benchmark V2 policy loading and offline outcome projection.

The V2 layer is deliberately a sidecar over the existing Stage 19 result.  It
does not execute a workflow, call a model, or reinterpret the Stage 19 metric
formulas.  A policy may mark an outcome as an authority gap; in that case the
projected outcome cannot become PASS, while a decisive final-outcome metric
failure remains FAIL.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from app.evaluator import MetricName, MetricStatus

from .dataset import BenchmarkDataset, load_dataset
from .models import DatasetSplit, TaskType
from .runner import BenchmarkRun, BenchmarkTaskResult, BenchmarkTaskStatus, ToolResultObservation
from .semantic_adjudication import SemanticAdjudicationResult, SemanticDecision
from .success import TaskSuccessStatus

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]
NumericValue = StrictInt | StrictFloat

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY_ROOT = _PACKAGE_ROOT.parent
DEFAULT_OUTCOME_POLICY_PATH = (
    _PACKAGE_ROOT / "tests" / "benchmark" / "fixtures" / "stage21-outcome-policy-v2.json"
)
DEFAULT_FORMAL105_RUN_GLOB = (
    _REPOSITORY_ROOT
    / "artifacts"
    / "stage21"
    / "formal-real-model-final"
    / "full-105"
    / "results"
    / "**"
    / "run.json"
)
DEFAULT_OFFLINE_PROJECTION_DIR = (
    _REPOSITORY_ROOT / "artifacts" / "stage21" / "v2-offline-projection"
)
DEFAULT_PREVIOUS_PROJECTION_PATH = DEFAULT_OFFLINE_PROJECTION_DIR / "outcome-v2.json"


class OutcomePolicyError(ValueError):
    """A fail-closed V2 policy or artifact error."""


class ToolRequirement(StrEnum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    NOT_REQUIRED = "NOT_REQUIRED"


class OutcomeAuthority(StrEnum):
    SUPPORTED_BY_EXISTING_FACTS = "SUPPORTED_BY_EXISTING_FACTS"
    OUTCOME_AUTHORITY_GAP = "OUTCOME_AUTHORITY_GAP"


class OutcomeMode(StrEnum):
    ALL = "ALL"
    ANY = "ANY"


class V2OutcomeStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class _OutcomeModel(BaseModel):
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


class OutcomePolicyToolRequirement(_OutcomeModel):
    tool_name: NonEmptyString = Field(alias="toolName")
    requirement: ToolRequirement
    reason: NonEmptyString | None = None


class OutcomePolicyTask(_OutcomeModel):
    benchmark_task_id: NonEmptyString = Field(alias="benchmarkTaskId")
    task_type: TaskType = Field(alias="taskType")
    split: DatasetSplit
    scenario: NonEmptyString
    outcome_authority: OutcomeAuthority = Field(alias="outcomeAuthority")
    outcome_metrics: tuple[MetricName, ...] = Field(alias="outcomeMetrics", min_length=1)
    expected_metric_values: dict[MetricName, Literal[0, 1]] = Field(
        default_factory=dict,
        alias="expectedMetricValues",
    )
    outcome_mode: OutcomeMode = Field(alias="outcomeMode")
    tool_requirements: tuple[OutcomePolicyToolRequirement, ...] = Field(
        default=(), alias="toolRequirements"
    )
    semantic_adjudication_allowed: StrictBool = Field(
        default=False,
        alias="semanticAdjudicationAllowed",
    )
    reason: NonEmptyString | None = None

    @field_validator("outcome_metrics")
    @classmethod
    def outcome_metrics_must_be_unique(
        cls, value: tuple[MetricName, ...]
    ) -> tuple[MetricName, ...]:
        if len(value) != len(set(value)):
            raise ValueError("outcomeMetrics must be unique")
        return value

    @model_validator(mode="after")
    def tool_requirements_must_be_unique(self) -> OutcomePolicyTask:
        names = [item.tool_name for item in self.tool_requirements]
        if len(names) != len(set(names)):
            raise ValueError("toolRequirements must contain at most one entry per tool")
        unknown_expectations = set(self.expected_metric_values) - set(self.outcome_metrics)
        if unknown_expectations:
            raise ValueError(
                "expectedMetricValues references metrics outside outcomeMetrics: "
                + ", ".join(sorted(item.value for item in unknown_expectations))
            )
        polarity_metrics = {MetricName.SCHEMA_VALID, MetricName.CONTRACT_ACCEPTED}
        unsupported_expectations = set(self.expected_metric_values) - polarity_metrics
        if unsupported_expectations:
            raise ValueError(
                "expectedMetricValues is limited to schema/contract polarity metrics: "
                + ", ".join(sorted(item.value for item in unsupported_expectations))
            )
        if self.expected_metric_values and self.task_type is not TaskType.TESTCASE_GENERATION:
            raise ValueError("expectedMetricValues is only valid for TESTCASE_GENERATION tasks")
        return self


class OutcomePolicy(_OutcomeModel):
    policy_version: NonEmptyString = Field(alias="policyVersion")
    dataset_id: NonEmptyString = Field(alias="datasetId")
    dataset_version: NonEmptyString = Field(alias="datasetVersion")
    task_schema_version: NonEmptyString = Field(alias="taskSchemaVersion")
    tasks: tuple[OutcomePolicyTask, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def task_ids_must_be_unique(self) -> OutcomePolicy:
        task_ids = [item.benchmark_task_id for item in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("policy tasks must not contain duplicate benchmarkTaskId")
        return self

    @property
    def task_by_id(self) -> Mapping[str, OutcomePolicyTask]:
        return {item.benchmark_task_id: item for item in self.tasks}


class OutcomeMetricObservation(_OutcomeModel):
    metric: MetricName
    status: MetricStatus
    value: NumericValue | None = None
    expected_value: Literal[0, 1] = Field(default=1, alias="expectedValue")
    reason: NonEmptyString | None = None


class ToolRequirementObservation(_OutcomeModel):
    tool_name: NonEmptyString = Field(alias="toolName")
    requirement: ToolRequirement
    invoked: StrictBool
    observed_tool_call_ids: tuple[NonEmptyString, ...] = Field(
        default=(), alias="observedToolCallIds"
    )
    reason: NonEmptyString


class V2TaskProjection(_OutcomeModel):
    benchmark_task_id: NonEmptyString = Field(alias="benchmarkTaskId")
    task_type: TaskType = Field(alias="taskType")
    split: DatasetSplit
    v1_status: TaskSuccessStatus = Field(alias="v1Status")
    v2_status: V2OutcomeStatus = Field(alias="v2Status")
    outcome_authority: OutcomeAuthority = Field(alias="outcomeAuthority")
    outcome_authority_gap: StrictBool = Field(alias="outcomeAuthorityGap")
    outcome_metrics: tuple[OutcomeMetricObservation, ...] = Field(alias="outcomeMetrics")
    diagnostic_metrics: tuple[OutcomeMetricObservation, ...] = Field(
        default=(), alias="diagnosticMetrics"
    )
    semantic_adjudication: SemanticAdjudicationResult | None = Field(
        default=None,
        alias="semanticAdjudication",
    )
    semantic_used_for_final_outcome: StrictBool = Field(
        default=False,
        alias="semanticUsedForFinalOutcome",
    )
    tool_requirements: tuple[ToolRequirementObservation, ...] = Field(alias="toolRequirements")
    observed_tool_names: tuple[NonEmptyString, ...] = Field(alias="observedToolNames")


class RateSummary(_OutcomeModel):
    status: Literal["VALUE", "NOT_APPLICABLE"]
    value: StrictFloat | None = None
    numerator: StrictInt = Field(ge=0)
    denominator: StrictInt = Field(ge=0)
    unknown_count: StrictInt = Field(alias="unknownCount", ge=0)

    @model_validator(mode="after")
    def value_matches_status(self) -> RateSummary:
        if self.status == "VALUE":
            if self.denominator <= 0 or self.value is None:
                raise ValueError("VALUE rate requires a positive denominator and value")
        elif self.value is not None:
            raise ValueError("NOT_APPLICABLE rate must not carry a value")
        if self.numerator > self.denominator:
            raise ValueError("rate numerator must not exceed denominator")
        return self


class CategoryProjectionSummary(_OutcomeModel):
    category: TaskType
    task_count: StrictInt = Field(alias="taskCount", ge=0)
    v1_status_counts: dict[str, StrictInt] = Field(alias="v1StatusCounts")
    v2_status_counts: dict[str, StrictInt] = Field(alias="v2StatusCounts")
    outcome_authority_gap_count: StrictInt = Field(alias="outcomeAuthorityGapCount", ge=0)
    outcome_accuracy: RateSummary = Field(alias="outcomeAccuracy")


class OutcomeV2Projection(_OutcomeModel):
    schema_version: Literal["stage21-outcome-v2-projection/v1"] = Field(
        default="stage21-outcome-v2-projection/v1", alias="schemaVersion"
    )
    policy_version: NonEmptyString = Field(alias="policyVersion")
    dataset_id: NonEmptyString = Field(alias="datasetId")
    dataset_version: NonEmptyString = Field(alias="datasetVersion")
    task_schema_version: NonEmptyString = Field(alias="taskSchemaVersion")
    source_artifact: NonEmptyString = Field(alias="sourceArtifact")
    task_count: StrictInt = Field(alias="taskCount", ge=0)
    projected_task_count: StrictInt = Field(alias="projectedTaskCount", ge=0)
    split_counts: dict[str, StrictInt] = Field(alias="splitCounts")
    v1_status_counts: dict[str, StrictInt] = Field(alias="v1StatusCounts")
    v2_status_counts: dict[str, StrictInt] = Field(alias="v2StatusCounts")
    outcome_accuracy: RateSummary = Field(alias="outcomeAccuracy")
    tool_invocation_rate: RateSummary = Field(alias="toolInvocationRate")
    required_tool_miss_rate: RateSummary = Field(alias="requiredToolMissRate")
    required_tool_count: StrictInt = Field(alias="requiredToolCount", ge=0)
    optional_tool_count: StrictInt = Field(alias="optionalToolCount", ge=0)
    not_required_tool_count: StrictInt = Field(alias="notRequiredToolCount", ge=0)
    required_tool_invocation_count: StrictInt = Field(alias="requiredToolInvocationCount", ge=0)
    optional_tool_invocation_count: StrictInt = Field(alias="optionalToolInvocationCount", ge=0)
    required_tool_miss_count: StrictInt = Field(alias="requiredToolMissCount", ge=0)
    outcome_authority_gap_count: StrictInt = Field(alias="outcomeAuthorityGapCount", ge=0)
    outcome_authority_gap_task_ids: tuple[NonEmptyString, ...] = Field(
        alias="outcomeAuthorityGapTaskIds"
    )
    categories: tuple[CategoryProjectionSummary, ...]
    tasks: tuple[V2TaskProjection, ...]


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OutcomePolicyError(f"cannot read JSON artifact {path}: {exc}") from exc


def _validate_raw_policy_metrics(raw: object) -> None:
    if not isinstance(raw, dict):
        return
    raw_tasks = raw.get("tasks")
    if not isinstance(raw_tasks, list):
        return
    known_metrics = {metric.value for metric in MetricName}
    for index, item in enumerate(raw_tasks):
        if not isinstance(item, dict):
            continue
        metrics = item.get("outcomeMetrics")
        if not isinstance(metrics, list):
            continue
        unknown = [value for value in metrics if value not in known_metrics]
        if unknown:
            raise OutcomePolicyError(
                f"unknown metric in policy task index {index}: {', '.join(map(str, unknown))}"
            )


def _validate_policy_against_dataset(
    policy: OutcomePolicy,
    dataset: BenchmarkDataset,
) -> None:
    manifest = dataset.manifest
    if len(dataset.tasks) != 105:
        raise OutcomePolicyError(
            f"V2 policy requires the Formal105 dataset, found {len(dataset.tasks)} tasks"
        )
    expected_ids = {task.benchmark_task_id for task in dataset.tasks}
    actual_ids = {task.benchmark_task_id for task in policy.tasks}
    missing = sorted(expected_ids - actual_ids)
    unknown = sorted(actual_ids - expected_ids)
    if missing:
        raise OutcomePolicyError(f"missing task policy: {', '.join(missing)}")
    if unknown:
        raise OutcomePolicyError(f"unknown task policy: {', '.join(unknown)}")
    if len(policy.tasks) != 105:
        raise OutcomePolicyError(
            f"V2 policy must contain exactly 105 task policies, found {len(policy.tasks)}"
        )
    if policy.dataset_id != manifest.dataset_id:
        raise OutcomePolicyError(
            f"dataset mismatch: policy datasetId={policy.dataset_id!r}, "
            f"manifest datasetId={manifest.dataset_id!r}"
        )
    if policy.dataset_version != manifest.dataset_version:
        raise OutcomePolicyError(
            f"dataset mismatch: policy datasetVersion={policy.dataset_version!r}, "
            f"manifest datasetVersion={manifest.dataset_version!r}"
        )
    if policy.task_schema_version != manifest.task_schema_version:
        raise OutcomePolicyError(
            f"dataset mismatch: policy taskSchemaVersion={policy.task_schema_version!r}, "
            f"manifest taskSchemaVersion={manifest.task_schema_version!r}"
        )
    tasks_by_id = {task.benchmark_task_id: task for task in dataset.tasks}
    for entry in policy.tasks:
        task = tasks_by_id[entry.benchmark_task_id]
        if entry.task_type != task.task_type:
            raise OutcomePolicyError(
                f"task type mismatch for {entry.benchmark_task_id}: "
                f"{entry.task_type.value} != {task.task_type.value}"
            )
        manifest_entry = next(
            item for item in manifest.tasks if item.benchmark_task_id == entry.benchmark_task_id
        )
        if entry.split != manifest_entry.split:
            raise OutcomePolicyError(
                f"task split mismatch for {entry.benchmark_task_id}: "
                f"{entry.split.value} != {manifest_entry.split.value}"
            )


def load_outcome_policy(
    path: Path | None = None,
    *,
    dataset: BenchmarkDataset | None = None,
) -> OutcomePolicy:
    """Load and fail closed on the complete 105-task V2 policy sidecar."""

    policy_path = path or DEFAULT_OUTCOME_POLICY_PATH
    raw = _read_json(policy_path)
    _validate_raw_policy_metrics(raw)
    try:
        # The project-wide strict models intentionally reject mutable Python
        # lists, while JSON arrays are the persisted representation of tuples.
        policy = OutcomePolicy.model_validate_json(json.dumps(raw))
    except ValidationError as exc:
        raise OutcomePolicyError(f"invalid outcome policy: {exc}") from exc
    effective_dataset = dataset or load_dataset()
    _validate_policy_against_dataset(policy, effective_dataset)
    return policy


def discover_formal105_run() -> Path:
    """Find the one checked-in Formal105 candidate run without executing anything."""

    results_root = (
        _REPOSITORY_ROOT
        / "artifacts"
        / "stage21"
        / "formal-real-model-final"
        / "full-105"
        / "results"
    )
    candidates = sorted(results_root.glob("**/run.json"))
    if not candidates:
        raise FileNotFoundError(
            "no persisted Formal105 candidate run.json was found under artifacts/stage21"
        )
    if len(candidates) > 1:
        raise OutcomePolicyError(
            "multiple Formal105 candidate run artifacts found; select one explicitly: "
            + ", ".join(str(path) for path in candidates)
        )
    return candidates[0]


def load_persisted_formal105_run(path: Path) -> BenchmarkRun:
    """Parse an existing persisted BenchmarkRun; this function never invokes a model."""

    raw = _read_json(path)
    try:
        return BenchmarkRun.model_validate_json(json.dumps(raw))
    except ValidationError as exc:
        raise OutcomePolicyError(f"persisted Formal105 run is invalid: {exc}") from exc


def _metric_observations(
    result: BenchmarkTaskResult | None,
    policy: OutcomePolicyTask,
) -> tuple[OutcomeMetricObservation, ...]:
    by_metric = (
        {item.metric: item for item in result.evaluation_result.metrics}
        if result is not None and result.evaluation_result is not None
        else {}
    )
    observations: list[OutcomeMetricObservation] = []
    for metric in policy.outcome_metrics:
        expected_value = policy.expected_metric_values.get(metric, 1)
        sample = by_metric.get(metric)
        if sample is None:
            observations.append(
                OutcomeMetricObservation(
                    metric=metric,
                    status=MetricStatus.UNKNOWN,
                    expectedValue=expected_value,
                    reason="required Stage 19 metric is absent from the persisted result",
                )
            )
            continue
        observations.append(
            OutcomeMetricObservation(
                metric=metric,
                status=sample.status,
                value=sample.value,
                expectedValue=expected_value,
                reason=sample.reason,
            )
        )
    return tuple(observations)


def _diagnostic_observations(
    result: BenchmarkTaskResult | None,
    outcome_metrics: Iterable[MetricName],
) -> tuple[OutcomeMetricObservation, ...]:
    """Project every persisted non-outcome metric as an independent diagnostic.

    The V2 policy selects only facts that can gate the final task result.  The
    remaining Stage 19 metrics are still copied into the V2 sidecar so that a
    relaxed outcome cannot be mistaken for a claim that tool, parameter,
    evidence, safety-process, or runtime behavior was correct.
    """

    if result is None or result.evaluation_result is None:
        return ()
    outcome_metric_set = set(outcome_metrics)
    return tuple(
        OutcomeMetricObservation(
            metric=sample.metric,
            status=sample.status,
            value=sample.value,
            reason=sample.reason,
        )
        for sample in result.evaluation_result.metrics
        if sample.metric not in outcome_metric_set
    )


def _status_for_observations(
    observations: tuple[OutcomeMetricObservation, ...],
    mode: OutcomeMode,
) -> V2OutcomeStatus:
    statuses: list[V2OutcomeStatus] = []
    for observation in observations:
        if observation.status is MetricStatus.VALUE and observation.value is not None:
            value = float(observation.value)
            statuses.append(
                V2OutcomeStatus.PASS
                if value == float(observation.expected_value)
                else V2OutcomeStatus.FAIL
            )
        else:
            statuses.append(V2OutcomeStatus.UNKNOWN)
    if mode is OutcomeMode.ALL:
        if V2OutcomeStatus.FAIL in statuses:
            return V2OutcomeStatus.FAIL
        if V2OutcomeStatus.UNKNOWN in statuses:
            return V2OutcomeStatus.UNKNOWN
        return V2OutcomeStatus.PASS
    if V2OutcomeStatus.PASS in statuses:
        return V2OutcomeStatus.PASS
    if V2OutcomeStatus.UNKNOWN in statuses:
        return V2OutcomeStatus.UNKNOWN
    return V2OutcomeStatus.FAIL


def _v1_status(result: BenchmarkTaskResult | None) -> TaskSuccessStatus:
    if result is None or result.task_success is None:
        return TaskSuccessStatus.UNKNOWN
    return result.task_success.status


def _observed_tool_calls(
    result: BenchmarkTaskResult | None,
) -> tuple[ToolResultObservation, ...]:
    if result is None:
        return ()
    return result.tool_result_observations


def _semantic_projection(
    policy: OutcomePolicyTask,
    result: BenchmarkTaskResult | None,
    observed_status: V2OutcomeStatus,
    current_status: V2OutcomeStatus,
    requirements: tuple[ToolRequirementObservation, ...],
) -> tuple[V2OutcomeStatus, SemanticAdjudicationResult | None, bool]:
    """Apply an explicit semantic policy only to an otherwise unresolved result."""

    semantic = result.semantic_adjudication if result is not None else None
    if semantic is None or not policy.semantic_adjudication_allowed:
        return current_status, semantic, False
    if policy.task_type not in {TaskType.FAILURE_DIAGNOSIS, TaskType.E2E_APIOPS}:
        return current_status, semantic, False

    protected_failure = (
        result is None
        or result.status is not BenchmarkTaskStatus.SUCCESS
        or any(
            item.requirement is ToolRequirement.REQUIRED and not item.invoked
            for item in requirements
        )
    )
    if protected_failure:
        return (
            V2OutcomeStatus.UNKNOWN if current_status is V2OutcomeStatus.PASS else current_status,
            semantic,
            False,
        )
    if result is not None and result.evaluation_result is not None:
        deterministic_metrics = {
            MetricName.VALID_JSON,
            MetricName.SCHEMA_VALID,
            MetricName.CONTRACT_ACCEPTED,
            MetricName.EXACT_MATCH,
            MetricName.TOOL_PRECISION,
            MetricName.TOOL_RECALL,
            MetricName.TOOL_EXACT_SET_MATCH,
            MetricName.PARAMETER_ACCURACY,
            MetricName.EVIDENCE_HIT,
            MetricName.SAFETY_ACCURACY,
        }
        for sample in result.evaluation_result.metrics:
            if sample.metric not in deterministic_metrics:
                continue
            if sample.status is MetricStatus.NOT_APPLICABLE:
                continue
            if sample.status is not MetricStatus.VALUE or sample.value != 1:
                return (
                    V2OutcomeStatus.UNKNOWN
                    if current_status is V2OutcomeStatus.PASS
                    else current_status,
                    semantic,
                    False,
                )
    if policy.outcome_authority is OutcomeAuthority.OUTCOME_AUTHORITY_GAP:
        return current_status, semantic, False
    if current_status is V2OutcomeStatus.FAIL or observed_status is V2OutcomeStatus.FAIL:
        return current_status, semantic, False
    if observed_status is not V2OutcomeStatus.UNKNOWN or not semantic.eligible:
        return current_status, semantic, False
    if semantic.decision is SemanticDecision.SEMANTIC_MATCH:
        used = semantic.model_copy(update={"used_for_final_outcome": True})
        return V2OutcomeStatus.PASS, used, True
    if semantic.decision is SemanticDecision.SEMANTIC_MISMATCH:
        used = semantic.model_copy(update={"used_for_final_outcome": True})
        return V2OutcomeStatus.FAIL, used, True
    return current_status, semantic, False


def _task_projection(
    policy: OutcomePolicyTask,
    result: BenchmarkTaskResult | None,
) -> V2TaskProjection:
    observations = _metric_observations(result, policy)
    observed_status = _status_for_observations(observations, policy.outcome_mode)
    normalized_facts = (
        {}
        if result is None or result.formal_evidence is None
        else result.formal_evidence.normalized_evaluation_facts
    )
    raw_structured = normalized_facts.get("structured_facts")
    if not isinstance(raw_structured, list):
        raw_structured = normalized_facts.get("structuredFacts")
    normalized_structured = (
        {
            str(item["name"]): item["value"]
            for item in raw_structured
            if isinstance(item, dict) and "name" in item and "value" in item
        }
        if isinstance(raw_structured, list)
        else {}
    )
    # Candidate assertions are observations, not independent business-code
    # authority. Preserve their raw values for exact-match failures, but do not
    # close a historical authority gap merely because the model guessed the GT.
    candidate_codes = {
        normalized_structured[name]
        for name in ("expected_error_code", "business_error")
        if isinstance(normalized_structured.get(name), str)
    }
    code_values = normalized_structured.get("response_code_contract_values")
    schema_code_authority = (
        normalized_structured.get("metadata_authority") == "JAVA_OPENAPI_BASELINE"
        and normalized_structured.get("response_code_contract_authority") == "JAVA_RESPONSE_SCHEMA"
        and isinstance(code_values, list)
        and bool(code_values)
        and all(isinstance(value, str) and value for value in code_values)
    )
    runner_code = normalized_structured.get("java_runner_business_outcome")
    runner_code_authority = (
        normalized_structured.get("report_authority") == "JAVA_TEST_REPORT"
        and normalized_structured.get("response_snapshot_present") is True
        and isinstance(runner_code, str)
        and bool(runner_code)
    )
    code_authority_satisfied = not candidate_codes or (
        len(candidate_codes) == 1 and (schema_code_authority or runner_code_authority)
    )
    code_contract_mismatch = bool(candidate_codes) and (
        (schema_code_authority and not candidate_codes.issubset(set(code_values)))
        or (runner_code_authority and candidate_codes != {runner_code})
    )
    if policy.task_type is TaskType.TESTCASE_GENERATION and code_contract_mismatch:
        observed_status = V2OutcomeStatus.FAIL
    testcase_authority_satisfied = (
        policy.task_type is TaskType.TESTCASE_GENERATION
        and code_authority_satisfied
        and any(
            item.metric is MetricName.EXACT_MATCH and item.status is MetricStatus.VALUE
            for item in observations
        )
        and all(item.status is MetricStatus.VALUE for item in observations)
    )
    insufficient_authority_satisfied = (
        policy.task_type is TaskType.FAILURE_DIAGNOSIS
        and policy.scenario == "INSUFFICIENT_EVIDENCE"
        and result is not None
        and result.status is BenchmarkTaskStatus.SUCCESS
        and normalized_structured.get("diagnosis_outcome") == "INSUFFICIENT_EVIDENCE"
        and normalized_structured.get("sufficient_evidence") is False
        and any(
            item.metric is MetricName.EXACT_MATCH
            and item.status is MetricStatus.VALUE
            and item.value == 1
            for item in observations
        )
        and all(item.status is MetricStatus.VALUE for item in observations)
    )
    terminal_facts = (
        {}
        if result is None or result.formal_evidence is None
        else {item.name: item.value for item in result.formal_evidence.terminal_decision_facts}
    )
    safety_terminal = terminal_facts.get("safety_terminal_decision")
    safety_authority = terminal_facts.get("safety_decision_authority")
    safety_authority_satisfied = (
        policy.task_type is TaskType.TOOL_SAFETY
        and any(
            item.metric is MetricName.SAFETY_ACCURACY and item.status is MetricStatus.VALUE
            for item in observations
        )
        and safety_terminal is not None
        and safety_terminal == terminal_facts.get("safety_outcome")
        and safety_authority
        in {
            "EXPLICIT_RUNTIME",
            "HUMAN_APPROVAL",
            "HUMAN_APPROVAL_GATE",
            "JAVA_TOOL_GATEWAY",
            "PYTHON_PREFLIGHT",
            "PYTHON_RUNTIME_CONTRACT",
        }
        and (
            safety_authority != "JAVA_TOOL_GATEWAY"
            or bool(result and result.tool_result_observations)
        )
    )
    e2e_java_authority_satisfied = (
        policy.task_type is TaskType.E2E_APIOPS
        and result is not None
        and result.status is BenchmarkTaskStatus.SUCCESS
        and normalized_structured.get("contract_accepted") is True
        and normalized_structured.get("metadata_authority") == "JAVA_OPENAPI_BASELINE"
        and normalized_structured.get("report_authority") == "JAVA_TEST_REPORT"
        and normalized_structured.get("java_runner_status") == "SUCCESS"
        and normalized_structured.get("runner_status") == "SUCCESS"
        and normalized_structured.get("response_snapshot_present") is True
        and any(
            item.metric is MetricName.EXACT_MATCH and item.status is MetricStatus.VALUE
            for item in observations
        )
        and all(item.status is MetricStatus.VALUE for item in observations)
    )
    rag_observations = tuple(
        item for item in _observed_tool_calls(result) if item.tool_name == "rag.search"
    )
    zero_hit_java_authority_satisfied = (
        policy.task_type is TaskType.RAG_EVIDENCE_RETRIEVAL
        and result is not None
        and result.status is BenchmarkTaskStatus.SUCCESS
        and normalized_structured.get("tool_status") == "SUCCESS"
        and normalized_structured.get("authorization_outcome") == "AUTHORIZED"
        and type(normalized_structured.get("result_count")) is int
        and normalized_structured.get("result_count") == 0
        and normalized_structured.get("evidence_leakage") is False
        and normalized_structured.get("evidence_ids") == []
        and len(rag_observations) == 1
        and rag_observations[0].tool_call_id in result.tool_call_ids
        and rag_observations[0].status == "SUCCESS"
        and rag_observations[0].has_data is True
        and rag_observations[0].mapping_status == "SUCCESS"
        and rag_observations[0].result_count == 0
        and any(
            item.metric is MetricName.EXACT_MATCH and item.status is MetricStatus.VALUE
            for item in observations
        )
        and all(item.status is MetricStatus.VALUE for item in observations)
    )
    # A historical gap is not permanent: a successful, persisted Java mapping
    # plus complete exact outcome facts supplies the formerly missing authority.
    # No task identity, guessed empty response, or metric alone can close it.
    effective_authority = (
        OutcomeAuthority.SUPPORTED_BY_EXISTING_FACTS
        if (
            testcase_authority_satisfied
            or insufficient_authority_satisfied
            or safety_authority_satisfied
            or e2e_java_authority_satisfied
            or zero_hit_java_authority_satisfied
        )
        else policy.outcome_authority
    )
    if effective_authority is OutcomeAuthority.OUTCOME_AUTHORITY_GAP:
        # An authority gap prevents a PASS claim, but it must not erase a
        # decisive final-outcome failure.  This is the key fail-closed
        # distinction between "cannot prove success" and "proved incorrect".
        v2_status = (
            V2OutcomeStatus.FAIL
            if observed_status is V2OutcomeStatus.FAIL
            else V2OutcomeStatus.UNKNOWN
        )
    else:
        v2_status = observed_status
    tool_observations = _observed_tool_calls(result)
    by_tool: dict[str, list[ToolResultObservation]] = {}
    for observation in tool_observations:
        by_tool.setdefault(observation.tool_name, []).append(observation)
    requirement_projections: list[ToolRequirementObservation] = []
    for requirement in policy.tool_requirements:
        observed = tuple(by_tool.get(requirement.tool_name, ()))
        observed_ids = tuple(item.tool_call_id for item in observed)
        if not observed_ids and result is not None and len(policy.tool_requirements) == 1:
            # BenchmarkTaskResult retains Tool Gateway call IDs even when an older
            # persisted artifact lacks the projected ToolResult observation.  A
            # single policy requirement makes that invocation attribution
            # unambiguous without consulting GroundTruth.
            observed_ids = tuple(result.tool_call_ids)
        requirement_projections.append(
            ToolRequirementObservation(
                toolName=requirement.tool_name,
                requirement=requirement.requirement,
                invoked=bool(observed_ids),
                observedToolCallIds=observed_ids,
                reason=(
                    "matching persisted Java ToolResult observation exists"
                    if observed
                    else (
                        "persisted Tool Gateway call ID establishes the single declared "
                        "tool invocation"
                        if observed_ids
                        else (
                            "no matching persisted Java ToolResult observation or "
                            "attributable Tool Gateway call ID exists"
                        )
                    )
                ),
            )
        )
    v2_status, semantic_adjudication, semantic_used = _semantic_projection(
        policy,
        result,
        observed_status,
        v2_status,
        tuple(requirement_projections),
    )
    return V2TaskProjection(
        benchmarkTaskId=policy.benchmark_task_id,
        taskType=policy.task_type,
        split=policy.split,
        v1Status=_v1_status(result),
        v2Status=v2_status,
        outcomeAuthority=effective_authority,
        outcomeAuthorityGap=(effective_authority is OutcomeAuthority.OUTCOME_AUTHORITY_GAP),
        outcomeMetrics=observations,
        diagnosticMetrics=_diagnostic_observations(result, policy.outcome_metrics),
        semanticAdjudication=semantic_adjudication,
        semanticUsedForFinalOutcome=semantic_used,
        toolRequirements=tuple(requirement_projections),
        observedToolNames=tuple(sorted({item.tool_name for item in tool_observations})),
    )


def _rate(numerator: int, denominator: int, unknown_count: int = 0) -> RateSummary:
    if denominator == 0:
        return RateSummary(
            status="NOT_APPLICABLE",
            numerator=0,
            denominator=0,
            unknownCount=unknown_count,
        )
    return RateSummary(
        status="VALUE",
        value=float(numerator / denominator),
        numerator=numerator,
        denominator=denominator,
        unknownCount=unknown_count,
    )


def _status_counts(values: Iterable[StrEnum]) -> dict[str, int]:
    counts = Counter(value.value for value in values)
    return {key: counts[key] for key in sorted(counts)}


def _outcome_rate(tasks: Iterable[V2TaskProjection]) -> RateSummary:
    values = tuple(tasks)
    passes = sum(item.v2_status is V2OutcomeStatus.PASS for item in values)
    fails = sum(item.v2_status is V2OutcomeStatus.FAIL for item in values)
    unknown = sum(item.v2_status is V2OutcomeStatus.UNKNOWN for item in values)
    return _rate(passes, passes + fails, unknown)


def _category_summary(
    category: TaskType,
    tasks: tuple[V2TaskProjection, ...],
) -> CategoryProjectionSummary:
    return CategoryProjectionSummary(
        category=category,
        taskCount=len(tasks),
        v1StatusCounts=_status_counts(item.v1_status for item in tasks),
        v2StatusCounts=_status_counts(item.v2_status for item in tasks),
        outcomeAuthorityGapCount=sum(item.outcome_authority_gap for item in tasks),
        outcomeAccuracy=_outcome_rate(tasks),
    )


def project_outcome_v2(
    run: BenchmarkRun,
    policy: OutcomePolicy,
    *,
    source_artifact: Path | str = "in-memory",
    require_full_dataset: bool = True,
) -> OutcomeV2Projection:
    """Project a persisted execution run into V2 without changing its contents."""

    if run.dataset_id != policy.dataset_id:
        raise OutcomePolicyError("dataset mismatch between run and V2 policy")
    if run.dataset_version != policy.dataset_version:
        raise OutcomePolicyError("dataset version mismatch between run and V2 policy")
    if run.task_schema_version != policy.task_schema_version:
        raise OutcomePolicyError("task schema version mismatch between run and V2 policy")

    results_by_id: dict[str, BenchmarkTaskResult] = {}
    for result in run.results:
        if result.benchmark_task_id in results_by_id:
            raise OutcomePolicyError(
                f"duplicate task result in persisted run: {result.benchmark_task_id}"
            )
        results_by_id[result.benchmark_task_id] = result
    policy_ids = set(policy.task_by_id)
    result_ids = set(results_by_id)
    selected_ids = tuple(run.selected_task_ids)
    if len(selected_ids) != len(set(selected_ids)):
        raise OutcomePolicyError("persisted run contains duplicate selected task IDs")
    if require_full_dataset and set(selected_ids) != policy_ids:
        missing_selected = sorted(policy_ids - set(selected_ids))
        unknown_selected = sorted(set(selected_ids) - policy_ids)
        details = []
        if missing_selected:
            details.append("missing=" + ",".join(missing_selected))
        if unknown_selected:
            details.append("unknown=" + ",".join(unknown_selected))
        raise OutcomePolicyError(
            "persisted run selectedTaskIds do not match policy: " + "; ".join(details)
        )
    missing = sorted(policy_ids - result_ids)
    unknown = sorted(result_ids - policy_ids)
    if require_full_dataset and missing:
        raise OutcomePolicyError(f"projected run is missing task results: {', '.join(missing)}")
    if unknown:
        raise OutcomePolicyError(
            f"projected run contains unknown task results: {', '.join(unknown)}"
        )
    for task_id, result in results_by_id.items():
        policy_task = policy.task_by_id[task_id]
        if result.task_type != policy_task.task_type:
            raise OutcomePolicyError(
                f"task type mismatch for persisted result {task_id}: "
                f"{result.task_type.value} != {policy_task.task_type.value}"
            )

    task_projections = tuple(
        _task_projection(policy_task, results_by_id.get(policy_task.benchmark_task_id))
        for policy_task in policy.tasks
        if require_full_dataset or policy_task.benchmark_task_id in results_by_id
    )
    if require_full_dataset and len(task_projections) != len(policy.tasks):
        raise OutcomePolicyError("projected task count does not equal policy task count")

    requirements = tuple(
        requirement for task in task_projections for requirement in task.tool_requirements
    )
    required = tuple(item for item in requirements if item.requirement is ToolRequirement.REQUIRED)
    optional = tuple(item for item in requirements if item.requirement is ToolRequirement.OPTIONAL)
    not_required = tuple(
        item for item in requirements if item.requirement is ToolRequirement.NOT_REQUIRED
    )
    required_invoked = sum(item.invoked for item in required)
    optional_invoked = sum(item.invoked for item in optional)
    required_miss = len(required) - required_invoked
    invocation_denominator = len(required) + len(optional)
    invocation_numerator = required_invoked + optional_invoked
    categories = tuple(
        _category_summary(
            category,
            tuple(item for item in task_projections if item.task_type is category),
        )
        for category in TaskType
    )
    gaps = tuple(item.benchmark_task_id for item in task_projections if item.outcome_authority_gap)
    return OutcomeV2Projection(
        policyVersion=policy.policy_version,
        datasetId=policy.dataset_id,
        datasetVersion=policy.dataset_version,
        taskSchemaVersion=policy.task_schema_version,
        sourceArtifact=str(source_artifact),
        taskCount=len(policy.tasks),
        projectedTaskCount=len(task_projections),
        splitCounts={
            split.value.upper(): sum(item.split is split for item in task_projections)
            for split in DatasetSplit
            if split is not DatasetSplit.UNASSIGNED
        },
        v1StatusCounts=_status_counts(item.v1_status for item in task_projections),
        v2StatusCounts=_status_counts(item.v2_status for item in task_projections),
        outcomeAccuracy=_outcome_rate(task_projections),
        toolInvocationRate=_rate(invocation_numerator, invocation_denominator),
        requiredToolMissRate=_rate(required_miss, len(required)),
        requiredToolCount=len(required),
        optionalToolCount=len(optional),
        notRequiredToolCount=len(not_required),
        requiredToolInvocationCount=required_invoked,
        optionalToolInvocationCount=optional_invoked,
        requiredToolMissCount=required_miss,
        outcomeAuthorityGapCount=len(gaps),
        outcomeAuthorityGapTaskIds=gaps,
        categories=categories,
        tasks=task_projections,
    )


def render_outcome_v2_summary(projection: OutcomeV2Projection) -> str:
    """Render the required human-readable offline projection summary."""

    def rate_text(rate: RateSummary) -> str:
        return "N/A" if rate.status == "NOT_APPLICABLE" else f"{rate.value:.4f}"

    lines = [
        "# Stage21 Benchmark V2 Offline Projection",
        "",
        "This report is a projection of an already-persisted Formal105 artifact. "
        "It does not call a model or rerun BenchmarkRunner.",
        "",
        f"- Policy: `{projection.policy_version}`",
        f"- Dataset: `{projection.dataset_id}@{projection.dataset_version}`",
        f"- Task schema: `{projection.task_schema_version}`",
        f"- Source artifact: `{projection.source_artifact}`",
        f"- Policy tasks: **{projection.task_count}**",
        f"- Projected tasks: **{projection.projected_task_count}**",
        "",
        "## V1 / V2 outcome status",
        "",
        f"- V1 PASS / FAIL / UNKNOWN: `{projection.v1_status_counts.get('PASS', 0)}` / "
        f"`{projection.v1_status_counts.get('FAIL', 0)}` / "
        f"`{projection.v1_status_counts.get('UNKNOWN', 0)}`",
        f"- V2 PASS / FAIL / UNKNOWN: `{projection.v2_status_counts.get('PASS', 0)}` / "
        f"`{projection.v2_status_counts.get('FAIL', 0)}` / "
        f"`{projection.v2_status_counts.get('UNKNOWN', 0)}`",
        f"- Outcome Accuracy: `{rate_text(projection.outcome_accuracy)}` "
        f"({projection.outcome_accuracy.numerator}/{projection.outcome_accuracy.denominator}; "
        f"unknown={projection.outcome_accuracy.unknown_count})",
        f"- OUTCOME_AUTHORITY_GAP: `{projection.outcome_authority_gap_count}`",
        "",
        "## Tool requirements",
        "",
        f"- REQUIRED tool count: `{projection.required_tool_count}`",
        f"- OPTIONAL tool count: `{projection.optional_tool_count}`",
        f"- NOT_REQUIRED tool count: `{projection.not_required_tool_count}`",
        f"- Tool Invocation Rate: `{rate_text(projection.tool_invocation_rate)}` "
        f"({projection.tool_invocation_rate.numerator}/{projection.tool_invocation_rate.denominator})",
        f"- Required Tool Miss: `{projection.required_tool_miss_count}`",
        f"- Required Tool Miss Rate: `{rate_text(projection.required_tool_miss_rate)}` "
        f"({projection.required_tool_miss_rate.numerator}/"
        f"{projection.required_tool_miss_rate.denominator})",
        "",
        "## Split counts",
        "",
        "| Split | Tasks |",
        "| --- | ---: |",
    ]
    lines.extend(f"| `{split}` | {count} |" for split, count in projection.split_counts.items())
    lines.extend(
        [
            "",
            "## Category projection",
            "",
            "| Category | Tasks | V1 PASS | V1 FAIL | V1 UNKNOWN | V2 PASS | V2 FAIL | "
            "V2 UNKNOWN | Outcome Accuracy | Gaps |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for category in projection.categories:
        lines.append(
            f"| `{category.category.value}` | {category.task_count} | "
            f"{category.v1_status_counts.get('PASS', 0)} | "
            f"{category.v1_status_counts.get('FAIL', 0)} | "
            f"{category.v1_status_counts.get('UNKNOWN', 0)} | "
            f"{category.v2_status_counts.get('PASS', 0)} | "
            f"{category.v2_status_counts.get('FAIL', 0)} | "
            f"{category.v2_status_counts.get('UNKNOWN', 0)} | "
            f"{rate_text(category.outcome_accuracy)} | "
            f"{category.outcome_authority_gap_count} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Stage19 metric formulas are read-only inputs to this projection.",
            "- V1 task files, GroundTruth, shared schema, and Agent Prompt are not read "
            "or changed by projection.",
            "- Tool invocation facts come from persisted `toolResultObservations`; missing "
            "observations are not inferred from GroundTruth.",
            "",
        ]
    )
    return "\n".join(lines)


def persist_outcome_v2_projection(
    projection: OutcomeV2Projection,
    output_dir: Path = DEFAULT_OFFLINE_PROJECTION_DIR,
) -> tuple[Path, Path]:
    """Persist the JSON and Markdown projection artifacts."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "outcome-v2.json"
    summary_path = output_dir / "outcome-v2-summary.md"
    json_path.write_text(
        json.dumps(projection.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    summary_path.write_text(render_outcome_v2_summary(projection), encoding="utf-8", newline="\n")
    return json_path, summary_path


def load_persisted_outcome_v2_projection(path: Path | str) -> OutcomeV2Projection:
    """Load a prior V2 projection for a read-only before/after comparison."""

    projection_path = Path(path)
    raw = _read_json(projection_path)
    try:
        return OutcomeV2Projection.model_validate_json(json.dumps(raw))
    except ValidationError as exc:
        raise OutcomePolicyError(
            f"persisted V2 projection is invalid: {projection_path}: {exc}"
        ) from exc


def _status_counts_with_zeros(counts: Mapping[str, int]) -> dict[str, int]:
    return {status.value: int(counts.get(status.value, 0)) for status in V2OutcomeStatus}


def _rate_payload(rate: RateSummary) -> dict[str, Any]:
    return rate.model_dump(mode="json")


def build_outcome_v2_delta(
    previous: OutcomeV2Projection,
    current: OutcomeV2Projection,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build task- and category-level deltas without re-evaluating any task."""

    previous_tasks = {item.benchmark_task_id: item for item in previous.tasks}
    current_tasks = {item.benchmark_task_id: item for item in current.tasks}
    if set(previous_tasks) != set(current_tasks):
        missing = sorted(set(previous_tasks) - set(current_tasks))
        added = sorted(set(current_tasks) - set(previous_tasks))
        raise OutcomePolicyError(
            "cannot compare V2 projections with different task IDs: "
            f"missing={missing}; added={added}"
        )

    transitions: Counter[str] = Counter()
    task_rows: list[dict[str, Any]] = []
    for task_id in current_tasks:
        old = previous_tasks[task_id]
        new = current_tasks[task_id]
        transition = f"{old.v2_status.value}->{new.v2_status.value}"
        transitions[transition] += 1
        if old.v2_status is new.v2_status:
            reason = "status unchanged"
        elif old.v2_status is V2OutcomeStatus.UNKNOWN and new.v2_status is V2OutcomeStatus.FAIL:
            reason = (
                "a decisive final-outcome metric failure is now retained as FAIL; "
                "the previous authority-gap ceiling had reported UNKNOWN"
            )
        elif new.v2_status is V2OutcomeStatus.PASS:
            reason = "current outcome authority and final facts prove the requested result"
        elif new.v2_status is V2OutcomeStatus.FAIL:
            reason = "current outcome-critical facts prove the requested result incorrect"
        else:
            reason = "current outcome-critical authority is insufficient to prove PASS"
        task_rows.append(
            {
                "benchmarkTaskId": task_id,
                "taskType": new.task_type.value,
                "split": new.split.value,
                "oldStatus": old.v2_status.value,
                "newStatus": new.v2_status.value,
                "transition": transition,
                "oldOutcomeAuthorityGap": old.outcome_authority_gap,
                "newOutcomeAuthorityGap": new.outcome_authority_gap,
                "reason": reason,
            }
        )

    old_counts = _status_counts_with_zeros(previous.v2_status_counts)
    new_counts = _status_counts_with_zeros(current.v2_status_counts)
    task_delta = {
        "schemaVersion": "stage21-outcome-v2-task-delta/v1",
        "previousPolicyVersion": previous.policy_version,
        "currentPolicyVersion": current.policy_version,
        "taskCount": current.task_count,
        "old": {
            "statusCounts": old_counts,
            "outcomeAccuracy": _rate_payload(previous.outcome_accuracy),
        },
        "new": {
            "statusCounts": new_counts,
            "outcomeAccuracy": _rate_payload(current.outcome_accuracy),
        },
        "delta": {
            "PASS": new_counts["PASS"] - old_counts["PASS"],
            "FAIL": new_counts["FAIL"] - old_counts["FAIL"],
            "UNKNOWN": new_counts["UNKNOWN"] - old_counts["UNKNOWN"],
            "unknownReducedBy": old_counts["UNKNOWN"] - new_counts["UNKNOWN"],
            "failToPass": transitions["FAIL->PASS"],
            "unknownToPass": transitions["UNKNOWN->PASS"],
            "unknownToFail": transitions["UNKNOWN->FAIL"],
            "passToFail": transitions["PASS->FAIL"],
        },
        "transitionCounts": dict(sorted(transitions.items())),
        "tasks": task_rows,
        "changedTasks": [row for row in task_rows if row["oldStatus"] != row["newStatus"]],
    }

    previous_categories = {item.category.value: item for item in previous.categories}
    current_categories = {item.category.value: item for item in current.categories}
    if set(previous_categories) != set(current_categories):
        raise OutcomePolicyError("cannot compare V2 projections with different categories")
    category_rows: list[dict[str, Any]] = []
    for category in current_categories:
        old = previous_categories[category]
        new = current_categories[category]
        old_category_counts = _status_counts_with_zeros(old.v2_status_counts)
        new_category_counts = _status_counts_with_zeros(new.v2_status_counts)
        category_rows.append(
            {
                "category": category,
                "taskCount": new.task_count,
                "old": {
                    "statusCounts": old_category_counts,
                    "outcomeAccuracy": _rate_payload(old.outcome_accuracy),
                    "outcomeAuthorityGapCount": old.outcome_authority_gap_count,
                },
                "new": {
                    "statusCounts": new_category_counts,
                    "outcomeAccuracy": _rate_payload(new.outcome_accuracy),
                    "outcomeAuthorityGapCount": new.outcome_authority_gap_count,
                },
                "delta": {
                    "PASS": new_category_counts["PASS"] - old_category_counts["PASS"],
                    "FAIL": new_category_counts["FAIL"] - old_category_counts["FAIL"],
                    "UNKNOWN": new_category_counts["UNKNOWN"] - old_category_counts["UNKNOWN"],
                    "outcomeAuthorityGapCount": (
                        new.outcome_authority_gap_count - old.outcome_authority_gap_count
                    ),
                },
            }
        )
    category_delta = {
        "schemaVersion": "stage21-outcome-v2-category-delta/v1",
        "previousPolicyVersion": previous.policy_version,
        "currentPolicyVersion": current.policy_version,
        "categories": category_rows,
    }
    return task_delta, category_delta


def _diagnostic_metric_status_counts(
    projection: OutcomeV2Projection,
) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {}
    for task in projection.tasks:
        for observation in task.diagnostic_metrics:
            counts.setdefault(observation.metric.value, Counter())[observation.status.value] += 1
    return {
        metric: {status: count for status, count in sorted(values.items())}
        for metric, values in sorted(counts.items())
    }


def persist_offline_outcome_v2_projection(
    projection: OutcomeV2Projection,
    *,
    output_dir: Path = DEFAULT_OFFLINE_PROJECTION_DIR,
    previous_projection: OutcomeV2Projection | None = None,
) -> tuple[Path, Path, Path, Path, Path]:
    """Persist the V2 projection and the required offline comparison artifacts."""

    json_path, summary_path = persist_outcome_v2_projection(projection, output_dir)
    task_delta: dict[str, Any]
    category_delta: dict[str, Any]
    if previous_projection is None:
        task_delta = {
            "schemaVersion": "stage21-outcome-v2-task-delta/v1",
            "previous": None,
            "currentPolicyVersion": projection.policy_version,
            "tasks": [],
            "changedTasks": [],
        }
        category_delta = {
            "schemaVersion": "stage21-outcome-v2-category-delta/v1",
            "previous": None,
            "currentPolicyVersion": projection.policy_version,
            "categories": [],
        }
    else:
        task_delta, category_delta = build_outcome_v2_delta(previous_projection, projection)
    summary = {
        "schemaVersion": "stage21-outcome-v2-offline-summary/v1",
        "policyVersion": projection.policy_version,
        "dataset": {
            "id": projection.dataset_id,
            "version": projection.dataset_version,
            "taskSchemaVersion": projection.task_schema_version,
        },
        "sourceArtifact": projection.source_artifact,
        "taskCount": projection.task_count,
        "projectedTaskCount": projection.projected_task_count,
        "v1StatusCounts": projection.v1_status_counts,
        "v2StatusCounts": projection.v2_status_counts,
        "outcomeAccuracy": _rate_payload(projection.outcome_accuracy),
        "outcomeAuthorityGapCount": projection.outcome_authority_gap_count,
        "diagnosticMetricStatusCounts": _diagnostic_metric_status_counts(projection),
        "comparison": {
            "previousPolicyVersion": (
                previous_projection.policy_version if previous_projection is not None else None
            ),
            "taskDelta": task_delta["delta"] if "delta" in task_delta else None,
        },
    }
    summary_json_path = output_dir / "outcome-v2-summary.json"
    task_delta_path = output_dir / "task-delta.json"
    category_delta_path = output_dir / "category-delta.json"
    for path, value in (
        (summary_json_path, summary),
        (task_delta_path, task_delta),
        (category_delta_path, category_delta),
    ):
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return json_path, summary_json_path, summary_path, task_delta_path, category_delta_path


def project_persisted_formal105(
    *,
    policy_path: Path | None = None,
    run_path: Path | None = None,
    output_dir: Path = DEFAULT_OFFLINE_PROJECTION_DIR,
    previous_projection_path: Path | None = None,
) -> OutcomeV2Projection:
    """Run the offline projection workflow over existing Formal105 artifacts."""

    policy = load_outcome_policy(policy_path)
    candidate = run_path or discover_formal105_run()
    run = load_persisted_formal105_run(candidate)
    projection = project_outcome_v2(run, policy, source_artifact=candidate)
    previous = (
        load_persisted_outcome_v2_projection(previous_projection_path)
        if previous_projection_path is not None and previous_projection_path.is_file()
        else None
    )
    persist_offline_outcome_v2_projection(
        projection,
        output_dir=output_dir,
        previous_projection=previous,
    )
    return projection


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project a persisted Stage21 Formal105 run into V2."
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_OUTCOME_POLICY_PATH)
    parser.add_argument("--run", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OFFLINE_PROJECTION_DIR)
    parser.add_argument("--previous-projection", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    projection = project_persisted_formal105(
        policy_path=args.policy,
        run_path=args.run,
        output_dir=args.output_dir,
        previous_projection_path=args.previous_projection,
    )
    print(
        "STAGE21_V2_OFFLINE_PROJECTION "
        + json.dumps(
            {
                "policyTasks": projection.task_count,
                "projectedTasks": projection.projected_task_count,
                "v1StatusCounts": projection.v1_status_counts,
                "v2StatusCounts": projection.v2_status_counts,
                "outcomeAuthorityGaps": projection.outcome_authority_gap_count,
                "requiredTools": projection.required_tool_count,
                "optionalTools": projection.optional_tool_count,
                "requiredToolMisses": projection.required_tool_miss_count,
            },
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "CategoryProjectionSummary",
    "DEFAULT_FORMAL105_RUN_GLOB",
    "DEFAULT_OFFLINE_PROJECTION_DIR",
    "DEFAULT_PREVIOUS_PROJECTION_PATH",
    "DEFAULT_OUTCOME_POLICY_PATH",
    "OutcomeAuthority",
    "OutcomeMetricObservation",
    "OutcomeMode",
    "OutcomePolicy",
    "OutcomePolicyError",
    "OutcomePolicyTask",
    "OutcomePolicyToolRequirement",
    "OutcomeV2Projection",
    "RateSummary",
    "ToolRequirement",
    "ToolRequirementObservation",
    "V2OutcomeStatus",
    "V2TaskProjection",
    "discover_formal105_run",
    "load_outcome_policy",
    "load_persisted_outcome_v2_projection",
    "load_persisted_formal105_run",
    "main",
    "persist_outcome_v2_projection",
    "persist_offline_outcome_v2_projection",
    "build_outcome_v2_delta",
    "project_outcome_v2",
    "project_persisted_formal105",
    "render_outcome_v2_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
