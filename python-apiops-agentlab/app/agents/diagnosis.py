"""Structured diagnosis inference over an existing bounded ContextPack."""

from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path

from pydantic import ValidationError

from app.clients.llm import LLMClient
from app.rag.context import ContextPack, ContextSource
from app.schemas.diagnosis_report import DiagnosisReport
from app.schemas.runner import TestReport
from app.tools import ToolIntent

_PROMPT_PATH = Path(__file__).parent / "prompts" / "diagnosis_v1.txt"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")
_MEMORY_REFINEMENT_PROMPT_PATH = (
    Path(__file__).parent / "prompts" / "diagnosis_memory_refinement_v1.txt"
)
_MEMORY_REFINEMENT_PROMPT_TEMPLATE = _MEMORY_REFINEMENT_PROMPT_PATH.read_text(encoding="utf-8")
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "shared-schemas" / "diagnosis-report-schema.json"
)
_DIAGNOSIS_SCHEMA = json.dumps(
    json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")),
    ensure_ascii=False,
    sort_keys=True,
)


class DiagnosisInferenceError(RuntimeError):
    """The model boundary did not return an accepted diagnosis decision."""


class DiagnosisCandidateParseError(DiagnosisInferenceError):
    """The model response was not a supported structured candidate."""


class DiagnosisIdentityError(DiagnosisInferenceError):
    """The candidate changed an authority-owned or workflow-owned identity."""


class DiagnosisEvidenceReferenceError(DiagnosisInferenceError):
    """The candidate cited evidence that is absent from the current ContextPack."""


class DiagnosisSemanticContractError(DiagnosisCandidateParseError):
    """The structured candidate violated the Diagnosis semantic contract."""


_TERMINAL_FAILURE_STATUSES = frozenset({"ASSERTION_FAILED", "EXECUTION_FAILED", "TIMEOUT"})
_NON_FAILURE_TYPES = frozenset({"NONE", "UNKNOWN"})


def _has_authoritative_execution_fact(
    context_pack: ContextPack,
    *,
    report: TestReport,
) -> bool:
    return any(
        item.source_type is ContextSource.EXECUTION_FACT
        and item.source_id == report.report_id
        and item.project_scope == report.project_id
        and any(
            provenance.source_type == "JAVA_TEST_REPORT"
            and provenance.source_id == report.report_id
            and provenance.project_id == report.project_id
            and provenance.run_id == report.run_id
            for provenance in item.provenance
        )
        for item in context_pack.items
    )


def _contains_explicit_conflict(value: object) -> bool:
    if isinstance(value, dict):
        if any(
            key.replace("_", "").lower() == "conflicttype"
            and isinstance(raw, str)
            and raw.strip()
            for key, raw in value.items()
        ):
            return True
        return any(_contains_explicit_conflict(raw) for raw in value.values())
    if isinstance(value, list):
        return any(_contains_explicit_conflict(raw) for raw in value)
    return False


def _has_explicit_conflicting_facts(context_pack: ContextPack) -> bool:
    for item in context_pack.items:
        try:
            payload = json.loads(item.content)
        except (TypeError, ValueError, JSONDecodeError):
            continue
        if _contains_explicit_conflict(payload):
            return True
    return False


def validate_diagnosis_semantics(
    candidate: DiagnosisReport,
    *,
    report: TestReport,
    context_pack: ContextPack,
) -> None:
    """Reject semantic violations without repairing or synthesizing a candidate."""

    if not candidate.sufficient_evidence:
        if not candidate.limitations:
            raise DiagnosisSemanticContractError(
                "insufficient DiagnosisReport evidence requires a limitation"
            )
        if not candidate.recommended_checks:
            raise DiagnosisSemanticContractError(
                "insufficient DiagnosisReport evidence requires recommended checks"
            )
        if any(hypothesis.confidence == "HIGH" for hypothesis in candidate.root_cause_hypotheses):
            raise DiagnosisSemanticContractError(
                "insufficient DiagnosisReport evidence cannot use HIGH confidence"
            )

    known_terminal_failure = (
        report.status in _TERMINAL_FAILURE_STATUSES
        and report.summary.failure_type not in _NON_FAILURE_TYPES
    )
    authoritative_execution_fact = _has_authoritative_execution_fact(
        context_pack,
        report=report,
    )
    if (
        known_terminal_failure
        and authoritative_execution_fact
        and report.summary.failure_type == "DNS_ERROR"
        and candidate.sufficient_evidence
    ):
        raise DiagnosisSemanticContractError(
            "DNS_ERROR execution evidence supports a provisional mechanism, not "
            "sufficient final root-cause evidence"
        )
    if (
        known_terminal_failure
        and authoritative_execution_fact
        and not candidate.root_cause_hypotheses
        and not _has_explicit_conflicting_facts(context_pack)
    ):
        raise DiagnosisSemanticContractError(
            "known terminal failure with authoritative execution evidence requires "
            "at least one provisional root-cause hypothesis"
        )


def _context_payload(context_pack: ContextPack) -> list[dict[str, object]]:
    return [
        {
            "itemId": item.source_id,
            "sourceType": item.source_type.value,
            "content": item.content,
            "provenance": [
                reference.model_dump(mode="json", exclude_none=True)
                for reference in item.provenance
            ],
            "truncated": item.truncated,
        }
        for item in context_pack.items
    ]


def render_diagnosis_prompt(
    context_pack: ContextPack,
    *,
    report: TestReport,
    trace_id: str,
    agent_run_id: str,
    continuation_reason: str | None = None,
) -> str:
    """Render the versioned prompt without copying a full TestReport or ToolResult."""

    mode = (
        "INITIAL: return either a final DiagnosisReport or one ToolIntent."
        if continuation_reason is None
        else "CONTINUATION: the tool budget is exhausted; return only a final DiagnosisReport."
    )
    return (
        _PROMPT_TEMPLATE.replace("{{MODE}}", mode)
        .replace("{{PROJECT_ID}}", str(report.project_id))
        .replace("{{RUN_ID}}", str(report.run_id))
        .replace("{{REPORT_ID}}", report.report_id)
        .replace("{{AGENT_RUN_ID}}", agent_run_id)
        .replace("{{TRACE_ID}}", trace_id)
        .replace("{{CONTINUATION_REASON}}", continuation_reason or "none")
        .replace("{{DIAGNOSIS_REPORT_SCHEMA}}", _DIAGNOSIS_SCHEMA)
        .replace(
            "{{CONTEXT_PACK}}",
            json.dumps(_context_payload(context_pack), ensure_ascii=False, sort_keys=True),
        )
    )


def render_diagnosis_memory_refinement_prompt(
    context_pack: ContextPack,
    *,
    report: TestReport,
    candidate: DiagnosisReport,
    trace_id: str,
    agent_run_id: str,
) -> str:
    """Render the hit-only prompt that can return a DiagnosisReport only."""

    return (
        _MEMORY_REFINEMENT_PROMPT_TEMPLATE.replace("{{PROJECT_ID}}", str(report.project_id))
        .replace("{{RUN_ID}}", str(report.run_id))
        .replace("{{REPORT_ID}}", report.report_id)
        .replace("{{AGENT_RUN_ID}}", agent_run_id)
        .replace("{{TRACE_ID}}", trace_id)
        .replace(
            "{{CANDIDATE_REPORT}}",
            json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
        )
        .replace("{{DIAGNOSIS_REPORT_SCHEMA}}", _DIAGNOSIS_SCHEMA)
        .replace(
            "{{CONTEXT_PACK}}",
            json.dumps(_context_payload(context_pack), ensure_ascii=False, sort_keys=True),
        )
    )


class DiagnosisInference:
    """Thin structured adapter over the existing provider-neutral LLMClient."""

    def __init__(self, llm: LLMClient) -> None:
        if not isinstance(llm, LLMClient):
            raise TypeError("llm must implement LLMClient")
        self._llm = llm

    async def generate(
        self,
        context_pack: ContextPack,
        *,
        report: TestReport,
        trace_id: str,
        agent_run_id: str,
        continuation_reason: str | None = None,
    ) -> DiagnosisReport | ToolIntent:
        """Return one validated final report or the existing ToolIntent model."""

        prompt = render_diagnosis_prompt(
            context_pack,
            report=report,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            continuation_reason=continuation_reason,
        )
        try:
            raw = await self._llm.complete(prompt)
        except Exception as exc:
            raise DiagnosisInferenceError("Diagnosis model call failed") from exc
        if not isinstance(raw, str) or not raw.strip():
            raise DiagnosisCandidateParseError("Diagnosis model returned an empty response")
        try:
            payload = json.loads(raw)
        except JSONDecodeError as exc:
            raise DiagnosisCandidateParseError("Diagnosis model response was not JSON") from exc
        if not isinstance(payload, dict):
            raise DiagnosisCandidateParseError("Diagnosis candidate must be a JSON object")

        try:
            candidate = DiagnosisReport.model_validate(payload)
        except ValidationError as report_error:
            try:
                return ToolIntent.model_validate(payload)
            except ValidationError as intent_error:
                raise DiagnosisCandidateParseError(
                    "Diagnosis candidate matched neither DiagnosisReport nor ToolIntent"
                ) from ExceptionGroup("candidate validation", [report_error, intent_error])

        self._validate_report_candidate(
            candidate,
            report=report,
            context_pack=context_pack,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
        )
        return candidate

    async def refine(
        self,
        context_pack: ContextPack,
        *,
        report: TestReport,
        candidate: DiagnosisReport,
        trace_id: str,
        agent_run_id: str,
    ) -> DiagnosisReport:
        """Return one final report after a confirmed Historical Memory context hit."""

        prompt = render_diagnosis_memory_refinement_prompt(
            context_pack,
            report=report,
            candidate=candidate,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
        )
        try:
            raw = await self._llm.complete(prompt)
        except Exception as exc:
            raise DiagnosisInferenceError("Diagnosis memory refinement call failed") from exc
        if not isinstance(raw, str) or not raw.strip():
            raise DiagnosisCandidateParseError(
                "Diagnosis memory refinement returned an empty response"
            )
        try:
            payload = json.loads(raw)
        except JSONDecodeError as exc:
            raise DiagnosisCandidateParseError(
                "Diagnosis memory refinement response was not JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise DiagnosisCandidateParseError(
                "Diagnosis memory refinement must return a JSON object"
            )
        try:
            refined = DiagnosisReport.model_validate(payload)
        except ValidationError as exc:
            raise DiagnosisCandidateParseError(
                "Diagnosis memory refinement must return only a DiagnosisReport"
            ) from exc
        self._validate_report_candidate(
            refined,
            report=report,
            context_pack=context_pack,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
        )
        return refined

    @staticmethod
    def _validate_report_candidate(
        candidate: DiagnosisReport,
        *,
        report: TestReport,
        context_pack: ContextPack,
        trace_id: str,
        agent_run_id: str,
    ) -> None:
        expected = (
            report.project_id,
            report.run_id,
            report.report_id,
            agent_run_id,
            trace_id,
        )
        actual = (
            candidate.project_id,
            candidate.run_id,
            candidate.report_id,
            candidate.agent_run_id,
            candidate.trace_id,
        )
        if actual != expected:
            raise DiagnosisIdentityError(
                "Diagnosis candidate changed projectId, runId, reportId, agentRunId, or traceId"
            )

        allowed_references = {item.source_id for item in context_pack.items}
        cited_references = {
            reference.item_id
            for hypothesis in candidate.root_cause_hypotheses
            for reference in hypothesis.evidence_refs
        }
        invented = cited_references - allowed_references
        if invented:
            raise DiagnosisEvidenceReferenceError(
                "Diagnosis candidate cited evidence absent from the current ContextPack"
            )
        validate_diagnosis_semantics(candidate, report=report, context_pack=context_pack)


__all__ = [
    "DiagnosisCandidateParseError",
    "DiagnosisEvidenceReferenceError",
    "DiagnosisIdentityError",
    "DiagnosisInference",
    "DiagnosisInferenceError",
    "DiagnosisSemanticContractError",
    "render_diagnosis_prompt",
    "render_diagnosis_memory_refinement_prompt",
    "validate_diagnosis_semantics",
]
