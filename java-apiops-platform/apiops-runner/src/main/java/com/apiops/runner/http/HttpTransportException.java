package com.apiops.runner.http;

import com.apiops.common.enums.FailureType;

public final class HttpTransportException extends RuntimeException {

    private final FailureType failureType;

    public HttpTransportException(FailureType failureType, String message, Throwable cause) {
        super(message, cause);
        this.failureType = failureType;
    }

    public FailureType failureType() {
        return failureType;
    }
}
