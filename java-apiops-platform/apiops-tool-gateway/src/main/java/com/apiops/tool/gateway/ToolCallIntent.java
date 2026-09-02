package com.apiops.tool.gateway;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;

/** Model output for one tool choice; trusted identity stays outside this object. */
public record ToolCallIntent(String toolName, Map<String, Object> arguments) {

    public ToolCallIntent {
        toolName = requireText(toolName, "toolName");
        Objects.requireNonNull(arguments, "arguments must not be null");
        arguments = Collections.unmodifiableMap(new LinkedHashMap<>(arguments));
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
