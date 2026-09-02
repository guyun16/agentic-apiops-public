package com.apiops.runner.application;

import com.apiops.runner.state.RunStatus;

import java.util.Objects;

/** One case's stable batch scheduling outcome; the run status remains authoritative in DB. */
public record BatchCaseOutcome(long runId, RunStatus status, Disposition disposition) {

    public BatchCaseOutcome {
        if (runId <= 0) {
            throw new IllegalArgumentException("runId must be positive");
        }
        Objects.requireNonNull(status, "status must not be null");
        if (!status.isTerminal()) {
            throw new IllegalArgumentException("status must be terminal");
        }
        Objects.requireNonNull(disposition, "disposition must not be null");
    }

    public enum Disposition {
        EXECUTED,
        CANCELLED_BEFORE_START,
        REJECTED,
        UNEXPECTED_FAILURE
    }
}
