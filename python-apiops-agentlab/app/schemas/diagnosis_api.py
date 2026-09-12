"""Public HTTP contracts for the real Diagnosis Studio execution boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from app.memory import MemoryWriteOutcome, MemoryWriteReason
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.runner import TestReport
from app.schemas.testcase_dsl import JsonValue


class _ApiModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )


class DiagnosisStartRequest(_ApiModel):
    """The only user-owned input to one real diagnosis execution."""

    project_id: StrictInt = Field(alias="projectId", ge=1)
    run_id: StrictInt = Field(alias="runId", ge=1)


class DiagnosisResumeRequest(_ApiModel):
    """One decision bound to the exact HITL request returned by the workflow."""

    decision: Literal["APPROVE", "EDIT", "REJECT"]
    edited_arguments: dict[StrictStr, JsonValue] | None = Field(
        default=None,
        alias="editedArguments",
    )

    @model_validator(mode="after")
    def edited_arguments_match_decision(self) -> DiagnosisResumeRequest:
        if self.decision == "EDIT" and self.edited_arguments is None:
            raise ValueError("editedArguments is required for EDIT")
        if self.decision != "EDIT" and self.edited_arguments is not None:
            raise ValueError("editedArguments is only valid for EDIT")
        return self


class DiagnosisMemoryWriteRequest(_ApiModel):
    """Select one final root-cause hypothesis for explicit human verification."""

    hypothesis_index: StrictInt = Field(alias="hypothesisIndex", ge=0)


class DiagnosisMemoryWriteResponse(_ApiModel):
    """Safe result of the explicit verified Diagnosis memory action."""

    agent_run_id: StrictStr = Field(alias="agentRunId", min_length=1)
    project_id: StrictInt = Field(alias="projectId", ge=1)
    run_id: StrictInt = Field(alias="runId", ge=1)
    outcome: MemoryWriteOutcome
    reason: MemoryWriteReason
    memory_id: StrictStr | None = Field(default=None, alias="memoryId")
    stored: StrictBool


class DiagnosisExecutionStep(_ApiModel):
    """Bounded progress read-model; it contains no prompt or raw tool payload."""

    id: StrictStr = Field(min_length=1)
    label: StrictStr = Field(min_length=1)
    detail: StrictStr = Field(min_length=1)
    state: Literal["COMPLETED", "ACTIVE", "PENDING", "REJECTED"]


class DiagnosisContextSummary(_ApiModel):
    """Safe counters for the real ContextPack and TraceRecorder."""

    evidence_items: StrictInt = Field(alias="evidenceItems", ge=0)
    context_characters: StrictInt = Field(alias="contextCharacters", ge=0)
    model_calls: StrictInt = Field(alias="modelCalls", ge=0)
    tool_calls: StrictInt = Field(alias="toolCalls", ge=0)
    unavailable_fields: tuple[StrictStr, ...] = Field(
        default=(),
        alias="unavailableFields",
    )


class DiagnosisApprovalScope(_ApiModel):
    workflow_id: StrictStr = Field(alias="workflowId", min_length=1)
    project_id: StrictStr = Field(alias="projectId", min_length=1)
    tool_intent_id: StrictStr = Field(alias="toolIntentId", min_length=1)
    arguments_fingerprint: StrictStr = Field(
        alias="argumentsFingerprint",
        pattern=r"^[0-9a-f]{64}$",
    )


class DiagnosisApprovalRequest(_ApiModel):
    """The existing Guardrails/HITL approval request, rendered for Studio."""

    tool_name: StrictStr = Field(alias="toolName", min_length=1)
    risk: StrictStr = Field(min_length=1)
    reason: StrictStr = Field(min_length=1)
    arguments: dict[StrictStr, JsonValue]
    scope: DiagnosisApprovalScope


class DiagnosisFailure(_ApiModel):
    code: StrictStr = Field(min_length=1)
    message: StrictStr = Field(min_length=1)


class DiagnosisRunSummary(_ApiModel):
    """Durable Diagnosis history item projected from the SQLite run record."""

    status: Literal[
        "RUNNING",
        "COMPLETED",
        "APPROVAL_REQUIRED",
        "FAILED",
        "REJECTED",
    ]
    provider: StrictStr = Field(min_length=1)
    model: StrictStr = Field(min_length=1)
    project_id: StrictInt = Field(alias="projectId", ge=1)
    run_id: StrictInt = Field(alias="runId", ge=1)
    task_id: StrictInt = Field(alias="taskId", ge=1)
    agent_run_id: StrictStr = Field(alias="agentRunId", min_length=1)
    trace_id: StrictStr = Field(alias="traceId", min_length=1)
    workflow_id: StrictStr = Field(alias="workflowId", min_length=1)
    api_id: StrictStr | None = Field(default=None, alias="apiId", min_length=1)
    report_id: StrictStr = Field(alias="reportId", min_length=1)
    diagnosis_report_id: StrictStr | None = Field(
        default=None,
        alias="diagnosisReportId",
        min_length=1,
    )
    summary: StrictStr | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class DiagnosisExecutionResponse(_ApiModel):
    """One complete real execution snapshot shared by Studio and Result."""

    status: Literal["COMPLETED", "APPROVAL_REQUIRED", "FAILED", "REJECTED"]
    runtime: Literal["PYTHON_AGENTLAB"]
    implementation: Literal["REAL"]
    workflow: StrictStr = Field(min_length=1)
    provider: StrictStr = Field(min_length=1)
    model: StrictStr = Field(min_length=1)
    project_id: StrictInt = Field(alias="projectId", ge=1)
    run_id: StrictInt = Field(alias="runId", ge=1)
    task_id: StrictInt = Field(alias="taskId", ge=1)
    report_id: StrictStr = Field(alias="reportId", min_length=1)
    agent_run_id: StrictStr = Field(alias="agentRunId", min_length=1)
    trace_id: StrictStr = Field(alias="traceId", min_length=1)
    workflow_id: StrictStr = Field(alias="workflowId", min_length=1)
    test_report: TestReport = Field(alias="testReport")
    report: DiagnosisReport | None = None
    tool_intent_id: StrictStr | None = Field(default=None, alias="toolIntentId")
    tool_call_id: StrictStr | None = Field(default=None, alias="toolCallId")
    approval_request: DiagnosisApprovalRequest | None = Field(
        default=None,
        alias="approvalRequest",
    )
    steps: tuple[DiagnosisExecutionStep, ...]
    context: DiagnosisContextSummary
    failure: DiagnosisFailure | None = None


__all__ = [
    "DiagnosisApprovalRequest",
    "DiagnosisApprovalScope",
    "DiagnosisContextSummary",
    "DiagnosisExecutionResponse",
    "DiagnosisExecutionStep",
    "DiagnosisFailure",
    "DiagnosisMemoryWriteRequest",
    "DiagnosisMemoryWriteResponse",
    "DiagnosisRunSummary",
    "DiagnosisResumeRequest",
    "DiagnosisStartRequest",
]
