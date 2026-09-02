"""Minimal redaction-safe safety violation facts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, StrictStr

from app.schemas.tool_call import ToolCall


class ViolationCode(StrEnum):
    UNKNOWN_UNSUPPORTED_TOOL = "UNKNOWN_UNSUPPORTED_TOOL"
    CROSS_PROJECT_SCOPE = "CROSS_PROJECT_SCOPE"
    SIDE_EFFECT_WRITE_DENIED = "SIDE_EFFECT_WRITE_DENIED"
    PROMPT_INJECTION_DETECTED = "PROMPT_INJECTION_DETECTED"
    SENSITIVE_DATA_DETECTED = "SENSITIVE_DATA_DETECTED"


class EvidenceSource(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    TOOL_RESULT = "TOOL_RESULT"
    LOG = "LOG"
    RAG = "RAG"
    HTTP = "HTTP"


class SafetyViolation(BaseModel):
    """Correlation-only event with no field for raw evidence or credentials."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    code: ViolationCode
    source: EvidenceSource
    trace_id: StrictStr
    agent_run_id: StrictStr
    tool_name: StrictStr


class SafetyViolationRecorder:
    """Process-local section-3 recorder; not a Stage 19 trace platform."""

    def __init__(self) -> None:
        self._events: list[SafetyViolation] = []

    def record(
        self,
        code: ViolationCode,
        source: EvidenceSource,
        tool_call: ToolCall,
    ) -> SafetyViolation:
        if not isinstance(tool_call, ToolCall):
            raise TypeError("tool_call must be a ToolCall")
        event = SafetyViolation(
            code=code,
            source=source,
            trace_id=tool_call.trace_id,
            agent_run_id=tool_call.agent_run_id,
            tool_name=tool_call.tool_name,
        )
        self._events.append(event)
        return event

    def events(self) -> tuple[SafetyViolation, ...]:
        return tuple(self._events)


__all__ = [
    "EvidenceSource",
    "SafetyViolation",
    "SafetyViolationRecorder",
    "ViolationCode",
]
