package com.apiops.auth.security;

import com.apiops.auth.repository.AuthUserRepository;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;

import java.util.Objects;

/**
 * Adapts the authentication user lookup port to Spring Security.
 * Password comparison remains the responsibility of Spring Security's
 * authentication provider, not this lookup service.
 */
public final class ApiOpsUserDetailsService implements UserDetailsService {

    private final AuthUserRepository authUserRepository;

    public ApiOpsUserDetailsService(AuthUserRepository authUserRepository) {
        this.authUserRepository = Objects.requireNonNull(
                authUserRepository,
                "authUserRepository must not be null"
        );
    }

    @Override
    public UserDetails loadUserByUsername(String username) throws UsernameNotFoundException {
        return authUserRepository.findByUsername(username)
                .orElseThrow(() -> new UsernameNotFoundException("User not found"));
    }
}
