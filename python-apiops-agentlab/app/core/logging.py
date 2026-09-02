"""Standard-library logging configuration with a deliberately small surface."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

LOGGER_NAME = "app"
logger = logging.getLogger(LOGGER_NAME)


@dataclass(frozen=True)
class CorrelationIds:
    """The request-local identifiers used only for application log correlation."""

    trace_id: str
    request_id: str


_correlation_ids: ContextVar[CorrelationIds | None] = ContextVar(
    "app_correlation_ids",
    default=None,
)


def current_correlation_ids() -> CorrelationIds | None:
    """Return the identifiers bound to the current request context, if any."""

    return _correlation_ids.get()


def correlation_log_extra() -> dict[str, str]:
    """Return safe structured fields without recording request headers."""

    ids = current_correlation_ids()
    if ids is None:
        return {"trace_id": "-", "request_id": "-"}
    return {"trace_id": ids.trace_id, "request_id": ids.request_id}


def _trace_id_or_new(value: str | None) -> str:
    if value is not None:
        candidate = value.strip()
        if candidate:
            return candidate
    return uuid4().hex


@contextmanager
def bind_correlation(trace_id: str | None) -> Iterator[CorrelationIds]:
    """Bind one request's trace ID and a newly generated request ID."""

    ids = CorrelationIds(trace_id=_trace_id_or_new(trace_id), request_id=uuid4().hex)
    token = _correlation_ids.set(ids)
    try:
        yield ids
    finally:
        _correlation_ids.reset(token)


def configure_logging(log_level: str = "INFO") -> None:
    """Configure standard logging without recording request payloads or headers."""

    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Unsupported log level: {log_level}")

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=numeric_level)
    logger.setLevel(numeric_level)
