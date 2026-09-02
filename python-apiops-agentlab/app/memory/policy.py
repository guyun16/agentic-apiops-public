"""Deterministic Historical Failure Memory write policy."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from .fingerprint import (
    build_failure_fingerprint,
    compute_content_hash,
    compute_memory_id,
)
from .models import (
    HistoricalFailureMemoryCandidate,
    HistoricalFailureMemoryEntry,
    MemoryLifecycleStatus,
    MemoryWriteDecision,
    MemoryWriteOutcome,
    MemoryWriteReason,
    VerificationStatus,
)
from .store import MemoryStore

_SENSITIVE_PATTERNS = (
    re.compile(r"\bauthorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(r"\bbearer\s+\S+", re.IGNORECASE),
    re.compile(
        r"\b(?:cookie|set-cookie)\b\s*(?:credential|header)?\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:password|secret|api[\s_-]?key|access[\s_-]?token)\b", re.IGNORECASE),
)
_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?previous\s+instructions\b", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(?:all\s+)?prior\s+instructions\b", re.IGNORECASE),
    re.compile(r"\b(?:reveal|show|expose)\s+(?:the\s+)?system\s+prompt\b", re.IGNORECASE),
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _candidate_texts(candidate: HistoricalFailureMemoryCandidate) -> Iterable[str]:
    yield candidate.api_id
    yield candidate.summary
    yield from candidate.symptoms
    yield candidate.root_cause
    yield candidate.resolution
    for reference in candidate.evidence_refs:
        yield reference.source_type
        yield reference.source_id


def contains_sensitive_content(candidate: HistoricalFailureMemoryCandidate) -> bool:
    """Return whether candidate text matches the conservative v1 secret gate."""

    return any(
        pattern.search(value) is not None
        for value in _candidate_texts(candidate)
        for pattern in _SENSITIVE_PATTERNS
    )


def contains_prompt_injection(candidate: HistoricalFailureMemoryCandidate) -> bool:
    """Return whether candidate text contains an obvious instruction injection."""

    return any(
        pattern.search(value) is not None
        for value in _candidate_texts(candidate)
        for pattern in _PROMPT_INJECTION_PATTERNS
    )


class MemoryWritePolicy:
    """Own the only supported candidate-to-store write path."""

    def __init__(
        self,
        store: MemoryStore | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or _utc_now

    def write(
        self,
        candidate: HistoricalFailureMemoryCandidate,
        *,
        project_id: int,
        store: MemoryStore | None = None,
    ) -> MemoryWriteDecision:
        """Run all gates in order and persist only an accepted entry."""

        if not isinstance(candidate, HistoricalFailureMemoryCandidate):
            raise TypeError("candidate must be a HistoricalFailureMemoryCandidate")
        target_store = store if store is not None else self._store
        if target_store is None:
            raise ValueError("MemoryWritePolicy requires a MemoryStore")

        # Gate 1: the application-supplied project scope is authoritative.
        if (
            isinstance(project_id, bool)
            or not isinstance(project_id, int)
            or project_id < 1
            or candidate.project_id != project_id
            or any(
                reference.project_id is not None and reference.project_id != project_id
                for reference in candidate.evidence_refs
            )
        ):
            return self._reject(
                MemoryWriteReason.PROJECT_SCOPE_MISMATCH,
                "candidate is outside the requested project scope",
            )

        # Gate 2: model output never supplies verification authority.
        if candidate.verification_status is not VerificationStatus.VERIFIED:
            return self._reject(
                MemoryWriteReason.UNVERIFIED,
                "candidate verification status is not VERIFIED",
            )

        # Gate 3: at least one structured or run-based provenance anchor is required.
        if candidate.source_run_id is None and not candidate.evidence_refs:
            return self._reject(
                MemoryWriteReason.MISSING_PROVENANCE,
                "candidate has no source run or evidence reference",
            )

        # Gate 4a/4b: conservative content and prompt-injection rejection.
        if contains_sensitive_content(candidate):
            return self._reject(
                MemoryWriteReason.SENSITIVE_CONTENT,
                "candidate contains prohibited sensitive content",
            )
        if contains_prompt_injection(candidate):
            return self._reject(
                MemoryWriteReason.PROMPT_INJECTION_CONTENT,
                "candidate contains an instruction-like injection",
            )

        # Gate 5: content idempotency first, then semantic conflict detection.
        failure_fingerprint = build_failure_fingerprint(
            api_id=candidate.api_id,
            symptoms=candidate.symptoms,
            root_cause=candidate.root_cause,
        )
        content_hash = compute_content_hash(candidate)
        existing_content = target_store.find_by_content_hash(
            project_id=project_id,
            content_hash=content_hash,
        )
        if existing_content is not None:
            return MemoryWriteDecision(
                outcome=MemoryWriteOutcome.IDEMPOTENT,
                reason=MemoryWriteReason.CONTENT_DUPLICATE,
                message="same content hash already exists in this project",
                entry=existing_content,
            )

        existing_fingerprint = target_store.find_by_failure_fingerprint(
            project_id=project_id,
            failure_fingerprint=failure_fingerprint,
        )
        if existing_fingerprint:
            return MemoryWriteDecision(
                outcome=MemoryWriteOutcome.DUPLICATE_CONFLICT,
                reason=MemoryWriteReason.FAILURE_FINGERPRINT_CONFLICT,
                message="same failure fingerprint already exists with different content",
                entry=existing_fingerprint[0],
            )

        now = self._clock()
        memory_id = compute_memory_id(
            project_id=project_id,
            failure_fingerprint=failure_fingerprint,
            content_hash=content_hash,
        )
        entry = HistoricalFailureMemoryEntry(
            memory_id=memory_id,
            project_id=project_id,
            api_id=candidate.api_id,
            failure_fingerprint=failure_fingerprint,
            summary=candidate.summary,
            symptoms=candidate.symptoms,
            root_cause=candidate.root_cause,
            resolution=candidate.resolution,
            source_run_id=candidate.source_run_id,
            evidence_refs=candidate.evidence_refs,
            verification_status=VerificationStatus.VERIFIED,
            lifecycle_status=MemoryLifecycleStatus.ACTIVE,
            content_hash=content_hash,
            created_at=now,
            updated_at=now,
        )
        target_store.save(entry)
        return MemoryWriteDecision(
            outcome=MemoryWriteOutcome.ACCEPT,
            reason=MemoryWriteReason.ACCEPTED,
            message="verified historical memory stored",
            entry=entry,
        )

    @staticmethod
    def _reject(reason: MemoryWriteReason, message: str) -> MemoryWriteDecision:
        return MemoryWriteDecision(
            outcome=MemoryWriteOutcome.REJECT,
            reason=reason,
            message=message,
        )


__all__ = [
    "MemoryWritePolicy",
    "contains_prompt_injection",
    "contains_sensitive_content",
]
