"""Deterministic workflow-side tool risk classification."""

from __future__ import annotations

from enum import StrEnum

from app.schemas.tool_call import ToolCall
from app.tools.core import ToolCatalog, ToolIntent


class ToolRisk(StrEnum):
    """Workflow risk labels; these do not grant Java resource authority."""

    READ_ONLY_LOW = "READ_ONLY_LOW"
    SENSITIVE_READ = "SENSITIVE_READ"
    EXPENSIVE = "EXPENSIVE"
    SIDE_EFFECT_WRITE = "SIDE_EFFECT_WRITE"
    CROSS_PROJECT_RISK = "CROSS_PROJECT_RISK"
    UNKNOWN_UNSUPPORTED = "UNKNOWN_UNSUPPORTED"


class ToolRiskClassifier:
    """Classify trusted workflow facts without accepting a model risk claim."""

    def __init__(self, catalog: ToolCatalog, *, trusted_project_id: str) -> None:
        if not isinstance(catalog, ToolCatalog):
            raise TypeError("catalog must be a ToolCatalog")
        if not trusted_project_id:
            raise ValueError("trusted_project_id must not be empty")
        self._catalog = catalog
        self._trusted_project_id = trusted_project_id

    def classify(self, intent: ToolIntent, tool_call: ToolCall) -> ToolRisk:
        if not isinstance(intent, ToolIntent):
            raise TypeError("intent must be a ToolIntent")
        if not isinstance(tool_call, ToolCall):
            raise TypeError("tool_call must be a ToolCall")
        if tool_call.project_id != self._trusted_project_id:
            return ToolRisk.CROSS_PROJECT_RISK
        if tool_call.tool_name == "runner.submit":
            return ToolRisk.SIDE_EFFECT_WRITE
        if not self._catalog.contains(intent.tool_name):
            return ToolRisk.UNKNOWN_UNSUPPORTED

        descriptor = self._catalog.get(intent.tool_name)
        if descriptor.contract_name != tool_call.tool_name:
            return ToolRisk.UNKNOWN_UNSUPPORTED
        if tool_call.tool_name == "redis.read":
            return ToolRisk.SENSITIVE_READ
        if tool_call.tool_name == "rag.search" and _is_expensive_rag_query(intent):
            return ToolRisk.EXPENSIVE
        return ToolRisk.READ_ONLY_LOW


def _is_expensive_rag_query(intent: ToolIntent) -> bool:
    top_k = intent.arguments.get("topK")
    return isinstance(top_k, int) and not isinstance(top_k, bool) and top_k > 10


__all__ = ["ToolRisk", "ToolRiskClassifier"]
