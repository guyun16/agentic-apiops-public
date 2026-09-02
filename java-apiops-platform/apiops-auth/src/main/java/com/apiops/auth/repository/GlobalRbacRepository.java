package com.apiops.auth.repository;

import java.util.Set;

/** Stable read contract for global roles and permissions assigned to a user. */
public interface GlobalRbacRepository {

    Set<String> findRoleCodesByUserId(long userId);

    Set<String> findPermissionCodesByUserId(long userId);
}
