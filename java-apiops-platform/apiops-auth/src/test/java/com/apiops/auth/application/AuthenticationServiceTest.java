package com.apiops.auth.application;

import com.apiops.auth.dto.LoginRequest;
import com.apiops.auth.config.JwtProperties;
import com.apiops.auth.enums.AuthErrorCode;
import com.apiops.auth.exception.AuthenticationFailureException;
import com.apiops.auth.jwt.JwtClaims;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.vo.LoginVO;
import com.apiops.common.enums.ErrorCode;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.DisabledException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.userdetails.UsernameNotFoundException;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentCaptor.forClass;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class AuthenticationServiceTest {

    private static final String ISSUER = "https://auth.apiops.test";
    private static final String SECRET = Base64.getEncoder().encodeToString(
            "authentication-service-jwt-secret-material".getBytes(StandardCharsets.UTF_8)
    );
    private static final Instant FIXED_TIME = Instant.parse("2035-01-01T00:00:00Z");
    private static final Duration TTL = Duration.ofMinutes(15);

    @Test
    void shouldAuthenticateThenIssueJwtFromAuthenticatedPrincipal() {
        AuthenticationManager manager = mock(AuthenticationManager.class);
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                42L, "alice", "$2a$10$not-a-real-test-hash", true, List.of()
        );
        Authentication authenticated = UsernamePasswordAuthenticationToken.authenticated(
                principal, null, List.of()
        );
        when(manager.authenticate(any(Authentication.class))).thenReturn(
                authenticated
        );
        JwtTokenService jwtTokenService = spy(jwtTokenService());

        LoginVO result = new AuthenticationService(manager, jwtTokenService)
                .login(new LoginRequest("alice", "test-password"));

        assertEquals(42L, result.userId());
        assertEquals("alice", result.username());
        assertEquals("Bearer", result.tokenType());
        assertFalse(result.accessToken().isBlank());
        assertNotNull(result.expiresAt());
        JwtClaims claims = jwtTokenService.parseAndValidate(result.accessToken());
        assertEquals(result.expiresAt(), claims.expiresAt());
        assertEquals(42L, claims.userId());
        assertEquals("alice", claims.username());
        verify(jwtTokenService).issueAccessToken(principal);
        var captured = forClass(Authentication.class);
        verify(manager).authenticate(captured.capture());
        assertFalse(captured.getValue().isAuthenticated());
        assertEquals("alice", captured.getValue().getName());
    }

    @Test
    void shouldUseTrustedAuthenticatedPrincipalClaimsInsteadOfLoginRequestUsername() {
        AuthenticationManager manager = mock(AuthenticationManager.class);
        ApiOpsPrincipal trustedPrincipal = new ApiOpsPrincipal(
                42L, "trusted-user", "$2a$10$not-a-real-test-hash", true, List.of()
        );
        Authentication authenticated = UsernamePasswordAuthenticationToken.authenticated(
                trustedPrincipal, null, List.of()
        );
        when(manager.authenticate(any(Authentication.class))).thenReturn(authenticated);
        JwtTokenService jwtTokenService = jwtTokenService();

        LoginVO result = new AuthenticationService(manager, jwtTokenService)
                .login(new LoginRequest("attacker-input", "test-password"));

        JwtClaims claims = jwtTokenService.parseAndValidate(result.accessToken());
        assertEquals("trusted-user", result.username());
        assertEquals("trusted-user", claims.username());
        assertEquals(42L, claims.userId());
    }

    @Test
    void shouldNotMapJwtIssuanceFailureToAuthenticationFailure() {
        AuthenticationManager manager = mock(AuthenticationManager.class);
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                42L, "alice", "$2a$10$not-a-real-test-hash", true, List.of()
        );
        Authentication authenticated = UsernamePasswordAuthenticationToken.authenticated(
                principal, null, List.of()
        );
        when(manager.authenticate(any(Authentication.class))).thenReturn(authenticated);
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        when(jwtTokenService.issueAccessToken(principal))
                .thenThrow(new IllegalStateException("JWT signing failed"));

        IllegalStateException failure = assertThrows(
                IllegalStateException.class,
                () -> new AuthenticationService(manager, jwtTokenService)
                        .login(new LoginRequest("alice", "test-password"))
        );

        assertEquals("JWT signing failed", failure.getMessage());
    }

    @Test
    void shouldMapBadCredentialsToSafeAuthenticationFailure() {
        AuthenticationManager manager = mock(AuthenticationManager.class);
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        when(manager.authenticate(any(Authentication.class)))
                .thenThrow(new BadCredentialsException("provider detail"));

        AuthenticationFailureException failure = assertThrows(
                AuthenticationFailureException.class,
                () -> new AuthenticationService(manager, jwtTokenService)
                        .login(new LoginRequest("alice", "wrong-password"))
        );

        assertEquals(AuthErrorCode.AUTHENTICATION_FAILED, failure.getErrorCode());
        assertEquals("A0003", failure.getErrorCode().getCode());
        assertEquals("authentication failed", failure.getMessage());
        assertFalse(failure.getErrorCode().getCode().equals(ErrorCode.PARAM_INVALID.getCode()));
        assertFalse(failure.getMessage().contains("wrong-password"));
        verifyNoInteractions(jwtTokenService);
    }

    @Test
    void shouldMapMissingUserToSameSafeAuthenticationFailure() {
        AuthenticationManager manager = mock(AuthenticationManager.class);
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        when(manager.authenticate(any(Authentication.class)))
                .thenThrow(new UsernameNotFoundException("internal user lookup detail"));

        AuthenticationFailureException failure = assertThrows(
                AuthenticationFailureException.class,
                () -> new AuthenticationService(manager, jwtTokenService)
                        .login(new LoginRequest("missing", "test-password"))
        );

        assertEquals(AuthErrorCode.AUTHENTICATION_FAILED, failure.getErrorCode());
        assertEquals("A0003", failure.getErrorCode().getCode());
        assertEquals("authentication failed", failure.getMessage());
        assertFalse(failure.getErrorCode().getCode().equals(ErrorCode.PARAM_INVALID.getCode()));
        assertFalse(failure.getMessage().contains("internal user lookup detail"));
        verifyNoInteractions(jwtTokenService);
    }

    @Test
    void shouldMapDisabledAccountToSameSafeAuthenticationFailure() {
        AuthenticationManager manager = mock(AuthenticationManager.class);
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        when(manager.authenticate(any(Authentication.class)))
                .thenThrow(new DisabledException("account disabled detail"));

        AuthenticationFailureException failure = assertThrows(
                AuthenticationFailureException.class,
                () -> new AuthenticationService(manager, jwtTokenService)
                        .login(new LoginRequest("disabled", "test-password"))
        );

        assertEquals(AuthErrorCode.AUTHENTICATION_FAILED, failure.getErrorCode());
        assertEquals("A0003", failure.getErrorCode().getCode());
        assertEquals("authentication failed", failure.getMessage());
        assertFalse(failure.getMessage().contains("account disabled detail"));
        verifyNoInteractions(jwtTokenService);
    }

    @Test
    void shouldKeepLoginRequestPasswordOutOfTextualRepresentation() {
        LoginRequest request = new LoginRequest("alice", "test-password");

        assertFalse(request.toString().contains("test-password"));
        assertTrue(request.toString().contains("alice"));
    }

    private JwtTokenService jwtTokenService() {
        return new JwtTokenService(
                new JwtProperties(ISSUER, TTL, SECRET),
                Clock.fixed(FIXED_TIME, ZoneOffset.UTC)
        );
    }

}
