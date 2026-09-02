package com.apiops.runner.execution;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.assertion.AssertionEngine;
import com.apiops.runner.assertion.AssertionEvaluationException;
import com.apiops.runner.assertion.AssertionEvaluator;
import com.apiops.runner.assertion.AssertionEvaluatorRegistry;
import com.apiops.runner.assertion.AssertionResult;
import com.apiops.runner.assertion.JsonPathAssertionEvaluator;
import com.apiops.runner.assertion.StatusCodeAssertionEvaluator;
import com.apiops.runner.dsl.AssertionSpec;
import com.apiops.runner.dsl.AssertionType;
import com.apiops.runner.dsl.EnvironmentSpec;
import com.apiops.runner.dsl.JsonPathAssertionSpec;
import com.apiops.runner.dsl.JsonPathOperator;
import com.apiops.runner.dsl.StatusCodeAssertionSpec;
import com.apiops.runner.dsl.TestStep;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.apiops.runner.http.HttpRequestBuilder;
import com.apiops.runner.http.HttpResponseSnapshot;
import com.apiops.runner.http.HttpTransport;
import com.apiops.runner.http.HttpTransportException;
import com.apiops.runner.state.RunStatus;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TestStepRunnerTest {

    private static final EnvironmentSpec ENVIRONMENT = new EnvironmentSpec(
            "http://localhost:8080", Map.of());

    @Test
    void http200WithPassingAssertionsIsSuccess() throws Exception {
        StepResult result = runner(snapshot(200, "{\"ok\":true}"), null)
                .run(ENVIRONMENT, step(
                        new StatusCodeAssertionSpec(200),
                        new JsonPathAssertionSpec(
                                "$.ok", JsonPathOperator.EQUALS,
                                new ObjectMapper().readTree("true"))));

        assertEquals(RunStatus.SUCCESS, result.status());
        assertEquals(FailureType.NONE, result.failureType());
        assertEquals(2, result.assertionResults().size());
        assertTrue(result.assertionResults().stream().allMatch(AssertionResult::passed));
    }

    @Test
    void http200WithMismatchIsAssertionFailed() {
        StepResult result = runner(snapshot(200, "{}"), null)
                .run(ENVIRONMENT, step(new StatusCodeAssertionSpec(201)));

        assertEquals(RunStatus.ASSERTION_FAILED, result.status());
        assertEquals(FailureType.ASSERTION_MISMATCH, result.failureType());
        assertFalse(result.assertionResults().getFirst().passed());
        assertEquals(200, result.responseSnapshot().statusCode());
    }

    @Test
    void http404Expected404IsSuccess() {
        StepResult result = runner(snapshot(404, "{\"error\":\"missing\"}"), null)
                .run(ENVIRONMENT, step(new StatusCodeAssertionSpec(404)));

        assertEquals(RunStatus.SUCCESS, result.status());
        assertEquals(404, result.responseSnapshot().statusCode());
    }

    @Test
    void http500Expected500IsSuccess() {
        StepResult result = runner(snapshot(500, "{\"error\":\"server\"}"), null)
                .run(ENVIRONMENT, step(new StatusCodeAssertionSpec(500)));

        assertEquals(RunStatus.SUCCESS, result.status());
        assertEquals(500, result.responseSnapshot().statusCode());
    }

    @Test
    void evaluatorExceptionBecomesExecutionFailedWithEvaluationFailureType() {
        AssertionEvaluator<StatusCodeAssertionSpec> evaluator = new AssertionEvaluator<>() {
            @Override
            public AssertionType supportedType() {
                return AssertionType.STATUS_CODE;
            }

            @Override
            public AssertionResult evaluate(
                    StatusCodeAssertionSpec assertion, com.apiops.runner.assertion.AssertionContext context) {
                throw new AssertionEvaluationException("evaluation failed");
            }
        };
        TestStepRunner runner = runner(
                snapshot(200, "{}"),
                new AssertionEngine(new AssertionEvaluatorRegistry(evaluator)));

        StepResult result = runner.run(ENVIRONMENT, step(new StatusCodeAssertionSpec(200)));

        assertEquals(RunStatus.EXECUTION_FAILED, result.status());
        assertEquals(FailureType.ASSERTION_EVALUATION_ERROR, result.failureType());
        assertTrue(result.assertionResults().isEmpty());
        assertEquals(200, result.responseSnapshot().statusCode());
    }

    @Test
    void timeoutDoesNotMapOrInvokeAssertionEngine() {
        AtomicInteger evaluations = new AtomicInteger();
        AssertionEvaluator<StatusCodeAssertionSpec> evaluator = countingEvaluator(evaluations);
        TestStepRunner runner = new TestStepRunner(
                new HttpRequestBuilder(),
                request -> {
                    throw new HttpTransportException(
                            FailureType.TIMEOUT, "timed out", new RuntimeException());
                },
                new AssertionContextMapper(),
                new AssertionEngine(new AssertionEvaluatorRegistry(evaluator)));

        StepResult result = runner.run(ENVIRONMENT, step(new StatusCodeAssertionSpec(200)));

        assertEquals(RunStatus.TIMEOUT, result.status());
        assertEquals(FailureType.TIMEOUT, result.failureType());
        assertNull(result.responseSnapshot());
        assertEquals(0, evaluations.get());
    }

    @Test
    void transportFailureDoesNotInvokeAssertionEngine() {
        AtomicInteger evaluations = new AtomicInteger();
        AssertionEvaluator<StatusCodeAssertionSpec> evaluator = countingEvaluator(evaluations);
        TestStepRunner runner = new TestStepRunner(
                new HttpRequestBuilder(),
                request -> {
                    throw new HttpTransportException(
                            FailureType.CONNECT_ERROR, "connection failed", new RuntimeException());
                },
                new AssertionContextMapper(),
                new AssertionEngine(new AssertionEvaluatorRegistry(evaluator)));

        StepResult result = runner.run(ENVIRONMENT, step(new StatusCodeAssertionSpec(200)));

        assertEquals(RunStatus.EXECUTION_FAILED, result.status());
        assertEquals(FailureType.CONNECT_ERROR, result.failureType());
        assertNull(result.responseSnapshot());
        assertEquals(0, evaluations.get());
    }

    @Test
    void requestBuildFailureDoesNotInvokeAssertionEngine() {
        AtomicInteger evaluations = new AtomicInteger();
        AssertionEvaluator<StatusCodeAssertionSpec> evaluator = countingEvaluator(evaluations);
        TestStepRunner runner = new TestStepRunner(
                new HttpRequestBuilder(),
                request -> {
                    throw new AssertionError("transport must not be called");
                },
                new AssertionContextMapper(),
                new AssertionEngine(new AssertionEvaluatorRegistry(evaluator)));

        StepResult result = runner.run(ENVIRONMENT,
                step("/resource/{id}", new StatusCodeAssertionSpec(200)));

        assertEquals(RunStatus.EXECUTION_FAILED, result.status());
        assertEquals(FailureType.REQUEST_BUILD_ERROR, result.failureType());
        assertNull(result.responseSnapshot());
        assertEquals(0, evaluations.get());
    }

    private TestStepRunner runner(HttpResponseSnapshot snapshot, AssertionEngine engine) {
        return new TestStepRunner(
                new HttpRequestBuilder(),
                request -> snapshot,
                new AssertionContextMapper(),
                engine == null ? stage7Engine() : engine);
    }

    private AssertionEngine stage7Engine() {
        return new AssertionEngine(new AssertionEvaluatorRegistry(
                new StatusCodeAssertionEvaluator(),
                new JsonPathAssertionEvaluator()));
    }

    private AssertionEvaluator<StatusCodeAssertionSpec> countingEvaluator(AtomicInteger evaluations) {
        return new AssertionEvaluator<>() {
            @Override
            public AssertionType supportedType() {
                return AssertionType.STATUS_CODE;
            }

            @Override
            public AssertionResult evaluate(
                    StatusCodeAssertionSpec assertion, com.apiops.runner.assertion.AssertionContext context) {
                evaluations.incrementAndGet();
                return new StatusCodeAssertionEvaluator().evaluate(assertion, context);
            }
        };
    }

    private TestStep step(AssertionSpec... assertions) {
        return step("/resource", assertions);
    }

    private TestStep step(String path, AssertionSpec... assertions) {
        return new TestStep(
                "step-1",
                "HTTP step",
                new com.apiops.runner.dsl.RequestSpec(
                        "GET", path, Map.of(), Map.of(), Map.of(), null),
                List.of(assertions),
                List.of());
    }

    private HttpResponseSnapshot snapshot(int statusCode, String body) {
        return new HttpResponseSnapshot(
                statusCode,
                Map.of("Content-Type", List.of("application/json")),
                body,
                20L);
    }
}
