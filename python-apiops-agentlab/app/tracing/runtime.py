"""Process-scoped trace sink composition and typed JSONL readback helpers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from functools import cache
from pathlib import Path

from app.core.settings import AppSettings, get_settings

from .exporter import JsonlTraceSink, read_trace_jsonl
from .models import TraceRecord
from .recorder import InMemoryTraceSink, TraceRecorder, TraceSink


@cache
def _build_trace_sink(
    sink_kind: str,
    jsonl_path: str,
    max_file_bytes: int,
) -> TraceSink:
    """Build one sink for one effective process configuration."""

    if sink_kind == "jsonl":
        return JsonlTraceSink(jsonl_path, max_file_bytes=max_file_bytes)
    if sink_kind == "memory":
        return InMemoryTraceSink()
    raise ValueError(f"unsupported trace sink: {sink_kind}")


def get_trace_sink(settings: AppSettings | None = None) -> TraceSink:
    """Return the process-scoped sink for the effective trace configuration."""

    effective_settings = settings if settings is not None else get_settings()
    return _build_trace_sink(
        effective_settings.trace_sink,
        effective_settings.trace_jsonl_path,
        effective_settings.trace_max_file_bytes,
    )


def create_trace_recorder(settings: AppSettings | None = None) -> TraceRecorder:
    """Create a fresh recorder backed by the process-scoped trace sink."""

    return TraceRecorder(get_trace_sink(settings))


def read_persisted_trace_records(
    settings: AppSettings | None = None,
) -> tuple[TraceRecord, ...]:
    """Read typed JSONL records, treating a missing file as empty history."""

    effective_settings = settings if settings is not None else get_settings()
    try:
        return read_trace_jsonl(Path(effective_settings.trace_jsonl_path))
    except FileNotFoundError:
        return ()


def normalize_trace_project_id(value: object) -> int | None:
    """Normalize one trace identity value to a positive Java project ID."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    try:
        project_id = int(value)
    except ValueError:
        return None
    return project_id if project_id > 0 else None


def resolve_trace_project_id(records: Sequence[TraceRecord]) -> int | None:
    """Resolve exactly one usable project owner, failing closed otherwise."""

    project_ids: set[int] = set()
    for record in records:
        if record.project_id is None:
            continue
        project_id = normalize_trace_project_id(record.project_id)
        if project_id is None:
            return None
        project_ids.add(project_id)
    return next(iter(project_ids)) if len(project_ids) == 1 else None


def _trace_sort_key(record: TraceRecord) -> tuple[str, int, datetime]:
    return (
        record.agent_run_id,
        record.sequence if record.sequence is not None else 0,
        record.timestamp,
    )


def query_persisted_trace_records(
    *,
    trace_id: str | None = None,
    agent_run_id: str | None = None,
    project_id: str | int | None = None,
    settings: AppSettings | None = None,
) -> tuple[TraceRecord, ...]:
    """Filter typed persisted records and return them in logical order."""

    records = read_persisted_trace_records(settings)
    requested_project_id = (
        normalize_trace_project_id(project_id) if project_id is not None else None
    )
    if project_id is not None and requested_project_id is None:
        return ()
    filtered = (
        record
        for record in records
        if (trace_id is None or record.trace_id == trace_id)
        and (agent_run_id is None or record.agent_run_id == agent_run_id)
        and (
            project_id is None
            or normalize_trace_project_id(record.project_id) == requested_project_id
        )
    )
    return tuple(sorted(filtered, key=_trace_sort_key))


__all__ = [
    "create_trace_recorder",
    "get_trace_sink",
    "normalize_trace_project_id",
    "query_persisted_trace_records",
    "read_persisted_trace_records",
    "resolve_trace_project_id",
]
