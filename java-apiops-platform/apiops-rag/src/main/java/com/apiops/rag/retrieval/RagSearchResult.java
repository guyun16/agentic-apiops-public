package com.apiops.rag.retrieval;

import com.apiops.rag.domain.EvidenceCitation;

import java.util.Objects;

/** Provider-agnostic retrieval result resolved against formal document knowledge. */
public record RagSearchResult(
        long projectId,
        String documentId,
        String chunkId,
        String content,
        double relevanceScore,
        EvidenceCitation citation
) {
    public RagSearchResult {
        Objects.requireNonNull(documentId, "documentId must not be null");
        Objects.requireNonNull(chunkId, "chunkId must not be null");
        Objects.requireNonNull(content, "content must not be null");
        Objects.requireNonNull(citation, "citation must not be null");
        if (!Double.isFinite(relevanceScore)) {
            throw new IllegalArgumentException("relevanceScore must be finite");
        }
        if (citation.projectId() != projectId
                || !citation.documentId().equals(documentId)
                || !citation.chunkId().equals(chunkId)
                || Double.compare(citation.score(), relevanceScore) != 0) {
            throw new IllegalArgumentException(
                    "citation does not match the retrieval result");
        }
    }
}
