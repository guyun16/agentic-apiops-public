package com.apiops.openapi.exception;

public enum OpenApiImportErrorCode {
    EMPTY_FILE,
    FILE_TOO_LARGE,
    FILE_READ_FAILED,
    INVALID_SOURCE_KEY,
    INVALID_OPENAPI,
    UNSUPPORTED_OPENAPI_VERSION,
    REMOTE_REF_NOT_ALLOWED
}
