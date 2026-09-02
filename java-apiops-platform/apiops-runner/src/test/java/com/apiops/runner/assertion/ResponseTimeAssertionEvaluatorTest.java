package com.apiops.runner.assertion;

import com.apiops.runner.dsl.ResponseTimeAssertionSpec;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ResponseTimeAssertionEvaluatorTest {

    private final ResponseTimeAssertionEvaluator evaluator =
            new ResponseTimeAssertionEvaluator();

    @Test
    void durationBelowMaximumPasses() {
        assertTrue(evaluator.evaluate(
                new ResponseTimeAssertionSpec(100), context(99L)).passed());
    }

    @Test
    void durationEqualToMaximumPasses() {
        assertTrue(evaluator.evaluate(
                new ResponseTimeAssertionSpec(100), context(100L)).passed());
    }

    @Test
    void durationAboveMaximumFails() {
        assertFalse(evaluator.evaluate(
                new ResponseTimeAssertionSpec(100), context(101L)).passed());
    }

    private AssertionContext context(long durationMs) {
        return new AssertionContext(200, Map.of(), null, durationMs);
    }
}
