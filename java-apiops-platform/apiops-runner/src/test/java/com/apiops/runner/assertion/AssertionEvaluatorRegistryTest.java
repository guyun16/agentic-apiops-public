package com.apiops.runner.assertion;

import com.apiops.runner.dsl.AssertionType;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class AssertionEvaluatorRegistryTest {

    @Test
    void looksUpStatusCodeEvaluatorByType() {
        StatusCodeAssertionEvaluator evaluator = new StatusCodeAssertionEvaluator();
        AssertionEvaluatorRegistry registry = new AssertionEvaluatorRegistry(evaluator);

        assertEquals(evaluator, registry.lookup(AssertionType.STATUS_CODE));
    }

    @Test
    void failsWhenTypeIsNotRegistered() {
        AssertionEvaluatorRegistry registry =
                new AssertionEvaluatorRegistry(new StatusCodeAssertionEvaluator());

        assertThrows(AssertionEvaluatorRegistryException.class,
                () -> registry.lookup(AssertionType.HEADER));
    }

    @Test
    void failsWhenTypeIsRegisteredMoreThanOnce() {
        assertThrows(AssertionEvaluatorRegistryException.class,
                () -> new AssertionEvaluatorRegistry(
                        new StatusCodeAssertionEvaluator(),
                        new StatusCodeAssertionEvaluator()));
    }
}
