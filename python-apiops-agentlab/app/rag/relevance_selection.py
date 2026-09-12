"""Deterministic intent-level selection over Java-ranked RAG evidence.

Java remains authoritative for authorization, vector retrieval, ranking, and
the configured relevance threshold.  This module only applies explicit query
semantics that a nearest-neighbour search cannot represent by itself: an
``undocumented`` request must not turn unrelated neighbours into a hit, while
an ``exact`` or ``precise`` request must not retain a weaker near-match.
"""

from __future__ import annotations

import re

from .models import EvidenceRetrieval, RetrievedEvidence

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_ABSENCE_MARKERS = frozenset({"undocumented", "nonexistent"})
_EXACTNESS_MARKERS = frozenset({"exact", "precise"})
_CONTROL_TOKENS = frozenset(
    {
        "evidence",
        "formal",
        "hit",
        "match",
        "near",
        "result",
        "retrieve",
        "retrieval",
        "search",
    }
)


def _tokens(value: str) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall(value.lower()))


def _evidence_tokens(item: RetrievedEvidence) -> frozenset[str]:
    citation = item.citation
    return _tokens(
        " ".join(
            (
                item.content,
                citation.title,
                citation.excerpt,
                citation.source_id.replace("/", " ").replace("-", " "),
                citation.source_type.replace("_", " "),
            )
        )
    )


def select_query_relevant_evidence(
    retrieval: EvidenceRetrieval,
    *,
    query: str,
) -> EvidenceRetrieval:
    """Return evidence consistent with explicit exactness/absence semantics.

    Queries without one of the explicit control words preserve Java's result
    unchanged.  This is intentionally not another numeric threshold and does
    not reinterpret scores or reorder ordinary retrievals.
    """

    query_tokens = _tokens(query)
    evidence = tuple(retrieval.evidence)
    if not evidence:
        return retrieval

    if query_tokens & _ABSENCE_MARKERS:
        concepts = query_tokens - _CONTROL_TOKENS - _ABSENCE_MARKERS
        selected = tuple(
            item for item in evidence if concepts <= _evidence_tokens(item)
        )
    elif query_tokens & _EXACTNESS_MARKERS:
        concepts = query_tokens - _CONTROL_TOKENS - _EXACTNESS_MARKERS
        if not concepts:
            return retrieval
        scored = tuple(
            (
                (
                    len(concepts & _evidence_tokens(item)),
                    len(concepts & _tokens(item.citation.title)),
                ),
                item,
            )
            for item in evidence
        )
        best_score = max(score for score, _ in scored)
        minimum_specificity = min(2, len(concepts))
        # A comparison document can mention every query concept in its body
        # without having that subject. Among equal full-text matches, prefer
        # the Java citation title's primary topic. Preserve Java order when
        # both coverage levels tie; source identities and types are not tie-breakers.
        selected = (
            tuple(item for score, item in scored if score == best_score)
            if best_score[0] >= minimum_specificity
            else ()
        )
    else:
        return retrieval

    return retrieval.model_copy(update={"evidence": list(selected)})


__all__ = ["select_query_relevant_evidence"]
