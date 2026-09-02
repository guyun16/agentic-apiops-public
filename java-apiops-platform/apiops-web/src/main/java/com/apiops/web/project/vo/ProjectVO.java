package com.apiops.web.project.vo;

import java.time.Instant;

public record ProjectVO(
        long id,
        String projectKey,
        String projectName,
        long ownerUserId,
        String status,
        Instant createdAt,
        Instant updatedAt
) {
}
