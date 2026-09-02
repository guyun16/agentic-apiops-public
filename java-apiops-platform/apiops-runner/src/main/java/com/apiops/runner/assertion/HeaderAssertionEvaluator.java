package com.apiops.runner.assertion;

import com.apiops.runner.dsl.AssertionType;
import com.apiops.runner.dsl.HeaderAssertionSpec;
import com.apiops.runner.dsl.HeaderOperator;

import java.util.List;
import java.util.Map;

public final class HeaderAssertionEvaluator
        implements AssertionEvaluator<HeaderAssertionSpec> {

    @Override
    public AssertionType supportedType() {
        return AssertionType.HEADER;
    }

    @Override
    public AssertionResult evaluate(
            HeaderAssertionSpec assertion,
            AssertionContext context) {
        if (assertion == null || context == null) {
            throw new AssertionEvaluationException(
                    "Header assertion requires an assertion and response context");
        }

        List<String> actualValues = context.headers().entrySet().stream()
                .filter(entry -> entry.getKey().equalsIgnoreCase(assertion.name()))
                .map(Map.Entry::getValue)
                .flatMap(List::stream)
                .toList();
        boolean passed = switch (assertion.operator()) {
            case EQUALS -> actualValues.stream().anyMatch(assertion.expected()::equals);
            case CONTAINS -> actualValues.stream().anyMatch(
                    value -> value.contains(assertion.expected()));
        };
        String message = passed
                ? "Header assertion matched: " + assertion.name()
                : "Header assertion did not match: " + assertion.name();
        return new AssertionResult(
                AssertionType.HEADER,
                passed,
                assertion.expected(),
                actualValues,
                message);
    }
}
