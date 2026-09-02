"""Deterministic tests for the Python-internal context engineering core."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.memory import (
    HistoricalFailureMemoryCandidate,
    MemoryEvidenceRef,
    MemoryWritePolicy,
    VerificationStatus,
)
from app.memory.store import InMemoryMemoryStore
from app.rag.context import (
    ContextItem,
    ContextPack,
    ContextPackBuilder,
    ContextPolicy,
    ContextProvenance,
    ContextRanker,
    ContextSource,
    DeterministicContextCompressor,
    SensitiveDataMasker,
)
from app.rag.models import EvidenceCitation, RetrievedEvidence

FIXTURE_SOURCE_PRECEDENCE = (
    ContextSource.EXECUTION_FACT,
    ContextSource.API_METADATA,
    ContextSource.RAG_EVIDENCE,
    ContextSource.SHORT_TERM_CONTEXT,
    ContextSource.USER_INTENT,
    ContextSource.HISTORICAL_MEMORY,
)


def make_item(
    source_type: ContextSource,
    source_id: str,
    content: str,
    *,
    project_scope: int | None = 101,
    priority: int = 0,
    relevance_score: float | None = None,
) -> ContextItem:
    return ContextItem(
        source_type=source_type,
        source_id=source_id,
        project_scope=project_scope,
        content=content,
        priority=priority,
        relevance_score=relevance_score,
    )


def make_evidence(*, content: str = "evidence content") -> RetrievedEvidence:
    citation = EvidenceCitation(
        sourceType="RUNBOOK",
        sourceId="runbook/orders",
        projectId=101,
        documentId="doc-orders",
        chunkId="chunk-1",
        score=0.91,
        title="Orders runbook",
        location="section:timeouts",
        excerpt="Evidence excerpt",
    )
    return RetrievedEvidence(
        projectId=101,
        documentId="doc-orders",
        chunkId="chunk-1",
        content=content,
        relevanceScore=0.91,
        citation=citation,
    )


def make_memory():
    candidate = HistoricalFailureMemoryCandidate(
        project_id=101,
        api_id="api-orders",
        summary="Order lookup timed out",
        symptoms=["504 response"],
        root_cause="upstream timeout",
        resolution="increase upstream timeout after verification",
        source_run_id=77,
        evidence_refs=[
            MemoryEvidenceRef(
                source_type="RUNBOOK",
                source_id="runbook/orders-timeouts",
                project_id=101,
                run_id=77,
            )
        ],
        verification_status=VerificationStatus.VERIFIED,
    )
    store = InMemoryMemoryStore()
    decision = MemoryWritePolicy(store).write(candidate, project_id=101)
    assert decision.entry is not None
    return decision.entry


def make_policy(
    *,
    source_precedence: tuple[ContextSource, ...] = FIXTURE_SOURCE_PRECEDENCE,
    **kwargs: object,
) -> ContextPolicy:
    return ContextPolicy(source_precedence=source_precedence, **kwargs)


def build_pack(items: list[ContextItem], policy: ContextPolicy | None = None):
    return ContextPackBuilder(
        policy or make_policy(),
        project_scope=101,
    ).build(items)


def test_all_recommended_context_sources_are_stable_and_modelable() -> None:
    expected = [
        "API_METADATA",
        "EXECUTION_FACT",
        "RAG_EVIDENCE",
        "HISTORICAL_MEMORY",
        "SHORT_TERM_CONTEXT",
        "USER_INTENT",
    ]

    assert [source.value for source in ContextSource] == expected
    assert [
        make_item(source, source.value, source.value).source_type.value for source in ContextSource
    ] == expected


def test_missing_source_precedence_policy_is_rejected() -> None:
    with pytest.raises(ValidationError, match="source_precedence"):
        ContextPolicy(total_char_budget=10)


def test_explicit_source_precedence_controls_deterministic_rank_order() -> None:
    items = [
        make_item(ContextSource.API_METADATA, "metadata", "metadata"),
        make_item(ContextSource.EXECUTION_FACT, "execution", "execution"),
        make_item(ContextSource.RAG_EVIDENCE, "evidence", "evidence"),
    ]
    first_policy = make_policy()
    second_precedence = (
        ContextSource.RAG_EVIDENCE,
        ContextSource.API_METADATA,
        ContextSource.EXECUTION_FACT,
        ContextSource.SHORT_TERM_CONTEXT,
        ContextSource.USER_INTENT,
        ContextSource.HISTORICAL_MEMORY,
    )
    second_policy = make_policy(source_precedence=second_precedence)

    first_ranker = ContextRanker(first_policy)
    second_ranker = ContextRanker(second_policy)

    assert [item.source_type for item in first_ranker.rank(items)] == [
        ContextSource.EXECUTION_FACT,
        ContextSource.API_METADATA,
        ContextSource.RAG_EVIDENCE,
    ]
    assert [item.source_type for item in second_ranker.rank(items)] == [
        ContextSource.RAG_EVIDENCE,
        ContextSource.API_METADATA,
        ContextSource.EXECUTION_FACT,
    ]
    assert first_ranker.policy is first_policy
    assert second_ranker.policy is second_policy


def test_api_metadata_and_execution_fact_have_distinct_source_roles() -> None:
    metadata = make_item(ContextSource.API_METADATA, "fact-1", "same content")
    execution = make_item(ContextSource.EXECUTION_FACT, "fact-1", "same content")

    ranked = ContextRanker(make_policy()).rank([metadata, execution])
    compressed = DeterministicContextCompressor(make_policy()).compress(ranked)
    pack = build_pack([metadata, execution])

    assert [item.source_type for item in ranked] == [
        ContextSource.EXECUTION_FACT,
        ContextSource.API_METADATA,
    ]
    assert len(compressed) == 2
    assert [item.source_type for item in pack.items] == [
        ContextSource.EXECUTION_FACT,
        ContextSource.API_METADATA,
    ]


def test_ranker_only_ranks_and_does_not_build_or_compress() -> None:
    ranker = ContextRanker(make_policy())
    items = [
        make_item(ContextSource.RAG_EVIDENCE, "evidence", "evidence"),
        make_item(ContextSource.EXECUTION_FACT, "execution", "execution"),
    ]

    assert [item.source_id for item in ranker.rank(items)] == ["execution", "evidence"]
    assert not hasattr(ranker, "build")
    assert not hasattr(ranker, "compress")


def test_compressor_dedup_filter_caps_and_trims_without_reranking() -> None:
    ranked_items = [
        make_item(ContextSource.API_METADATA, "metadata", "12345", priority=2),
        make_item(ContextSource.API_METADATA, "metadata", "duplicate", priority=1),
        make_item(ContextSource.RAG_EVIDENCE, "evidence-low", "drop", priority=0),
        make_item(ContextSource.RAG_EVIDENCE, "evidence-high", "67890", priority=2),
        make_item(ContextSource.RAG_EVIDENCE, "evidence-cap", "later", priority=2),
    ]
    policy = make_policy(
        drop_below_priority=1,
        per_source_caps={ContextSource.RAG_EVIDENCE: 1},
        per_item_char_budget=4,
        total_char_budget=7,
    )

    result = DeterministicContextCompressor(policy).compress_with_stats(ranked_items)

    assert [item.source_id for item in result.items] == ["metadata", "evidence-high"]
    assert [item.content for item in result.items] == ["1234", "678"]
    assert [item.truncated for item in result.items] == [True, True]
    assert result.deduplicated_item_count == 4
    assert result.policy_selected_item_count == 2


def test_same_input_has_stable_builder_output_and_tie_breaking() -> None:
    items = [
        make_item(ContextSource.HISTORICAL_MEMORY, "memory-b", "same text", priority=1),
        make_item(ContextSource.API_METADATA, "metadata-2", "metadata two", relevance_score=0.2),
        make_item(ContextSource.API_METADATA, "metadata-1", "metadata one", relevance_score=0.2),
        make_item(ContextSource.HISTORICAL_MEMORY, "memory-a", "same text", priority=1),
    ]
    policy = make_policy(total_char_budget=100)

    first = build_pack(items, policy)
    second = build_pack(list(reversed(items)), policy)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [item.source_id for item in first.items] == [
        "metadata-1",
        "metadata-2",
        "memory-a",
        "memory-b",
    ]


def test_duplicate_identity_is_removed_without_text_similarity_merge() -> None:
    duplicate = make_item(ContextSource.API_METADATA, "metadata-1", "version one")
    same_identity_different_text = make_item(
        ContextSource.API_METADATA,
        "metadata-1",
        "version two",
        priority=1,
    )
    different_project = make_item(
        ContextSource.API_METADATA,
        "metadata-1",
        "other project fact",
        project_scope=202,
    )
    different_source = make_item(
        ContextSource.RAG_EVIDENCE,
        "metadata-1",
        "retrieved text with same words",
    )

    pack = build_pack(
        [duplicate, same_identity_different_text, different_project, different_source]
    )

    assert pack.input_item_count == 4
    assert pack.eligible_item_count == 3
    assert pack.deduplicated_item_count == 2
    assert pack.dropped_item_count == 2
    assert [item.source_type for item in pack.items] == [
        ContextSource.API_METADATA,
        ContextSource.RAG_EVIDENCE,
    ]
    assert pack.items[0].content == "version two"


def test_over_budget_trim_is_deterministic_and_accounted() -> None:
    items = [
        make_item(ContextSource.API_METADATA, "metadata", "12345"),
        make_item(ContextSource.RAG_EVIDENCE, "evidence", "67890"),
        make_item(ContextSource.HISTORICAL_MEMORY, "memory", "later"),
    ]

    pack = build_pack(items, make_policy(total_char_budget=8))

    assert [item.content for item in pack.items] == ["12345", "678"]
    assert pack.items[1].truncated is True
    assert pack.budget_limit == 8
    assert pack.budget_used == 8
    assert pack.policy_selected_item_count == 3
    assert pack.dropped_item_count == 1


def test_execution_fact_precedes_many_high_similarity_historical_memories() -> None:
    execution_fact = make_item(
        ContextSource.EXECUTION_FACT,
        "execution-timeout",
        "execution timeout is 30 seconds",
        relevance_score=0.01,
    )
    memories = [
        make_item(
            ContextSource.HISTORICAL_MEMORY,
            f"memory-{index}",
            f"historical timeout precedent {index}",
            priority=100,
            relevance_score=0.99,
        )
        for index in range(10)
    ]

    pack = build_pack(
        [*memories, execution_fact],
        make_policy(total_char_budget=len(execution_fact.content)),
    )

    assert [item.source_id for item in pack.items] == ["execution-timeout"]
    assert pack.items[0].source_type is ContextSource.EXECUTION_FACT


def test_compression_preserves_citation_and_provenance() -> None:
    evidence = make_evidence(content="0123456789")
    item = ContextItem.from_retrieved_evidence(evidence)

    pack = build_pack(
        [item],
        make_policy(per_item_char_budget=4, total_char_budget=4),
    )

    assert pack.items[0].content == "0123"
    assert pack.items[0].truncated is True
    assert pack.items[0].citation == evidence.citation
    assert pack.items[0].provenance == (
        ContextProvenance(
            source_type="RUNBOOK",
            source_id="runbook/orders",
            project_id=101,
            document_id="doc-orders",
            chunk_id="chunk-1",
            location="section:timeouts",
        ),
    )


def test_evidence_provenance_identity_is_not_merged_for_same_text() -> None:
    first = make_evidence(content="same chunk text")
    second = first.model_copy(
        update={
            "citation": first.citation.model_copy(update={"source_id": "runbook/other"}),
        }
    )

    pack = build_pack(
        [
            ContextItem.from_retrieved_evidence(first),
            ContextItem.from_retrieved_evidence(second),
        ]
    )

    assert pack.deduplicated_item_count == 2
    assert len(pack.items) == 2


def test_historical_memory_adapter_preserves_structured_provenance() -> None:
    memory = make_memory()

    item = ContextItem.from_historical_memory(memory)

    assert item.source_type is ContextSource.HISTORICAL_MEMORY
    assert item.source_id == memory.memory_id
    assert item.project_scope == memory.project_id
    assert {(reference.source_type, reference.source_id) for reference in item.provenance} == {
        ("RUNBOOK", "runbook/orders-timeouts"),
        ("RUN", "run:77"),
    }


def test_sensitive_data_masker_covers_required_secret_forms() -> None:
    raw = (
        "Authorization: Bearer auth-token "
        "Bearer bare-token "
        "Cookie: sid=cookie-value; theme=dark "
        "password=pass-value "
        "api_key=api-value "
        "secret=secret-value"
    )

    masked = SensitiveDataMasker().mask_text(raw)

    for secret in (
        "auth-token",
        "bare-token",
        "cookie-value",
        "pass-value",
        "api-value",
        "secret-value",
    ):
        assert secret not in masked
    assert "Authorization: Bearer" in masked
    assert "Cookie: sid=" in masked
    assert "password=" in masked
    assert "api_key=" in masked
    assert "secret=" in masked


def test_masking_preserves_identity_provenance_citation_and_truncated() -> None:
    evidence = make_evidence(content="password=raw-password")
    item = ContextItem.from_retrieved_evidence(evidence).model_copy(update={"truncated": True})

    masked = SensitiveDataMasker().mask(item)

    assert "raw-password" not in masked.content
    assert masked.source_type is item.source_type
    assert masked.source_id == item.source_id
    assert masked.project_scope == item.project_scope
    assert masked.provenance == item.provenance
    assert masked.citation == item.citation
    assert masked.truncated is True


def test_builder_masks_content_and_textual_citation_fields_before_pack_boundary() -> None:
    evidence = make_evidence(content="Authorization: Bearer raw-token")
    citation = evidence.citation.model_copy(
        update={"excerpt": "secret=raw-excerpt", "location": "password=raw-location"}
    )
    item = ContextItem.from_retrieved_evidence(evidence.model_copy(update={"citation": citation}))

    pack = build_pack([item])
    serialized = pack.model_dump_json()

    for secret in ("raw-token", "raw-excerpt", "raw-location"):
        assert secret not in serialized
    assert pack.items[0].source_type is ContextSource.RAG_EVIDENCE
    assert pack.items[0].source_id == item.source_id
    assert pack.items[0].provenance[0].source_type == item.provenance[0].source_type
    assert pack.items[0].provenance[0].source_id == item.provenance[0].source_id
    assert pack.items[0].provenance[0].location == "password=************"


def test_cross_project_items_are_ineligible_before_ranking() -> None:
    current = make_item(ContextSource.API_METADATA, "same-id", "current", project_scope=101)
    other = make_item(ContextSource.EXECUTION_FACT, "other-id", "other", project_scope=202)
    unscoped = make_item(ContextSource.USER_INTENT, "unscoped", "unscoped", project_scope=None)

    pack = build_pack([other, unscoped, current])

    assert pack.project_scope == 101
    assert pack.input_item_count == 3
    assert pack.eligible_item_count == 1
    assert [item.source_id for item in pack.items] == ["same-id"]
    assert all(item.project_scope == 101 for item in pack.items)


def test_empty_input_forms_a_legal_project_scoped_context_pack() -> None:
    pack = build_pack([])

    assert pack == ContextPack(project_scope=101)
    assert pack.items == ()
    assert pack.budget_used == 0
    assert pack.input_item_count == 0
    assert pack.eligible_item_count == 0
    assert pack.dropped_item_count == 0


def test_final_acceptance_multisource_pack_retains_roles_and_provenance() -> None:
    evidence = make_evidence(
        content="Authorization: Bearer raw-evidence-token " + "supporting evidence " * 5
    )
    memory = make_memory()
    short_term = make_item(
        ContextSource.SHORT_TERM_CONTEXT,
        "turn-1",
        "recent task context",
    )
    items = [
        make_item(ContextSource.API_METADATA, "orders-contract", "GET /orders/{orderId}"),
        make_item(ContextSource.EXECUTION_FACT, "run-77", "current timeout is 30s"),
        ContextItem.from_retrieved_evidence(evidence),
        ContextItem.from_historical_memory(memory),
        short_term,
        short_term,
    ]
    policy = make_policy(per_item_char_budget=40, total_char_budget=200)

    first = build_pack(items, policy)
    second = build_pack(list(reversed(items)), policy)

    assert first == second
    assert [item.source_type for item in first.items] == [
        ContextSource.EXECUTION_FACT,
        ContextSource.API_METADATA,
        ContextSource.RAG_EVIDENCE,
        ContextSource.SHORT_TERM_CONTEXT,
        ContextSource.HISTORICAL_MEMORY,
    ]
    assert first.deduplicated_item_count == 5
    assert first.items[2].citation == evidence.citation
    assert first.items[2].provenance
    assert first.items[2].truncated is True
    assert "raw-evidence-token" not in first.model_dump_json()
    assert first.budget_used <= 200
