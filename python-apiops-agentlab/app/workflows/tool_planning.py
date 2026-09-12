"""Deterministic Tool Planning and evidence sufficiency decisions.

This module is intentionally a small execution-side boundary.  It never
imports benchmark Ground Truth and it does not decide from a model's final
diagnosis.  Callers provide the runtime task contract, observed facts, and the
allow-listed tool names; the returned decision is safe to record and route.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator

from app.rag.context import ContextItem, ContextPack, ContextSource
from app.schemas.runner import TestReport
from app.tools import ToolIntent

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]


class ToolPlanningError(ValueError):
    """A runtime planning input cannot produce a safe tool intent."""


class ToolRequirement(StrEnum):
    """The execution-side action required by the current runtime contract."""

    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    NOT_REQUIRED = "NOT_REQUIRED"
    DENY = "DENY"
    UNRESOLVED = "UNRESOLVED"


class EvidenceSufficiency(StrEnum):
    """Pre-tool evidence state; it is not the model's final report field."""

    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    UNRESOLVED = "UNRESOLVED"


class ToolPlanningDecision(BaseModel):
    """Auditable, Ground Truth-free decision at the workflow routing gate."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
        frozen=True,
        validate_default=True,
    )

    requirement: ToolRequirement
    selected_tool: NonEmptyString | None = None
    reason: NonEmptyString = Field(max_length=1024)
    evidence_sufficiency: EvidenceSufficiency
    authority_source: NonEmptyString = Field(max_length=256)
    allowed: StrictBool
    capability_available: StrictBool | None = None

    @model_validator(mode="after")
    def validate_route_contract(self) -> ToolPlanningDecision:
        if self.requirement is ToolRequirement.REQUIRED:
            if self.selected_tool is None:
                raise ValueError("REQUIRED decision must select a tool")
            if not self.allowed:
                raise ValueError("REQUIRED decision must be allowed")
            if self.capability_available is not True:
                raise ValueError("REQUIRED decision must confirm capability availability")
        elif self.requirement is ToolRequirement.OPTIONAL:
            if not self.allowed:
                raise ValueError("OPTIONAL decision must be allowed")
        elif self.requirement is ToolRequirement.NOT_REQUIRED:
            if self.selected_tool is not None:
                raise ValueError("NOT_REQUIRED decision must not select a tool")
            if not self.allowed:
                raise ValueError("NOT_REQUIRED decision must remain routable")
        elif self.allowed:
            raise ValueError("DENY and UNRESOLVED decisions must not be allowed")
        return self

    @property
    def must_invoke(self) -> bool:
        """Whether the deterministic gate must enter the tool path."""

        return self.requirement is ToolRequirement.REQUIRED


def _task_type_value(task_type: object) -> str:
    value = getattr(task_type, "value", task_type)
    if not isinstance(value, str) or not value.strip():
        raise TypeError("task_type must be a non-empty string or enum")
    return value.strip().upper()


def _validate_readiness_inputs(
    project_id: int | None,
    query_source: str | None,
    capability_available: bool | None,
) -> None:
    if project_id is not None and (
        isinstance(project_id, bool) or not isinstance(project_id, int)
    ):
        raise TypeError("project_id must be an integer or None")
    if query_source is not None and not isinstance(query_source, str):
        raise TypeError("query_source must be a string or None")
    if capability_available is not None and not isinstance(capability_available, bool):
        raise TypeError("capability_available must be a boolean or None")


def _effective_query_source(
    instruction: str,
    context: str,
    query_source: str | None,
) -> str:
    if query_source is not None:
        return query_source
    for candidate in (instruction, context):
        if candidate.strip():
            return candidate
    return ""


def _evidence_value(value: EvidenceSufficiency | str) -> EvidenceSufficiency:
    if isinstance(value, EvidenceSufficiency):
        return value
    if not isinstance(value, str):
        raise TypeError("evidence_sufficiency must be an EvidenceSufficiency or string")
    try:
        return EvidenceSufficiency(value.strip().upper())
    except ValueError as exc:
        raise ToolPlanningError(f"unknown evidence sufficiency: {value}") from exc


def _requirement_value(value: ToolRequirement | str) -> ToolRequirement:
    if isinstance(value, ToolRequirement):
        return value
    if not isinstance(value, str):
        raise TypeError("runtime_requirement must be a ToolRequirement or string")
    try:
        return ToolRequirement(value.strip().upper())
    except ValueError as exc:
        raise ToolPlanningError(f"unknown tool requirement: {value}") from exc


def _allowed_tool_names(allowed_tools: Iterable[str]) -> tuple[str, ...]:
    if isinstance(allowed_tools, str):
        raise TypeError("allowed_tools must be an iterable of tool names")
    names: list[str] = []
    for name in allowed_tools:
        if not isinstance(name, str) or not name.strip():
            raise TypeError("allowed_tools must contain non-empty strings")
        normalized = name.strip()
        if normalized not in names:
            names.append(normalized)
    return tuple(names)


def _context_text(context: Iterable[str | ContextItem] | None) -> str:
    if context is None:
        return ""
    if isinstance(context, str):
        return context
    parts: list[str] = []
    for item in context:
        if isinstance(item, ContextItem):
            parts.append(item.content)
        elif isinstance(item, str):
            parts.append(item)
        else:
            raise TypeError("context must contain only strings or ContextItem values")
    return "\n".join(parts)


def _select_tool(
    task_type: str,
    *,
    allowed_tools: tuple[str, ...],
    selected_tool: str | None,
) -> str | None:
    if selected_tool is not None:
        if not isinstance(selected_tool, str) or not selected_tool.strip():
            raise TypeError("selected_tool must be a non-empty string when provided")
        return selected_tool.strip()

    if task_type == "RAG_EVIDENCE_RETRIEVAL":
        return "rag.search"
    return allowed_tools[0] if len(allowed_tools) == 1 else None


def _unresolved(
    *,
    reason: str,
    evidence_sufficiency: EvidenceSufficiency,
    selected_tool: str | None = None,
    authority_source: str = "MISSING_EXECUTION_CONTRACT",
    capability_available: bool | None = None,
) -> ToolPlanningDecision:
    return ToolPlanningDecision(
        requirement=ToolRequirement.UNRESOLVED,
        selected_tool=selected_tool,
        reason=reason,
        evidence_sufficiency=evidence_sufficiency,
        authority_source=authority_source,
        allowed=False,
        capability_available=capability_available,
    )


def _rag_readiness_reason(
    *,
    tools: tuple[str, ...],
    project_id: int | None,
    query_source: str,
    capability_available: bool | None,
) -> str | None:
    missing: list[str] = []
    if "rag.search" not in tools:
        missing.append("rag.search is not in the runtime allow-list")
    if project_id is None or project_id < 1:
        missing.append("canonical project identity is unavailable")
    if not query_source.strip():
        missing.append("query source is empty")
    if capability_available is not True:
        missing.append("rag.search runtime capability is unavailable")
    if not missing:
        return None
    return "RAG execution is unresolved: " + "; ".join(missing) + "."


def decide_tool_requirement(
    task_type: object,
    *,
    evidence_sufficiency: EvidenceSufficiency | str = EvidenceSufficiency.UNRESOLVED,
    allowed_tools: Iterable[str] = (),
    instruction: str = "",
    context: Iterable[str | ContextItem] | None = None,
    project_id: int | None = None,
    query_source: str | None = None,
    capability_available: bool | None = None,
    runtime_requirement: ToolRequirement | str | None = None,
    selected_tool: str | None = None,
) -> ToolPlanningDecision:
    """Build one deterministic decision from runtime-visible inputs only.

    ``runtime_requirement`` is the adapter seam for a future versioned
    execution-side task contract. Evaluation fields are intentionally not
    accepted here.
    """

    if not isinstance(instruction, str):
        raise TypeError("instruction must be a string")
    _validate_readiness_inputs(project_id, query_source, capability_available)
    task_kind = _task_type_value(task_type)
    tools = _allowed_tool_names(allowed_tools)
    context_value = _context_text(context)
    effective_query = _effective_query_source(instruction, context_value, query_source)
    sufficiency = _evidence_value(evidence_sufficiency)
    requested_tool = _select_tool(
        task_kind,
        allowed_tools=tools,
        selected_tool=selected_tool,
    )

    if runtime_requirement is not None:
        requirement = _requirement_value(runtime_requirement)
        if requirement is ToolRequirement.DENY:
            return ToolPlanningDecision(
                requirement=requirement,
                selected_tool=requested_tool,
                reason="Runtime safety contract forbids this operation; no Java call is permitted.",
                evidence_sufficiency=sufficiency,
                authority_source="RUNTIME_SAFETY_CONTRACT",
                allowed=False,
            )
        if requirement is ToolRequirement.UNRESOLVED:
            return _unresolved(
                reason="Runtime contract explicitly leaves tool requirement unresolved.",
                evidence_sufficiency=sufficiency,
                selected_tool=None,
            )
        if requirement is ToolRequirement.NOT_REQUIRED:
            return ToolPlanningDecision(
                requirement=requirement,
                reason="Runtime contract states that no tool is required.",
                evidence_sufficiency=sufficiency,
                authority_source="RUNTIME_TASK_CONTRACT",
                allowed=True,
            )
        if requested_tool is None:
            return _unresolved(
                reason="Runtime contract requires a tool, but no selected tool is available.",
                evidence_sufficiency=sufficiency,
            )
        if requested_tool not in tools:
            return _unresolved(
                reason=f"Runtime contract selected {requested_tool}, which is not allow-listed.",
                evidence_sufficiency=sufficiency,
                selected_tool=requested_tool,
            )
        if requested_tool == "rag.search":
            readiness_reason = _rag_readiness_reason(
                tools=tools,
                project_id=project_id,
                query_source=effective_query,
                capability_available=capability_available,
            )
            if readiness_reason is not None:
                return _unresolved(
                    reason=readiness_reason,
                    evidence_sufficiency=sufficiency,
                    selected_tool=requested_tool,
                    authority_source="RAG_RUNTIME_READINESS",
                    capability_available=capability_available,
                )
        if capability_available is not True:
            return _unresolved(
                reason=(
                    f"Runtime contract selected {requested_tool}, but its runtime "
                    "capability is unavailable."
                ),
                evidence_sufficiency=sufficiency,
                selected_tool=requested_tool,
                authority_source="RUNTIME_TOOL_CAPABILITY",
                capability_available=capability_available,
            )
        return ToolPlanningDecision(
            requirement=requirement,
            selected_tool=requested_tool,
            reason=(
                "Runtime contract requires the selected tool."
                if requirement is ToolRequirement.REQUIRED
                else "Runtime contract permits the selected tool without requiring it."
            ),
            evidence_sufficiency=sufficiency,
            authority_source="RUNTIME_TASK_CONTRACT",
            allowed=True,
            capability_available=capability_available,
        )

    if task_kind == "RAG_EVIDENCE_RETRIEVAL":
        if requested_tool != "rag.search":
            return _unresolved(
                reason="RAG retrieval requires the selected runtime tool rag.search.",
                evidence_sufficiency=sufficiency,
                selected_tool=requested_tool,
                authority_source="TASK_TYPE_RUNTIME_CONTRACT",
                capability_available=capability_available,
            )
        readiness_reason = _rag_readiness_reason(
            tools=tools,
            project_id=project_id,
            query_source=effective_query,
            capability_available=capability_available,
        )
        if readiness_reason is not None:
            return _unresolved(
                reason=readiness_reason,
                evidence_sufficiency=sufficiency,
                selected_tool="rag.search",
                authority_source="RAG_RUNTIME_READINESS",
                capability_available=capability_available,
            )
        return ToolPlanningDecision(
            requirement=ToolRequirement.REQUIRED,
            selected_tool="rag.search",
            reason="Retrieval is the formal runtime objective; direct answering is not sufficient.",
            evidence_sufficiency=sufficiency,
            authority_source="TASK_TYPE_RUNTIME_CONTRACT",
            allowed=True,
            capability_available=True,
        )

    if task_kind == "TESTCASE_GENERATION":
        return ToolPlanningDecision(
            requirement=ToolRequirement.NOT_REQUIRED,
            reason="Testcase generation has no diagnosis tool requirement in the current contract.",
            evidence_sufficiency=sufficiency,
            authority_source="TASK_TYPE_RUNTIME_CONTRACT",
            allowed=True,
        )

    if task_kind in {"FAILURE_DIAGNOSIS", "TOOL_SAFETY", "E2E_APIOPS"}:
        return _unresolved(
            reason="BLOCKER: formal execution-side Tool Requirement Contract is missing.",
            evidence_sufficiency=sufficiency,
        )

    return _unresolved(
        reason=f"No execution-side tool policy is defined for task type {task_kind}.",
        evidence_sufficiency=sufficiency,
    )


def _normalise_fact_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _fact_value(facts: Mapping[str, object], *names: str) -> object | None:
    wanted = {_normalise_fact_key(name) for name in names}
    for key, value in facts.items():
        if _normalise_fact_key(key) in wanted:
            return value
    return None


def _fact_mapping_from_context(items: tuple[ContextItem, ...]) -> dict[str, object]:
    facts: dict[str, object] = {}
    for item in items:
        if item.source_type not in {ContextSource.EXECUTION_FACT, ContextSource.SHORT_TERM_CONTEXT}:
            continue
        try:
            value = json.loads(item.content)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        nested = value.get("facts")
        if isinstance(nested, dict):
            facts.update(nested)
        else:
            facts.update(value)
    return facts


def _context_items(value: Iterable[ContextItem] | ContextPack) -> tuple[ContextItem, ...]:
    if isinstance(value, ContextPack):
        return value.items
    if isinstance(value, ContextItem):
        return (value,)
    if isinstance(value, (str, bytes)):
        raise TypeError("context_items must contain ContextItem values")
    items = tuple(value)
    if any(not isinstance(item, ContextItem) for item in items):
        raise TypeError("context_items must contain ContextItem values")
    return items


def _has_verified_rag_evidence(item: ContextItem) -> bool:
    if item.source_type is not ContextSource.RAG_EVIDENCE:
        return False
    if not item.content.strip() or (not item.provenance and item.citation is None):
        return False
    if item.citation is not None:
        return all(
            isinstance(getattr(item.citation, field), str)
            and getattr(item.citation, field).strip()
            for field in ("source_type", "source_id", "document_id", "chunk_id")
        )
    try:
        payload = json.loads(item.content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(payload, list):
        return False
    return any(
        isinstance(entry, dict)
        and any(
            isinstance(entry.get(key), str) and entry[key].strip()
            for key in ("text", "content")
        )
        for entry in payload
    )


def _has_transport_boundary(report: TestReport) -> bool:
    steps = [step for case in report.cases for step in case.steps]
    return bool(steps) and all(
        step.response_status_code is None and not step.assertion_results for step in steps
    )


def _has_error_http_response(report: TestReport) -> bool:
    """Whether Java observed a semantic HTTP error response.

    Runner ``SUCCESS`` means that request execution and configured assertions
    completed successfully.  It does not turn an observed 4xx/5xx business
    response into a semantic no-failure result.
    """

    return any(
        step.response_status_code is not None and step.response_status_code >= 400
        for case in report.cases
        for step in case.steps
    )


def assess_evidence_sufficiency(
    report: TestReport | None = None,
    context_items: Iterable[ContextItem] | ContextPack = (),
    *,
    observed_facts: Mapping[str, object] | None = None,
) -> EvidenceSufficiency:
    """Assess only structured pre-tool facts and current context.

    Missing/conflicting evidence is explicit ``INSUFFICIENT``.  A terminal
    report with a known transport boundary and no HTTP/assertion observation is
    ``SUFFICIENT``.  Ambiguous or absent authority remains ``UNRESOLVED``.
    """

    if report is not None and not isinstance(report, TestReport):
        raise TypeError("report must be a TestReport or None")
    if observed_facts is not None and not isinstance(observed_facts, Mapping):
        raise TypeError("observed_facts must be a mapping or None")
    items = _context_items(context_items)
    facts = _fact_mapping_from_context(items)
    if observed_facts is not None:
        facts.update(observed_facts)

    missing = _fact_value(facts, "missingEvidence", "missing_evidence")
    conflict = _fact_value(facts, "conflictType", "conflict_type")
    if (isinstance(missing, (list, tuple, set)) and missing) or (
        isinstance(missing, str) and missing.strip()
    ):
        return EvidenceSufficiency.INSUFFICIENT
    if isinstance(conflict, str) and conflict.strip():
        return EvidenceSufficiency.INSUFFICIENT
    if any(_has_verified_rag_evidence(item) for item in items):
        return EvidenceSufficiency.SUFFICIENT

    fact_failure = _fact_value(facts, "failureType", "failure_type")
    known_fact_failure = isinstance(fact_failure, str) and fact_failure not in {
        "",
        "NONE",
        "UNKNOWN",
    }
    response_present = _fact_value(
        facts,
        "responseSnapshotPresent",
        "response_snapshot_present",
        "responseBodyPresent",
        "response_body_present",
    )
    assertion_count = _fact_value(facts, "assertionCount", "assertion_count")
    boundary = _fact_value(facts, "diagnosisBoundary", "diagnosis_boundary")
    runner_status = _fact_value(facts, "runnerStatus", "runner_status")
    if (
        known_fact_failure
        and response_present is False
        and assertion_count == 0
        and (boundary == "TRANSPORT_NOT_HTTP" or runner_status == "EXECUTION_FAILED")
    ):
        return EvidenceSufficiency.SUFFICIENT

    if report is None:
        return EvidenceSufficiency.UNRESOLVED
    if report.status in {"PENDING", "RUNNING"}:
        return EvidenceSufficiency.UNRESOLVED
    failure_type = report.summary.failure_type
    if (
        failure_type == "NONE"
        and report.status == "SUCCESS"
        and not _has_error_http_response(report)
    ):
        return EvidenceSufficiency.SUFFICIENT
    if failure_type == "UNKNOWN":
        return EvidenceSufficiency.UNRESOLVED
    if (
        report.status == "EXECUTION_FAILED"
        and report.summary.failed_assertions == 0
        and _has_transport_boundary(report)
    ):
        return EvidenceSufficiency.SUFFICIENT
    has_failure_detail = any(
        case.status != "SUCCESS"
        or case.failure_type != "NONE"
        or any(
            step.status != "SUCCESS"
            or step.failure_type != "NONE"
            or bool(step.assertion_results)
            or step.response_status_code is not None
            for step in case.steps
        )
        for case in report.cases
    )
    if has_failure_detail or report.summary.failed_assertions > 0:
        return EvidenceSufficiency.UNRESOLVED
    return EvidenceSufficiency.INSUFFICIENT


def build_tool_intent(
    decision: ToolPlanningDecision,
    *,
    query_source: str | None = None,
    arguments: Mapping[str, Any] | None = None,
    target_project_id: int | None = None,
    top_k: int = 5,
) -> ToolIntent:
    """Construct a ToolIntent from runtime context after the decision gate."""

    if not isinstance(decision, ToolPlanningDecision):
        raise TypeError("decision must be a ToolPlanningDecision")
    if decision.requirement not in {ToolRequirement.REQUIRED, ToolRequirement.OPTIONAL}:
        raise ToolPlanningError("a non-invokable decision cannot produce a ToolIntent")
    if not decision.allowed or decision.selected_tool is None:
        raise ToolPlanningError("decision does not authorize a selected tool")
    if isinstance(target_project_id, bool) or (
        target_project_id is not None
        and (not isinstance(target_project_id, int) or target_project_id < 1)
    ):
        raise ToolPlanningError("target_project_id must be a positive integer when provided")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
        raise ToolPlanningError("top_k must be an integer between 1 and 20")

    if decision.selected_tool == "rag.search":
        if not isinstance(query_source, str) or not query_source.strip():
            raise ToolPlanningError("rag.search query must come from non-empty runtime context")
        params: dict[str, object] = {"query": query_source.strip(), "topK": top_k}
        if target_project_id is not None:
            params["targetProjectId"] = target_project_id
    else:
        if not isinstance(arguments, Mapping):
            raise ToolPlanningError(
                f"runtime arguments are required for selected tool {decision.selected_tool}"
            )
        params = dict(arguments)
    return ToolIntent(tool_name=decision.selected_tool, arguments=params)


def build_rag_tool_intent(
    decision: ToolPlanningDecision,
    *,
    query_source: str,
    target_project_id: int | None = None,
    top_k: int = 5,
) -> ToolIntent:
    """Explicit convenience wrapper for the required RAG path."""

    if decision.selected_tool != "rag.search":
        raise ToolPlanningError("decision does not select rag.search")
    return build_tool_intent(
        decision,
        query_source=query_source,
        target_project_id=target_project_id,
        top_k=top_k,
    )


def build_tool_decision(*args: object, **kwargs: object) -> ToolPlanningDecision:
    """Compatibility-friendly name for the deterministic decision builder."""

    return decide_tool_requirement(*args, **kwargs)  # type: ignore[arg-type]


__all__ = [
    "EvidenceSufficiency",
    "ToolPlanningDecision",
    "ToolPlanningError",
    "ToolRequirement",
    "assess_evidence_sufficiency",
    "build_rag_tool_intent",
    "build_tool_decision",
    "build_tool_intent",
    "decide_tool_requirement",
]
