package com.apiops.runner.assertion;

import com.apiops.runner.dsl.AssertionType;
import com.apiops.runner.dsl.ResponseTimeAssertionSpec;

public final class ResponseTimeAssertionEvaluator
        implements AssertionEvaluator<ResponseTimeAssertionSpec> {

    @Override
    public AssertionType supportedType() {
        return AssertionType.RESPONSE_TIME;
    }

    @Override
    public AssertionResult evaluate(
            ResponseTimeAssertionSpec assertion,
            AssertionContext context) {
        if (assertion == null || context == null) {
            throw new AssertionEvaluationException(
                    "Response time assertion requires an assertion and response context");
        }

        long actual = context.durationMs();
        int expected = assertion.maxMs();
        boolean passed = actual <= expected;
        return new AssertionResult(
                AssertionType.RESPONSE_TIME,
                passed,
                expected,
                actual,
                passed
                        ? "Response time is within limit: " + actual + "ms"
                        : "Response time exceeded limit: " + actual + "ms");
    }
}
