"""Durability tests for the Python-owned DiagnosisRun repository."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.schemas.runner import TestReport as RunnerTestReport
from app.services.diagnosis_repository import (
    SQLiteDiagnosisRunRepository,
    StoredDiagnosisRun,
)
from app.workflows.approval import ApprovalRequest


def _test_report() -> RunnerTestReport:
    return RunnerTestReport.model_validate(
        {
            "projectId": 41,
            "taskId": 301,
            "runId": 701,
            "reportId": "report:701",
            "status": "ASSERTION_FAILED",
            "startedAt": "2026-08-23T11:59:58Z",
            "finishedAt": "2026-08-23T12:00:00Z",
            "summary": {
                "totalCases": 1,
                "totalSteps": 1,
                "totalAssertions": 1,
                "passedAssertions": 0,
                "failedAssertions": 1,
                "failureType": "ASSERTION_MISMATCH",
            },
            "cases": [
                {
                    "caseId": "case-failed",
                    "status": "ASSERTION_FAILED",
                    "failureType": "ASSERTION_MISMATCH",
                    "steps": [],
                }
            ],
        }
    )


def stored_run(
    *,
    agent_run_id: str = "agent_run:1",
    workflow_id: str = "workflow:1",
    project_id: int = 41,
    status: str = "APPROVAL_REQUIRED",
) -> StoredDiagnosisRun:
    test_report = _test_report().model_copy(update={"project_id": project_id})
    return StoredDiagnosisRun(
        agent_run_id=agent_run_id,
        workflow_id=workflow_id,
        trace_id="trace:1",
        project_id=project_id,
        run_id=701,
        api_id="orders.get",
        test_report=test_report,
        model="deepseek-v4-flash",
        status=status,
        approval_request=ApprovalRequest(
            workflow_id=workflow_id,
            project_id="41",
            intent_id="intent:1",
            tool_name="redis.read",
            arguments_fingerprint="0" * 64,
        ),
        approval_arguments={"key": "task:41"},
        approval_risk="REQUIRE_APPROVAL",
        tool_intent_id="intent:1",
    )


def test_save_get_roundtrip(tmp_path: Path) -> None:
    repository = SQLiteDiagnosisRunRepository(tmp_path / "agentlab-runtime.sqlite3")
    record = stored_run()

    repository.save(record)

    assert repository.get(record.agent_run_id) == record
    repository.close()


def test_close_reopen_preserves_record(tmp_path: Path) -> None:
    database_path = tmp_path / "agentlab-runtime.sqlite3"
    record = stored_run()
    first = SQLiteDiagnosisRunRepository(database_path)
    first.save(record)
    first.close()

    second = SQLiteDiagnosisRunRepository(database_path)
    assert second.get(record.agent_run_id) == record
    second.close()


def test_save_upserts_status_and_preserves_created_at(tmp_path: Path) -> None:
    database_path = tmp_path / "agentlab-runtime.sqlite3"
    repository = SQLiteDiagnosisRunRepository(database_path)
    pending = stored_run()
    repository.save(pending)
    with sqlite3.connect(database_path) as connection:
        created_at = connection.execute(
            "SELECT created_at FROM diagnosis_run WHERE agent_run_id = ?",
            (pending.agent_run_id,),
        ).fetchone()[0]

    completed = pending.model_copy(update={"status": "COMPLETED"})
    repository.save(completed)

    assert repository.get(pending.agent_run_id) == completed
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT created_at, updated_at FROM diagnosis_run WHERE agent_run_id = ?",
            (pending.agent_run_id,),
        ).fetchone()
    assert row[0] == created_at
    assert row[1] >= created_at
    repository.close()


def test_agent_run_id_cannot_change_workflow_identity(tmp_path: Path) -> None:
    repository = SQLiteDiagnosisRunRepository(tmp_path / "agentlab-runtime.sqlite3")
    repository.save(stored_run())

    with pytest.raises(ValueError, match="different workflow_id"):
        repository.save(stored_run(workflow_id="workflow:other"))

    assert repository.get("agent_run:1").workflow_id == "workflow:1"
    repository.close()


def test_missing_returns_none(tmp_path: Path) -> None:
    repository = SQLiteDiagnosisRunRepository(tmp_path / "agentlab-runtime.sqlite3")

    assert repository.get("missing") is None
    repository.close()


def test_list_by_project_id_is_isolated_and_newest_first(tmp_path: Path) -> None:
    database_path = tmp_path / "agentlab-runtime.sqlite3"
    repository = SQLiteDiagnosisRunRepository(database_path)
    repository.save(stored_run(agent_run_id="agent_run:old", workflow_id="workflow:old"))
    repository.save(
        stored_run(
            agent_run_id="agent_run:other-project",
            workflow_id="workflow:other-project",
            project_id=42,
        )
    )
    repository.save(stored_run(agent_run_id="agent_run:new", workflow_id="workflow:new"))
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE diagnosis_run SET updated_at = ? WHERE agent_run_id = ?",
            ("2026-08-23T12:00:00+00:00", "agent_run:old"),
        )
        connection.execute(
            "UPDATE diagnosis_run SET updated_at = ? WHERE agent_run_id = ?",
            ("2026-08-23T12:01:00+00:00", "agent_run:new"),
        )

    entries = repository.list_by_project_id(41)

    assert [entry.run.agent_run_id for entry in entries] == [
        "agent_run:new",
        "agent_run:old",
    ]
    assert all(entry.run.project_id == 41 for entry in entries)
    repository.close()


def test_existing_schema_is_upgraded_for_project_history(tmp_path: Path) -> None:
    database_path = tmp_path / "agentlab-runtime.sqlite3"
    record = stored_run()
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE diagnosis_run (
                agent_run_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO diagnosis_run (
                agent_run_id, workflow_id, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                record.agent_run_id,
                record.workflow_id,
                record.model_dump_json(by_alias=True),
                "2026-08-23T12:00:00+00:00",
                "2026-08-23T12:00:01+00:00",
            ),
        )

    repository = SQLiteDiagnosisRunRepository(database_path)

    assert repository.list_by_project_id(41)[0].run == record
    with sqlite3.connect(database_path) as connection:
        project_id = connection.execute(
            "SELECT project_id FROM diagnosis_run WHERE agent_run_id = ?",
            (record.agent_run_id,),
        ).fetchone()[0]
    assert project_id == 41
    repository.close()


@pytest.mark.parametrize("project_id", (0, -1, True, "41"))
def test_list_rejects_invalid_project_id(tmp_path: Path, project_id: object) -> None:
    repository = SQLiteDiagnosisRunRepository(tmp_path / "agentlab-runtime.sqlite3")

    with pytest.raises(ValueError, match="positive integer"):
        repository.list_by_project_id(project_id)  # type: ignore[arg-type]

    repository.close()


def test_credentials_are_not_modelled_or_persisted(tmp_path: Path) -> None:
    database_path = tmp_path / "agentlab-runtime.sqlite3"
    marker = "super-secret-java-token-marker"
    repository = SQLiteDiagnosisRunRepository(database_path)
    record = stored_run()
    repository.save(record)

    assert "token" not in StoredDiagnosisRun.model_fields
    with sqlite3.connect(database_path) as connection:
        payload = connection.execute(
            "SELECT payload_json FROM diagnosis_run WHERE agent_run_id = ?",
            (record.agent_run_id,),
        ).fetchone()[0]
    assert marker not in payload
    repository.close()
