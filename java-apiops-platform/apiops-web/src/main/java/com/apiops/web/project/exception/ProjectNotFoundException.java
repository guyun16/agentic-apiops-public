package com.apiops.web.project.exception;

public final class ProjectNotFoundException extends RuntimeException {

    public ProjectNotFoundException(long projectId) {
        super("Project not found: " + projectId);
    }
}
