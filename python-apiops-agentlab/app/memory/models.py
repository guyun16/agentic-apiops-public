"""Python-owned Historical Failure Memory models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from .fingerprint import (
    build_failure_fingerprint,
    compute_content_hash,
    compute_memory_id,
)

NonEmptyString: TypeAlias = Annotated[StrictStr, Field(min_length=1)]


class _MemoryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
        frozen=True,
    )


class VerificationStatus(StrEnum):
    """Whether an authoritative application step verified the diagnosis."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class MemoryLifecycleStatus(StrEnum):
    """Lifecycle visibility for a stored historical memory."""

    ACTIVE = "ACTIVE"
    STALE = "STALE"
    REVOKED = "REVOKED"


class MemoryEvidenceRef(_MemoryModel):
    """Structured provenance pointing at an external authoritative source."""

    source_type: NonEmptyString
    source_id: NonEmptyString
    project_id: StrictInt | None = Field(default=None, ge=1)
    run_id: StrictInt | None = Field(default=None, ge=1)


class HistoricalFailureMemoryCandidate(_MemoryModel):
    """Candidate content submitted to the deterministic write policy.

    A candidate has no memory ID, lifecycle, timestamp, or caller-supplied
    content hash.  Those identities are created only after the write gates
    pass.
    """

    project_id: StrictInt = Field(ge=1)
    api_id: NonEmptyString
    summary: NonEmptyString
    symptoms: list[NonEmptyString] = Field(min_length=1)
    root_cause: NonEmptyString
    resolution: NonEmptyString
    source_run_id: StrictInt | None = Field(default=None, ge=1)
    evidence_refs: list[MemoryEvidenceRef] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED

    @property
    def failure_fingerprint(self) -> str:
        """Return the deterministic semantic identity for this candidate."""

        return build_failure_fingerprint(
            api_id=self.api_id,
            symptoms=self.symptoms,
            root_cause=self.root_cause,
        )

    @property
    def content_hash(self) -> str:
        """Return the deterministic content identity used by the policy."""

        return compute_content_hash(self)


class HistoricalFailureMemoryEntry(_MemoryModel):
    """A verified, project-scoped historical precedent."""

    memory_id: NonEmptyString
    project_id: StrictInt = Field(ge=1)
    api_id: NonEmptyString
    failure_fingerprint: NonEmptyString
    summary: NonEmptyString
    symptoms: list[NonEmptyString] = Field(min_length=1)
    root_cause: NonEmptyString
    resolution: NonEmptyString
    source_run_id: StrictInt | None = Field(default=None, ge=1)
    evidence_refs: list[MemoryEvidenceRef] = Field(default_factory=list)
    verification_status: VerificationStatus
    lifecycle_status: MemoryLifecycleStatus
    content_hash: NonEmptyString
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_identity_and_authority(self) -> HistoricalFailureMemoryEntry:
        if self.source_run_id is None and not self.evidence_refs:
            raise ValueError("historical memory entry requires provenance")
        if any(
            reference.project_id is not None and reference.project_id != self.project_id
            for reference in self.evidence_refs
        ):
            raise ValueError("memory evidence references must stay in the memory project")
        if (
            self.lifecycle_status is MemoryLifecycleStatus.ACTIVE
            and self.verification_status is not VerificationStatus.VERIFIED
        ):
            raise ValueError("only verified memory entries may be ACTIVE")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("updated_at must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")

        expected_fingerprint = build_failure_fingerprint(
            api_id=self.api_id,
            symptoms=self.symptoms,
            root_cause=self.root_cause,
        )
        if self.failure_fingerprint != expected_fingerprint:
            raise ValueError("failure_fingerprint does not match structured failure identity")

        expected_content_hash = compute_content_hash(self)
        if self.content_hash != expected_content_hash:
            raise ValueError("content_hash does not match memory content")

        expected_memory_id = compute_memory_id(
            project_id=self.project_id,
            failure_fingerprint=self.failure_fingerprint,
            content_hash=self.content_hash,
        )
        if self.memory_id != expected_memory_id:
            raise ValueError("memory_id does not match stable memory identity")
        return self


class MemoryWriteOutcome(StrEnum):
    """Result category returned by the write policy."""

    ACCEPT = "ACCEPT"
    IDEMPOTENT = "IDEMPOTENT"
    REJECT = "REJECT"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"


class MemoryWriteReason(StrEnum):
    """Stable reason codes for policy decisions."""

    ACCEPTED = "ACCEPTED"
    PROJECT_SCOPE_MISMATCH = "PROJECT_SCOPE_MISMATCH"
    UNVERIFIED = "UNVERIFIED"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    SENSITIVE_CONTENT = "SENSITIVE_CONTENT"
    PROMPT_INJECTION_CONTENT = "PROMPT_INJECTION_CONTENT"
    CONTENT_DUPLICATE = "CONTENT_DUPLICATE"
    FAILURE_FINGERPRINT_CONFLICT = "FAILURE_FINGERPRINT_CONFLICT"


@dataclass(frozen=True)
class MemoryWriteDecision:
    """Immutable policy result; only ``ACCEPT`` creates a new entry."""

    outcome: MemoryWriteOutcome
    reason: MemoryWriteReason
    message: str
    entry: HistoricalFailureMemoryEntry | None = None

    @property
    def decision(self) -> MemoryWriteOutcome:
        """Compatibility-friendly name for the outcome value."""

        return self.outcome

    @property
    def status(self) -> MemoryWriteOutcome:
        return self.outcome

    @property
    def accepted(self) -> bool:
        return self.outcome is MemoryWriteOutcome.ACCEPT

    @property
    def stored(self) -> bool:
        return self.outcome in {
            MemoryWriteOutcome.ACCEPT,
            MemoryWriteOutcome.IDEMPOTENT,
        }


__all__ = [
    "HistoricalFailureMemoryCandidate",
    "HistoricalFailureMemoryEntry",
    "MemoryEvidenceRef",
    "MemoryLifecycleStatus",
    "MemoryWriteDecision",
    "MemoryWriteOutcome",
    "MemoryWriteReason",
    "VerificationStatus",
]
