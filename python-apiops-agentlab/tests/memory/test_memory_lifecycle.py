"""Application-layer Historical Failure Memory lifecycle tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.memory import (
    HistoricalFailureMemoryCandidate,
    MemoryLifecycleStatus,
    MemoryWritePolicy,
    SQLiteMemoryStore,
    VerificationStatus,
)
from app.services.historical_memory import (
    HistoricalMemoryLifecycleError,
    HistoricalMemoryService,
)

FIXED_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class StepClock:
    def __init__(self) -> None:
        self.current = FIXED_TIME

    def __call__(self) -> datetime:
        self.current += timedelta(seconds=1)
        return self.current


def make_service(tmp_path: Path) -> tuple[SQLiteMemoryStore, HistoricalMemoryService, str]:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3", clock=StepClock())
    decision = MemoryWritePolicy(store, clock=lambda: FIXED_TIME).write(
        HistoricalFailureMemoryCandidate(
            project_id=101,
            api_id="orders.get",
            summary="A verified order failure",
            symptoms=["HTTP 500"],
            root_cause="upstream service unavailable",
            resolution="restore the upstream service",
            source_run_id=77,
            verification_status=VerificationStatus.VERIFIED,
        ),
        project_id=101,
    )
    assert decision.entry is not None
    return store, HistoricalMemoryService(store), decision.entry.memory_id


def test_active_to_stale_to_revoked_updates_timestamp(tmp_path: Path) -> None:
    store, service, memory_id = make_service(tmp_path)
    try:
        stale = service.mark_stale(101, memory_id)
        assert stale.lifecycle_status is MemoryLifecycleStatus.STALE
        assert stale.updated_at > stale.created_at

        revoked = service.revoke(101, memory_id)
        assert revoked.lifecycle_status is MemoryLifecycleStatus.REVOKED
        assert revoked.updated_at > stale.updated_at
    finally:
        store.close()


def test_active_to_revoked_is_allowed(tmp_path: Path) -> None:
    store, service, memory_id = make_service(tmp_path)
    try:
        revoked = service.revoke(101, memory_id)
        assert revoked.lifecycle_status is MemoryLifecycleStatus.REVOKED
    finally:
        store.close()


@pytest.mark.parametrize(
    ("initial", "target"),
    [
        (MemoryLifecycleStatus.STALE, MemoryLifecycleStatus.ACTIVE),
        (MemoryLifecycleStatus.REVOKED, MemoryLifecycleStatus.ACTIVE),
        (MemoryLifecycleStatus.REVOKED, MemoryLifecycleStatus.STALE),
    ],
)
def test_forbidden_transitions_fail_closed(
    tmp_path: Path,
    initial: MemoryLifecycleStatus,
    target: MemoryLifecycleStatus,
) -> None:
    store, service, memory_id = make_service(tmp_path)
    try:
        store.update_lifecycle(memory_id, initial)
        before = store.get(memory_id)
        with pytest.raises(HistoricalMemoryLifecycleError):
            service.transition(project_id=101, memory_id=memory_id, target=target)
        assert store.get(memory_id) == before
    finally:
        store.close()


def test_same_state_operations_are_idempotent(tmp_path: Path) -> None:
    store, service, memory_id = make_service(tmp_path)
    try:
        stale = service.mark_stale(101, memory_id)
        assert service.mark_stale(101, memory_id) == stale
        revoked = service.revoke(101, memory_id)
        assert service.revoke(101, memory_id) == revoked
    finally:
        store.close()


def test_project_mismatch_fails_closed_without_mutation(tmp_path: Path) -> None:
    store, service, memory_id = make_service(tmp_path)
    try:
        before = store.get(memory_id)
        with pytest.raises(HistoricalMemoryLifecycleError):
            service.mark_stale(202, memory_id)
        assert store.get(memory_id) == before
    finally:
        store.close()


def test_lifecycle_state_and_active_only_retrieval_survive_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite3"
    store, service, memory_id = make_service(tmp_path)
    entry = store.get(memory_id)
    assert entry is not None
    stale = service.mark_stale(101, memory_id)
    store.close()

    reopened = SQLiteMemoryStore(database_path, clock=lambda: FIXED_TIME + timedelta(minutes=1))
    try:
        assert reopened.get(memory_id) == stale
        resumed_service = HistoricalMemoryService(reopened)
        revoked = resumed_service.revoke(101, memory_id)
        assert revoked.lifecycle_status is MemoryLifecycleStatus.REVOKED
    finally:
        reopened.close()

    final_store = SQLiteMemoryStore(database_path)
    try:
        final = final_store.get(memory_id)
        assert final is not None
        assert final.lifecycle_status is MemoryLifecycleStatus.REVOKED
        assert (
            final_store.list_by_project(
                project_id=101,
                lifecycle_status=MemoryLifecycleStatus.ACTIVE,
            )
            == []
        )
    finally:
        final_store.close()
