"""SQLite persistence for Python-owned Historical Failure Memory."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from .models import (
    HistoricalFailureMemoryEntry,
    MemoryEvidenceRef,
    MemoryLifecycleStatus,
    VerificationStatus,
)

_TABLE_NAME = "historical_failure_memory"
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
    memory_id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    api_id TEXT NOT NULL,
    failure_fingerprint TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    summary TEXT NOT NULL,
    symptoms TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    resolution TEXT NOT NULL,
    source_run_id INTEGER,
    evidence_refs TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_historical_memory_failure
    ON {_TABLE_NAME}(project_id, failure_fingerprint, lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_historical_memory_api
    ON {_TABLE_NAME}(project_id, api_id, lifecycle_status);
"""
_SELECT_COLUMNS = f"""
SELECT memory_id, project_id, api_id, failure_fingerprint, content_hash,
       summary, symptoms, root_cause, resolution, source_run_id, evidence_refs,
       verification_status, lifecycle_status, created_at, updated_at
FROM {_TABLE_NAME}
"""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _entry_to_values(entry: HistoricalFailureMemoryEntry) -> tuple[object, ...]:
    return (
        entry.memory_id,
        entry.project_id,
        entry.api_id,
        entry.failure_fingerprint,
        entry.content_hash,
        entry.summary,
        _json_dumps(entry.symptoms),
        entry.root_cause,
        entry.resolution,
        entry.source_run_id,
        _json_dumps([reference.model_dump(mode="json") for reference in entry.evidence_refs]),
        entry.verification_status.value,
        entry.lifecycle_status.value,
        entry.created_at.isoformat(),
        entry.updated_at.isoformat(),
    )


def _entry_from_row(row: sqlite3.Row) -> HistoricalFailureMemoryEntry:
    symptoms = json.loads(row["symptoms"])
    evidence_refs = json.loads(row["evidence_refs"])
    return HistoricalFailureMemoryEntry(
        memory_id=row["memory_id"],
        project_id=row["project_id"],
        api_id=row["api_id"],
        failure_fingerprint=row["failure_fingerprint"],
        content_hash=row["content_hash"],
        summary=row["summary"],
        symptoms=symptoms,
        root_cause=row["root_cause"],
        resolution=row["resolution"],
        source_run_id=row["source_run_id"],
        evidence_refs=[MemoryEvidenceRef(**reference) for reference in evidence_refs],
        verification_status=VerificationStatus(row["verification_status"]),
        lifecycle_status=MemoryLifecycleStatus(row["lifecycle_status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class SQLiteMemoryStore:
    """Deterministic durable implementation of the ``MemoryStore`` protocol."""

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_path = os.fspath(database_path)
        if not self.database_path:
            raise ValueError("database_path must not be empty")
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()
        self._clock = clock or _utc_now

    def close(self) -> None:
        """Close the connection; the database file remains durable."""

        with self._lock:
            self._connection.close()

    def __enter__(self) -> SQLiteMemoryStore:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def save(self, entry: HistoricalFailureMemoryEntry) -> None:
        if not isinstance(entry, HistoricalFailureMemoryEntry):
            raise TypeError("entry must be a HistoricalFailureMemoryEntry")
        if entry.verification_status is not VerificationStatus.VERIFIED:
            raise ValueError("only verified entries may be stored")
        if entry.lifecycle_status is not MemoryLifecycleStatus.ACTIVE:
            raise ValueError("new entries must be ACTIVE")

        with self._lock:
            existing = self.get(entry.memory_id)
            if existing is not None:
                if existing != entry:
                    raise ValueError("memory_id already belongs to different content")
                return

            duplicate = self.find_by_content_hash(
                project_id=entry.project_id,
                content_hash=entry.content_hash,
            )
            if duplicate is not None and duplicate.memory_id != entry.memory_id:
                raise ValueError("content_hash already belongs to a different memory")

            try:
                with self._connection:
                    self._connection.execute(
                        f"INSERT INTO {_TABLE_NAME} ("
                        "memory_id, project_id, api_id, failure_fingerprint, content_hash, "
                        "summary, symptoms, root_cause, resolution, source_run_id, "
                        "evidence_refs, verification_status, lifecycle_status, "
                        "created_at, updated_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        _entry_to_values(entry),
                    )
            except sqlite3.IntegrityError as exc:
                raise ValueError("memory entry conflicts with existing content") from exc

    def get(self, memory_id: str) -> HistoricalFailureMemoryEntry | None:
        with self._lock:
            row = self._connection.execute(
                f"{_SELECT_COLUMNS} WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return None if row is None else _entry_from_row(row)

    def find_by_content_hash(
        self,
        *,
        project_id: int,
        content_hash: str,
    ) -> HistoricalFailureMemoryEntry | None:
        with self._lock:
            row = self._connection.execute(
                f"{_SELECT_COLUMNS} WHERE project_id = ? AND content_hash = ? "
                "ORDER BY memory_id LIMIT 1",
                (project_id, content_hash),
            ).fetchone()
        return None if row is None else _entry_from_row(row)

    def find_by_failure_fingerprint(
        self,
        *,
        project_id: int,
        failure_fingerprint: str,
        lifecycle_status: MemoryLifecycleStatus | None = None,
    ) -> list[HistoricalFailureMemoryEntry]:
        query = f"{_SELECT_COLUMNS} WHERE project_id = ? AND failure_fingerprint = ?"
        parameters: list[Any] = [project_id, failure_fingerprint]
        if lifecycle_status is not None:
            query += " AND lifecycle_status = ?"
            parameters.append(lifecycle_status.value)
        query += " ORDER BY memory_id"
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [_entry_from_row(row) for row in rows]

    def list_by_project(
        self,
        *,
        project_id: int,
        lifecycle_status: MemoryLifecycleStatus | None = None,
    ) -> list[HistoricalFailureMemoryEntry]:
        query = f"{_SELECT_COLUMNS} WHERE project_id = ?"
        parameters: list[Any] = [project_id]
        if lifecycle_status is not None:
            query += " AND lifecycle_status = ?"
            parameters.append(lifecycle_status.value)
        query += " ORDER BY memory_id"
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [_entry_from_row(row) for row in rows]

    def update_lifecycle(
        self,
        memory_id: str,
        lifecycle_status: MemoryLifecycleStatus,
    ) -> HistoricalFailureMemoryEntry:
        with self._lock:
            existing = self.get(memory_id)
            if existing is None:
                raise KeyError(memory_id)
            payload = existing.model_dump()
            payload.update(
                lifecycle_status=lifecycle_status,
                updated_at=self._clock(),
            )
            updated = HistoricalFailureMemoryEntry(**payload)
            with self._connection:
                cursor = self._connection.execute(
                    f"UPDATE {_TABLE_NAME} SET lifecycle_status = ?, updated_at = ? "
                    "WHERE memory_id = ?",
                    (
                        updated.lifecycle_status.value,
                        updated.updated_at.isoformat(),
                        memory_id,
                    ),
                )
        if cursor.rowcount != 1:
            raise KeyError(memory_id)
        return updated

    def list_all(self) -> list[HistoricalFailureMemoryEntry]:
        with self._lock:
            rows = self._connection.execute(f"{_SELECT_COLUMNS} ORDER BY memory_id").fetchall()
        return [_entry_from_row(row) for row in rows]

    def __len__(self) -> int:
        with self._lock:
            row = self._connection.execute(f"SELECT COUNT(*) FROM {_TABLE_NAME}").fetchone()
        return int(row[0])


__all__ = ["SQLiteMemoryStore"]
