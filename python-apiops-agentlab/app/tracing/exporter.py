"""Bounded append-only JSONL sink and typed trace readback."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from threading import RLock

from pydantic import TypeAdapter

from .models import TraceLimits, TraceRecord
from .redaction import redact_value

_TRACE_RECORD_ADAPTER = TypeAdapter(TraceRecord)
_DEFAULT_MAX_FILE_BYTES = 16 * 1024 * 1024


class TraceExportLimitError(RuntimeError):
    """The append would exceed an explicit JSONL storage boundary."""


class JsonlTraceSink:
    """Append already-observed trace facts without deriving business fields."""

    def __init__(
        self,
        path: str | Path,
        *,
        limits: TraceLimits | None = None,
        max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
    ) -> None:
        if isinstance(max_file_bytes, bool) or not isinstance(max_file_bytes, int):
            raise TypeError("max_file_bytes must be an integer")
        if max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive")
        self._path = Path(path)
        self._limits = limits or TraceLimits()
        self._max_file_bytes = max_file_bytes
        self._lock = RLock()

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: Mapping[str, object]) -> None:
        """Redact once more, bound, and append one record as one JSON line."""

        safe = redact_value(record, max_summary_chars=self._limits.max_summary_chars)
        if not isinstance(safe, Mapping):
            raise TypeError("trace record must be a mapping")
        if not isinstance(safe.get("sequence"), int) or safe["sequence"] < 1:
            raise ValueError("exported trace record requires an assigned positive sequence")
        line = json.dumps(
            safe,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        encoded = f"{line}\n".encode()
        if len(encoded) > self._limits.max_record_bytes:
            raise TraceExportLimitError("single JSONL record exceeds max_record_bytes")

        with self._lock:
            current_bytes = self._path.stat().st_size if self._path.exists() else 0
            if current_bytes + len(encoded) > self._max_file_bytes:
                raise TraceExportLimitError("JSONL file exceeds max_file_bytes")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("ab") as stream:
                stream.write(encoded)


def read_trace_jsonl(path: str | Path) -> tuple[TraceRecord, ...]:
    """Restore typed records; physical line order is retained but not authoritative."""

    records: list[TraceRecord] = []
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = _TRACE_RECORD_ADAPTER.validate_json(line)
            except Exception as exc:
                raise ValueError(f"invalid trace JSONL record at line {line_number}") from exc
            if record.sequence is None:
                raise ValueError(f"trace JSONL record at line {line_number} has no sequence")
            records.append(record)
    return tuple(records)


__all__ = ["JsonlTraceSink", "TraceExportLimitError", "read_trace_jsonl"]
