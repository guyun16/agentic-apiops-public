package com.apiops.auth.web;

import com.apiops.auth.enums.AuthErrorCode;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.MediaType;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

final class RestSecurityResponseWriter {

    private RestSecurityResponseWriter() {
    }

    static void write(
            HttpServletResponse response,
            int status,
            AuthErrorCode errorCode
    ) throws IOException {
        response.setStatus(status);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.getWriter().write("{\"success\":false,\"code\":\""
                + errorCode.getCode()
                + "\",\"message\":\""
                + errorCode.getMessage()
                + "\",\"data\":null}");
    }
}
