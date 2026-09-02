"""Contract tests for the Java-backed evidence consumer."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from app.clients.java_apiops import JavaApiOpsClient
from app.rag import (
    EvidenceAuthorizationError,
    EvidenceRequestContractError,
    EvidenceResponseContractError,
    EvidenceRetriever,
    EvidenceSystemError,
    RetrievedEvidence,
)
from app.rag.java_retriever import JavaEvidenceRetriever

RequestHandler = Callable[[httpx.Request], Awaitable[httpx.Response]]


def citation_payload(
    *,
    project_id: int,
    document_id: str,
    chunk_id: str,
    score: float,
    source_id: str = "runbook/orders",
) -> dict[str, Any]:
    return {
        "sourceType": "RUNBOOK",
        "sourceId": source_id,
        "projectId": project_id,
        "documentId": document_id,
        "chunkId": chunk_id,
        "score": score,
        "title": "Orders runbook",
        "location": f"chunk:{chunk_id}",
        "excerpt": f"Excerpt for {chunk_id}",
    }


def evidence_payload(
    *,
    project_id: int,
    document_id: str,
    chunk_id: str,
    score: float,
) -> dict[str, Any]:
    return {
        "projectId": project_id,
        "documentId": document_id,
        "chunkId": chunk_id,
        "content": f"Evidence content for {chunk_id}",
        "relevanceScore": score,
        "citation": citation_payload(
            project_id=project_id,
            document_id=document_id,
            chunk_id=chunk_id,
            score=score,
        ),
    }


def tool_result(
    *,
    status: str = "SUCCESS",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": "0.1.0",
        "toolCallId": "tool-call-1",
        "status": status,
        "data": data,
        "error": None if status == "SUCCESS" else {"code": status, "message": "denied"},
        "sanitized": True,
        "traceId": "T500",
    }


def rag_data(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ragQueryId": "ragq_123",
        "results": results,
    }


async def retrieve(
    handler: RequestHandler,
    **kwargs: Any,
) -> Any:
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test/",
            timeout_seconds=2.5,
        )
        call_kwargs = {
            "project_id": 41,
            "query": "why did the order fail",
            "top_k": 2,
            "token": "secret-token",
            "trace_id": "T500",
        }
        call_kwargs.update(kwargs)
        return await client.retrieve_evidence(
            **call_kwargs,
        )


@pytest.mark.anyio
async def test_success_maps_multiple_evidence_and_preserves_java_order() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=tool_result(
                data=rag_data(
                    [
                        evidence_payload(
                            project_id=41,
                            document_id="doc-2",
                            chunk_id="chunk-2",
                            score=0.40,
                        ),
                        evidence_payload(
                            project_id=41,
                            document_id="doc-1",
                            chunk_id="chunk-1",
                            score=0.95,
                        ),
                    ]
                )
            ),
        )

    result = await retrieve(handler)

    assert result.rag_query_id == "ragq_123"
    assert [item.chunk_id for item in result.evidence] == ["chunk-2", "chunk-1"]
    assert [item.relevance_score for item in result.evidence] == [0.40, 0.95]
    assert result.evidence[0].citation.source_type == "RUNBOOK"
    assert result.evidence[0].citation.source_id == "runbook/orders"
    assert result.evidence[0].citation.location == "chunk:chunk-2"
    assert result.evidence[0].citation.excerpt == "Excerpt for chunk-2"

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://java.example.test/api/v1/projects/41/tool-calls"
    assert request.headers["authorization"] == "Bearer secret-token"
    assert request.headers["x-trace-id"] == "T500"
    request_body = json.loads(request.content)
    assert request_body["schemaVersion"] == "0.2.0"
    assert request_body["projectId"] == "41"
    assert request_body["toolName"] == "rag.search"
    assert request_body["params"] == {"query": "why did the order fail", "topK": 2}
    assert request_body["traceId"] == "T500"
    assert request_body["agentRunId"].startswith("evidence:")
    assert "toolCallId" not in request_body
    assert "arguments" not in request_body


@pytest.mark.anyio
async def test_zero_hit_success_returns_empty_evidence_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=tool_result(data=rag_data([])))

    result = await retrieve(handler)

    assert result.rag_query_id == "ragq_123"
    assert result.evidence == []


@pytest.mark.anyio
async def test_http_403_is_authorization_error_not_zero_hit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    with pytest.raises(EvidenceAuthorizationError) as error:
        await retrieve(handler)

    assert error.value.status_code == 403
    assert error.value.tool_status is None


@pytest.mark.anyio
async def test_java_forbidden_tool_result_is_authorization_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=tool_result(status="FORBIDDEN"),
        )

    with pytest.raises(EvidenceAuthorizationError) as error:
        await retrieve(handler)

    assert error.value.status_code is None
    assert error.value.tool_status == "FORBIDDEN"


@pytest.mark.anyio
async def test_java_server_failure_is_stable_system_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "temporary failure"})

    with pytest.raises(EvidenceSystemError) as error:
        await retrieve(handler)

    assert error.value.status_code == 503


@pytest.mark.anyio
async def test_java_transport_failure_is_stable_system_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret-token connection failure", request=request)

    with pytest.raises(EvidenceSystemError) as error:
        await retrieve(handler)

    assert str(error.value) == "Java RAG request failed during transport"
    assert "secret-token" not in str(error.value)


@pytest.mark.anyio
async def test_malformed_citation_is_response_contract_error() -> None:
    malformed = evidence_payload(
        project_id=41,
        document_id="doc-1",
        chunk_id="chunk-1",
        score=0.91,
    )
    del malformed["citation"]["sourceId"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=tool_result(data=rag_data([malformed])))

    with pytest.raises(EvidenceResponseContractError):
        await retrieve(handler)


@pytest.mark.anyio
async def test_citation_score_mismatch_is_response_contract_error() -> None:
    malformed = evidence_payload(
        project_id=41,
        document_id="doc-1",
        chunk_id="chunk-1",
        score=0.91,
    )
    malformed["citation"]["score"] = 0.90

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=tool_result(data=rag_data([malformed])))

    with pytest.raises(EvidenceResponseContractError):
        await retrieve(handler)


@pytest.mark.anyio
async def test_java_param_invalid_is_request_contract_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=tool_result(status="PARAM_INVALID"),
        )

    with pytest.raises(EvidenceRequestContractError) as error:
        await retrieve(handler)

    assert error.value.tool_status == "PARAM_INVALID"


@pytest.mark.anyio
async def test_java_result_invalid_is_response_contract_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=tool_result(status="RESULT_INVALID"),
        )

    with pytest.raises(EvidenceResponseContractError):
        await retrieve(handler)


@pytest.mark.anyio
async def test_invalid_json_is_response_contract_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(EvidenceResponseContractError):
        await retrieve(handler)


@pytest.mark.anyio
async def test_java_evidence_retriever_implements_port_without_token_argument() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=tool_result(data=rag_data([])))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url="https://java.example.test",
            timeout_seconds=1,
        )
        retriever = JavaEvidenceRetriever(
            client,
            token_provider=lambda: "secret-token",
            trace_id_provider=lambda: "T500",
        )
        assert isinstance(retriever, EvidenceRetriever)
        assert await retriever.retrieve(project_id=41, query="evidence", top_k=1) == []


@pytest.mark.anyio
async def test_fake_evidence_retriever_is_deterministic_at_the_port() -> None:
    class FakeEvidenceRetriever:
        async def retrieve(
            self,
            *,
            project_id: int,
            query: str,
            top_k: int,
        ) -> list[RetrievedEvidence]:
            assert (project_id, query, top_k) == (41, "evidence", 1)
            return [
                RetrievedEvidence.model_validate(
                    evidence_payload(
                        project_id=41,
                        document_id="doc-1",
                        chunk_id="chunk-1",
                        score=0.91,
                    )
                )
            ]

    async def consume(retriever: EvidenceRetriever) -> list[RetrievedEvidence]:
        return await retriever.retrieve(project_id=41, query="evidence", top_k=1)

    retriever = FakeEvidenceRetriever()
    assert isinstance(retriever, EvidenceRetriever)
    result = await consume(retriever)
    assert [item.chunk_id for item in result] == ["chunk-1"]


@pytest.mark.anyio
@pytest.mark.parametrize("top_k", [1, 20])
async def test_java_top_k_boundaries_are_forwarded(top_k: int) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=tool_result(data=rag_data([])))

    await retrieve(handler, top_k=top_k)

    body = json.loads(requests[0].content)
    assert body["params"]["topK"] == top_k


@pytest.mark.anyio
@pytest.mark.parametrize("top_k", [0, 21, True, 1.5])
async def test_invalid_top_k_is_rejected_without_a_java_call(top_k: Any) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    with pytest.raises(ValueError, match="top_k"):
        await retrieve(handler, top_k=top_k)

    assert calls == 0
