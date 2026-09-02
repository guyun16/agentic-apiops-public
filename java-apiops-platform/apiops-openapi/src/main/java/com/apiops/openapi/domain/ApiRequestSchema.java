package com.apiops.openapi.domain;

import java.time.Instant;

public record ApiRequestSchema(
        long id,
        String apiId,
        long projectId,
        boolean required,
        String mediaType,
        String schemaJson,
        Instant createdAt
) {
}
