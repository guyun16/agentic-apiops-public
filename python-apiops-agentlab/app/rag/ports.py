"""Consumer port for project-scoped evidence retrieval."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import RetrievedEvidence


@runtime_checkable
class EvidenceRetriever(Protocol):
    """Minimal read-only port; it does not own context, prompting, or routing."""

    async def retrieve(
        self,
        *,
        project_id: int,
        query: str,
        top_k: int,
    ) -> list[RetrievedEvidence]:
        """Return Java-ranked evidence for the requested project and query."""
