package com.apiops.runner.execution;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.assertion.AssertionContext;
import com.apiops.runner.assertion.AssertionEngine;
import com.apiops.runner.assertion.AssertionEvaluationException;
import com.apiops.runner.assertion.AssertionEvaluatorRegistryException;
import com.apiops.runner.assertion.AssertionResult;
import com.apiops.runner.dsl.EnvironmentSpec;
import com.apiops.runner.dsl.TestStep;
import com.apiops.runner.http.HttpRequestBuildException;
import com.apiops.runner.http.HttpRequestBuilder;
import com.apiops.runner.http.HttpResponseSnapshot;
import com.apiops.runner.http.HttpExchangeCapture;
import com.apiops.runner.http.HttpTransport;
import com.apiops.runner.http.HttpTransportException;
import com.apiops.runner.state.RunStatus;

import java.net.http.HttpRequest;
import java.util.List;
import java.util.Objects;

public final class TestStepRunner {

    private final HttpRequestBuilder requestBuilder;
    private final HttpTransport transport;
    private final AssertionContextMapper contextMapper;
    private final AssertionEngine assertionEngine;

    public TestStepRunner(
            HttpRequestBuilder requestBuilder,
            HttpTransport transport,
            AssertionContextMapper contextMapper,
            AssertionEngine assertionEngine) {
        this.requestBuilder = Objects.requireNonNull(requestBuilder, "requestBuilder must not be null");
        this.transport = Objects.requireNonNull(transport, "transport must not be null");
        this.contextMapper = Objects.requireNonNull(contextMapper, "contextMapper must not be null");
        this.assertionEngine = Objects.requireNonNull(assertionEngine, "assertionEngine must not be null");
    }

    public StepResult run(EnvironmentSpec environment, TestStep step) {
        Objects.requireNonNull(environment, "environment must not be null");
        Objects.requireNonNull(step, "step must not be null");

        HttpRequest request;
        try {
            request = requestBuilder.build(environment, step.request());
        } catch (HttpRequestBuildException exception) {
            return failedExecution(exception.failureType(), null);
        }

        HttpResponseSnapshot snapshot;
        try {
            snapshot = transport.execute(request);
        } catch (HttpTransportException exception) {
            RunStatus status = exception.failureType() == FailureType.TIMEOUT
                    ? RunStatus.TIMEOUT
                    : RunStatus.EXECUTION_FAILED;
            return new StepResult(status, exception.failureType(), List.of(), null,
                    HttpExchangeCapture.capture(request, step.request(), null));
        }

        AssertionContext context = contextMapper.map(snapshot);
        try {
            List<AssertionResult> assertionResults = assertionEngine.evaluate(
                    step.assertions(), context);
            boolean passed = assertionResults.stream().allMatch(AssertionResult::passed);
            return new StepResult(
                    passed ? RunStatus.SUCCESS : RunStatus.ASSERTION_FAILED,
                    passed ? FailureType.NONE : FailureType.ASSERTION_MISMATCH,
                    assertionResults,
                    snapshot, HttpExchangeCapture.capture(request, step.request(), snapshot));
        } catch (AssertionEvaluationException | AssertionEvaluatorRegistryException exception) {
            return new StepResult(RunStatus.EXECUTION_FAILED, FailureType.ASSERTION_EVALUATION_ERROR,
                    List.of(), snapshot, HttpExchangeCapture.capture(request, step.request(), snapshot));
        }
    }

    private StepResult failedExecution(
            FailureType failureType, HttpResponseSnapshot snapshot) {
        return new StepResult(RunStatus.EXECUTION_FAILED, failureType, List.of(), snapshot);
    }
}
