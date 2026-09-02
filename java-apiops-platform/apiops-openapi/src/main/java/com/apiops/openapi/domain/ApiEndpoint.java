package com.apiops.openapi.domain;

import java.time.Instant;

public record ApiEndpoint(
        long id,
        String apiId,
        String apiDocId,
        long projectId,
        String operationId,
        String httpMethod,
        String path,
        String summary,
        String description,
        String tagsJson,
        String serversJson,
        String securityJson,
        boolean deprecated,
        Instant createdAt,
        Instant updatedAt
) {
}
