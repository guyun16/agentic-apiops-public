package com.apiops.runner.assertion;

import com.apiops.runner.dsl.AssertionType;
import com.apiops.runner.dsl.StatusCodeAssertionSpec;

public final class StatusCodeAssertionEvaluator
        implements AssertionEvaluator<StatusCodeAssertionSpec> {

    @Override
    public AssertionType supportedType() {
        return AssertionType.STATUS_CODE;
    }

    @Override
    public AssertionResult evaluate(
            StatusCodeAssertionSpec assertion,
            AssertionContext context) {
        if (assertion == null || context == null) {
            throw new AssertionEvaluationException(
                    "Status code assertion requires an assertion and response context");
        }

        int expected = assertion.expected();
        int actual = context.statusCode();
        boolean passed = expected == actual;
        String message = passed
                ? "Status code matched expected value: " + expected
                : "Expected status code " + expected + " but was " + actual;
        return new AssertionResult(
                AssertionType.STATUS_CODE, passed, expected, actual, message);
    }
}
