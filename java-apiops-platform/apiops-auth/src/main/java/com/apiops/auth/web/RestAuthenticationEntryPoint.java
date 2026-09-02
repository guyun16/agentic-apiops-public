package com.apiops.auth.web;

import com.apiops.auth.enums.AuthErrorCode;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.web.AuthenticationEntryPoint;

import java.io.IOException;

/** Stable JSON response for requests without an acceptable authentication. */
public final class RestAuthenticationEntryPoint implements AuthenticationEntryPoint {

    @Override
    public void commence(
            HttpServletRequest request,
            HttpServletResponse response,
            AuthenticationException authException
    ) throws IOException, ServletException {
        RestSecurityResponseWriter.write(
                response,
                HttpServletResponse.SC_UNAUTHORIZED,
                AuthErrorCode.AUTHENTICATION_REQUIRED
        );
    }
}
