package com.apiops.openapi.vo;

import java.time.Instant;

public record ApiDocumentVO(
        String apiDocId,
        long projectId,
        String sourceKey,
        String documentName,
        String openapiVersion,
        String title,
        String apiVersion,
        String documentFormat,
        String contentHash,
        int versionNo,
        String status,
        Instant createdAt,
        Instant updatedAt
) {
}
