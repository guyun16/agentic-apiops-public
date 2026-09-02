"""Deterministic identities for Historical Failure Memory.

The fingerprint is a semantic failure identity.  The content hash is a
duplicate identity for the complete memory content.  They intentionally use
different canonical payloads.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

_NON_IDENTITY_CHARS = re.compile(r"[\W_]+", re.UNICODE)


def normalize_identity(value: str) -> str:
    """Normalize a human-entered identity without retaining punctuation noise."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _NON_IDENTITY_CHARS.sub(" ", normalized)
    return " ".join(normalized.split())


def _sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_failure_fingerprint(
    *,
    api_id: str,
    symptoms: Sequence[str],
    root_cause: str,
) -> str:
    """Build the v1 semantic failure identity.

    Summary and resolution are deliberately excluded.  Symptom order and
    formatting are normalized so equivalent structured failure descriptions
    produce the same fingerprint.
    """

    semantic_identity = {
        "api_id": normalize_identity(api_id),
        "symptoms": sorted({normalize_identity(symptom) for symptom in symptoms}),
        "root_cause": normalize_identity(root_cause),
    }
    return _sha256(semantic_identity)


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value[name]
    return getattr(value, name)


def _reference_identity(reference: object) -> dict[str, object]:
    return {
        "source_type": normalize_identity(str(_field(reference, "source_type"))),
        "source_id": normalize_identity(str(_field(reference, "source_id"))),
        "project_id": _field(reference, "project_id"),
        "run_id": _field(reference, "run_id"),
    }


def compute_content_hash(memory: object) -> str:
    """Hash the canonical memory content, excluding lifecycle and timestamps."""

    symptoms = _field(memory, "symptoms")
    evidence_refs = _field(memory, "evidence_refs")
    content_identity = {
        "project_id": _field(memory, "project_id"),
        "api_id": normalize_identity(str(_field(memory, "api_id"))),
        "failure_fingerprint": str(_field(memory, "failure_fingerprint"))
        if not callable(getattr(memory, "failure_fingerprint", None))
        else build_failure_fingerprint(
            api_id=str(_field(memory, "api_id")),
            symptoms=[str(item) for item in symptoms],
            root_cause=str(_field(memory, "root_cause")),
        ),
        "summary": normalize_identity(str(_field(memory, "summary"))),
        "symptoms": sorted({normalize_identity(str(item)) for item in symptoms}),
        "root_cause": normalize_identity(str(_field(memory, "root_cause"))),
        "resolution": normalize_identity(str(_field(memory, "resolution"))),
        "source_run_id": _field(memory, "source_run_id"),
        "evidence_refs": sorted(
            (_reference_identity(reference) for reference in evidence_refs),
            key=lambda reference: json.dumps(
                reference,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
        "verification_status": str(_field(memory, "verification_status")),
    }
    return _sha256(content_identity)


def compute_memory_id(*, project_id: int, failure_fingerprint: str, content_hash: str) -> str:
    """Build a stable identity for one project-scoped memory entry."""

    identity = {
        "project_id": project_id,
        "failure_fingerprint": failure_fingerprint,
        "content_hash": content_hash,
    }
    return f"memory_{_sha256(identity)}"


# Explicit aliases make the identity helpers easy to discover without adding
# a second implementation.
compute_failure_fingerprint = build_failure_fingerprint


__all__ = [
    "build_failure_fingerprint",
    "compute_content_hash",
    "compute_failure_fingerprint",
    "compute_memory_id",
    "normalize_identity",
]
