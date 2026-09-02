package com.apiops.web.project.repository;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.web.project.domain.AccessibleProject;
import com.apiops.web.project.domain.Project;
import com.apiops.web.project.domain.ProjectMember;

import java.util.List;
import java.util.Optional;

/** Explicit fail-closed fallback when the host application has no DataSource. */
public final class EmptyProjectRepository implements ProjectRepository {

    private static IllegalStateException notConfigured() {
        return new IllegalStateException("Project persistence is not configured");
    }

    @Override
    public Project createProjectWithOwner(String projectKey, String projectName, long ownerUserId) {
        throw notConfigured();
    }

    @Override
    public Optional<Project> findById(long projectId) {
        throw notConfigured();
    }

    @Override
    public List<AccessibleProject> findAccessibleProjectsByUserId(long userId) {
        throw notConfigured();
    }

    @Override
    public Optional<Project> updateProjectName(long projectId, String projectName) {
        throw notConfigured();
    }

    @Override
    public ProjectMember addMember(long projectId, long userId, ProjectRole projectRole) {
        throw notConfigured();
    }
}
