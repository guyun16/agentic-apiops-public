package com.apiops.openapi.exception;

import java.util.Objects;

public final class OpenApiImportException extends RuntimeException {

    private final OpenApiImportErrorCode errorCode;

    public OpenApiImportException(OpenApiImportErrorCode errorCode) {
        super(errorCode.name());
        this.errorCode = Objects.requireNonNull(errorCode, "errorCode must not be null");
    }

    public OpenApiImportException(OpenApiImportErrorCode errorCode, Throwable cause) {
        super(errorCode.name(), cause);
        this.errorCode = Objects.requireNonNull(errorCode, "errorCode must not be null");
    }

    public OpenApiImportErrorCode errorCode() {
        return errorCode;
    }
}
