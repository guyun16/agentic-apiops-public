"""Java-backed implementation of the Python evidence consumer port."""

from __future__ import annotations

from collections.abc import Callable

from app.clients.java_apiops import JavaApiOpsClient

from .models import RetrievedEvidence


class JavaEvidenceRetriever:
    """Delegate evidence reads to Java while keeping credentials out of the port."""

    def __init__(
        self,
        client: JavaApiOpsClient,
        *,
        token_provider: Callable[[], str],
        trace_id_provider: Callable[[], str | None] | None = None,
    ) -> None:
        if not isinstance(client, JavaApiOpsClient):
            raise TypeError("client must be a JavaApiOpsClient")
        if not callable(token_provider):
            raise TypeError("token_provider must be callable")
        if trace_id_provider is not None and not callable(trace_id_provider):
            raise TypeError("trace_id_provider must be callable or None")

        self._client = client
        self._token_provider = token_provider
        self._trace_id_provider = trace_id_provider

    async def retrieve(
        self,
        *,
        project_id: int,
        query: str,
        top_k: int,
    ) -> list[RetrievedEvidence]:
        """Return only typed evidence; Java remains the authorization authority."""

        result = await self._client.retrieve_evidence(
            project_id=project_id,
            query=query,
            top_k=top_k,
            token=self._token_provider(),
            trace_id=(self._trace_id_provider() if self._trace_id_provider is not None else None),
        )
        return result.evidence
