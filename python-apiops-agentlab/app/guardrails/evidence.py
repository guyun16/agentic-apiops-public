"""Deterministic handling for untrusted textual tool evidence."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictStr

from app.guardrails.violations import (
    EvidenceSource,
    SafetyViolationRecorder,
    ViolationCode,
)
from app.schemas.testcase_dsl import JsonValue
from app.schemas.tool_call import ToolCall
from app.schemas.tool_result import ToolResult

_PROMPT_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior)\s+instructions?\b",
        r"\b(?:system prompt|developer message)\b",
        r"\b(?:call|invoke|execute|run)\s+(?:the\s+)?tool\b",
        r"\breveal\b.{0,40}\b(?:secret|token|password)\b",
        r"\byou are now\b",
    )
)
_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(\b(?:authorization\s*:\s*)?bearer\s+)([A-Za-z0-9._~+/=-]+)"),
    re.compile(r"(?i)(\b(?:password|passwd|api[_-]?key|secret|token)\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(\bcookie\s*:\s*)([^\r\n]+)"),
)


class SensitiveDataOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    text: StrictStr
    detected: bool


class UntrustedEvidence(BaseModel):
    """Text safe to expose as data, never as a trusted instruction."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    source: EvidenceSource
    text: StrictStr
    prompt_injection_detected: bool
    sensitive_data_detected: bool
    trusted_instruction: Literal[False] = False


class PromptInjectionDetector:
    def detect(self, text: str) -> bool:
        return any(pattern.search(text) is not None for pattern in _PROMPT_INJECTION_PATTERNS)


class SensitiveDataGuard:
    def mask(self, text: str) -> SensitiveDataOutcome:
        masked = text
        detected = False
        for pattern in _SENSITIVE_PATTERNS:
            masked, count = pattern.subn(r"\1[REDACTED]", masked)
            detected = detected or count > 0
        return SensitiveDataOutcome(text=masked, detected=detected)


class UntrustedEvidenceProcessor:
    """Tag, inspect, and mask bounded result text without creating ToolCalls."""

    def __init__(
        self,
        *,
        recorder: SafetyViolationRecorder | None = None,
        max_items: int = 16,
        max_chars: int = 2_048,
    ) -> None:
        if max_items < 1 or max_chars < 1:
            raise ValueError("evidence limits must be positive")
        self._detector = PromptInjectionDetector()
        self._sensitive_data = SensitiveDataGuard()
        self._recorder = recorder
        self._max_items = max_items
        self._max_chars = max_chars

    def process(
        self,
        text: str,
        *,
        source: EvidenceSource,
        tool_call: ToolCall,
    ) -> UntrustedEvidence:
        prompt_injection = self._detector.detect(text)
        masked = self._sensitive_data.mask(text)
        if self._recorder is not None:
            if prompt_injection:
                self._recorder.record(
                    ViolationCode.PROMPT_INJECTION_DETECTED,
                    source,
                    tool_call,
                )
            if masked.detected:
                self._recorder.record(
                    ViolationCode.SENSITIVE_DATA_DETECTED,
                    source,
                    tool_call,
                )
        return UntrustedEvidence(
            source=source,
            text=masked.text[: self._max_chars],
            prompt_injection_detected=prompt_injection,
            sensitive_data_detected=masked.detected,
        )

    def from_tool_result(
        self,
        result: ToolResult,
        *,
        tool_call: ToolCall,
        source: EvidenceSource = EvidenceSource.TOOL_RESULT,
    ) -> tuple[UntrustedEvidence, ...]:
        texts: list[str] = []
        _collect_text(result.data, texts, limit=self._max_items)
        return tuple(self.process(text, source=source, tool_call=tool_call) for text in texts)


def _collect_text(value: JsonValue, output: list[str], *, limit: int) -> None:
    if len(output) >= limit:
        return
    if isinstance(value, str):
        output.append(value)
    elif isinstance(value, list):
        for item in value:
            _collect_text(item, output, limit=limit)
    elif isinstance(value, dict):
        for key in sorted(value):
            _collect_text(value[key], output, limit=limit)


__all__ = [
    "PromptInjectionDetector",
    "SensitiveDataGuard",
    "SensitiveDataOutcome",
    "UntrustedEvidence",
    "UntrustedEvidenceProcessor",
]
