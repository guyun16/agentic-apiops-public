package com.apiops.web.infrastructure.web;

import com.apiops.web.config.ApiOpsProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

@Component
public class TraceIdFilter extends OncePerRequestFilter {

    static final String TRACE_ID = "traceId";
    static final String REQUEST_ID = "requestId";

    private final ApiOpsProperties apiOpsProperties;

    public TraceIdFilter(ApiOpsProperties apiOpsProperties) {
        this.apiOpsProperties = apiOpsProperties;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        String headerName = apiOpsProperties.tracing().headerName();
        String traceId = resolveOrGenerateTraceId(request.getHeader(headerName));
        String requestId = generateId();

        response.setHeader(headerName, traceId);
        response.setHeader("X-Request-Id", requestId);
        MDC.put(TRACE_ID, traceId);
        MDC.put(REQUEST_ID, requestId);

        try {
            filterChain.doFilter(request, response);
        } finally {
            MDC.remove(TRACE_ID);
            MDC.remove(REQUEST_ID);
        }
    }

    private String resolveOrGenerateTraceId(String incomingTraceId) {
        if (incomingTraceId == null || incomingTraceId.isBlank()) {
            return generateId();
        }
        return incomingTraceId;
    }

    private String generateId() {
        return UUID.randomUUID().toString();
    }
}
