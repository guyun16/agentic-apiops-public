"""Workflow preflight policy layered above Java's final authority."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.guardrails.violations import (
    EvidenceSource,
    SafetyViolationRecorder,
    ViolationCode,
)
from app.schemas.tool_call import ToolCall
from app.tools import ToolIntent, ToolRisk, ToolRiskClassifier


class PreflightDecision(StrEnum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


class PreflightOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    risk: ToolRisk
    decision: PreflightDecision
    violation_code: ViolationCode | None = None


class PreflightPolicy:
    """Map deterministic risk to workflow control; ALLOW is not authorization."""

    def decide(self, risk: ToolRisk) -> PreflightOutcome:
        if risk is ToolRisk.READ_ONLY_LOW:
            return PreflightOutcome(risk=risk, decision=PreflightDecision.ALLOW)
        if risk in {ToolRisk.SENSITIVE_READ, ToolRisk.EXPENSIVE}:
            return PreflightOutcome(
                risk=risk,
                decision=PreflightDecision.REQUIRE_APPROVAL,
            )
        violation_codes = {
            ToolRisk.SIDE_EFFECT_WRITE: ViolationCode.SIDE_EFFECT_WRITE_DENIED,
            ToolRisk.CROSS_PROJECT_RISK: ViolationCode.CROSS_PROJECT_SCOPE,
            ToolRisk.UNKNOWN_UNSUPPORTED: ViolationCode.UNKNOWN_UNSUPPORTED_TOOL,
        }
        return PreflightOutcome(
            risk=risk,
            decision=PreflightDecision.DENY,
            violation_code=violation_codes[risk],
        )


class ToolPreflightGuard:
    """Compose classification, policy, and redaction-safe denial recording."""

    def __init__(
        self,
        classifier: ToolRiskClassifier,
        *,
        policy: PreflightPolicy | None = None,
        recorder: SafetyViolationRecorder | None = None,
    ) -> None:
        if not isinstance(classifier, ToolRiskClassifier):
            raise TypeError("classifier must be a ToolRiskClassifier")
        self._classifier = classifier
        self._policy = policy or PreflightPolicy()
        self._recorder = recorder

    def evaluate(self, intent: ToolIntent, tool_call: ToolCall) -> PreflightOutcome:
        outcome = self._policy.decide(self._classifier.classify(intent, tool_call))
        if outcome.violation_code is not None and self._recorder is not None:
            self._recorder.record(
                outcome.violation_code,
                EvidenceSource.PREFLIGHT,
                tool_call,
            )
        return outcome


__all__ = [
    "PreflightDecision",
    "PreflightOutcome",
    "PreflightPolicy",
    "ToolPreflightGuard",
]
