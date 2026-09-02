package com.apiops.auth.repository;

import com.apiops.auth.security.ApiOpsPrincipal;

import java.util.Map;
import java.util.Optional;

/**
 * Local fallback used when the host application has no configured DataSource.
 * The same encoded demonstration credential is supplied by auth-seed.sql.
 */
public final class InMemoryAuthUserRepository implements AuthUserRepository {

    private static final String DEMO_USERNAME = "demo-user";
    private static final String DEMO_PASSWORD_HASH =
            "$2a$10$WenTT0lW/ci4aaLqa/z6geN7/oL9nzW0jsie1LdXjDbRFPeAh4hTi";

    private final Map<String, ApiOpsPrincipal> users;

    private InMemoryAuthUserRepository(Map<String, ApiOpsPrincipal> users) {
        this.users = Map.copyOf(users);
    }

    public static InMemoryAuthUserRepository demoUser() {
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                1L,
                DEMO_USERNAME,
                DEMO_PASSWORD_HASH,
                true,
                null
        );
        return new InMemoryAuthUserRepository(Map.of(DEMO_USERNAME, principal));
    }

    @Override
    public Optional<ApiOpsPrincipal> findByUsername(String username) {
        return Optional.ofNullable(users.get(username));
    }
}
