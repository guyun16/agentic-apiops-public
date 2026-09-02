package com.apiops.runner.assertion;

import com.apiops.runner.dsl.JsonPathAssertionSpec;
import com.apiops.runner.dsl.JsonPathOperator;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.DecimalNode;
import com.fasterxml.jackson.databind.node.IntNode;
import com.fasterxml.jackson.databind.node.LongNode;
import com.fasterxml.jackson.databind.node.TextNode;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class JsonPathAssertionEvaluatorTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private final JsonPathAssertionEvaluator evaluator = new JsonPathAssertionEvaluator();

    @Test
    void equalsPassesAndFailsForStringValues() throws Exception {
        JsonNode body = MAPPER.readTree("{\"code\":\"OK\"}");

        assertTrue(evaluator.evaluate(
                new JsonPathAssertionSpec("$.code", JsonPathOperator.EQUALS,
                        TextNode.valueOf("OK")), context(body)).passed());
        assertFalse(evaluator.evaluate(
                new JsonPathAssertionSpec("$.code", JsonPathOperator.EQUALS,
                        TextNode.valueOf("NO")), context(body)).passed());
    }

    @Test
    void equalsUsesNumericValueRatherThanNumberClass() throws Exception {
        JsonNode body = MAPPER.readTree("{\"value\":100.0}");
        List<JsonNode> equivalentNumbers = List.of(
                IntNode.valueOf(100),
                LongNode.valueOf(100L),
                DecimalNode.valueOf(new BigDecimal("100.00")));

        for (JsonNode expected : equivalentNumbers) {
            assertTrue(evaluator.evaluate(
                    new JsonPathAssertionSpec("$.value", JsonPathOperator.EQUALS,
                            expected), context(body)).passed());
        }
    }

    @Test
    void numberDoesNotEqualString() throws Exception {
        AssertionResult result = evaluator.evaluate(
                new JsonPathAssertionSpec("$.value", JsonPathOperator.EQUALS,
                        TextNode.valueOf("100")),
                context(MAPPER.readTree("{\"value\":100}")));

        assertFalse(result.passed());
    }

    @Test
    void existsPassesForPresentField() throws Exception {
        AssertionResult result = evaluator.evaluate(
                new JsonPathAssertionSpec("$.value", JsonPathOperator.EXISTS, null),
                context(MAPPER.readTree("{\"value\":\"present\"}")));

        assertTrue(result.passed());
    }

    @Test
    void existsPassesWhenPresentValueIsNull() throws Exception {
        AssertionResult result = evaluator.evaluate(
                new JsonPathAssertionSpec("$.value", JsonPathOperator.EXISTS, null),
                context(MAPPER.readTree("{\"value\":null}")));

        assertTrue(result.passed());
    }

    @Test
    void missingPathReturnsFailedResult() throws Exception {
        AssertionResult result = evaluator.evaluate(
                new JsonPathAssertionSpec("$.missing", JsonPathOperator.EXISTS, null),
                context(MAPPER.readTree("{\"value\":1}")));

        assertFalse(result.passed());
    }

    @Test
    void missingPathEqualsReturnsFailedResult() throws Exception {
        AssertionResult result = evaluator.evaluate(
                new JsonPathAssertionSpec("$.missing", JsonPathOperator.EQUALS,
                        IntNode.valueOf(1)),
                context(MAPPER.readTree("{\"value\":1}")));

        assertFalse(result.passed());
    }

    @Test
    void invalidExpressionIsAnEvaluationError() throws Exception {
        assertThrows(AssertionEvaluationException.class, () -> evaluator.evaluate(
                new JsonPathAssertionSpec("$[", JsonPathOperator.EXISTS, null),
                context(MAPPER.readTree("{\"value\":1}"))));
    }

    @Test
    void nonJsonResponseBodyIsAnEvaluationError() {
        assertThrows(AssertionEvaluationException.class, () -> evaluator.evaluate(
                new JsonPathAssertionSpec("$.value", JsonPathOperator.EXISTS, null),
                context(TextNode.valueOf("not-json"))));
    }

    private AssertionContext context(JsonNode body) {
        return new AssertionContext(200, Map.of(), body, 10L);
    }
}
