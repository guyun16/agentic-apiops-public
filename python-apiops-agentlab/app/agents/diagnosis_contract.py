"""Insufficient-evidence structural checks, without pretending to judge prose.

No evaluation reference is accepted here. A clean observation is necessary, never
sufficient, for a content-correct diagnosis. The existing wire schema is unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from app.rag.context import ContextPack
from app.schemas.diagnosis_report import DiagnosisReport
from app.tracing.redaction import canonical_json_hash

CONTRACT_VERSION = "insufficient-evidence-v1"


def context_payload(context_pack: ContextPack) -> list[dict[str, object]]:
    return [
        {
            "itemId": item.source_id,
            "sourceType": item.source_type.value,
            "content": item.content,
            "provenance": [p.model_dump(mode="json", exclude_none=True) for p in item.provenance],
            "truncated": item.truncated,
        }
        for item in context_pack.items
    ]


def structural_issues(
    candidate: Mapping[str, object], evidence: Sequence[Mapping[str, object]]
) -> tuple[str, ...]:
    """Check only present facts, including partial historical exports.

    Missing fields are handled separately as UNKNOWN; a known violation remains
    decisive even when other fields are missing. No words in statements are matched.
    """
    issues: list[str] = []
    insufficient = candidate.get("sufficientEvidence") is False
    for key, label in (
        ("limitations", "a limitation"),
        ("recommendedChecks", "recommended checks"),
    ):
        if insufficient and key in candidate:
            values = candidate[key]
            if not isinstance(values, list) or not any(
                isinstance(v, str) and v.strip() for v in values
            ):
                issues.append(f"insufficient DiagnosisReport evidence requires {label}")
    hypotheses = candidate.get("rootCauseHypotheses")
    allowed = {e["itemId"] for e in evidence}
    if isinstance(hypotheses, list):
        if candidate.get("sufficientEvidence") is True and not hypotheses:
            issues.append("sufficient final root-cause evidence requires a stated hypothesis")
        for hypothesis in hypotheses:
            if not isinstance(hypothesis, dict):
                issues.append("hypothesis must be an object")
                continue
            if insufficient and hypothesis.get("confidence") == "HIGH":
                issues.append("insufficient DiagnosisReport evidence cannot use HIGH confidence")
            refs = hypothesis.get("evidenceRefs")
            if not isinstance(refs, list) or not refs:
                issues.append("hypothesis requires evidence references")
            elif any(not isinstance(r, dict) or r.get("itemId") not in allowed for r in refs):
                issues.append("hypothesis cites evidence absent from the current ContextPack")
    report_items = [item for item in evidence if item.get("sourceType") == "EXECUTION_FACT"]
    for item in report_items:
        if item.get("sourceType") != "EXECUTION_FACT":
            continue
        try:
            report = json.loads(str(item["content"]))
        except (ValueError, TypeError):
            continue
        if not isinstance(report, dict):
            continue
        # A sole Java report remains authoritative if the candidate changes its ID.
        # Multiple reports cannot identify the current report by position alone.
        if len(report_items) != 1 and report.get("reportId") != candidate.get("reportId"):
            continue
        for key in ("projectId", "runId", "reportId"):
            if key in candidate and key in report and candidate[key] != report[key]:
                issues.append(f"DiagnosisReport changed authoritative {key}")
        steps = [s for c in report.get("relevantCases", []) for s in c.get("relevantSteps", [])]
        if candidate.get("failureType") == "NONE" and any(
            isinstance(s.get("responseStatusCode"), int) and s["responseStatusCode"] >= 400
            for s in steps
        ):
            issues.append(
                "an authoritative error HTTP response cannot have semantic diagnosis NONE"
            )
        if (
            report.get("summary", {}).get("failureType") == "DNS_ERROR"
            and candidate.get("sufficientEvidence") is True
        ):
            issues.append("DNS_ERROR alone is not sufficient final root-cause evidence")
    return tuple(dict.fromkeys(issues))


def observe_diagnosis_contract(
    candidate: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    *,
    complete_original: bool = True,
) -> dict[str, object]:
    """A digest and check results, not full-report retention or semantic approval."""
    fields = {field.alias or name for name, field in DiagnosisReport.model_fields.items()}
    payload = {key: value for key, value in candidate.items() if key in fields}
    missing = sorted(fields - payload.keys())
    issues = list(structural_issues(payload, evidence))
    if complete_original:
        try:
            DiagnosisReport.model_validate(candidate)
        except ValueError:
            issues.append("complete DiagnosisReport violates the wire schema")
    complete = complete_original and not missing
    return {
        "version": CONTRACT_VERSION,
        "candidateDigest": canonical_json_hash(payload) if complete else None,
        "persistedFieldsDigest": canonical_json_hash(payload),
        "evidenceDigest": canonical_json_hash(evidence),
        "complete": complete,
        "missingFields": missing,
        "sufficientEvidence": payload.get("sufficientEvidence"),
        "structuralIssues": issues,
    }
