package com.apiops.auth.security;

import com.apiops.auth.repository.AuthUserRepository;
import org.junit.jupiter.api.Test;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UsernameNotFoundException;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ApiOpsUserDetailsServiceTest {

    @Test
    void shouldReturnPrincipalLoadedByUsername() {
        ApiOpsPrincipal principal = principal(List.of(new SimpleGrantedAuthority("ROLE_USER")));
        AuthUserRepository repository = username -> Optional.of(principal);
        ApiOpsUserDetailsService service = new ApiOpsUserDetailsService(repository);

        UserDetails loaded = service.loadUserByUsername("alice");

        assertSame(principal, loaded);
        assertEquals("alice", loaded.getUsername());
        assertEquals(1L, ((ApiOpsPrincipal) loaded).getUserId());
    }

    @Test
    void shouldThrowWhenUserDoesNotExist() {
        AuthUserRepository repository = username -> Optional.empty();
        ApiOpsUserDetailsService service = new ApiOpsUserDetailsService(repository);

        assertThrows(
                UsernameNotFoundException.class,
                () -> service.loadUserByUsername("missing")
        );
    }

    @Test
    void shouldNormalizeNullAuthoritiesToEmptyCollection() {
        ApiOpsPrincipal principal = principal(null);

        assertTrue(principal.getAuthorities().isEmpty());
        assertFalse(principal.toString().contains(principal.getPasswordHash()));
    }

    @Test
    void shouldNotRequirePasswordEncoderForLookup() {
        ApiOpsPrincipal principal = principal(List.of());
        ApiOpsUserDetailsService service = new ApiOpsUserDetailsService(
                username -> Optional.of(principal)
        );

        assertSame(principal, service.loadUserByUsername("alice"));
    }

    private ApiOpsPrincipal principal(List<SimpleGrantedAuthority> authorities) {
        return new ApiOpsPrincipal(
                1L,
                "alice",
                "$2a$10$not-a-real-test-hash",
                true,
                authorities
        );
    }
}
