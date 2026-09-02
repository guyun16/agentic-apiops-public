package com.apiops.rag.vector;

import java.util.Objects;

/** Project-scoped match with a provider-normalized, higher-is-better relevance score. */
public record VectorSearchMatch(
        long projectId,
        String documentId,
        String chunkId,
        double relevanceScore
) {

    public VectorSearchMatch {
        Objects.requireNonNull(documentId, "documentId must not be null");
        Objects.requireNonNull(chunkId, "chunkId must not be null");
        if (!Double.isFinite(relevanceScore)) {
            throw new IllegalArgumentException("relevanceScore must be finite");
        }
    }
}
