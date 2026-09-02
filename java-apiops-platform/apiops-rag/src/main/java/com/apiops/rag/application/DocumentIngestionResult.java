package com.apiops.rag.application;

import com.apiops.rag.domain.DocumentStatus;
import com.apiops.rag.embedding.EmbeddingModel;

import java.util.Objects;

public record DocumentIngestionResult(
        long projectId,
        String documentId,
        String contentHash,
        int chunkCount,
        DocumentStatus status,
        EmbeddingModel embeddingModel
) {
    public DocumentIngestionResult {
        Objects.requireNonNull(documentId, "documentId must not be null");
        Objects.requireNonNull(contentHash, "contentHash must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(embeddingModel, "embeddingModel must not be null");
    }
}
