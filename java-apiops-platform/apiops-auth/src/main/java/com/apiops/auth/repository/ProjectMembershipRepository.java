package com.apiops.auth.repository;

import com.apiops.auth.enums.ProjectRole;

import java.util.Optional;

/** Stable read contract for a user's membership in one project. */
public interface ProjectMembershipRepository {

    Optional<ProjectRole> findProjectRole(long userId, long projectId);
}
