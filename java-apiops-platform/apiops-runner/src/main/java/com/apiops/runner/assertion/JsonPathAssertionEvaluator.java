package com.apiops.runner.assertion;

import com.apiops.runner.dsl.AssertionType;
import com.apiops.runner.dsl.JsonPathAssertionSpec;
import com.apiops.runner.dsl.JsonPathOperator;
import com.fasterxml.jackson.databind.JsonNode;
import com.jayway.jsonpath.Configuration;
import com.jayway.jsonpath.JsonPath;
import com.jayway.jsonpath.JsonPathException;
import com.jayway.jsonpath.PathNotFoundException;
import com.jayway.jsonpath.spi.json.JacksonJsonNodeJsonProvider;

import java.math.BigDecimal;

public final class JsonPathAssertionEvaluator
        implements AssertionEvaluator<JsonPathAssertionSpec> {

    private final Configuration configuration = Configuration.builder()
            .jsonProvider(new JacksonJsonNodeJsonProvider())
            .build();

    @Override
    public AssertionType supportedType() {
        return AssertionType.JSON_PATH;
    }

    @Override
    public AssertionResult evaluate(
            JsonPathAssertionSpec assertion,
            AssertionContext context) {
        if (assertion == null || context == null) {
            throw new AssertionEvaluationException(
                    "JSONPath assertion requires an assertion and response context");
        }
        if (assertion.operator() == JsonPathOperator.EQUALS && assertion.expected() == null) {
            throw new AssertionEvaluationException(
                    "JSONPath EQUALS assertion requires expected");
        }
        JsonNode body = context.body();
        if (body == null || body.isTextual()) {
            throw new AssertionEvaluationException(
                    "JSONPath assertion requires a parsed JSON response body");
        }

        try {
            JsonNode actual = JsonPath.using(configuration)
                    .parse(body.toString())
                    .read(assertion.expression());
            boolean passed = assertion.operator() == JsonPathOperator.EXISTS
                    || jsonEquals(assertion.expected(), actual);
            return new AssertionResult(
                    AssertionType.JSON_PATH,
                    passed,
                    assertion.expected(),
                    actual,
                    passed
                            ? "JSONPath assertion matched: " + assertion.expression()
                            : "JSONPath assertion did not match: " + assertion.expression());
        } catch (PathNotFoundException exception) {
            return new AssertionResult(
                    AssertionType.JSON_PATH,
                    false,
                    assertion.expected(),
                    null,
                    "JSONPath did not resolve: " + assertion.expression());
        } catch (JsonPathException exception) {
            throw new AssertionEvaluationException(
                    "Unable to evaluate JSONPath: " + assertion.expression(), exception);
        } catch (RuntimeException exception) {
            throw new AssertionEvaluationException(
                    "Unable to evaluate JSONPath: " + assertion.expression(), exception);
        }
    }

    private boolean jsonEquals(JsonNode expected, JsonNode actual) {
        if (expected == null) {
            return false;
        }
        if (expected.isNumber() && actual != null && actual.isNumber()) {
            return new BigDecimal(expected.toString())
                    .compareTo(new BigDecimal(actual.toString())) == 0;
        }
        return expected.equals(actual);
    }
}
