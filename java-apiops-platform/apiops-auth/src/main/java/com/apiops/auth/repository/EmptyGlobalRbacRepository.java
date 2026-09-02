package com.apiops.auth.repository;

import java.util.Set;

/** Empty fallback when the host application has no configured DataSource. */
public final class EmptyGlobalRbacRepository implements GlobalRbacRepository {

    @Override
    public Set<String> findRoleCodesByUserId(long userId) {
        return Set.of();
    }

    @Override
    public Set<String> findPermissionCodesByUserId(long userId) {
        return Set.of();
    }
}
