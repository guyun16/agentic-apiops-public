"""Single-pass context enrichment for the Stage 16 generation workflow."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.memory.models import (
    HistoricalFailureMemoryEntry,
    MemoryLifecycleStatus,
    VerificationStatus,
)
from app.rag.context import ContextItem, ContextPack, ContextPackBuilder, ContextPolicy
from app.rag.errors import (
    EvidenceAuthorizationError,
    EvidenceRequestContractError,
    EvidenceResponseContractError,
    EvidenceSystemError,
)
from app.rag.ports import EvidenceRetriever
from app.workflows.generation_context import GenerationContext
from app.workflows.state import ContextEnrichmentStatus

HistoricalMemoryProvider = Callable[
    [int, GenerationContext], Iterable[HistoricalFailureMemoryEntry]
]


@dataclass(frozen=True)
class ContextEnrichmentResult:
    """Context output and a sanitized workflow-local outcome."""

    status: ContextEnrichmentStatus
    context_pack: ContextPack | None
    error: str | None = None


def build_evidence_query(context: GenerationContext) -> str:
    """Build a stable query using only the selected generation context."""

    return json.dumps(
        {
            "apiId": context.api_id,
            "method": context.method,
            "operationId": context.operation_id,
            "path": context.path,
            "strategy": context.strategy.value,
            "supportingEvidence": context.supporting_evidence,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class ContextEnricher:
    """Retrieve evidence once and assemble one project-isolated ContextPack."""

    def __init__(
        self,
        evidence_retriever: EvidenceRetriever,
        *,
        evidence_top_k: int,
        context_policy: ContextPolicy,
        memory_provider: HistoricalMemoryProvider | None = None,
    ) -> None:
        if isinstance(evidence_top_k, bool) or not isinstance(evidence_top_k, int):
            raise TypeError("evidence_top_k must be an integer")
        if evidence_top_k < 1:
            raise ValueError("evidence_top_k must be positive")
        if not isinstance(context_policy, ContextPolicy):
            raise TypeError("context_policy must be a ContextPolicy")
        self._evidence_retriever = evidence_retriever
        self._evidence_top_k = evidence_top_k
        self._context_policy = context_policy
        self._memory_provider = memory_provider

    async def enrich(
        self,
        *,
        project_id: int,
        generation_context: GenerationContext,
    ) -> ContextEnrichmentResult:
        """Return READY, DEGRADED, or fail-closed FAILED context."""

        try:
            evidence = await self._evidence_retriever.retrieve(
                project_id=project_id,
                query=build_evidence_query(generation_context),
                top_k=self._evidence_top_k,
            )
        except EvidenceAuthorizationError:
            return ContextEnrichmentResult(
                status=ContextEnrichmentStatus.FAILED,
                context_pack=None,
                error="EVIDENCE_AUTHORIZATION_DENIED",
            )
        except EvidenceRequestContractError:
            return ContextEnrichmentResult(
                status=ContextEnrichmentStatus.FAILED,
                context_pack=None,
                error="EVIDENCE_REQUEST_CONTRACT_ERROR",
            )
        except EvidenceResponseContractError:
            return ContextEnrichmentResult(
                status=ContextEnrichmentStatus.FAILED,
                context_pack=None,
                error="EVIDENCE_RESPONSE_CONTRACT_ERROR",
            )
        except EvidenceSystemError:
            evidence = []
            status = ContextEnrichmentStatus.DEGRADED
            error = "EVIDENCE_SYSTEM_ERROR"
        else:
            status = ContextEnrichmentStatus.READY
            error = None

        items = [ContextItem.from_retrieved_evidence(item) for item in evidence]
        if self._memory_provider is not None:
            memories = self._memory_provider(project_id, generation_context)
            items.extend(
                ContextItem.from_historical_memory(memory)
                for memory in memories
                if memory.verification_status is VerificationStatus.VERIFIED
                and memory.lifecycle_status is MemoryLifecycleStatus.ACTIVE
            )

        context_pack = ContextPackBuilder(
            self._context_policy,
            project_scope=project_id,
        ).build(items)
        return ContextEnrichmentResult(
            status=status,
            context_pack=context_pack,
            error=error,
        )


__all__ = [
    "ContextEnricher",
    "ContextEnrichmentResult",
    "HistoricalMemoryProvider",
    "build_evidence_query",
]
