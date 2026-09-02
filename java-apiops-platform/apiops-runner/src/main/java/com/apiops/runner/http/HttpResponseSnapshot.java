package com.apiops.runner.http;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

public record HttpResponseSnapshot(
        int statusCode,
        Map<String, List<String>> headers,
        String body,
        long durationMs
) {
    public HttpResponseSnapshot {
        if (durationMs < 0) {
            throw new IllegalArgumentException("durationMs must not be negative");
        }
        headers = copyHeaders(headers);
    }

    private static Map<String, List<String>> copyHeaders(Map<String, List<String>> source) {
        if (source == null || source.isEmpty()) {
            return Map.of();
        }
        Map<String, List<String>> copy = new TreeMap<>(String.CASE_INSENSITIVE_ORDER);
        source.forEach((name, values) -> copy.put(
                name, Collections.unmodifiableList(new ArrayList<>(values))));
        return Collections.unmodifiableMap(copy);
    }
}
