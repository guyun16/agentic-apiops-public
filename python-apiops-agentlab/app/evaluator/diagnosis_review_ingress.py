"""Evaluation-only ingress for a review of already frozen retained evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.evaluator.models import DiagnosisContentReview
from app.tracing.redaction import canonical_json_hash

DIMENSIONS = frozenset(
    {
        "observed_facts",
        "hypothesis_grounding",
        "uncertainty",
        "citation_support",
        "limitations_and_checks",
    }
)


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_content_review(
    review: dict,
    retained: dict,
    *,
    seal_digest: str,
) -> DiagnosisContentReview:
    """Validate provenance/binding, never infer semantic truth from text keywords."""
    if review.get("method") != "CODEX_REVIEW" or review.get("reviewer") != "Codex":
        raise ValueError("content review must identify CODEX_REVIEW / Codex")
    expected = {
        "outputSealDigest": seal_digest,
        "taskId": retained["taskId"],
        "candidateDigest": retained["originalCandidateDigest"],
        "evidenceDigest": retained["originalEvidenceDigest"],
        "retainedCandidateDigest": canonical_json_hash(retained["diagnosisReport"]),
        "retainedEvidenceDigest": canonical_json_hash(retained["boundedEvidence"]),
    }
    if any(review.get(key) != value for key, value in expected.items()):
        raise ValueError("review does not bind this frozen candidate and evidence")
    for key in ("retainedCandidateDigest", "retainedEvidenceDigest"):
        if retained[key] != expected[key]:
            raise ValueError("retained evidence digest mismatch")
    dimensions = review.get("dimensions", {})
    if set(dimensions) != DIMENSIONS:
        raise ValueError("review must cover exactly five dimensions")
    for dimension in dimensions.values():
        if (
            not isinstance(dimension.get("reason"), str)
            or not dimension["reason"].strip()
            or not dimension.get("evidence")
            or any(not isinstance(ref, str) or not ref.strip() for ref in dimension["evidence"])
        ):
            raise ValueError("each review dimension requires reason and evidence references")
        for reference in dimension["evidence"]:
            name, separator, pointer = reference.partition("#")
            if name not in {"diagnosisReport", "boundedEvidence"} or separator != "#":
                raise ValueError("review evidence must reference the frozen retained payload")
            value = retained[name]
            try:
                if pointer and not pointer.startswith("/"):
                    raise ValueError("invalid JSON pointer")
                for token in pointer.split("/")[1:]:
                    token = token.replace("~1", "/").replace("~0", "~")
                    value = value[int(token)] if isinstance(value, list) else value[token]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValueError("review evidence reference does not exist") from exc
    checks = {name: value["verdict"] for name, value in dimensions.items()}
    if retained["redactionChangedCandidate"] and set(checks.values()) == {"PASS"}:
        raise ValueError("censored candidate cannot receive complete-content PASS")
    return DiagnosisContentReview(
        candidate_digest=retained["originalCandidateDigest"],
        candidate_scope="complete",
        evidence_digest=retained["originalEvidenceDigest"],
        reference=review["reference"],
        rationale=review["rationale"],
        checks=checks,
    )


def verify_output_seal(root: Path) -> dict:
    seal = json.loads((root / "output-seal.json").read_text(encoding="utf-8"))
    for relative, expected in seal["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or file_digest(path) != expected:
            raise ValueError("frozen output integrity violation")
    current = {
        str(path.relative_to(root)).replace("\\", "/")
        for directory in ("raw", "retention", "ledger")
        for path in (root / directory).rglob("*")
        if path.is_file()
    }
    if current != set(seal["files"]):
        raise ValueError("frozen output set changed")
    return seal
