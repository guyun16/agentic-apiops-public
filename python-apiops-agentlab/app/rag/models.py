"""Strict Python models for the Java RAG evidence read contract."""

from __future__ import annotations

import math

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


class _EvidenceModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
        frozen=True,
    )


class EvidenceCitation(_EvidenceModel):
    """Java-owned citation identity and provenance for one evidence item."""

    source_type: StrictStr = Field(alias="sourceType")
    source_id: StrictStr = Field(alias="sourceId")
    project_id: StrictInt = Field(alias="projectId", ge=1)
    document_id: StrictStr = Field(alias="documentId")
    chunk_id: StrictStr = Field(alias="chunkId")
    score: StrictFloat
    title: StrictStr
    location: StrictStr
    excerpt: StrictStr

    @field_validator("score")
    @classmethod
    def score_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


class RetrievedEvidence(_EvidenceModel):
    """One Java-ranked evidence result with its authoritative citation."""

    project_id: StrictInt = Field(alias="projectId", ge=1)
    document_id: StrictStr = Field(alias="documentId")
    chunk_id: StrictStr = Field(alias="chunkId")
    content: StrictStr
    relevance_score: StrictFloat = Field(alias="relevanceScore")
    citation: EvidenceCitation

    @field_validator("relevance_score")
    @classmethod
    def relevance_score_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("relevanceScore must be finite")
        return value

    @model_validator(mode="after")
    def citation_identity_must_match_result(self) -> RetrievedEvidence:
        if self.citation.project_id != self.project_id:
            raise ValueError("citation projectId must match result projectId")
        if self.citation.document_id != self.document_id:
            raise ValueError("citation documentId must match result documentId")
        if self.citation.chunk_id != self.chunk_id:
            raise ValueError("citation chunkId must match result chunkId")
        if self.citation.score != self.relevance_score:
            raise ValueError("citation score must match result relevanceScore")
        return self


class EvidenceRetrieval(_EvidenceModel):
    """The successful Java RAG result, retaining query identity and order.

    ``_resultTruncated`` is Java Tool Gateway metadata added by ``ResultLimiter``
    after the RAG tool's domain result has been sanitized.  It is part of the
    wire contract rather than an unknown RAG field, so model it explicitly while
    continuing to reject every other extra field and every non-boolean marker.
    """

    rag_query_id: StrictStr = Field(alias="ragQueryId", min_length=1)
    evidence: list[RetrievedEvidence] = Field(alias="results")
    result_truncated: StrictBool = Field(default=False, alias="_resultTruncated")
