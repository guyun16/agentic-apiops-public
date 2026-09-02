package com.apiops.common.enums;

public enum FailureType implements BaseEnum {

    NONE("NONE", "no failure"),
    ASSERTION_MISMATCH("ASSERTION_MISMATCH", "assertion mismatch"),
    ASSERTION_EVALUATION_ERROR("ASSERTION_EVALUATION_ERROR", "assertion evaluation error"),
    HTTP_STATUS_ERROR("HTTP_STATUS_ERROR", "http status error"),
    TIMEOUT("TIMEOUT", "timeout"),
    NETWORK_ERROR("NETWORK_ERROR", "network error"),
    REQUEST_BUILD_ERROR("REQUEST_BUILD_ERROR", "request build error"),
    INVALID_TARGET_URI("INVALID_TARGET_URI", "invalid target URI"),
    DNS_ERROR("DNS_ERROR", "DNS error"),
    CONNECT_ERROR("CONNECT_ERROR", "connection error"),
    TLS_ERROR("TLS_ERROR", "TLS error"),
    IO_ERROR("IO_ERROR", "I/O error"),
    SCHEMA_INVALID("SCHEMA_INVALID", "schema invalid"),
    BUSINESS_ERROR("BUSINESS_ERROR", "business error"),
    TOOL_ERROR("TOOL_ERROR", "tool error"),
    SYSTEM_ERROR("SYSTEM_ERROR", "system error"),
    UNKNOWN("UNKNOWN", "unknown failure");

    private final String code;
    private final String message;

    FailureType(String code, String message) {
        this.code = code;
        this.message = message;
    }

    @Override
    public String getCode() {
        return code;
    }

    @Override
    public String getMessage() {
        return message;
    }
}
