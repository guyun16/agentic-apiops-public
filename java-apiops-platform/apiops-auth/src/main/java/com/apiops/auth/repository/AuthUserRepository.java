package com.apiops.auth.repository;

import com.apiops.auth.security.ApiOpsPrincipal;

import java.util.Optional;

/** Authentication user lookup port used by Spring Security authentication. */
public interface AuthUserRepository {

    Optional<ApiOpsPrincipal> findByUsername(String username);
}
