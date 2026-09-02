package com.apiops.runner.state;

public final class InvalidRunStateTransitionException extends IllegalStateException {

    public InvalidRunStateTransitionException(RunStatus from, RunStatus to) {
        super("Illegal run status transition: " + from + " -> " + to);
    }
}
