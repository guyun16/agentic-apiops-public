"""Durable Python-owned DiagnosisRun identity and approval read model."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.diagnosis_api import DiagnosisFailure
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.runner import TestReport
from app.schemas.testcase_dsl import JsonValue
from app.workflows.approval import ApprovalRequest

_TABLE_NAME = "diagnosis_run"
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
    agent_run_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diagnosis_run_workflow_id
    ON {_TABLE_NAME}(workflow_id);
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
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

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
                            payload_json,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(agent_run_id) DO UPDATE SET
                            workflow_id = excluded.workflow_id,
                            payload_json = excluded.payload_json,
                            updated_at = excluded.updated_at
                        """,
                        (
                            record.agent_run_id,
                            record.workflow_id,
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

    def close(self) -> None:
        """Close the connection while leaving the SQLite file intact."""

        with self._lock:
            self._connection.close()

    def __enter__(self) -> SQLiteDiagnosisRunRepository:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback
        self.close()


__all__ = ["SQLiteDiagnosisRunRepository", "StoredDiagnosisRun"]
