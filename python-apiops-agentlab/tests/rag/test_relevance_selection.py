from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.rag import EvidenceRetrieval, select_query_relevant_evidence


def _item(
    source_id: str,
    content: str,
    *,
    score: float,
    title: str | None = None,
) -> dict[str, object]:
    document_id = f"doc-{source_id}"
    chunk_id = f"chunk-{source_id}"
    return {
        "projectId": 41,
        "documentId": document_id,
        "chunkId": chunk_id,
        "content": content,
        "relevanceScore": score,
        "citation": {
            "sourceType": "RUNBOOK",
            "sourceId": source_id,
            "projectId": 41,
            "documentId": document_id,
            "chunkId": chunk_id,
            "score": score,
            "title": title if title is not None else source_id,
            "location": "chunk:0",
            "excerpt": content,
        },
    }


def _retrieval(*items: dict[str, object]) -> EvidenceRetrieval:
    return EvidenceRetrieval.model_validate(
        {"ragQueryId": "ragq-1", "results": list(items)}
    )


def test_exact_query_keeps_best_lexical_identity_and_rejects_near_match() -> None:
    retrieval = _retrieval(
        _item(
            "orders-constraint-index",
            "Orders exact unique index and duplicate key constraint.",
            score=0.81,
        ),
        _item(
            "payment-near-match",
            "Payments has a unique provider reference.",
            score=0.79,
        ),
    )

    selected = select_query_relevant_evidence(
        retrieval,
        query="formal exact unique index near match",
    )

    assert [item.citation.source_id for item in selected.evidence] == [
        "orders-constraint-index"
    ]


def test_undocumented_query_converts_unrelated_neighbours_to_zero_hit() -> None:
    retrieval = _retrieval(
        _item("orders-runbook", "Orders quantity and unique index rules.", score=0.61),
        _item("runner-runbook", "Runner timeout and lifecycle rules.", score=0.59),
    )

    selected = select_query_relevant_evidence(
        retrieval,
        query="formal undocumented retention policy",
    )

    assert selected.evidence == []


def test_undocumented_query_retains_evidence_for_the_requested_topic() -> None:
    retrieval = _retrieval(
        _item(
            "retention-reference",
            "Retention policy authority for records that are not in the public API contract.",
            score=0.73,
        ),
        _item("runner-runbook", "Runner timeout and lifecycle rules.", score=0.59),
    )

    selected = select_query_relevant_evidence(
        retrieval,
        query="formal undocumented retention policy",
    )

    assert [item.citation.source_id for item in selected.evidence] == [
        "retention-reference"
    ]


def test_ordinary_query_preserves_java_ranked_results() -> None:
    retrieval = _retrieval(
        _item("first", "First Java result.", score=0.51),
        _item("second", "Second Java result.", score=0.92),
    )

    selected = select_query_relevant_evidence(
        retrieval,
        query="diagnose order failure",
    )

    assert selected is retrieval
    assert [item.citation.source_id for item in selected.evidence] == ["first", "second"]


@pytest.mark.parametrize("reverse_order", [False, True])
def test_exact_query_preserves_co_best_evidence_in_java_order(reverse_order: bool) -> None:
    relevant = [
        _item("api-reference", "Orders constraint: quantity is a positive integer.", score=0.82,
              title="Orders constraint API reference"),
        _item("schema-reference", "Orders constraint: customer reference is unique.", score=0.79,
              title="Orders constraint schema reference"),
    ]
    if reverse_order:
        relevant.reverse()
    retrieval = _retrieval(
        *relevant,
        _item("catalog-reference", "Catalog product names are unrelated to orders.", score=0.77),
    )

    selected = select_query_relevant_evidence(retrieval, query="orders constraint precise")

    assert [item.citation.source_id for item in selected.evidence] == [
        item["citation"]["sourceId"] for item in relevant
    ]
    assert selected.evidence == retrieval.evidence[:2]
    assert selected.rag_query_id == retrieval.rag_query_id
    assert len(retrieval.evidence) == 3


def test_exact_query_does_not_invent_missing_schema_evidence_or_keep_weaker_distractor() -> None:
    retrieval = _retrieval(
        _item("api-reference", "Orders constraint: quantity is a positive integer.", score=0.79),
        _item("catalog-reference", "Product catalog has orders display labels.", score=0.93),
        _item("payments-reference", "Payments constraint uses provider references.", score=0.89),
    )

    selected = select_query_relevant_evidence(retrieval, query="orders constraint precise")

    assert selected.evidence == [retrieval.evidence[0]]
    assert all(item.citation.source_id != "schema-reference" for item in selected.evidence)


def test_exact_query_drops_all_under_specific_candidates_even_when_tied() -> None:
    retrieval = _retrieval(
        _item("catalog-a", "Product catalog has orders display labels.", score=0.85),
        _item("catalog-b", "Product catalog has orders display labels.", score=0.83),
    )

    selected = select_query_relevant_evidence(retrieval, query="orders constraint precise")

    assert selected.evidence == []


def _java_corpus_item(name: str) -> dict[str, object]:
    corpus = Path(__file__).resolve().parents[3] / (
        "java-apiops-platform/apiops-web/src/test/resources/stage21/rag-corpus-v2"
    )
    manifest = json.loads((corpus / "corpus-manifest.json").read_text(encoding="utf-8"))
    source_id = f"stage21-rag-v2/project-41/{name}"
    metadata = next(row for row in manifest["documents"] if row["sourceKey"] == source_id)
    item = _item(
        source_id,
        (corpus / metadata["file"]).read_text(encoding="utf-8").strip(),
        score=0.8,  # Test input only; historical Java audit does not retain scores.
        title=metadata["title"],
    )
    item["citation"]["sourceType"] = metadata["sourceType"]
    return item


@pytest.mark.parametrize("reverse_order", [False, True])
@pytest.mark.parametrize(
    ("query", "names"),
    [
        (
            "formal exact unique index near match",
            ("orders-constraint-index", "payment-near-match", "orders-api-constraints"),
        ),
        (
            "orders constraint precise",
            ("orders-api-constraints", "orders-constraint-index", "orders-incident-report"),
        ),
    ],
)
def test_real_java_titles_disambiguate_comparison_mentions_and_broad_runbooks(
    query: str, names: tuple[str, ...], reverse_order: bool,
) -> None:
    items = [_java_corpus_item(name) for name in names]
    if reverse_order:
        items.reverse()
    retrieval = _retrieval(*items)
    # The Payments comparison really mentions Orders and its index in the body.
    if "payment-near-match" in names:
        payment = next(
            row for row in retrieval.evidence
            if "payment-near-match" in row.citation.source_id
        )
        assert "Orders" in payment.content
        assert "index" in payment.content

    selected = select_query_relevant_evidence(retrieval, query=query)

    assert [item.citation.source_id for item in selected.evidence] == [
        "stage21-rag-v2/project-41/orders-constraint-index"
    ]
    assert selected.evidence[0] in retrieval.evidence
    assert len(retrieval.evidence) == 3


def test_primary_title_preference_is_generic_and_does_not_follow_source_identity() -> None:
    retrieval = _retrieval(
        _item(
            "exact-storage-quota-index",
            "A network comparison mentions a storage quota index but covers latency.",
            score=0.99, title="Network latency comparison",
        ),
        _item(
            "opaque-document-b",
            "The storage quota index records per-volume resource limits.",
            score=0.61, title="Storage quota index reference",
        ),
    )

    selected = select_query_relevant_evidence(retrieval, query="exact storage quota index")

    assert selected.evidence == [retrieval.evidence[1]]


def test_primary_title_does_not_promote_a_candidate_with_weaker_full_text_coverage() -> None:
    retrieval = _retrieval(
        _item("opaque-a", "A unique index constraint rejects duplicates.", score=0.6,
              title="Schema reference"),
        _item("opaque-b", "An index is a lookup structure.", score=0.9,
              title="Index reference"),
    )

    selected = select_query_relevant_evidence(retrieval, query="exact unique index constraint")

    assert selected.evidence == [retrieval.evidence[0]]
