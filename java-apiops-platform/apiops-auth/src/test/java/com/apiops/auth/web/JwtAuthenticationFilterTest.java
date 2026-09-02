package com.apiops.auth.web;

import com.apiops.auth.config.JwtProperties;
import com.apiops.auth.jwt.JwtClaims;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.repository.GlobalRbacRepository;
import com.apiops.auth.security.ApiOpsPrincipal;
import jakarta.servlet.FilterChain;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.web.AuthenticationEntryPoint;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class JwtAuthenticationFilterTest {

    private static final String ISSUER = "https://auth.apiops.test";
    private static final String SECRET = Base64.getEncoder().encodeToString(
            "jwt-filter-test-secret-material-2026".getBytes(StandardCharsets.UTF_8)
    );
    private static final Duration TTL = Duration.ofMinutes(15);
    private static final Instant NOW = Instant.parse("2035-01-01T00:00:00Z");

    @AfterEach
    void clearSecurityContext() {
        org.springframework.security.core.context.SecurityContextHolder.clearContext();
    }

    @Test
    void shouldContinueWithoutAuthorizationHeaderWithoutParsingToken() throws Exception {
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        GlobalRbacRepository rbacRepository = mock(GlobalRbacRepository.class);
        AuthenticationEntryPoint entryPoint = mock(AuthenticationEntryPoint.class);
        FilterChain chain = mock(FilterChain.class);

        filter(jwtTokenService, userDetailsService, entryPoint)
                .doFilter(
                        new MockHttpServletRequest(),
                        new MockHttpServletResponse(),
                        chain
                );

        verify(chain).doFilter(any(), any());
        verifyNoInteractions(jwtTokenService, userDetailsService, entryPoint);
    }

    @Test
    void shouldContinueForNonBearerAuthorizationHeader() throws Exception {
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        AuthenticationEntryPoint entryPoint = mock(AuthenticationEntryPoint.class);
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("Authorization", "Basic credentials");
        FilterChain chain = mock(FilterChain.class);

        filter(jwtTokenService, userDetailsService, entryPoint)
                .doFilter(request, new MockHttpServletResponse(), chain);

        verify(chain).doFilter(any(), any());
        verifyNoInteractions(jwtTokenService, userDetailsService, entryPoint);
    }

    @Test
    void shouldWriteAuthenticatedPrincipalFromValidToken() throws Exception {
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        GlobalRbacRepository rbacRepository = mock(GlobalRbacRepository.class);
        AuthenticationEntryPoint entryPoint = mock(AuthenticationEntryPoint.class);
        ApiOpsPrincipal principal = principal(
                42L,
                "alice",
                new SimpleGrantedAuthority("ROLE_USER")
        );
        when(jwtTokenService.parseAndValidate("valid-token"))
                .thenReturn(new JwtClaims(42L, "alice", NOW, NOW.plus(TTL)));
        when(userDetailsService.loadUserByUsername("alice")).thenReturn(principal);
        when(rbacRepository.findPermissionCodesByUserId(42L))
                .thenReturn(Set.of("PLATFORM_PROJECT_LIST"));
        FilterChain chain = mock(FilterChain.class);
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("Authorization", "Bearer valid-token");

        filter(jwtTokenService, userDetailsService, rbacRepository, entryPoint)
                .doFilter(request, new MockHttpServletResponse(), chain);

        Authentication authentication = org.springframework.security.core.context.SecurityContextHolder
                .getContext()
                .getAuthentication();
        assertTrue(authentication.isAuthenticated());
        assertSame(principal, authentication.getPrincipal());
        assertNull(authentication.getCredentials());
        assertEquals(List.of(new SimpleGrantedAuthority("PLATFORM_PROJECT_LIST")),
                authentication.getAuthorities());
        verify(chain).doFilter(any(), any());
        verify(jwtTokenService).parseAndValidate("valid-token");
        verify(userDetailsService).loadUserByUsername("alice");
        verify(rbacRepository).findPermissionCodesByUserId(42L);
        verifyNoInteractions(entryPoint);
    }

    @Test
    void shouldRestorePlatformAdminPermissionsWithoutRolePrefix() throws Exception {
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        GlobalRbacRepository rbacRepository = mock(GlobalRbacRepository.class);
        AuthenticationEntryPoint entryPoint = mock(AuthenticationEntryPoint.class);
        ApiOpsPrincipal principal = principal(42L, "alice");
        when(jwtTokenService.parseAndValidate("admin-token"))
                .thenReturn(new JwtClaims(42L, "alice", NOW, NOW.plus(TTL)));
        when(userDetailsService.loadUserByUsername("alice")).thenReturn(principal);
        when(rbacRepository.findPermissionCodesByUserId(42L))
                .thenReturn(Set.of("PLATFORM_PROJECT_CREATE", "PLATFORM_PROJECT_LIST"));
        FilterChain chain = mock(FilterChain.class);
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("Authorization", "Bearer admin-token");

        filter(jwtTokenService, userDetailsService, rbacRepository, entryPoint)
                .doFilter(request, new MockHttpServletResponse(), chain);

        Authentication authentication = org.springframework.security.core.context.SecurityContextHolder
                .getContext()
                .getAuthentication();
        assertEquals(Set.of(
                        new SimpleGrantedAuthority("PLATFORM_PROJECT_CREATE"),
                        new SimpleGrantedAuthority("PLATFORM_PROJECT_LIST")
                ), Set.copyOf(authentication.getAuthorities()));
        assertTrue(authentication.isAuthenticated());
        verify(chain).doFilter(any(), any());
    }

    @Test
    void shouldKeepAuthenticationSuccessfulWhenUserHasNoPermissions() throws Exception {
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        GlobalRbacRepository rbacRepository = mock(GlobalRbacRepository.class);
        AuthenticationEntryPoint entryPoint = mock(AuthenticationEntryPoint.class);
        ApiOpsPrincipal principal = principal(42L, "alice");
        when(jwtTokenService.parseAndValidate("no-permission-token"))
                .thenReturn(new JwtClaims(42L, "alice", NOW, NOW.plus(TTL)));
        when(userDetailsService.loadUserByUsername("alice")).thenReturn(principal);
        when(rbacRepository.findPermissionCodesByUserId(42L)).thenReturn(Set.of());
        FilterChain chain = mock(FilterChain.class);
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("Authorization", "Bearer no-permission-token");

        filter(jwtTokenService, userDetailsService, rbacRepository, entryPoint)
                .doFilter(request, new MockHttpServletResponse(), chain);

        Authentication authentication = org.springframework.security.core.context.SecurityContextHolder
                .getContext()
                .getAuthentication();
        assertTrue(authentication.isAuthenticated());
        assertTrue(authentication.getAuthorities().isEmpty());
        verify(chain).doFilter(any(), any());
    }

    @Test
    void shouldNotFailOpenWhenGlobalRbacRepositoryFails() throws Exception {
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        GlobalRbacRepository rbacRepository = mock(GlobalRbacRepository.class);
        AuthenticationEntryPoint entryPoint = mock(AuthenticationEntryPoint.class);
        ApiOpsPrincipal principal = principal(42L, "alice");
        when(jwtTokenService.parseAndValidate("valid-token"))
                .thenReturn(new JwtClaims(42L, "alice", NOW, NOW.plus(TTL)));
        when(userDetailsService.loadUserByUsername("alice")).thenReturn(principal);
        when(rbacRepository.findPermissionCodesByUserId(42L))
                .thenThrow(new IllegalStateException("RBAC store unavailable"));
        FilterChain chain = mock(FilterChain.class);
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("Authorization", "Bearer valid-token");
        org.springframework.security.core.context.SecurityContextHolder.clearContext();

        assertThrows(
                IllegalStateException.class,
                () -> filter(jwtTokenService, userDetailsService, rbacRepository, entryPoint)
                        .doFilter(request, new MockHttpServletResponse(), chain)
        );

        assertNull(org.springframework.security.core.context.SecurityContextHolder
                .getContext().getAuthentication());
        verify(chain, never()).doFilter(any(), any());
        verifyNoInteractions(entryPoint);
    }

    @Test
    void shouldExposeEachPermissionAsOneAuthority() throws Exception {
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        GlobalRbacRepository rbacRepository = mock(GlobalRbacRepository.class);
        AuthenticationEntryPoint entryPoint = mock(AuthenticationEntryPoint.class);
        ApiOpsPrincipal principal = principal(42L, "alice");
        when(jwtTokenService.parseAndValidate("deduplicated-token"))
                .thenReturn(new JwtClaims(42L, "alice", NOW, NOW.plus(TTL)));
        when(userDetailsService.loadUserByUsername("alice")).thenReturn(principal);
        when(rbacRepository.findPermissionCodesByUserId(42L)).thenReturn(
                new LinkedHashSet<>(List.of(
                        "PLATFORM_PROJECT_LIST",
                        "PLATFORM_PROJECT_CREATE"
                ))
        );
        FilterChain chain = mock(FilterChain.class);
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("Authorization", "Bearer deduplicated-token");

        filter(jwtTokenService, userDetailsService, rbacRepository, entryPoint)
                .doFilter(request, new MockHttpServletResponse(), chain);

        Authentication authentication = org.springframework.security.core.context.SecurityContextHolder
                .getContext()
                .getAuthentication();
        assertEquals(2, authentication.getAuthorities().size());
        assertEquals(Set.of(
                        new SimpleGrantedAuthority("PLATFORM_PROJECT_CREATE"),
                        new SimpleGrantedAuthority("PLATFORM_PROJECT_LIST")
                ), Set.copyOf(authentication.getAuthorities()));
    }

    @Test
    void shouldRejectEmptyBearerTokenAndStopChain() throws Exception {
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        AuthenticationEntryPoint entryPoint = mock(AuthenticationEntryPoint.class);
        FilterChain chain = mock(FilterChain.class);
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("Authorization", "Bearer ");

        filter(jwtTokenService, userDetailsService, entryPoint)
                .doFilter(request, new MockHttpServletResponse(), chain);

        verify(entryPoint).commence(any(), any(), any());
        verify(chain, never()).doFilter(any(), any());
        verifyNoInteractions(jwtTokenService, userDetailsService);
        assertNull(org.springframework.security.core.context.SecurityContextHolder
                .getContext().getAuthentication());
    }

    @Test
    void shouldRejectMalformedTokenClearContextAndStopChain() throws Exception {
        AuthenticationEntryPoint entryPoint = mock(AuthenticationEntryPoint.class);
        FilterChain chain = mock(FilterChain.class);
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("Authorization", "Bearer not-a-jwt");
        org.springframework.security.core.context.SecurityContextHolder.getContext()
                .setAuthentication(UsernamePasswordAuthenticationToken.unauthenticated(
                        "pending", null
                ));

        filter(jwtTokenService(Clock.fixed(NOW, ZoneOffset.UTC)),
                mock(UserDetailsService.class), entryPoint)
                .doFilter(request, new MockHttpServletResponse(), chain);

        verify(entryPoint).commence(any(), any(), any());
        verify(chain, never()).doFilter(any(), any());
        assertNull(org.springframework.security.core.context.SecurityContextHolder
                .getContext().getAuthentication());
    }

    @Test
    void shouldRejectExpiredTokenThroughJwtServiceAndStopChain() throws Exception {
        JwtTokenService issuingService = jwtTokenService(
                Clock.fixed(Instant.parse("2020-01-01T00:00:00Z"), ZoneOffset.UTC)
        );
        JwtTokenService validatingService = jwtTokenService(Clock.fixed(NOW, ZoneOffset.UTC));
        String expiredToken = issuingService.generateAccessToken(principal(42L, "alice"));
        AuthenticationEntryPoint entryPoint = mock(AuthenticationEntryPoint.class);
        FilterChain chain = mock(FilterChain.class);
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("Authorization", "Bearer " + expiredToken);

        filter(validatingService, mock(UserDetailsService.class), entryPoint)
                .doFilter(request, new MockHttpServletResponse(), chain);

        verify(entryPoint).commence(any(), any(), any());
        verify(chain, never()).doFilter(any(), any());
        assertNull(org.springframework.security.core.context.SecurityContextHolder
                .getContext().getAuthentication());
    }

    @Test
    void shouldNotOverwriteExistingAuthenticatedIdentity() throws Exception {
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        AuthenticationEntryPoint entryPoint = mock(AuthenticationEntryPoint.class);
        Authentication existing = UsernamePasswordAuthenticationToken.authenticated(
                principal(7L, "existing"), null, List.of()
        );
        org.springframework.security.core.context.SecurityContextHolder.getContext()
                .setAuthentication(existing);
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("Authorization", "Bearer invalid-token");
        FilterChain chain = new MockFilterChain();

        filter(jwtTokenService, userDetailsService, entryPoint)
                .doFilter(request, new MockHttpServletResponse(), chain);

        assertSame(existing, org.springframework.security.core.context.SecurityContextHolder
                .getContext().getAuthentication());
        verifyNoInteractions(jwtTokenService, userDetailsService, entryPoint);
    }

    @Test
    void shouldRestoreBearerIdentityWhenContextContainsAnonymousAuthentication() throws Exception {
        JwtTokenService jwtTokenService = mock(JwtTokenService.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        AuthenticationEntryPoint entryPoint = mock(AuthenticationEntryPoint.class);
        ApiOpsPrincipal principal = principal(42L, "alice");
        when(jwtTokenService.parseAndValidate("valid-token"))
                .thenReturn(new JwtClaims(42L, "alice", NOW, NOW.plus(TTL)));
        when(userDetailsService.loadUserByUsername("alice")).thenReturn(principal);
        org.springframework.security.core.context.SecurityContextHolder.getContext()
                .setAuthentication(new AnonymousAuthenticationToken(
                        "test-key",
                        "anonymousUser",
                        List.of(new SimpleGrantedAuthority("ROLE_ANONYMOUS"))
                ));
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("Authorization", "Bearer valid-token");
        FilterChain chain = mock(FilterChain.class);

        filter(jwtTokenService, userDetailsService, entryPoint)
                .doFilter(request, new MockHttpServletResponse(), chain);

        Authentication authentication = org.springframework.security.core.context.SecurityContextHolder
                .getContext()
                .getAuthentication();
        assertSame(principal, authentication.getPrincipal());
        verify(jwtTokenService).parseAndValidate("valid-token");
        verify(userDetailsService).loadUserByUsername("alice");
        verify(chain).doFilter(any(), any());
        verifyNoInteractions(entryPoint);
    }

    private JwtAuthenticationFilter filter(
            JwtTokenService jwtTokenService,
            UserDetailsService userDetailsService,
            AuthenticationEntryPoint entryPoint
    ) {
        return filter(
                jwtTokenService,
                userDetailsService,
                mock(GlobalRbacRepository.class),
                entryPoint
        );
    }

    private JwtAuthenticationFilter filter(
            JwtTokenService jwtTokenService,
            UserDetailsService userDetailsService,
            GlobalRbacRepository globalRbacRepository,
            AuthenticationEntryPoint entryPoint
    ) {
        return new JwtAuthenticationFilter(
                jwtTokenService,
                userDetailsService,
                globalRbacRepository,
                entryPoint
        );
    }

    private JwtTokenService jwtTokenService(Clock clock) {
        return new JwtTokenService(new JwtProperties(ISSUER, TTL, SECRET), clock);
    }

    private ApiOpsPrincipal principal(Long userId, String username,
                                      org.springframework.security.core.GrantedAuthority... authorities) {
        return new ApiOpsPrincipal(userId, username, "test-password-hash", true,
                List.of(authorities));
    }
}
