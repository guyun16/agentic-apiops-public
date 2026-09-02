"""Store abstraction and deterministic in-memory implementation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from .models import (
    HistoricalFailureMemoryEntry,
    MemoryLifecycleStatus,
    VerificationStatus,
)


@runtime_checkable
class MemoryStore(Protocol):
    """Persistence port; acceptance decisions remain in ``MemoryWritePolicy``."""

    def save(self, entry: HistoricalFailureMemoryEntry) -> None:
        """Persist one policy-approved entry."""

    def get(self, memory_id: str) -> HistoricalFailureMemoryEntry | None:
        """Read one entry by its stable identity."""

    def find_by_content_hash(
        self,
        *,
        project_id: int,
        content_hash: str,
    ) -> HistoricalFailureMemoryEntry | None:
        """Find a content duplicate inside one project."""

    def find_by_failure_fingerprint(
        self,
        *,
        project_id: int,
        failure_fingerprint: str,
        lifecycle_status: MemoryLifecycleStatus | None = None,
    ) -> list[HistoricalFailureMemoryEntry]:
        """Find semantic matches, optionally constrained by lifecycle."""

    def list_by_project(
        self,
        *,
        project_id: int,
        lifecycle_status: MemoryLifecycleStatus | None = None,
    ) -> list[HistoricalFailureMemoryEntry]:
        """List entries for one project."""

    def update_lifecycle(
        self,
        memory_id: str,
        lifecycle_status: MemoryLifecycleStatus,
    ) -> HistoricalFailureMemoryEntry:
        """Change lifecycle without changing historical content identity."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemoryMemoryStore:
    """Small deterministic store for tests and local application wiring.

    This is intentionally not a production persistence choice.  It provides
    the port needed by this stage while leaving a future backend decision
    explicit.
    """

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._entries: dict[str, HistoricalFailureMemoryEntry] = {}
        self._clock = clock or _utc_now

    def save(self, entry: HistoricalFailureMemoryEntry) -> None:
        if not isinstance(entry, HistoricalFailureMemoryEntry):
            raise TypeError("entry must be a HistoricalFailureMemoryEntry")
        if entry.verification_status is not VerificationStatus.VERIFIED:
            raise ValueError("only verified entries may be stored")
        if entry.lifecycle_status is not MemoryLifecycleStatus.ACTIVE:
            raise ValueError("new entries must be ACTIVE")

        existing = self._entries.get(entry.memory_id)
        if existing is not None and existing != entry:
            raise ValueError("memory_id already belongs to different content")

        duplicate = self.find_by_content_hash(
            project_id=entry.project_id,
            content_hash=entry.content_hash,
        )
        if duplicate is not None and duplicate.memory_id != entry.memory_id:
            raise ValueError("content_hash already belongs to a different memory")

        self._entries[entry.memory_id] = entry

    def get(self, memory_id: str) -> HistoricalFailureMemoryEntry | None:
        return self._entries.get(memory_id)

    def find_by_content_hash(
        self,
        *,
        project_id: int,
        content_hash: str,
    ) -> HistoricalFailureMemoryEntry | None:
        matches = [
            entry
            for entry in self._entries.values()
            if entry.project_id == project_id and entry.content_hash == content_hash
        ]
        return min(matches, key=lambda entry: entry.memory_id) if matches else None

    def find_by_failure_fingerprint(
        self,
        *,
        project_id: int,
        failure_fingerprint: str,
        lifecycle_status: MemoryLifecycleStatus | None = None,
    ) -> list[HistoricalFailureMemoryEntry]:
        matches = [
            entry
            for entry in self._entries.values()
            if entry.project_id == project_id
            and entry.failure_fingerprint == failure_fingerprint
            and (lifecycle_status is None or entry.lifecycle_status is lifecycle_status)
        ]
        return sorted(matches, key=lambda entry: entry.memory_id)

    def list_by_project(
        self,
        *,
        project_id: int,
        lifecycle_status: MemoryLifecycleStatus | None = None,
    ) -> list[HistoricalFailureMemoryEntry]:
        matches = [
            entry
            for entry in self._entries.values()
            if entry.project_id == project_id
            and (lifecycle_status is None or entry.lifecycle_status is lifecycle_status)
        ]
        return sorted(matches, key=lambda entry: entry.memory_id)

    def update_lifecycle(
        self,
        memory_id: str,
        lifecycle_status: MemoryLifecycleStatus,
    ) -> HistoricalFailureMemoryEntry:
        existing = self._entries.get(memory_id)
        if existing is None:
            raise KeyError(memory_id)
        payload = existing.model_dump()
        payload.update(
            lifecycle_status=lifecycle_status,
            updated_at=self._clock(),
        )
        updated = HistoricalFailureMemoryEntry(**payload)
        self._entries[memory_id] = updated
        return updated

    def mark_stale(self, memory_id: str) -> HistoricalFailureMemoryEntry:
        return self.update_lifecycle(memory_id, MemoryLifecycleStatus.STALE)

    def revoke(self, memory_id: str) -> HistoricalFailureMemoryEntry:
        return self.update_lifecycle(memory_id, MemoryLifecycleStatus.REVOKED)

    def list_all(self) -> list[HistoricalFailureMemoryEntry]:
        return sorted(self._entries.values(), key=lambda entry: entry.memory_id)

    def __len__(self) -> int:
        return len(self._entries)


__all__ = ["InMemoryMemoryStore", "MemoryStore"]
