package com.apiops.openapi.domain;

import java.time.Instant;

public record ApiExample(
        long id,
        String apiId,
        long projectId,
        String ownerType,
        long ownerRefId,
        String exampleName,
        String summary,
        String description,
        String valueJson,
        Instant createdAt
) {
}
