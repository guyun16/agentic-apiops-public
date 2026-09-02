package com.apiops.auth.application;

import com.apiops.auth.dto.LoginRequest;
import com.apiops.auth.exception.AuthenticationFailureException;
import com.apiops.auth.jwt.IssuedAccessToken;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.vo.LoginVO;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;

import java.util.Objects;

public final class AuthenticationService {

    private final AuthenticationManager authenticationManager;
    private final JwtTokenService jwtTokenService;

    public AuthenticationService(
            AuthenticationManager authenticationManager,
            JwtTokenService jwtTokenService
    ) {
        this.authenticationManager = Objects.requireNonNull(
                authenticationManager,
                "authenticationManager must not be null"
        );
        this.jwtTokenService = Objects.requireNonNull(
                jwtTokenService,
                "jwtTokenService must not be null"
        );
    }

    public LoginVO login(LoginRequest request) {
        Objects.requireNonNull(request, "request must not be null");

        Authentication authentication;
        try {
            Authentication unauthenticated = UsernamePasswordAuthenticationToken.unauthenticated(
                    request.getUsername(),
                    request.getPassword()
            );
            authentication = authenticationManager.authenticate(unauthenticated);
        } catch (AuthenticationException exception) {
            throw new AuthenticationFailureException();
        }

        if (!(authentication.getPrincipal() instanceof ApiOpsPrincipal principal)) {
            throw new AuthenticationFailureException();
        }
        IssuedAccessToken issuedToken = jwtTokenService.issueAccessToken(principal);
        return new LoginVO(
                principal.getUserId(),
                principal.getUsername(),
                "Bearer",
                issuedToken.accessToken(),
                issuedToken.expiresAt()
        );
    }
}
