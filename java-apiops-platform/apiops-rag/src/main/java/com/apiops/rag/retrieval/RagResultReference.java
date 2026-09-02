package com.apiops.rag.retrieval;

import java.util.Objects;

/** Stable retrieval fact reference without duplicated chunk content. */
public record RagResultReference(String documentId, String chunkId) {
    public RagResultReference {
        Objects.requireNonNull(documentId, "documentId must not be null");
        Objects.requireNonNull(chunkId, "chunkId must not be null");
    }
}
