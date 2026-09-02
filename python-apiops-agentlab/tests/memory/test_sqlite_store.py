"""SQLite persistence and Store parity tests for Historical Failure Memory."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.memory import (
    HistoricalFailureMemoryCandidate,
    MemoryLifecycleStatus,
    MemoryRetriever,
    MemoryWriteOutcome,
    MemoryWritePolicy,
    MemoryWriteReason,
    SQLiteMemoryStore,
    VerificationStatus,
)

FIXED_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def make_candidate(
    *,
    project_id: int = 101,
    api_id: str = "orders.get",
    summary: str = "Order lookup returned HTTP 500",
    root_cause: str = "database connection pool exhausted",
    resolution: str = "restore pool capacity and retry the operation",
) -> HistoricalFailureMemoryCandidate:
    return HistoricalFailureMemoryCandidate(
        project_id=project_id,
        api_id=api_id,
        summary=summary,
        symptoms=["HTTP 500", "database unavailable"],
        root_cause=root_cause,
        resolution=resolution,
        source_run_id=9001,
        verification_status=VerificationStatus.VERIFIED,
    )


def save_candidate(
    store: SQLiteMemoryStore,
    candidate: HistoricalFailureMemoryCandidate,
):
    decision = MemoryWritePolicy(store, clock=lambda: FIXED_TIME).write(
        candidate,
        project_id=candidate.project_id,
    )
    assert decision.outcome is MemoryWriteOutcome.ACCEPT
    assert decision.entry is not None
    return decision.entry


def test_verified_entry_survives_close_and_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "historical-memory.sqlite3"
    store = SQLiteMemoryStore(database_path, clock=lambda: FIXED_TIME)
    entry = save_candidate(store, make_candidate())
    store.close()

    reopened = SQLiteMemoryStore(database_path, clock=lambda: FIXED_TIME)
    try:
        assert reopened.get(entry.memory_id) == entry
    finally:
        reopened.close()


def test_queries_are_project_scoped_and_deterministically_ordered(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3", clock=lambda: FIXED_TIME)
    entries = [
        save_candidate(store, make_candidate(api_id="billing.get", root_cause="billing timeout")),
        save_candidate(store, make_candidate(api_id="orders.get")),
    ]
    other_project = save_candidate(store, make_candidate(project_id=202))

    try:
        ordered = store.list_by_project(project_id=101)
        assert [entry.memory_id for entry in ordered] == sorted(
            entry.memory_id for entry in entries
        )
        assert (
            store.find_by_content_hash(
                project_id=101,
                content_hash=entries[1].content_hash,
            )
            == entries[1]
        )
        assert store.find_by_failure_fingerprint(
            project_id=101,
            failure_fingerprint=entries[1].failure_fingerprint,
        ) == [entries[1]]
        assert store.list_by_project(project_id=202) == [other_project]
        assert store.find_by_failure_fingerprint(
            project_id=202,
            failure_fingerprint=entries[1].failure_fingerprint,
        ) == [other_project]
        assert store.list_by_project(project_id=303) == []
    finally:
        store.close()


def test_sqlite_policy_keeps_duplicate_and_conflict_semantics(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3", clock=lambda: FIXED_TIME)
    policy = MemoryWritePolicy(store, clock=lambda: FIXED_TIME)
    first_candidate = make_candidate()
    conflict_candidate = make_candidate(
        summary="The order lookup failed again after the pool exhausted",
        resolution="increase pool size and redeploy the service",
    )

    try:
        first = policy.write(first_candidate, project_id=101)
        duplicate = policy.write(first_candidate, project_id=101)
        conflict = policy.write(conflict_candidate, project_id=101)

        assert first.outcome is MemoryWriteOutcome.ACCEPT
        assert duplicate.outcome is MemoryWriteOutcome.IDEMPOTENT
        assert duplicate.reason is MemoryWriteReason.CONTENT_DUPLICATE
        assert duplicate.entry == first.entry
        assert conflict.outcome is MemoryWriteOutcome.DUPLICATE_CONFLICT
        assert conflict.reason is MemoryWriteReason.FAILURE_FINGERPRINT_CONFLICT
        assert len(store) == 1
    finally:
        store.close()


def test_lifecycle_survives_reopen_and_default_retriever_stays_active_only(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.sqlite3"
    stale_time = FIXED_TIME + timedelta(minutes=1)
    revoked_time = FIXED_TIME + timedelta(minutes=2)
    times = iter((stale_time, revoked_time))
    store = SQLiteMemoryStore(database_path, clock=lambda: next(times))
    entry = save_candidate(store, make_candidate())
    stale = store.update_lifecycle(entry.memory_id, MemoryLifecycleStatus.STALE)
    store.close()

    reopened = SQLiteMemoryStore(database_path, clock=lambda: revoked_time)
    try:
        assert reopened.get(entry.memory_id) == stale
        retriever = MemoryRetriever(reopened)
        assert (
            retriever.retrieve(
                project_id=101,
                failure_fingerprint=entry.failure_fingerprint,
            )
            == []
        )

        revoked = reopened.update_lifecycle(entry.memory_id, MemoryLifecycleStatus.REVOKED)
        assert revoked.updated_at == revoked_time
    finally:
        reopened.close()

    final_store = SQLiteMemoryStore(database_path)
    try:
        assert final_store.get(entry.memory_id).lifecycle_status is MemoryLifecycleStatus.REVOKED
        assert (
            MemoryRetriever(final_store).retrieve(
                project_id=101,
                failure_fingerprint=entry.failure_fingerprint,
            )
            == []
        )
    finally:
        final_store.close()


def test_schema_contains_required_fields_indexes_and_project_content_key(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite3"
    store = SQLiteMemoryStore(database_path)
    store.close()

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(historical_failure_memory)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(historical_failure_memory)")
        }
        unique_indexes = [
            row[1]
            for row in connection.execute("PRAGMA index_list(historical_failure_memory)")
            if row[2]
        ]

    assert columns == {
        "memory_id",
        "project_id",
        "api_id",
        "failure_fingerprint",
        "content_hash",
        "summary",
        "symptoms",
        "root_cause",
        "resolution",
        "source_run_id",
        "evidence_refs",
        "verification_status",
        "lifecycle_status",
        "created_at",
        "updated_at",
    }
    assert "idx_historical_memory_failure" in indexes
    assert "idx_historical_memory_api" in indexes
    assert unique_indexes


def test_shared_sqlite_retriever_is_safe_across_runtime_threads(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3", clock=lambda: FIXED_TIME)
    entry = save_candidate(store, make_candidate())
    retriever = MemoryRetriever(store)

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            matches = list(
                executor.map(
                    lambda _: retriever.retrieve(
                        project_id=101,
                        failure_fingerprint=entry.failure_fingerprint,
                    ),
                    range(8),
                )
            )
        assert matches == [[entry]] * 8
    finally:
        store.close()
