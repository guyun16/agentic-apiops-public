package com.apiops.runner.execution;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.assertion.AssertionResult;
import com.apiops.runner.http.HttpResponseSnapshot;
import com.apiops.runner.http.HttpExchangeSnapshot;
import com.apiops.runner.state.RunStatus;

import java.util.List;
import java.util.Objects;

public record StepResult(
        RunStatus status,
        FailureType failureType,
        List<AssertionResult> assertionResults,
        HttpResponseSnapshot responseSnapshot,
        HttpExchangeSnapshot httpExchange
) {
    public StepResult(RunStatus status, FailureType failureType,
                      List<AssertionResult> assertionResults, HttpResponseSnapshot responseSnapshot) {
        this(status, failureType, assertionResults, responseSnapshot, null);
    }
    public StepResult {
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(failureType, "failureType must not be null");
        assertionResults = List.copyOf(
                Objects.requireNonNull(assertionResults, "assertionResults must not be null"));
    }
}
