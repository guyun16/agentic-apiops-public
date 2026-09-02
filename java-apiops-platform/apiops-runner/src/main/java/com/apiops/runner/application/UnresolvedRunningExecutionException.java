package com.apiops.runner.application;

/**
 * Signals a RUNNING execution whose ownership cannot be safely retried or proven active.
 */
public final class UnresolvedRunningExecutionException extends RuntimeException {

    public UnresolvedRunningExecutionException(String message) {
        super(message);
    }

    public UnresolvedRunningExecutionException(String message, Throwable cause) {
        super(message, cause);
    }
}
