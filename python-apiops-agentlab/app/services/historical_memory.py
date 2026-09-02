"""Application lifecycle service for Historical Failure Memory."""

from __future__ import annotations

from app.memory.models import HistoricalFailureMemoryEntry, MemoryLifecycleStatus
from app.memory.store import MemoryStore

_ALLOWED_TRANSITIONS = {
    MemoryLifecycleStatus.ACTIVE: {
        MemoryLifecycleStatus.STALE,
        MemoryLifecycleStatus.REVOKED,
    },
    MemoryLifecycleStatus.STALE: {MemoryLifecycleStatus.REVOKED},
    MemoryLifecycleStatus.REVOKED: set(),
}


class HistoricalMemoryLifecycleError(ValueError):
    """Raised when a lifecycle operation is out of scope or illegal."""


class HistoricalMemoryService:
    """Apply the Historical Memory lifecycle state machine at the app layer."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def mark_stale(
        self,
        project_id: int,
        memory_id: str,
    ) -> HistoricalFailureMemoryEntry:
        return self.transition(
            project_id=project_id,
            memory_id=memory_id,
            target=MemoryLifecycleStatus.STALE,
        )

    def revoke(
        self,
        project_id: int,
        memory_id: str,
    ) -> HistoricalFailureMemoryEntry:
        return self.transition(
            project_id=project_id,
            memory_id=memory_id,
            target=MemoryLifecycleStatus.REVOKED,
        )

    def transition(
        self,
        project_id: int,
        memory_id: str,
        target: MemoryLifecycleStatus,
    ) -> HistoricalFailureMemoryEntry:
        if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id < 1:
            raise HistoricalMemoryLifecycleError("project_id must be a positive integer")
        if not isinstance(target, MemoryLifecycleStatus):
            raise HistoricalMemoryLifecycleError("target must be a MemoryLifecycleStatus")

        entry = self._store.get(memory_id)
        if entry is None:
            raise KeyError(memory_id)
        if entry.project_id != project_id:
            raise HistoricalMemoryLifecycleError("memory belongs to a different project")
        if entry.lifecycle_status is target:
            return entry
        if target not in _ALLOWED_TRANSITIONS[entry.lifecycle_status]:
            raise HistoricalMemoryLifecycleError(
                f"cannot transition memory from {entry.lifecycle_status.value} to {target.value}"
            )
        return self._store.update_lifecycle(memory_id, target)


__all__ = ["HistoricalMemoryLifecycleError", "HistoricalMemoryService"]
