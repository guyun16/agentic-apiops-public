"""Durable Python-owned DiagnosisRun identity and approval read model."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.errors import ApplicationError
from app.schemas.diagnosis_api import (
    DiagnosisContextSummary,
    DiagnosisExecutionStep,
    DiagnosisFailure,
)
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.runner import TestReport
from app.schemas.testcase_dsl import JsonValue
from app.services.diagnosis_lock import diagnosis_lock
from app.workflows.approval import ApprovalRequest

_TABLE_NAME = "diagnosis_run"
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
    agent_run_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL UNIQUE,
    project_id INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diagnosis_run_workflow_id
    ON {_TABLE_NAME}(workflow_id);
CREATE INDEX IF NOT EXISTS idx_diagnosis_run_project_updated
    ON {_TABLE_NAME}(project_id, updated_at DESC);
"""


class StoredDiagnosisRun(BaseModel):
    """Strict JSON-safe snapshot needed to recover one Diagnosis execution."""

    model_config = ConfigDict(extra="forbid", strict=True)

    agent_run_id: str
    workflow_id: str
    trace_id: str
    project_id: int
    run_id: int
    api_id: str | None
    test_report: TestReport
    model: str
    provider: str = "DeepSeek"
    status: Literal[
        "RUNNING",
        "COMPLETED",
        "APPROVAL_REQUIRED",
        "FAILED",
        "REJECTED",
    ]
    diagnosis_report: DiagnosisReport | None = None
    approval_request: ApprovalRequest | None = None
    approval_arguments: dict[str, JsonValue] | None = None
    approval_risk: str | None = None
    tool_intent_id: str | None = None
    tool_call_id: str | None = None
    failure: DiagnosisFailure | None = None
    steps: tuple[DiagnosisExecutionStep, ...] | None = None
    context: DiagnosisContextSummary | None = None


@dataclass(frozen=True, slots=True)
class StoredDiagnosisRunEntry:
    """One durable run plus repository-owned lifecycle timestamps."""

    run: StoredDiagnosisRun
    created_at: datetime
    updated_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SQLiteDiagnosisRunRepository:
    """Small SQLite repository for Python-owned DiagnosisRun recovery state."""

    def __init__(self, database_path: str | os.PathLike[str]) -> None:
        self.database_path = os.fspath(database_path)
        if not self.database_path:
            raise ValueError("database_path must not be empty")
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._temporary_locks = (
            tempfile.TemporaryDirectory() if self.database_path == ":memory:" else None
        )
        self._lock_directory = (
            Path(self._temporary_locks.name)
            if self._temporary_locks
            else Path(str(Path(self.database_path).resolve()) + ".diagnosis-locks")
        )
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Create the current schema and upgrade pre-project-index databases in place."""

        table_exists = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (_TABLE_NAME,),
        ).fetchone()
        if table_exists is None:
            self._connection.executescript(_SCHEMA)
            self._connection.commit()
            return

        columns = {
            row["name"] for row in self._connection.execute(f"PRAGMA table_info({_TABLE_NAME})")
        }
        with self._connection:
            if "project_id" not in columns:
                self._connection.execute(f"ALTER TABLE {_TABLE_NAME} ADD COLUMN project_id INTEGER")
            rows = self._connection.execute(
                f"""
                SELECT agent_run_id, payload_json
                FROM {_TABLE_NAME}
                WHERE project_id IS NULL
                """
            ).fetchall()
            for row in rows:
                record = StoredDiagnosisRun.model_validate_json(row["payload_json"])
                self._connection.execute(
                    f"UPDATE {_TABLE_NAME} SET project_id = ? WHERE agent_run_id = ?",
                    (record.project_id, row["agent_run_id"]),
                )
            self._connection.executescript(
                f"""
                CREATE INDEX IF NOT EXISTS idx_diagnosis_run_workflow_id
                    ON {_TABLE_NAME}(workflow_id);
                CREATE INDEX IF NOT EXISTS idx_diagnosis_run_project_updated
                    ON {_TABLE_NAME}(project_id, updated_at DESC);
                """
            )

    def save(self, record: StoredDiagnosisRun) -> None:
        if not isinstance(record, StoredDiagnosisRun):
            raise TypeError("record must be a StoredDiagnosisRun")
        payload = record.model_dump_json(by_alias=True)
        now = _utc_now().isoformat()
        with self._lock:
            existing = self._connection.execute(
                f"SELECT workflow_id, created_at FROM {_TABLE_NAME} WHERE agent_run_id = ?",
                (record.agent_run_id,),
            ).fetchone()
            if existing is not None and existing["workflow_id"] != record.workflow_id:
                raise ValueError("agent_run_id already belongs to a different workflow_id")
            created_at = existing["created_at"] if existing is not None else now
            try:
                with self._connection:
                    self._connection.execute(
                        f"""
                        INSERT INTO {_TABLE_NAME} (
                            agent_run_id,
                            workflow_id,
                            project_id,
                            payload_json,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(agent_run_id) DO UPDATE SET
                            workflow_id = excluded.workflow_id,
                            project_id = excluded.project_id,
                            payload_json = excluded.payload_json,
                            updated_at = excluded.updated_at
                        """,
                        (
                            record.agent_run_id,
                            record.workflow_id,
                            record.project_id,
                            payload,
                            created_at,
                            now,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise ValueError("diagnosis run conflicts with existing identity") from exc

    def get(self, agent_run_id: str) -> StoredDiagnosisRun | None:
        with self._lock:
            row = self._connection.execute(
                f"SELECT payload_json FROM {_TABLE_NAME} WHERE agent_run_id = ?",
                (agent_run_id,),
            ).fetchone()
        return None if row is None else StoredDiagnosisRun.model_validate_json(row["payload_json"])

    def list_by_project_id(self, project_id: int) -> tuple[StoredDiagnosisRunEntry, ...]:
        """Return one project's runs, newest repository update first."""

        if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id < 1:
            raise ValueError("project_id must be a positive integer")
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT payload_json, created_at, updated_at
                FROM {_TABLE_NAME}
                WHERE project_id = ?
                ORDER BY updated_at DESC, agent_run_id DESC
                """,
                (project_id,),
            ).fetchall()
        return tuple(
            StoredDiagnosisRunEntry(
                run=StoredDiagnosisRun.model_validate_json(row["payload_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        )

    def close(self) -> None:
        """Close the connection while leaving the SQLite file intact."""

        with self._lock:
            self._connection.close()

    def execution_lock(self, project_id: int, run_id: int):
        return diagnosis_lock(self._lock_directory, project_id, run_id)

    def recover_interrupted(self, project_id: int) -> None:
        """Recover only abandoned RUNNING records; live workers retain their lock."""
        for entry in self.list_by_project_id(project_id):
            if entry.run.status != "RUNNING":
                continue
            try:
                with self.execution_lock(project_id, entry.run.run_id):
                    self.recover_locked(project_id, entry.run.run_id)
            except ApplicationError as exc:
                if exc.code != "DIAGNOSIS_ALREADY_RUNNING":
                    raise

    def recover_locked(self, project_id: int, run_id: int) -> None:
        """Caller must own execution_lock. Re-read to avoid overwriting a completed run."""
        for entry in self.list_by_project_id(project_id):
            if entry.run.run_id == run_id and entry.run.status == "RUNNING":
                self.save(
                    entry.run.model_copy(
                        update={
                            "status": "FAILED",
                            "failure": DiagnosisFailure(
                                code="DIAGNOSIS_INTERRUPTED",
                                message=(
                                    "The diagnosis worker stopped before saving a result. "
                                    "Start a new diagnosis to retry; previous tool calls "
                                    "are not replayed automatically."
                                ),
                            ),
                        }
                    )
                )

    def __enter__(self) -> SQLiteDiagnosisRunRepository:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback
        self.close()


__all__ = [
    "SQLiteDiagnosisRunRepository",
    "StoredDiagnosisRun",
    "StoredDiagnosisRunEntry",
]
