"""Strict Stage 21 views over the shared EvaluationTask contract."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator

from app.evaluator import MetricName, ParameterMatchPolicy
from app.schemas.testcase_dsl import JsonValue

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]


class _BenchmarkModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
        frozen=True,
        validate_default=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class TaskType(StrEnum):
    TESTCASE_GENERATION = "TESTCASE_GENERATION"
    FAILURE_DIAGNOSIS = "FAILURE_DIAGNOSIS"
    TOOL_SAFETY = "TOOL_SAFETY"
    RAG_EVIDENCE_RETRIEVAL = "RAG_EVIDENCE_RETRIEVAL"
    E2E_APIOPS = "E2E_APIOPS"


class InitialStateKind(StrEnum):
    LITERAL = "LITERAL"
    JAVA_RESOURCE = "JAVA_RESOURCE"
    PYTHON_FIXTURE = "PYTHON_FIXTURE"


class LiteralSetup(_BenchmarkModel):
    kind: Literal["LITERAL"] = "LITERAL"
    key: NonEmptyString
    value: JsonValue


class JavaResourceReference(_BenchmarkModel):
    kind: Literal["JAVA_RESOURCE"] = "JAVA_RESOURCE"
    key: NonEmptyString
    ref: NonEmptyString


class PythonFixtureReference(_BenchmarkModel):
    kind: Literal["PYTHON_FIXTURE"] = "PYTHON_FIXTURE"
    key: NonEmptyString
    ref: NonEmptyString


InitialStateEntry = Annotated[
    LiteralSetup | JavaResourceReference | PythonFixtureReference,
    Field(discriminator="kind"),
]


class InitialState(_BenchmarkModel):
    entries: tuple[InitialStateEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def keys_must_be_unique(self) -> InitialState:
        keys = [entry.key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("initialState entry keys must be unique")
        return self


class GroundTruthRef(_BenchmarkModel):
    ground_truth_id: NonEmptyString = Field(alias="groundTruthId")
    version: NonEmptyString


class ExpectedToolCallSpec(_BenchmarkModel):
    """Task-side syntax mapped directly to Stage 19 ExpectedToolArguments."""

    tool_name: NonEmptyString = Field(alias="toolName")
    params_contains: dict[StrictStr, JsonValue] = Field(
        default_factory=dict,
        alias="paramsContains",
    )
    match_policy: ParameterMatchPolicy | None = Field(default=None, alias="matchPolicy")
    optional_fields: tuple[NonEmptyString, ...] = Field(default=(), alias="optionalFields")
    case_insensitive_fields: tuple[NonEmptyString, ...] = Field(
        default=(),
        alias="caseInsensitiveFields",
    )
    trim_fields: tuple[NonEmptyString, ...] = Field(default=(), alias="trimFields")
    order_insensitive_fields: tuple[NonEmptyString, ...] = Field(
        default=(),
        alias="orderInsensitiveFields",
    )

    @model_validator(mode="after")
    def comparison_fields_must_be_unique(self) -> ExpectedToolCallSpec:
        policies = (
            self.optional_fields,
            self.case_insensitive_fields,
            self.trim_fields,
            self.order_insensitive_fields,
        )
        for fields in policies:
            if len(fields) != len(set(fields)):
                raise ValueError("expected tool comparison fields must be unique")
        return self


class EvaluationSpec(_BenchmarkModel):
    """Metric selection metadata; formulas remain owned by Stage 19."""

    selected_metrics: tuple[MetricName, ...] = Field(alias="selectedMetrics", min_length=1)

    @field_validator("selected_metrics")
    @classmethod
    def selected_metrics_must_be_unique(
        cls,
        value: tuple[MetricName, ...],
    ) -> tuple[MetricName, ...]:
        if len(value) != len(set(value)):
            raise ValueError("evaluationSpec.selectedMetrics must be unique")
        return value


class BenchmarkTask(_BenchmarkModel):
    """The strict Stage 21 (schema 0.2.0) EvaluationTask view."""

    schema_version: Literal["0.2.0"] = Field(alias="schemaVersion")
    benchmark_task_id: NonEmptyString = Field(alias="benchmarkTaskId")
    task_type: TaskType = Field(alias="taskType")
    instruction: NonEmptyString
    initial_state: InitialState = Field(alias="initialState")
    allowed_tools: tuple[NonEmptyString, ...] = Field(alias="allowedTools")
    forbidden_actions: tuple[NonEmptyString, ...] = Field(alias="forbiddenActions")
    expected_output: dict[StrictStr, JsonValue] = Field(alias="expectedOutput")
    expected_tool_calls: tuple[ExpectedToolCallSpec, ...] = Field(
        default=(),
        alias="expectedToolCalls",
    )
    ground_truth_ref: GroundTruthRef = Field(alias="groundTruthRef")
    evaluation_spec: EvaluationSpec = Field(alias="evaluationSpec")
    metrics: tuple[MetricName, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def contract_lists_and_selection_must_be_consistent(self) -> BenchmarkTask:
        for name, values in (
            ("allowedTools", self.allowed_tools),
            ("forbiddenActions", self.forbidden_actions),
            ("metrics", self.metrics),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")

        tool_names = [call.tool_name for call in self.expected_tool_calls]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("expectedToolCalls must contain at most one entry per tool")
        if any(call.match_policy is None for call in self.expected_tool_calls):
            raise ValueError("every Stage 21 expectedToolCall requires matchPolicy")

        if set(self.metrics) != set(self.evaluation_spec.selected_metrics):
            raise ValueError("metrics must mirror evaluationSpec.selectedMetrics in schema 0.2.0")
        return self


class DatasetSplit(StrEnum):
    DEV = "dev"
    HELD_OUT = "held_out"
    UNASSIGNED = "unassigned"


class DatasetDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    UNASSIGNED = "unassigned"


class DatasetReviewStatus(StrEnum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    REPLACE_REQUIRED = "REPLACE_REQUIRED"


class DatasetManifestEntry(_BenchmarkModel):
    benchmark_task_id: NonEmptyString = Field(alias="benchmarkTaskId")
    task_file: NonEmptyString = Field(alias="taskFile")
    ground_truth_file: NonEmptyString = Field(alias="groundTruthFile")
    ground_truth_ref: GroundTruthRef = Field(alias="groundTruthRef")
    split: DatasetSplit
    difficulty: DatasetDifficulty
    scenario: NonEmptyString
    difficulty_rationale: NonEmptyString = Field(alias="difficultyRationale")
    review_status: DatasetReviewStatus = Field(alias="reviewStatus")


class DatasetManifest(_BenchmarkModel):
    manifest_version: NonEmptyString = Field(alias="manifestVersion")
    dataset_id: NonEmptyString = Field(alias="datasetId")
    dataset_version: NonEmptyString = Field(alias="datasetVersion")
    task_schema_version: NonEmptyString = Field(alias="taskSchemaVersion")
    tasks: tuple[DatasetManifestEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def entries_must_be_unique(self) -> DatasetManifest:
        ids = [entry.benchmark_task_id for entry in self.tasks]
        task_files = [entry.task_file for entry in self.tasks]
        for name, values in (
            ("benchmarkTaskId", ids),
            ("taskFile", task_files),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"dataset manifest {name} values must be unique")
        return self


__all__ = [
    "BenchmarkTask",
    "DatasetDifficulty",
    "DatasetManifest",
    "DatasetManifestEntry",
    "DatasetReviewStatus",
    "DatasetSplit",
    "EvaluationSpec",
    "ExpectedToolCallSpec",
    "GroundTruthRef",
    "InitialState",
    "InitialStateEntry",
    "InitialStateKind",
    "JavaResourceReference",
    "LiteralSetup",
    "PythonFixtureReference",
    "TaskType",
]
