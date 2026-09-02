package com.apiops.auth.repository;

import com.apiops.auth.enums.ProjectRole;

import java.util.Optional;

/** Empty fallback when the host application has no configured DataSource. */
public final class EmptyProjectMembershipRepository implements ProjectMembershipRepository {

    @Override
    public Optional<ProjectRole> findProjectRole(long userId, long projectId) {
        return Optional.empty();
    }
}
