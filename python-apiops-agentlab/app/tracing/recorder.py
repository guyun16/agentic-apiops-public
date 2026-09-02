"""Best-effort in-memory trace recorder boundary."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from copy import deepcopy
from threading import RLock
from typing import Protocol

from .models import (
    TRACE_RECORD_TYPES,
    TraceLimits,
    TraceRecord,
)
from .redaction import redact_value

logger = logging.getLogger(__name__)


class TraceSink(Protocol):
    """Serialization sink; a sink failure must never become workflow failure."""

    def write(self, record: Mapping[str, object]) -> None:
        """Persist one already-redacted JSON-compatible record."""


class InMemoryTraceSink:
    """Small test/default sink; it is not a JSONL exporter or durable store."""

    def __init__(self) -> None:
        self._records: list[dict[str, object]] = []

    def write(self, record: Mapping[str, object]) -> None:
        self._records.append(deepcopy(dict(record)))

    @property
    def records(self) -> tuple[dict[str, object], ...]:
        return tuple(deepcopy(self._records))


class TraceRecorder:
    """Observe typed facts without participating in business routing.

    ``record`` deliberately returns ``None``.  It allocates sequence numbers,
    redacts/serializes a bounded payload, and contains sink failures.  It does
    not retry a model/tool, alter a decision, or raise a route-affecting error.
    """

    def __init__(
        self,
        sink: TraceSink | None = None,
        *,
        limits: TraceLimits | None = None,
    ) -> None:
        if sink is not None and not callable(getattr(sink, "write", None)):
            raise TypeError("sink must provide write(record)")
        if limits is not None and not isinstance(limits, TraceLimits):
            raise TypeError("limits must be a TraceLimits")
        self._sink = sink or InMemoryTraceSink()
        self._limits = limits or TraceLimits()
        self._next_sequence_by_run: dict[str, int] = {}
        self._run_record_counts: dict[str, int] = {}
        self._run_bytes: dict[str, int] = {}
        self._stopped_runs: set[str] = set()
        self._typed_records: list[TraceRecord] = []
        self._lock = RLock()
        self._degraded = False
        self._degradation_reasons: list[str] = []

    @property
    def limits(self) -> TraceLimits:
        return self._limits

    @property
    def degraded(self) -> bool:
        return self._degraded

    @property
    def degradation_reasons(self) -> tuple[str, ...]:
        return tuple(self._degradation_reasons)

    @property
    def accepted_records(self) -> int:
        with self._lock:
            return sum(self._run_record_counts.values())

    @property
    def typed_records(self) -> tuple[TraceRecord, ...]:
        """Return accepted typed records for an existing evaluator boundary."""

        with self._lock:
            return tuple(self._typed_records)

    def record(self, record: TraceRecord) -> None:
        """Best-effort observe one typed record; never expose a route boolean."""

        run_id = getattr(record, "agent_run_id", "unknown")
        try:
            with self._lock:
                if not isinstance(record, TRACE_RECORD_TYPES):
                    raise TypeError("record must be a supported internal trace model")
                self._record_typed(record)
        except Exception as exc:  # noqa: BLE001 - recorder boundary contains all sink failures
            self._degrade(str(run_id), f"recording_exception:{type(exc).__name__}")

    def _record_typed(self, record: TraceRecord) -> None:
        run_id = record.agent_run_id
        if run_id in self._stopped_runs:
            return

        sequence = self._next_sequence_by_run.get(run_id, 0) + 1
        assigned = record.model_copy(update={"sequence": sequence})
        payload = assigned.model_dump(mode="json", exclude_none=False)
        redacted = redact_value(
            payload,
            max_summary_chars=self._limits.max_summary_chars,
        )
        serialized = json.dumps(
            redacted,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        record_bytes = len(serialized.encode("utf-8"))
        if record_bytes > self._limits.max_record_bytes:
            self._stopped_runs.add(run_id)
            self._degrade(run_id, "single_record_size_limit")
            return

        current_count = self._run_record_counts.get(run_id, 0)
        current_bytes = self._run_bytes.get(run_id, 0)
        if current_count >= self._limits.max_run_records:
            self._stopped_runs.add(run_id)
            self._degrade(run_id, "run_record_count_limit")
            return
        if current_bytes + record_bytes > self._limits.max_run_bytes:
            self._stopped_runs.add(run_id)
            self._degrade(run_id, "run_size_limit")
            return

        self._typed_records.append(assigned)
        self._next_sequence_by_run[run_id] = sequence
        self._run_record_counts[run_id] = current_count + 1
        self._run_bytes[run_id] = current_bytes + record_bytes
        self._sink.write(redacted if isinstance(redacted, Mapping) else {})

    def _degrade(self, run_id: str, reason: str) -> None:
        self._degraded = True
        marker = f"{run_id}:{reason}"
        if marker not in self._degradation_reasons:
            self._degradation_reasons.append(marker)
        try:
            logger.warning("trace recorder degraded: %s", marker)
        except Exception:  # pragma: no cover - logging must not affect business
            pass


__all__ = ["InMemoryTraceSink", "TraceRecorder", "TraceSink"]
