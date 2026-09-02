package com.apiops.runner.application;

import com.apiops.runner.state.RunStatus;

import java.util.Objects;

public record AsyncExecutionResult(Disposition disposition, RunStatus status) {

    public AsyncExecutionResult {
        Objects.requireNonNull(disposition, "disposition must not be null");
        Objects.requireNonNull(status, "status must not be null");
    }

    public enum Disposition {
        EXECUTED,
        DUPLICATE_TERMINAL
    }
}
