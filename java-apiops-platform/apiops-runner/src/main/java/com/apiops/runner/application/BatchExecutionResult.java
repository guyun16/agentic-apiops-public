package com.apiops.runner.application;

import com.apiops.runner.state.RunStatus;

import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record BatchExecutionResult(
        UUID batchId,
        RunStatus status,
        boolean cancelRequested,
        List<BatchCaseOutcome> caseOutcomes) {

    public BatchExecutionResult {
        Objects.requireNonNull(batchId, "batchId must not be null");
        Objects.requireNonNull(status, "status must not be null");
        if (!status.isTerminal()) {
            throw new IllegalArgumentException("status must be terminal");
        }
        caseOutcomes = List.copyOf(
                Objects.requireNonNull(caseOutcomes, "caseOutcomes must not be null"));
    }
}
