package com.apiops.auth.repository;

import com.apiops.auth.security.ApiOpsPrincipal;

import java.util.Optional;

/** Safe no-datasource fallback: no fixed credentials are available. */
public final class EmptyAuthUserRepository implements AuthUserRepository {

    @Override
    public Optional<ApiOpsPrincipal> findByUsername(String username) {
        return Optional.empty();
    }
}
