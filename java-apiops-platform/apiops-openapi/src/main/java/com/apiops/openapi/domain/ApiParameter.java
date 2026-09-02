package com.apiops.openapi.domain;

import java.time.Instant;

public record ApiParameter(
        long id,
        String apiId,
        long projectId,
        String name,
        String location,
        boolean required,
        String description,
        String schemaJson,
        String exampleJson,
        Instant createdAt
) {
}
