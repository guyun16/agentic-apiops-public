package com.apiops.runner.state;

public enum RunStatus {

    PENDING,
    RUNNING,
    SUCCESS,
    ASSERTION_FAILED,
    EXECUTION_FAILED,
    TIMEOUT,
    CANCELLED;

    public boolean isTerminal() {
        return this != PENDING && this != RUNNING;
    }
}
