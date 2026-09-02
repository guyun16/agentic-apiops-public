package com.apiops.agent.structured;

import java.util.List;

public final class StructuredOutputException extends RuntimeException {

    private final StructuredOutputFailureType failureType;
    private final List<String> errors;

    public StructuredOutputException(
            StructuredOutputFailureType failureType, List<String> errors) {
        super("Candidate structured output is invalid: " + failureType);
        this.failureType = failureType;
        this.errors = List.copyOf(errors);
    }

    public StructuredOutputFailureType failureType() {
        return failureType;
    }

    public List<String> errors() {
        return errors;
    }
}
