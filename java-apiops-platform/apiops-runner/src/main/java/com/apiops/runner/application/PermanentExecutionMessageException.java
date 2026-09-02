package com.apiops.runner.application;

/** Non-retryable mismatch between a trigger message and the execution contract. */
public final class PermanentExecutionMessageException extends RuntimeException {

    public PermanentExecutionMessageException(String message) {
        super(message);
    }
}
