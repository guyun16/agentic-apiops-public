package com.apiops.runner.validation;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.assertion.AssertionEngine;
import com.apiops.runner.assertion.AssertionEvaluatorRegistry;
import com.apiops.runner.assertion.HeaderAssertionEvaluator;
import com.apiops.runner.assertion.JsonPathAssertionEvaluator;
import com.apiops.runner.assertion.ResponseTimeAssertionEvaluator;
import com.apiops.runner.assertion.StatusCodeAssertionEvaluator;
import com.apiops.runner.dsl.EnvironmentSpec;
import com.apiops.runner.dsl.TestCase;
import com.apiops.runner.execution.AssertionContextMapper;
import com.apiops.runner.execution.StepResult;
import com.apiops.runner.execution.TestStepRunner;
import com.apiops.runner.http.HttpRequestBuilder;
import com.apiops.runner.http.JdkHttpTransport;
import com.apiops.runner.state.RunStatus;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

import java.time.Duration;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class Stage8DemoOrderHttpE2ETest {

    private static final String ENABLED = "APIOPS_DEMO_ORDER_E2E";
    private static final String BASE_URL = "APIOPS_DEMO_ORDER_BASE_URL";
    private static final String FAULT_BASE_URL = "APIOPS_DEMO_ORDER_FAULT_BASE_URL";

    private final ObjectMapper mapper = TestCaseDslTestSupport.mapper();
    private final TestCaseDslValidator validator = TestCaseDslTestSupport.validator(mapper);
    private final TestStepRunner runner = runner();

    @Test
    void realHttpSuccessProducesPassingAssertionsAndSuccessStatus() throws Exception {
        TestCase testCase = fixture("e2e/stage8-demo-product-success.json", BASE_URL);

        StepResult result = runner.run(testCase.environment(), testCase.steps().getFirst());

        assertNotNull(result.responseSnapshot());
        assertEquals(200, result.responseSnapshot().statusCode());
        assertEquals(2, result.assertionResults().size());
        assertTrue(result.assertionResults().stream().allMatch(assertion -> assertion.passed()));
        assertEquals(RunStatus.SUCCESS, result.status());
        assertEquals(FailureType.NONE, result.failureType());
    }

    @Test
    void realHttpMismatchProducesAssertionFailedRatherThanExecutionFailed() throws Exception {
        TestCase testCase = fixture(
                "e2e/stage8-demo-product-assertion-failed.json", BASE_URL);

        StepResult result = runner.run(testCase.environment(), testCase.steps().getFirst());

        assertNotNull(result.responseSnapshot());
        assertEquals(200, result.responseSnapshot().statusCode());
        assertEquals(1, result.assertionResults().size());
        assertFalse(result.assertionResults().getFirst().passed());
        assertEquals(RunStatus.ASSERTION_FAILED, result.status());
        assertEquals(FailureType.ASSERTION_MISMATCH, result.failureType());
    }

    @Test
    void realConnectFailureProducesNoSnapshotOrAssertions() throws Exception {
        requireEnabled();
        TestCase testCase = parse("e2e/stage8-connect-failure.json");

        StepResult result = runner.run(testCase.environment(), testCase.steps().getFirst());

        assertNull(result.responseSnapshot());
        assertTrue(result.assertionResults().isEmpty());
        assertEquals(RunStatus.EXECUTION_FAILED, result.status());
        assertEquals(FailureType.CONNECT_ERROR, result.failureType());
    }

    @Test
    void realHttp500MatchingExpectationIsSuccess() throws Exception {
        TestCase testCase = fixture(
                "e2e/stage8-demo-http-500-success.json", FAULT_BASE_URL);

        StepResult result = runner.run(testCase.environment(), testCase.steps().getFirst());

        assertNotNull(result.responseSnapshot());
        assertEquals(500, result.responseSnapshot().statusCode());
        assertEquals(2, result.assertionResults().size());
        assertTrue(result.assertionResults().stream().allMatch(assertion -> assertion.passed()));
        assertEquals(RunStatus.SUCCESS, result.status());
        assertEquals(FailureType.NONE, result.failureType());
    }

    private TestCase fixture(String name, String baseUrlVariable) throws Exception {
        requireEnabled();
        String baseUrl = System.getenv(baseUrlVariable);
        Assumptions.assumeTrue(baseUrl != null && !baseUrl.isBlank(),
                () -> "Set " + baseUrlVariable + " to a running demo-order-service instance");
        TestCase source = parse(name);
        return new TestCase(
                source.schemaVersion(),
                source.caseId(),
                source.projectId(),
                source.apiId(),
                source.name(),
                new EnvironmentSpec(baseUrl, source.environment().variables()),
                source.description(),
                source.tags(),
                source.steps());
    }

    private TestCase parse(String name) throws Exception {
        String json = TestCaseDslTestSupport.fixture(name);
        ValidationResult validation = validator.validate(json);
        assertTrue(validation.valid(), () -> validation.errors().toString());
        return validator.parse(json);
    }

    private void requireEnabled() {
        Assumptions.assumeTrue(Boolean.parseBoolean(System.getenv(ENABLED)),
                () -> "Set " + ENABLED + "=true for real demo-order-service E2E tests");
    }

    private TestStepRunner runner() {
        AssertionEngine engine = new AssertionEngine(new AssertionEvaluatorRegistry(
                new StatusCodeAssertionEvaluator(),
                new HeaderAssertionEvaluator(),
                new JsonPathAssertionEvaluator(),
                new ResponseTimeAssertionEvaluator()));
        return new TestStepRunner(
                new HttpRequestBuilder(),
                new JdkHttpTransport(Duration.ofSeconds(5)),
                new AssertionContextMapper(mapper),
                engine);
    }
}
