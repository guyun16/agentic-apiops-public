package com.apiops.openapi.domain;

import java.time.Instant;

public record ApiDocument(
        long id,
        String apiDocId,
        long projectId,
        String sourceKey,
        String documentName,
        String openapiVersion,
        String title,
        String apiVersion,
        String documentFormat,
        String contentHash,
        String rawContent,
        int versionNo,
        String status,
        long createdBy,
        Instant createdAt,
        Instant updatedAt
) {
}
