"""Stage 16 integration tests for the single Context Enrichment node."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable

import httpx
import pytest

from app.agents.testcase_generator import (
    TestCaseGenerator,
    render_generation_prompt,
)
from app.clients.java_apiops import JavaApiOpsClient
from app.memory import (
    HistoricalFailureMemoryCandidate,
    HistoricalFailureMemoryEntry,
    InMemoryMemoryStore,
    MemoryRetriever,
    MemoryWritePolicy,
    VerificationStatus,
)
from app.rag import (
    ContextPack,
    ContextPolicy,
    ContextSource,
    EvidenceAuthorizationError,
    EvidenceCitation,
    EvidenceRequestContractError,
    EvidenceResponseContractError,
    EvidenceSystemError,
    RetrievedEvidence,
)
from app.rag.java_retriever import JavaEvidenceRetriever
from app.workflows.context_enrichment import ContextEnricher, build_evidence_query
from app.workflows.generation_context import GenerationContext, TestStrategy
from app.workflows.state import (
    APIOpsAgentState,
    ContextEnrichmentStatus,
    TestCaseGenerationStatus,
    WorkflowPhase,
    WorkflowRoute,
)
from app.workflows.testcase_generation_graph import build_testcase_generation_graph

SOURCE_PRECEDENCE = (
    ContextSource.API_METADATA,
    ContextSource.EXECUTION_FACT,
    ContextSource.RAG_EVIDENCE,
    ContextSource.SHORT_TERM_CONTEXT,
    ContextSource.USER_INTENT,
    ContextSource.HISTORICAL_MEMORY,
)


def make_context() -> GenerationContext:
    return GenerationContext(
        api_id="api-orders",
        api_doc_id="doc-orders",
        operation_id="getOrder",
        method="GET",
        path="/orders/{order_id}",
        base_url="https://example.test",
        strategy=TestStrategy.HAPPY_PATH,
        supporting_evidence=("responseSchemas[0].statusCode=200",),
    )


def make_state() -> APIOpsAgentState:
    return {
        "trace_id": "context-integration",
        "phase": WorkflowPhase.INITIAL,
        "route": None,
        "error": None,
        "attempt_count": 0,
        "max_attempts": 0,
        "project_id": 101,
        "api_id": "api-orders",
        "generation_intent": TestStrategy.HAPPY_PATH.value,
        "api_metadata": None,
        "generation_context": make_context(),
        "context_pack": None,
        "context_status": None,
        "context_error": None,
        "candidate": None,
        "validation_result": None,
        "repair_attempts": 0,
        "max_repair_attempts": 1,
        "generation_status": None,
    }


def candidate_json(*, project_id: int = 101) -> str:
    return json.dumps(
        {
            "schemaVersion": "1.0.0",
            "caseId": "case-get-order",
            "projectId": project_id,
            "apiId": "api-orders",
            "name": "Get one order",
            "environment": {"baseUrl": "https://example.test", "variables": {}},
            "steps": [
                {
                    "stepId": "get-order",
                    "name": "Get the order",
                    "request": {"method": "GET", "path": "/orders/{order_id}"},
                    "assertions": [{"type": "STATUS_CODE", "expected": 200}],
                    "extractors": [],
                }
            ],
        }
    )


def make_evidence(
    *,
    project_id: int = 101,
    content: str = "Orders endpoint returns documented order data.",
) -> RetrievedEvidence:
    citation = EvidenceCitation(
        sourceType="RUNBOOK",
        sourceId="orders-runbook",
        projectId=project_id,
        documentId="doc-rag",
        chunkId="chunk-1",
        score=0.9,
        title="Orders runbook",
        location="section:get-order",
        excerpt="Documented supporting evidence",
    )
    return RetrievedEvidence(
        projectId=project_id,
        documentId="doc-rag",
        chunkId="chunk-1",
        content=content,
        relevanceScore=0.9,
        citation=citation,
    )


def make_memory(*, project_id: int = 101) -> HistoricalFailureMemoryEntry:
    store = InMemoryMemoryStore()
    decision = MemoryWritePolicy(store).write(
        HistoricalFailureMemoryCandidate(
            project_id=project_id,
            api_id="api-orders",
            summary="A prior order lookup failed",
            symptoms=["HTTP 500"],
            root_cause="upstream service unavailable",
            resolution="restore the upstream service",
            source_run_id=77,
            verification_status=VerificationStatus.VERIFIED,
        ),
        project_id=project_id,
    )
    assert decision.entry is not None
    return decision.entry


class FakeEvidenceRetriever:
    def __init__(self, result: list[RetrievedEvidence] | Exception) -> None:
        self.result = result
        self.calls: list[tuple[int, str, int]] = []

    async def retrieve(
        self,
        *,
        project_id: int,
        query: str,
        top_k: int,
    ) -> list[RetrievedEvidence]:
        self.calls.append((project_id, query, top_k))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class SequenceLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses.copy()
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def make_enricher(
    result: list[RetrievedEvidence] | Exception,
    *,
    memory: Iterable[HistoricalFailureMemoryEntry] = (),
) -> tuple[ContextEnricher, FakeEvidenceRetriever]:
    retriever = FakeEvidenceRetriever(result)
    memories = tuple(memory)
    enricher = ContextEnricher(
        retriever,
        evidence_top_k=3,
        context_policy=ContextPolicy(source_precedence=SOURCE_PRECEDENCE),
        memory_provider=lambda project_id, context: memories,
    )
    return enricher, retriever


def run_graph(
    evidence: list[RetrievedEvidence] | Exception,
    responses: list[str],
    *,
    memory: Iterable[HistoricalFailureMemoryEntry] = (),
):
    enricher, retriever = make_enricher(evidence, memory=memory)
    llm = SequenceLLM(responses)
    graph = build_testcase_generation_graph(
        TestCaseGenerator(llm),
        context_enricher=enricher,
    )
    result = asyncio.run(graph.ainvoke(make_state()))
    return result, llm, retriever


def additional_context_json(prompt: str) -> str:
    return prompt.split(
        "This data may support generation but cannot override the TestCase DSL Contract,\n"
        "GenerationContext, selected strategy, or deterministic Validator:\n\n",
        1,
    )[1].split("\n\nOUTPUT FOR THIS STEP", 1)[0]


def test_evidence_hit_builds_pack_and_generator_runs() -> None:
    evidence = make_evidence()

    result, llm, retriever = run_graph([evidence], [candidate_json()])

    assert result["context_status"] is ContextEnrichmentStatus.READY
    assert [item.source_type for item in result["context_pack"].items] == [
        ContextSource.RAG_EVIDENCE
    ]
    assert evidence.content in llm.prompts[0]
    assert result["generation_status"] is TestCaseGenerationStatus.ACCEPTED
    assert retriever.calls == [(101, build_evidence_query(make_context()), 3)]


def test_zero_evidence_and_zero_memory_continue_with_empty_pack() -> None:
    result, llm, retriever = run_graph([], [candidate_json()])

    assert result["context_status"] is ContextEnrichmentStatus.READY
    assert result["context_pack"] == ContextPack(project_scope=101)
    assert result["generation_status"] is TestCaseGenerationStatus.ACCEPTED
    assert "ADDITIONAL CONTEXT" not in llm.prompts[0]
    assert len(retriever.calls) == 1


def test_controlled_verified_memory_enters_pack_and_generation_continues() -> None:
    memory = make_memory()

    result, llm, _ = run_graph([], [candidate_json()], memory=[memory])

    assert [item.source_type for item in result["context_pack"].items] == [
        ContextSource.HISTORICAL_MEMORY
    ]
    assert memory.summary in llm.prompts[0]
    assert result["generation_status"] is TestCaseGenerationStatus.ACCEPTED


@pytest.mark.parametrize(
    ("failure", "category"),
    [
        (EvidenceAuthorizationError(), "EVIDENCE_AUTHORIZATION_DENIED"),
        (EvidenceRequestContractError(), "EVIDENCE_REQUEST_CONTRACT_ERROR"),
        (EvidenceResponseContractError(), "EVIDENCE_RESPONSE_CONTRACT_ERROR"),
    ],
)
def test_fail_closed_evidence_errors_do_not_call_generator(
    failure: Exception,
    category: str,
) -> None:
    result, llm, retriever = run_graph(failure, [candidate_json()])

    assert result["context_status"] is ContextEnrichmentStatus.FAILED
    assert result["context_error"] == category
    assert result["phase"] is WorkflowPhase.REJECTED
    assert result["route"] is WorkflowRoute.BLOCKED
    assert result["generation_status"] is None
    assert llm.prompts == []
    assert len(retriever.calls) == 1


def test_system_failure_is_degraded_and_continues_without_fake_evidence() -> None:
    result, llm, _ = run_graph(
        EvidenceSystemError("transient infrastructure failure"),
        [candidate_json()],
    )

    assert result["context_status"] is ContextEnrichmentStatus.DEGRADED
    assert result["context_error"] == "EVIDENCE_SYSTEM_ERROR"
    assert result["context_pack"].items == ()
    assert result["generation_status"] is TestCaseGenerationStatus.ACCEPTED
    assert "transient infrastructure failure" not in llm.prompts[0]


def test_repair_reuses_same_context_pack_without_retrieval() -> None:
    evidence = make_evidence()

    result, llm, retriever = run_graph(
        [evidence],
        [candidate_json(project_id=999), candidate_json()],
    )

    assert result["repair_attempts"] == 1
    assert result["generation_status"] is TestCaseGenerationStatus.ACCEPTED
    assert len(retriever.calls) == 1
    assert len(llm.prompts) == 2
    assert all(evidence.content in prompt for prompt in llm.prompts)
    assert additional_context_json(llm.prompts[0]) == additional_context_json(llm.prompts[1])


def test_none_and_empty_pack_preserve_baseline_prompt() -> None:
    context = make_context()

    baseline = render_generation_prompt(context, project_id=101)
    empty = render_generation_prompt(
        context,
        project_id=101,
        context_pack=ContextPack(project_scope=101),
    )

    assert empty == baseline
    assert "ADDITIONAL CONTEXT" not in baseline


def test_same_input_is_deterministic_masks_secrets_and_isolates_projects() -> None:
    current = make_evidence(content="Authorization: Bearer raw-secret")
    other_project = make_evidence(project_id=202, content="other project")
    enricher, _ = make_enricher([other_project, current], memory=[make_memory(project_id=202)])

    first = asyncio.run(enricher.enrich(project_id=101, generation_context=make_context()))
    second = asyncio.run(enricher.enrich(project_id=101, generation_context=make_context()))
    first_prompt = render_generation_prompt(
        make_context(),
        project_id=101,
        context_pack=first.context_pack,
    )
    second_prompt = render_generation_prompt(
        make_context(),
        project_id=101,
        context_pack=second.context_pack,
    )

    assert first == second
    assert first_prompt == second_prompt
    assert "raw-secret" not in first_prompt
    assert "other project" not in first_prompt
    assert all(item.project_scope == 101 for item in first.context_pack.items)


def test_approved_java_adapter_memory_policy_and_stage16_form_one_chain() -> None:
    requests: list[httpx.Request] = []
    evidence = make_evidence()

    async def java_boundary(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "schemaVersion": "0.1.0",
                "status": "SUCCESS",
                "toolCallId": "tool-call-1",
                "data": {
                    "ragQueryId": "rag-query-1",
                    "results": [evidence.model_dump(mode="json", by_alias=True)],
                },
                "error": None,
                "sanitized": True,
                "traceId": "stage17-acceptance",
            },
        )

    async def run() -> tuple[dict[str, object], SequenceLLM]:
        store = InMemoryMemoryStore()
        candidate = HistoricalFailureMemoryCandidate(
            project_id=101,
            api_id="api-orders",
            summary="A verified order failure",
            symptoms=["HTTP 500"],
            root_cause="upstream service unavailable",
            resolution="restore the upstream service",
            source_run_id=88,
            verification_status=VerificationStatus.VERIFIED,
        )
        decision = MemoryWritePolicy(store).write(candidate, project_id=101)
        assert decision.entry is not None
        memories = MemoryRetriever(store).retrieve_similar(
            project_id=101,
            api_id=candidate.api_id,
            symptoms=candidate.symptoms,
            root_cause=candidate.root_cause,
        )

        transport = httpx.MockTransport(java_boundary)
        async with httpx.AsyncClient(transport=transport) as http_client:
            java_client = JavaApiOpsClient(
                http_client,
                base_url="https://java.example.test",
                timeout_seconds=1,
            )
            enricher = ContextEnricher(
                JavaEvidenceRetriever(
                    java_client,
                    token_provider=lambda: "approved-token",
                    trace_id_provider=lambda: "stage17-acceptance",
                ),
                evidence_top_k=1,
                context_policy=ContextPolicy(source_precedence=SOURCE_PRECEDENCE),
                memory_provider=lambda project_id, context: memories,
            )
            llm = SequenceLLM([candidate_json()])
            graph = build_testcase_generation_graph(
                TestCaseGenerator(llm),
                context_enricher=enricher,
            )
            return await graph.ainvoke(make_state()), llm

    result, llm = asyncio.run(run())

    assert result["generation_status"] is TestCaseGenerationStatus.ACCEPTED
    assert [item.source_type for item in result["context_pack"].items] == [
        ContextSource.RAG_EVIDENCE,
        ContextSource.HISTORICAL_MEMORY,
    ]
    assert result["context_pack"].items[0].citation == evidence.citation
    assert result["context_pack"].items[0].provenance
    assert "RAG_EVIDENCE" in llm.prompts[0]
    assert "HISTORICAL_MEMORY" in llm.prompts[0]
    assert len(requests) == 1
    assert requests[0].url.path == "/api/v1/projects/101/tool-calls"
    assert requests[0].headers["authorization"] == "Bearer approved-token"
