package com.apiops.agent.structured;

import com.apiops.runner.dsl.TestCase;
import com.apiops.runner.validation.TestCaseDslValidationException;
import com.apiops.runner.validation.TestCaseDslValidator;
import com.apiops.runner.validation.ValidationError;

import java.util.Objects;

public final class TestCaseCandidateMapper implements StructuredCandidateMapper<TestCase> {

    private final TestCaseDslValidator validator;

    public TestCaseCandidateMapper(TestCaseDslValidator validator) {
        this.validator = Objects.requireNonNull(validator, "validator");
    }

    public TestCase parse(String candidate) {
        try {
            return validator.parse(candidate);
        } catch (TestCaseDslValidationException exception) {
            StructuredOutputFailureType type = exception.result().errors().stream()
                    .anyMatch(error -> "JSON_PARSE_ERROR".equals(error.code()))
                    ? StructuredOutputFailureType.JSON_PARSE
                    : StructuredOutputFailureType.CONTRACT_INVALID;
            throw new StructuredOutputException(type,
                    exception.result().errors().stream()
                            .map(this::describe)
                            .toList());
        }
    }

    private String describe(ValidationError error) {
        return error.path() + " " + error.code();
    }
}
