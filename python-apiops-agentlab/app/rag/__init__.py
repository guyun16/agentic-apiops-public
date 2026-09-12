"""Python consumer contract for Java-backed RAG evidence."""

from .context import (
    ContextCompressionResult,
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
from .errors import (
    EvidenceAuthorizationError,
    EvidenceRequestContractError,
    EvidenceResponseContractError,
    EvidenceRetrievalError,
    EvidenceSystemError,
)
from .models import EvidenceCitation, EvidenceRetrieval, RetrievedEvidence
from .ports import EvidenceRetriever
from .relevance_selection import select_query_relevant_evidence

__all__ = [
    "EvidenceAuthorizationError",
    "EvidenceCitation",
    "EvidenceRequestContractError",
    "EvidenceResponseContractError",
    "EvidenceRetrieval",
    "EvidenceRetrievalError",
    "EvidenceRetriever",
    "EvidenceSystemError",
    "RetrievedEvidence",
    "ContextCompressionResult",
    "ContextItem",
    "ContextPack",
    "ContextPackBuilder",
    "ContextPolicy",
    "ContextProvenance",
    "ContextRanker",
    "ContextSource",
    "DeterministicContextCompressor",
    "SensitiveDataMasker",
    "select_query_relevant_evidence",
]
