package com.apiops.openapi.domain;

import java.time.Instant;

public record ApiResponseSchema(
        long id,
        String apiId,
        long projectId,
        String statusCode,
        String description,
        String mediaType,
        String schemaJson,
        Instant createdAt
) {
}
