package com.apiops.web.project.repository;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.web.project.domain.AccessibleProject;
import com.apiops.web.project.domain.Project;
import com.apiops.web.project.domain.ProjectMember;

import java.util.List;
import java.util.Optional;

/** Persistence boundary for project resources and their memberships. */
public interface ProjectRepository {

    /**
     * Creates the project and its OWNER membership in one atomic operation.
     */
    Project createProjectWithOwner(String projectKey, String projectName, long ownerUserId);

    Optional<Project> findById(long projectId);

    List<AccessibleProject> findAccessibleProjectsByUserId(long userId);

    Optional<Project> updateProjectName(long projectId, String projectName);

    ProjectMember addMember(long projectId, long userId, ProjectRole projectRole);
}
