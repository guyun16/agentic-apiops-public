package com.apiops.rag.domain;

import java.util.Objects;

/** Stable project-scoped source location for external diagnostic knowledge. */
public record EvidenceCitation(
        String sourceType,
        String sourceId,
        long projectId,
        String documentId,
        String chunkId,
        double score,
        String title,
        String location,
        String excerpt
) {
    public EvidenceCitation {
        Objects.requireNonNull(sourceType, "sourceType must not be null");
        Objects.requireNonNull(sourceId, "sourceId must not be null");
        Objects.requireNonNull(documentId, "documentId must not be null");
        Objects.requireNonNull(chunkId, "chunkId must not be null");
        if (!Double.isFinite(score)) {
            throw new IllegalArgumentException("score must be finite");
        }
        Objects.requireNonNull(title, "title must not be null");
        Objects.requireNonNull(location, "location must not be null");
        Objects.requireNonNull(excerpt, "excerpt must not be null");
    }
}
