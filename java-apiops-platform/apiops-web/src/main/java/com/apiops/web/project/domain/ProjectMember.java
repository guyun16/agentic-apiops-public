package com.apiops.web.project.domain;

import com.apiops.auth.enums.ProjectRole;

import java.time.Instant;

public record ProjectMember(
        long projectId,
        long userId,
        ProjectRole projectRole,
        Instant joinedAt
) {
}
