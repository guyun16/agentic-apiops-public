package com.apiops.web.project.vo;

import com.apiops.auth.enums.ProjectRole;

import java.time.Instant;

public record ProjectMemberVO(
        long projectId,
        long userId,
        ProjectRole projectRole,
        Instant joinedAt
) {
}
