package com.apiops.common.enums;

/** Stable tool-result statuses; existing wire values remain compatible. */
public enum ToolStatus implements BaseEnum {

    SUCCESS("SUCCESS", "tool call succeeded"),
    FAILED("FAILED", "tool call failed"),
    FORBIDDEN("FORBIDDEN", "tool call forbidden"),
    TIMEOUT("TIMEOUT", "tool call timed out"),
    PARAM_INVALID("PARAM_INVALID", "tool parameter invalid"),
    RESULT_INVALID("RESULT_INVALID", "tool result invalid");

    private final String code;
    private final String message;

    ToolStatus(String code, String message) {
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
