package com.apiops.demo.order.order.controller;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.util.UrlPathHelper;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** Authentication precedes request binding and cannot change ordinary order requests. */
@Component
@Profile("local")
public class BenchmarkOrderAuthFilter extends OncePerRequestFilter {
    private final String apiKey;

    public BenchmarkOrderAuthFilter(@Value("${apiops.benchmark.order-api-key:}") String apiKey) {
        this.apiKey = apiKey;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !"POST".equals(request.getMethod())
                || !"/stage21/auth-check".equals(new UrlPathHelper().getPathWithinApplication(request));
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
            FilterChain chain) throws ServletException, IOException {
        String supplied = request.getHeader("Authorization");
        if (apiKey.isBlank() || supplied == null || !MessageDigest.isEqual(
                apiKey.getBytes(StandardCharsets.UTF_8), supplied.getBytes(StandardCharsets.UTF_8))) {
            response.setStatus(401);
            response.setContentType("application/json");
            response.getWriter().write("{\"success\":false,\"code\":\"AUTH_UNAUTHORIZED\",\"message\":\"API key required\",\"data\":null}");
            return;
        }
        chain.doFilter(request, response);
    }
}
