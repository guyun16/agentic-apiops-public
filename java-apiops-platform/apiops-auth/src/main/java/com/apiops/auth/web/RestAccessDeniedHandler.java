package com.apiops.auth.web;

import com.apiops.auth.enums.AuthErrorCode;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.web.access.AccessDeniedHandler;

import java.io.IOException;

/** Stable JSON response for an authenticated principal without permission. */
public final class RestAccessDeniedHandler implements AccessDeniedHandler {

    @Override
    public void handle(
            HttpServletRequest request,
            HttpServletResponse response,
            AccessDeniedException accessDeniedException
    ) throws IOException, ServletException {
        RestSecurityResponseWriter.write(
                response,
                HttpServletResponse.SC_FORBIDDEN,
                AuthErrorCode.ACCESS_DENIED
        );
    }
}
