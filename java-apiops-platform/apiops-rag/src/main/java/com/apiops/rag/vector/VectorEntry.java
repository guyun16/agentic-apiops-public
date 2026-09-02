package com.apiops.rag.vector;

import com.apiops.rag.embedding.EmbeddingVector;

import java.util.Map;
import java.util.Objects;

/** Derived retrieval entry linked to a formal project-scoped chunk. */
public record VectorEntry(
        long projectId,
        String documentId,
        String chunkId,
        String contentHash,
        EmbeddingVector embedding,
        Map<String, String> metadata
) {
    public VectorEntry {
        Objects.requireNonNull(documentId, "documentId must not be null");
        Objects.requireNonNull(chunkId, "chunkId must not be null");
        Objects.requireNonNull(contentHash, "contentHash must not be null");
        Objects.requireNonNull(embedding, "embedding must not be null");
        metadata = Map.copyOf(Objects.requireNonNull(metadata, "metadata must not be null"));
    }
}
