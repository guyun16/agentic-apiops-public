package com.apiops.tool.gateway;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;

/** Executes a validated diagnostic HTTP request and returns sanitizable data only. */
public final class HttpReadExecutor {
    private final HttpGuard guard;
    private final HttpDiagnosticClient client;

    public HttpReadExecutor(HttpGuard guard, HttpDiagnosticClient client) {
        this.guard = Objects.requireNonNull(guard);
        this.client = Objects.requireNonNull(client);
    }

    public Object execute(ToolExecutionContext context, ToolCallIntent intent) throws Exception {
        HttpGuard.Validation validation = guard.validate(intent);
        if (!validation.allowed()) {
            throw new IllegalStateException("HTTP denied: " + validation.reason());
        }
        HttpDiagnosticClient.Response response = client.send(
                validation.method(), validation.uri(), validation.headers());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", response.status());
        result.put("headers", response.headers());
        result.put("body", response.body());
        return Map.copyOf(result);
    }
}
