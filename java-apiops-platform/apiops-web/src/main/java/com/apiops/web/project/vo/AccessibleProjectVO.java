package com.apiops.web.project.vo;

import com.apiops.auth.enums.ProjectRole;

public record AccessibleProjectVO(
        long projectId,
        String projectName,
        ProjectRole projectRole
) {
}
