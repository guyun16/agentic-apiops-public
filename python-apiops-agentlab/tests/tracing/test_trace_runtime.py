from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings import AppSettings
from app.tracing import (
    AgentRun,
    InMemoryTraceSink,
    JsonlTraceSink,
    TraceEvent,
    TraceExportLimitError,
    TraceStatus,
    create_trace_recorder,
    get_trace_sink,
    query_persisted_trace_records,
    read_persisted_trace_records,
    resolve_trace_project_id,
)


def _settings(
    tmp_path: Path,
    *,
    trace_sink: str = "jsonl",
    max_file_bytes: int = 16 * 1024 * 1024,
) -> AppSettings:
    return AppSettings(
        trace_sink=trace_sink,
        trace_jsonl_path=str(tmp_path / "agent-traces.jsonl"),
        trace_max_file_bytes=max_file_bytes,
    )


def _record(
    *,
    trace_id: str,
    agent_run_id: str,
    sequence: int | None = None,
    project_id: int | str | None = None,
    timestamp: datetime | None = None,
) -> AgentRun:
    return AgentRun(
        trace_id=trace_id,
        agent_run_id=agent_run_id,
        sequence=sequence,
        timestamp=timestamp or datetime(2026, 1, 1, tzinfo=UTC),
        project_id=project_id,
        event=TraceEvent.START,
        status=TraceStatus.RUNNING,
    )


def _persist(settings: AppSettings, *records: AgentRun) -> None:
    sink = get_trace_sink(settings)
    assert isinstance(sink, JsonlTraceSink)
    for record in records:
        sink.write(record.model_dump(mode="json", exclude_none=False))


def test_trace_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("TRACE_SINK", "TRACE_JSONL_PATH", "TRACE_MAX_FILE_BYTES"):
        monkeypatch.delenv(name, raising=False)

    settings = AppSettings()

    assert settings.trace_sink == "jsonl"
    assert settings.trace_jsonl_path == "data/traces/agent-traces.jsonl"
    assert settings.trace_max_file_bytes == 16 * 1024 * 1024


def test_trace_settings_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "custom-traces.jsonl"
    monkeypatch.setenv("TRACE_SINK", "memory")
    monkeypatch.setenv("TRACE_JSONL_PATH", str(path))
    monkeypatch.setenv("TRACE_MAX_FILE_BYTES", "4096")

    settings = AppSettings()

    assert settings.trace_sink == "memory"
    assert settings.trace_jsonl_path == str(path)
    assert settings.trace_max_file_bytes == 4096


def test_trace_settings_reject_invalid_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACE_SINK", "invalid")

    with pytest.raises(ValidationError):
        AppSettings()


@pytest.mark.parametrize("value", ["0", "-1"])
def test_trace_settings_reject_non_positive_file_limit(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("TRACE_MAX_FILE_BYTES", value)

    with pytest.raises(ValidationError):
        AppSettings()


def test_jsonl_sink_is_process_scoped_and_uses_configured_file_limit(tmp_path: Path) -> None:
    settings = _settings(tmp_path, max_file_bytes=1)

    sink_1 = get_trace_sink(settings)
    sink_2 = get_trace_sink(settings)

    assert sink_1 is sink_2
    assert isinstance(sink_1, JsonlTraceSink)
    assert sink_1.path == Path(settings.trace_jsonl_path)
    with pytest.raises(TraceExportLimitError):
        sink_1.write(
            _record(trace_id="trace-limit", agent_run_id="run-limit", sequence=1).model_dump(
                mode="json",
                exclude_none=False,
            )
        )


def test_memory_sink_is_process_scoped(tmp_path: Path) -> None:
    settings = _settings(tmp_path, trace_sink="memory")

    sink_1 = get_trace_sink(settings)
    sink_2 = get_trace_sink(settings)

    assert sink_1 is sink_2
    assert isinstance(sink_1, InMemoryTraceSink)
    assert not Path(settings.trace_jsonl_path).exists()


def test_recorder_factory_is_fresh_but_uses_shared_sink(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    recorder_1 = create_trace_recorder(settings)
    recorder_2 = create_trace_recorder(settings)

    assert recorder_1 is not recorder_2
    assert get_trace_sink(settings) is get_trace_sink(settings)

    recorder_1.record(_record(trace_id="trace-a", agent_run_id="run-a"))
    recorder_2.record(_record(trace_id="trace-b", agent_run_id="run-b"))
    persisted = read_persisted_trace_records(settings)

    assert [record.agent_run_id for record in persisted] == ["run-a", "run-b"]
    assert all(isinstance(record, AgentRun) for record in persisted)


def test_missing_jsonl_is_empty_history(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    assert not Path(settings.trace_jsonl_path).exists()
    assert read_persisted_trace_records(settings) == ()


def test_query_filters_by_trace_id(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _persist(
        settings,
        _record(trace_id="trace-a", agent_run_id="run-a", sequence=1),
        _record(trace_id="trace-b", agent_run_id="run-b", sequence=1),
    )

    result = query_persisted_trace_records(trace_id="trace-a", settings=settings)

    assert [record.trace_id for record in result] == ["trace-a"]


def test_query_filters_by_agent_run_id(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _persist(
        settings,
        _record(trace_id="trace-a", agent_run_id="run-a", sequence=1),
        _record(trace_id="trace-b", agent_run_id="run-b", sequence=1),
    )

    result = query_persisted_trace_records(agent_run_id="run-a", settings=settings)

    assert [record.agent_run_id for record in result] == ["run-a"]


def test_query_filters_use_and_semantics_and_project_id(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _persist(
        settings,
        _record(trace_id="trace-a", agent_run_id="run-a", sequence=1, project_id=11),
        _record(trace_id="trace-a", agent_run_id="run-b", sequence=1, project_id=22),
        _record(trace_id="trace-b", agent_run_id="run-b", sequence=2, project_id=22),
    )

    and_result = query_persisted_trace_records(
        trace_id="trace-a",
        agent_run_id="run-b",
        settings=settings,
    )
    project_result = query_persisted_trace_records(project_id=22, settings=settings)

    assert [(record.trace_id, record.agent_run_id) for record in and_result] == [
        ("trace-a", "run-b")
    ]
    assert [record.sequence for record in project_result] == [1, 2]


def test_query_sorts_by_run_sequence_then_timestamp_not_physical_order(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    second = _record(
        trace_id="trace-order",
        agent_run_id="run-order",
        sequence=2,
        timestamp=start + timedelta(seconds=2),
    )
    first = _record(
        trace_id="trace-order",
        agent_run_id="run-order",
        sequence=1,
        timestamp=start + timedelta(seconds=1),
    )
    _persist(settings, second, first)

    result = query_persisted_trace_records(trace_id="trace-order", settings=settings)

    assert [record.sequence for record in result] == [1, 2]
    assert all(isinstance(record, AgentRun) for record in result)


def test_resolve_trace_project_id_accepts_one_normalized_owner() -> None:
    records = (
        _record(trace_id="trace-owner", agent_run_id="run-owner", project_id=41),
        _record(trace_id="trace-owner", agent_run_id="run-owner", project_id="41"),
        _record(trace_id="trace-owner", agent_run_id="run-owner", project_id=None),
    )

    assert resolve_trace_project_id(records) == 41


def test_resolve_trace_project_id_fails_closed_without_one_valid_owner() -> None:
    assert resolve_trace_project_id(
        (_record(trace_id="trace-owner", agent_run_id="run-owner"),)
    ) is None
    assert resolve_trace_project_id(
        (
            _record(trace_id="trace-owner", agent_run_id="run-owner", project_id=41),
            _record(trace_id="trace-owner", agent_run_id="run-owner", project_id=42),
        )
    ) is None


@pytest.mark.parametrize("project_id", (0, -1, "", " ", "not-a-number", True))
def test_resolve_trace_project_id_rejects_unusable_values(project_id: object) -> None:
    record = _record(trace_id="trace-owner", agent_run_id="run-owner").model_copy(
        update={"project_id": project_id}
    )

    assert resolve_trace_project_id((record,)) is None


def test_query_project_filter_normalizes_numeric_string_ids(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _persist(
        settings,
        _record(trace_id="trace-project", agent_run_id="run-project", project_id="41", sequence=1),
        _record(trace_id="trace-other", agent_run_id="run-other", project_id=42, sequence=1),
    )

    result = query_persisted_trace_records(project_id=41, settings=settings)

    assert [(record.trace_id, record.project_id) for record in result] == [
        ("trace-project", "41")
    ]
