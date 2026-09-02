"""Strict Pydantic v2 view for the shared DiagnosisReport contract."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

FailureType: TypeAlias = Literal[
    "NONE",
    "ASSERTION_MISMATCH",
    "ASSERTION_EVALUATION_ERROR",
    "HTTP_STATUS_ERROR",
    "TIMEOUT",
    "NETWORK_ERROR",
    "REQUEST_BUILD_ERROR",
    "INVALID_TARGET_URI",
    "DNS_ERROR",
    "CONNECT_ERROR",
    "TLS_ERROR",
    "IO_ERROR",
    "SCHEMA_INVALID",
    "BUSINESS_ERROR",
    "TOOL_ERROR",
    "SYSTEM_ERROR",
    "UNKNOWN",
    "ASSERTION_FAILED",
    "AUTH_ERROR",
    "VALIDATION_ERROR",
    "DATABASE_CONSTRAINT_ERROR",
    "UPSTREAM_SERVICE_ERROR",
]

Confidence: TypeAlias = Literal["LOW", "MEDIUM", "HIGH"]
NonEmptyString: TypeAlias = Annotated[StrictStr, Field(min_length=1)]


class _DiagnosisModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class EvidenceRef(_DiagnosisModel):
    """Structural citation identity; contextual existence is validated elsewhere."""

    item_id: NonEmptyString = Field(alias="itemId")


class RootCauseHypothesis(_DiagnosisModel):
    statement: NonEmptyString
    confidence: Confidence
    evidence_refs: list[EvidenceRef] = Field(alias="evidenceRefs", min_length=1)


class DiagnosisReport(_DiagnosisModel):
    """Typed inference result without execution-fact or citation lookup semantics."""

    schema_version: Literal["0.1.0"] = Field(alias="schemaVersion")
    report_id: NonEmptyString = Field(alias="reportId")
    agent_run_id: NonEmptyString = Field(alias="agentRunId")
    project_id: StrictInt = Field(alias="projectId", ge=1)
    run_id: StrictInt = Field(alias="runId", ge=1)
    failure_type: FailureType = Field(alias="failureType")
    summary: NonEmptyString
    root_cause_hypotheses: list[RootCauseHypothesis] = Field(alias="rootCauseHypotheses")
    sufficient_evidence: StrictBool = Field(alias="sufficientEvidence")
    limitations: list[NonEmptyString]
    recommended_checks: list[NonEmptyString] = Field(alias="recommendedChecks")
    trace_id: NonEmptyString = Field(alias="traceId")
