package com.apiops.runner.assertion;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** Facts already collected from a response; it does not execute a request. */
public record AssertionContext(
        int statusCode,
        Map<String, List<String>> headers,
        JsonNode body,
        long durationMs
) {
    public AssertionContext {
        Objects.requireNonNull(headers, "headers must not be null");
        Map<String, List<String>> copiedHeaders = new LinkedHashMap<>();
        headers.forEach((name, values) -> copiedHeaders.put(
                Objects.requireNonNull(name, "header name must not be null"),
                List.copyOf(Objects.requireNonNull(values, "header values must not be null"))));
        headers = Map.copyOf(copiedHeaders);
    }
}
