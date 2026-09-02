"""Strict consumer views of the existing Java Runner and TestReport REST contracts."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from .diagnosis_report import FailureType
from .testcase_dsl import JsonValue

NonEmptyString: TypeAlias = Annotated[StrictStr, Field(min_length=1)]
_UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
UuidString: TypeAlias = Annotated[
    StrictStr,
    Field(pattern=_UUID_PATTERN),
]
RunStatus: TypeAlias = Literal[
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "ASSERTION_FAILED",
    "EXECUTION_FAILED",
    "TIMEOUT",
    "CANCELLED",
]
TerminalRunStatus: TypeAlias = Literal[
    "SUCCESS",
    "ASSERTION_FAILED",
    "EXECUTION_FAILED",
    "TIMEOUT",
    "CANCELLED",
]


class _RunnerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=False, strict=True, frozen=True)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class RunnerSubmission(_RunnerModel):
    """Java-owned identities returned by the existing batch submit endpoint."""

    batch_id: UuidString = Field(alias="batchId")
    task_ids: tuple[Annotated[StrictInt, Field(ge=1)], ...] = Field(alias="taskIds", min_length=1)
    run_ids: tuple[Annotated[StrictInt, Field(ge=1)], ...] = Field(alias="runIds", min_length=1)

    @field_validator("task_ids", "run_ids", mode="before")
    @classmethod
    def accept_json_arrays(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def identities_must_be_aligned(self) -> RunnerSubmission:
        if len(self.task_ids) != len(self.run_ids):
            raise ValueError("taskIds and runIds must have the same length")
        return self


class RunnerProgress(_RunnerModel):
    """One TaskProgressSnapshot delivered by Java's public SSE boundary."""

    project_id: Annotated[StrictInt, Field(ge=1)] = Field(alias="projectId")
    task_id: Annotated[StrictInt, Field(ge=1)] = Field(alias="taskId")
    run_id: Annotated[StrictInt, Field(ge=1)] = Field(alias="runId")
    total: Annotated[StrictInt, Field(ge=0)]
    completed: Annotated[StrictInt, Field(ge=0)]
    running: Annotated[StrictInt, Field(ge=0)]
    success: Annotated[StrictInt, Field(ge=0)]
    assertion_failed: Annotated[StrictInt, Field(ge=0)] = Field(alias="assertionFailed")
    execution_failed: Annotated[StrictInt, Field(ge=0)] = Field(alias="executionFailed")
    timeout: Annotated[StrictInt, Field(ge=0)]
    cancelled: Annotated[StrictInt, Field(ge=0)]
    status: RunStatus
    updated_at: NonEmptyString = Field(alias="updatedAt")

    @property
    def terminal(self) -> bool:
        return self.status not in {"PENDING", "RUNNING"}


class AssertionResult(_RunnerModel):
    type: Literal["STATUS_CODE", "HEADER", "JSON_PATH", "RESPONSE_TIME"]
    passed: StrictBool
    expected: JsonValue
    actual: JsonValue
    message: StrictStr


class TestReportStep(_RunnerModel):
    step_id: NonEmptyString = Field(alias="stepId")
    status: RunStatus
    failure_type: FailureType = Field(alias="failureType")
    response_status_code: StrictInt | None = Field(alias="responseStatusCode")
    duration_ms: Annotated[StrictInt, Field(ge=0)] | None = Field(alias="durationMs")
    assertion_results: tuple[AssertionResult, ...] = Field(alias="assertionResults")

    @field_validator("assertion_results", mode="before")
    @classmethod
    def accept_json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class TestReportCase(_RunnerModel):
    case_id: NonEmptyString = Field(alias="caseId")
    status: RunStatus
    failure_type: FailureType = Field(alias="failureType")
    steps: tuple[TestReportStep, ...]

    @field_validator("steps", mode="before")
    @classmethod
    def accept_json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class TestReportSummary(_RunnerModel):
    total_cases: Annotated[StrictInt, Field(ge=0)] = Field(alias="totalCases")
    total_steps: Annotated[StrictInt, Field(ge=0)] = Field(alias="totalSteps")
    total_assertions: Annotated[StrictInt, Field(ge=0)] = Field(alias="totalAssertions")
    passed_assertions: Annotated[StrictInt, Field(ge=0)] = Field(alias="passedAssertions")
    failed_assertions: Annotated[StrictInt, Field(ge=0)] = Field(alias="failedAssertions")
    failure_type: FailureType = Field(alias="failureType")


class TestReport(_RunnerModel):
    """Typed read-only view of Java TestReportVO, including its Java-owned identity."""

    project_id: Annotated[StrictInt, Field(ge=1)] = Field(alias="projectId")
    task_id: Annotated[StrictInt, Field(ge=1)] = Field(alias="taskId")
    run_id: Annotated[StrictInt, Field(ge=1)] = Field(alias="runId")
    report_id: NonEmptyString = Field(alias="reportId")
    status: RunStatus
    started_at: NonEmptyString = Field(alias="startedAt")
    finished_at: NonEmptyString | None = Field(alias="finishedAt")
    summary: TestReportSummary
    cases: tuple[TestReportCase, ...]

    @field_validator("cases", mode="before")
    @classmethod
    def accept_json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


__all__ = [
    "AssertionResult",
    "RunnerProgress",
    "RunnerSubmission",
    "RunStatus",
    "TerminalRunStatus",
    "TestReport",
    "TestReportCase",
    "TestReportStep",
    "TestReportSummary",
]
