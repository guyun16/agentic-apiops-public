package com.apiops.runner.validation;

public final class TestCaseDslValidationException extends RuntimeException {

    private final ValidationResult result;

    public TestCaseDslValidationException(ValidationResult result) {
        super(message(result));
        this.result = result;
    }

    public ValidationResult result() {
        return result;
    }

    private static String message(ValidationResult result) {
        return result.errors().stream()
                .map(ValidationError::message)
                .findFirst()
                .orElse("TestCase DSL validation failed");
    }
}
