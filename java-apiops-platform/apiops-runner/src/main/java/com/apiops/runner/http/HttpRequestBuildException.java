package com.apiops.runner.http;

import com.apiops.common.enums.FailureType;

public final class HttpRequestBuildException extends RuntimeException {

    private final FailureType failureType;

    public HttpRequestBuildException(FailureType failureType, String message) {
        super(message);
        this.failureType = failureType;
    }

    public HttpRequestBuildException(FailureType failureType, String message, Throwable cause) {
        super(message, cause);
        this.failureType = failureType;
    }

    public FailureType failureType() {
        return failureType;
    }
}
