package com.apiops.runner.assertion;

import com.apiops.runner.dsl.AssertionType;
import com.apiops.runner.dsl.HeaderAssertionSpec;
import com.apiops.runner.dsl.HeaderOperator;
import com.apiops.runner.dsl.JsonPathAssertionSpec;
import com.apiops.runner.dsl.JsonPathOperator;
import com.apiops.runner.dsl.ResponseTimeAssertionSpec;
import com.apiops.runner.dsl.StatusCodeAssertionSpec;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AssertionEngineTest {

    private static final AssertionContext RESPONSE =
            new AssertionContext(200, Map.of(), null, 12L);

    @Test
    void evaluatesMatchingStatusCodeAsPassed() {
        AssertionResult result = new StatusCodeAssertionEvaluator()
                .evaluate(new StatusCodeAssertionSpec(200), RESPONSE);

        assertTrue(result.passed());
        assertEquals(200, result.expected());
        assertEquals(200, result.actual());
    }

    @Test
    void returnsFailedResultWhenStatusCodeDoesNotMatch() {
        AssertionResult result = new StatusCodeAssertionEvaluator()
                .evaluate(new StatusCodeAssertionSpec(201), RESPONSE);

        assertFalse(result.passed());
        assertEquals(201, result.expected());
        assertEquals(200, result.actual());
    }

    @Test
    void reportsEvaluatorExecutionErrorAsException() {
        StatusCodeAssertionEvaluator evaluator = new StatusCodeAssertionEvaluator();

        assertThrows(AssertionEvaluationException.class,
                () -> evaluator.evaluate(new StatusCodeAssertionSpec(200), null));
    }

    @Test
    void evaluatesOneAssertionThroughRegistry() {
        AssertionEngine engine = new AssertionEngine(
                new AssertionEvaluatorRegistry(new StatusCodeAssertionEvaluator()));

        List<AssertionResult> results = engine.evaluate(
                List.of(new StatusCodeAssertionSpec(200)), RESPONSE);

        assertEquals(1, results.size());
        assertTrue(results.getFirst().passed());
    }

    @Test
    void preservesInputOrderAndContinuesAfterFailedAssertion() {
        AssertionEngine engine = new AssertionEngine(
                new AssertionEvaluatorRegistry(new StatusCodeAssertionEvaluator()));

        List<AssertionResult> results = engine.evaluate(List.of(
                new StatusCodeAssertionSpec(201),
                new StatusCodeAssertionSpec(200)), RESPONSE);

        assertEquals(2, results.size());
        assertFalse(results.get(0).passed());
        assertTrue(results.get(1).passed());
        assertEquals(201, results.get(0).expected());
        assertEquals(200, results.get(1).expected());
    }

    @Test
    void propagatesEvaluatorExecutionErrorInsteadOfReturningFailedResult() {
        AssertionEvaluationException expected =
                new AssertionEvaluationException("evaluator could not execute");
        AssertionEvaluator<StatusCodeAssertionSpec> failingEvaluator =
                new AssertionEvaluator<>() {
                    @Override
                    public AssertionType supportedType() {
                        return AssertionType.STATUS_CODE;
                    }

                    @Override
                    public AssertionResult evaluate(
                            StatusCodeAssertionSpec assertion,
                            AssertionContext context) {
                        throw expected;
                    }
                };
        AssertionEngine engine = new AssertionEngine(
                new AssertionEvaluatorRegistry(failingEvaluator));

        AssertionEvaluationException actual = assertThrows(
                AssertionEvaluationException.class,
                () -> engine.evaluate(
                        List.of(new StatusCodeAssertionSpec(200)), RESPONSE));

        assertSame(expected, actual);
    }

    @Test
    void evaluatesMixedAssertionsInInputOrder() throws Exception {
        AssertionContext context = new AssertionContext(
                200,
                Map.of("Content-Type", List.of("application/json")),
                new ObjectMapper().readTree("{\"ok\":true}"),
                25L);
        AssertionEngine engine = new AssertionEngine(new AssertionEvaluatorRegistry(
                new StatusCodeAssertionEvaluator(),
                new HeaderAssertionEvaluator(),
                new JsonPathAssertionEvaluator(),
                new ResponseTimeAssertionEvaluator()));

        List<AssertionResult> results = engine.evaluate(List.of(
                new StatusCodeAssertionSpec(200),
                new HeaderAssertionSpec("content-type", HeaderOperator.CONTAINS,
                        "json"),
                new JsonPathAssertionSpec("$.ok", JsonPathOperator.EQUALS,
                        new ObjectMapper().readTree("true")),
                new ResponseTimeAssertionSpec(25)), context);

        assertEquals(List.of(
                AssertionType.STATUS_CODE,
                AssertionType.HEADER,
                AssertionType.JSON_PATH,
                AssertionType.RESPONSE_TIME), results.stream()
                .map(AssertionResult::type)
                .toList());
        assertTrue(results.stream().allMatch(AssertionResult::passed));
    }
}
