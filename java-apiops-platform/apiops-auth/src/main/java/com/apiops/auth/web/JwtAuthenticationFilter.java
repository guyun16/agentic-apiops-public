package com.apiops.auth.web;

import com.apiops.auth.jwt.JwtClaims;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.repository.GlobalRbacRepository;
import com.apiops.auth.security.ApiOpsPrincipal;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.context.SecurityContextHolderStrategy;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Collection;
import java.util.Objects;

/** Restores the authenticated principal from a validated Bearer JWT. */
public final class JwtAuthenticationFilter extends OncePerRequestFilter {

    private static final String BEARER_SCHEME = "Bearer";

    private final JwtTokenService jwtTokenService;
    private final UserDetailsService userDetailsService;
    private final GlobalRbacRepository globalRbacRepository;
    private final AuthenticationEntryPoint authenticationEntryPoint;
    private final SecurityContextHolderStrategy securityContextHolderStrategy =
            SecurityContextHolder.getContextHolderStrategy();

    public JwtAuthenticationFilter(
            JwtTokenService jwtTokenService,
            UserDetailsService userDetailsService,
            AuthenticationEntryPoint authenticationEntryPoint
    ) {
        this(jwtTokenService, userDetailsService, null, authenticationEntryPoint);
    }

    public JwtAuthenticationFilter(
            JwtTokenService jwtTokenService,
            UserDetailsService userDetailsService,
            GlobalRbacRepository globalRbacRepository,
            AuthenticationEntryPoint authenticationEntryPoint
    ) {
        this.jwtTokenService = Objects.requireNonNull(
                jwtTokenService,
                "jwtTokenService must not be null"
        );
        this.userDetailsService = Objects.requireNonNull(
                userDetailsService,
                "userDetailsService must not be null"
        );
        this.globalRbacRepository = globalRbacRepository;
        this.authenticationEntryPoint = Objects.requireNonNull(
                authenticationEntryPoint,
                "authenticationEntryPoint must not be null"
        );
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        if (hasExistingAuthenticatedIdentity()) {
            filterChain.doFilter(request, response);
            return;
        }

        String authorization = request.getHeader("Authorization");
        if (authorization == null || !authorization.startsWith(BEARER_SCHEME)) {
            filterChain.doFilter(request, response);
            return;
        }
        if (!authorization.equals(BEARER_SCHEME)
                && !authorization.startsWith(BEARER_SCHEME + " ")) {
            filterChain.doFilter(request, response);
            return;
        }

        String token = authorization.substring(BEARER_SCHEME.length()).trim();
        if (token.isEmpty()) {
            reject(request, response, new BadCredentialsException("Invalid bearer token"));
            return;
        }

        try {
            JwtClaims claims = jwtTokenService.parseAndValidate(token);
            ApiOpsPrincipal principal = loadCurrentPrincipal(claims);
            Collection<SimpleGrantedAuthority> authorities = loadAuthorities(principal);
            Authentication authentication =
                    org.springframework.security.authentication.UsernamePasswordAuthenticationToken
                            .authenticated(principal, null, authorities);
            SecurityContext context = securityContextHolderStrategy.createEmptyContext();
            context.setAuthentication(authentication);
            securityContextHolderStrategy.setContext(context);
            filterChain.doFilter(request, response);
        } catch (JwtTokenService.JwtTokenValidationException exception) {
            reject(request, response, new BadCredentialsException("Invalid bearer token"));
        } catch (AuthenticationException exception) {
            reject(request, response, exception);
        }
    }

    private ApiOpsPrincipal loadCurrentPrincipal(JwtClaims claims) {
        UserDetails userDetails = userDetailsService.loadUserByUsername(claims.username());
        if (!(userDetails instanceof ApiOpsPrincipal principal)
                || principal.getUserId() != claims.userId()
                || !principal.isEnabled()) {
            throw new BadCredentialsException("Invalid bearer authentication");
        }
        return principal;
    }

    private Collection<SimpleGrantedAuthority> loadAuthorities(ApiOpsPrincipal principal) {
        if (globalRbacRepository == null) {
            return principal.getAuthorities().stream()
                    .map(authority -> new SimpleGrantedAuthority(authority.getAuthority()))
                    .toList();
        }
        return globalRbacRepository.findPermissionCodesByUserId(principal.getUserId()).stream()
                .map(SimpleGrantedAuthority::new)
                .toList();
    }

    private boolean hasExistingAuthenticatedIdentity() {
        Authentication authentication = securityContextHolderStrategy
                .getContext()
                .getAuthentication();
        return authentication != null
                && authentication.isAuthenticated()
                && !(authentication instanceof AnonymousAuthenticationToken);
    }

    private void reject(
            HttpServletRequest request,
            HttpServletResponse response,
            AuthenticationException exception
    ) throws IOException, ServletException {
        securityContextHolderStrategy.clearContext();
        authenticationEntryPoint.commence(request, response, exception);
    }
}
