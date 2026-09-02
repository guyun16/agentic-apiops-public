package com.apiops.web.project.dto;

import com.apiops.auth.enums.ProjectRole;

public record AddProjectMemberRequest(
        long userId,
        ProjectRole projectRole
) {
}
