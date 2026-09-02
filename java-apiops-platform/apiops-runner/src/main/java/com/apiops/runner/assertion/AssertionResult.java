package com.apiops.runner.assertion;

import com.apiops.runner.dsl.AssertionType;

import java.util.Objects;

public record AssertionResult(
        AssertionType type,
        boolean passed,
        Object expected,
        Object actual,
        String message
) {
    public AssertionResult {
        Objects.requireNonNull(type, "type must not be null");
        Objects.requireNonNull(message, "message must not be null");
    }
}
