package com.apiops.runner.execution;

import com.apiops.runner.assertion.AssertionContext;
import com.apiops.runner.http.HttpResponseSnapshot;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.TextNode;

import java.util.Objects;

public final class AssertionContextMapper {

    private final ObjectMapper objectMapper;

    public AssertionContextMapper() {
        this(new ObjectMapper());
    }

    public AssertionContextMapper(ObjectMapper objectMapper) {
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
    }

    public AssertionContext map(HttpResponseSnapshot snapshot) {
        Objects.requireNonNull(snapshot, "snapshot must not be null");
        return new AssertionContext(
                snapshot.statusCode(),
                snapshot.headers(),
                parseBody(snapshot.body()),
                snapshot.durationMs());
    }

    private JsonNode parseBody(String body) {
        if (body == null || body.isBlank()) {
            return null;
        }
        try {
            JsonNode parsed = objectMapper.readTree(body);
            return parsed == null ? null : parsed;
        } catch (JsonProcessingException exception) {
            // Keep non-JSON response facts available to status/header assertions.
            // JSONPath evaluation will classify the textual body as an evaluation error.
            return TextNode.valueOf(body);
        }
    }
}
