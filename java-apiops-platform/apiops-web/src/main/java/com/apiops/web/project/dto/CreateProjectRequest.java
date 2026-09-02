package com.apiops.web.project.dto;

public record CreateProjectRequest(
        String projectKey,
        String projectName
) {
}
