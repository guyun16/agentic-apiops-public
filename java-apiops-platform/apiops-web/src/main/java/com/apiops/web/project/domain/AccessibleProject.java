package com.apiops.web.project.domain;

import com.apiops.auth.enums.ProjectRole;

public record AccessibleProject(
        long projectId,
        String projectName,
        ProjectRole projectRole
) {
}
