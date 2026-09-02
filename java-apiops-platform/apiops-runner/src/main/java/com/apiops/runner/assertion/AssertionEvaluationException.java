package com.apiops.runner.assertion;

public class AssertionEvaluationException extends RuntimeException {

    public AssertionEvaluationException(String message) {
        super(message);
    }

    public AssertionEvaluationException(String message, Throwable cause) {
        super(message, cause);
    }
}
