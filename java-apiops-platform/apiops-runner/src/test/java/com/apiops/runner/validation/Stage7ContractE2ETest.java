package com.apiops.runner.validation;

import com.apiops.runner.assertion.AssertionContext;
import com.apiops.runner.assertion.AssertionEngine;
import com.apiops.runner.assertion.AssertionEvaluatorRegistry;
import com.apiops.runner.assertion.AssertionResult;
import com.apiops.runner.assertion.HeaderAssertionEvaluator;
import com.apiops.runner.assertion.JsonPathAssertionEvaluator;
import com.apiops.runner.assertion.ResponseTimeAssertionEvaluator;
import com.apiops.runner.assertion.StatusCodeAssertionEvaluator;
import com.apiops.runner.dsl.TestCase;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class Stage7ContractE2ETest {

    private final ObjectMapper mapper = TestCaseDslTestSupport.mapper();
    private final TestCaseDslValidator validator = TestCaseDslTestSupport.validator(mapper);
    private final AssertionEngine engine = new AssertionEngine(new AssertionEvaluatorRegistry(
            new StatusCodeAssertionEvaluator(),
            new HeaderAssertionEvaluator(),
            new JsonPathAssertionEvaluator(),
            new ResponseTimeAssertionEvaluator()));

    @Test
    void successfulCreateOrderFixtureFlowsFromDslToPassingResults() throws Exception {
        String json = TestCaseDslTestSupport.fixture("e2e/create-order-success.json");
        TestCase testCase = parseValidFixture(json);
        JsonNode responseBody = mapper.readTree("""
                {
                  "success": true,
                  "code": "ORDER_SUCCESS",
                  "message": "success",
                  "data": {"id": 10}
                }
                """);

        List<AssertionResult> results = engine.evaluate(
                testCase.steps().getFirst().assertions(),
                new AssertionContext(
                        200,
                        Map.of("Content-Type", List.of("application/json")),
                        responseBody,
                        42L));

        assertEquals("api_create_order", testCase.apiId());
        assertEquals("POST", testCase.steps().getFirst().request().method());
        assertEquals("/orders", testCase.steps().getFirst().request().path());
        assertEquals(5, results.size());
        assertTrue(results.stream().allMatch(AssertionResult::passed));
    }

    @Test
    void negativeBusinessFixturePassesWhenSyntheticConflictMatchesExpected() throws Exception {
        String json = TestCaseDslTestSupport.fixture(
                "e2e/create-order-insufficient-inventory.json");
        TestCase testCase = parseValidFixture(json);
        JsonNode responseBody = mapper.readTree("""
                {
                  "success": false,
                  "code": "ORDER_BUSINESS_CONFLICT",
                  "message": "insufficient inventory for product id 10",
                  "data": null
                }
                """);

        List<AssertionResult> results = engine.evaluate(
                testCase.steps().getFirst().assertions(),
                new AssertionContext(
                        409,
                        Map.of("content-type", List.of("application/json")),
                        responseBody,
                        44L));

        assertEquals("api_create_order", testCase.apiId());
        assertEquals(409, results.getFirst().actual());
        assertEquals(5, results.size());
        assertTrue(results.stream().allMatch(AssertionResult::passed));
    }

    private TestCase parseValidFixture(String json) {
        ValidationResult validation = validator.validate(json);
        assertTrue(validation.valid(), () -> validation.errors().toString());
        return validator.parse(json);
    }
}
