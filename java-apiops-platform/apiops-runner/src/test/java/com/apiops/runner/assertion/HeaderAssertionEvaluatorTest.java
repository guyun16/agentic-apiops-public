package com.apiops.runner.assertion;

import com.apiops.runner.dsl.HeaderAssertionSpec;
import com.apiops.runner.dsl.HeaderOperator;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HeaderAssertionEvaluatorTest {

    private final HeaderAssertionEvaluator evaluator = new HeaderAssertionEvaluator();

    @Test
    void equalsPassesForExactHeaderNameAndValue() {
        AssertionResult result = evaluator.evaluate(
                new HeaderAssertionSpec("Content-Type", HeaderOperator.EQUALS,
                        "application/json"),
                context(Map.of("Content-Type", List.of("application/json"))));

        assertTrue(result.passed());
    }

    @Test
    void headerNameComparisonIsCaseInsensitive() {
        AssertionResult result = evaluator.evaluate(
                new HeaderAssertionSpec("content-type", HeaderOperator.EQUALS,
                        "application/json"),
                context(Map.of("Content-Type", List.of("application/json"))));

        assertTrue(result.passed());
    }

    @Test
    void missingHeaderReturnsFailedResult() {
        AssertionResult result = evaluator.evaluate(
                new HeaderAssertionSpec("X-Missing", HeaderOperator.EQUALS, "value"),
                context(Map.of("X-Other", List.of("value"))));

        assertFalse(result.passed());
    }

    @Test
    void equalsFailsWhenNoValueEqualsExpected() {
        AssertionResult result = evaluator.evaluate(
                new HeaderAssertionSpec("X-Mode", HeaderOperator.EQUALS, "strict"),
                context(Map.of("X-Mode", List.of("safe", "relaxed"))));

        assertFalse(result.passed());
    }

    @Test
    void containsPassesWhenAnyValueContainsExpected() {
        AssertionResult result = evaluator.evaluate(
                new HeaderAssertionSpec("X-Mode", HeaderOperator.CONTAINS, "rel"),
                context(Map.of("X-Mode", List.of("safe", "relaxed"))));

        assertTrue(result.passed());
    }

    @Test
    void containsFailsWhenNoValueContainsExpected() {
        AssertionResult result = evaluator.evaluate(
                new HeaderAssertionSpec("X-Mode", HeaderOperator.CONTAINS, "strict"),
                context(Map.of("X-Mode", List.of("safe", "relaxed"))));

        assertFalse(result.passed());
    }

    @Test
    void multiValueHeaderEqualsPassesOnAnyValue() {
        AssertionResult result = evaluator.evaluate(
                new HeaderAssertionSpec("Set-Cookie", HeaderOperator.EQUALS, "b=2"),
                context(Map.of("Set-Cookie", List.of("a=1", "b=2"))));

        assertTrue(result.passed());
    }

    private AssertionContext context(Map<String, List<String>> headers) {
        return new AssertionContext(200, headers, null, 10L);
    }
}
