package com.apiops.web.project.domain;

import java.time.Instant;

public record Project(
        long id,
        String projectKey,
        String projectName,
        long ownerUserId,
        String status,
        Instant createdAt,
        Instant updatedAt
) {
}
