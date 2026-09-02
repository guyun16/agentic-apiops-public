package com.apiops.rag.domain;

import java.time.Instant;
import java.util.Objects;

/** A project-scoped original diagnostic knowledge source and its lifecycle identity. */
public record Document(
        String documentId,
        long projectId,
        String sourceKey,
        String sourceType,
        String title,
        String fileName,
        String mediaType,
        String contentHash,
        DocumentStatus status,
        long createdBy,
        Instant createdAt
) {
    public Document {
        Objects.requireNonNull(documentId, "documentId must not be null");
        Objects.requireNonNull(sourceKey, "sourceKey must not be null");
        Objects.requireNonNull(sourceType, "sourceType must not be null");
        Objects.requireNonNull(title, "title must not be null");
        Objects.requireNonNull(fileName, "fileName must not be null");
        Objects.requireNonNull(mediaType, "mediaType must not be null");
        Objects.requireNonNull(contentHash, "contentHash must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }

    public Document withStatus(DocumentStatus nextStatus) {
        return new Document(
                documentId, projectId, sourceKey, sourceType, title, fileName,
                mediaType, contentHash, nextStatus, createdBy, createdAt);
    }
}
