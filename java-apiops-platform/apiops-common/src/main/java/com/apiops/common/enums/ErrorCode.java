package com.apiops.common.enums;

/**
 * Machine-readable error codes shared across platform modules.
 */
public enum ErrorCode implements BaseEnum {

    SUCCESS("00000", "success"),
    PARAM_INVALID("A0001", "request parameter invalid"),
    RESOURCE_NOT_FOUND("A0002", "resource not found"),
    TASK_STATUS_INVALID("B0001", "task status invalid"),
    CASE_STATUS_INVALID("B0002", "case status invalid"),
    TOOL_CALL_FAILED("C0001", "tool call failed"),
    TOOL_RESULT_INVALID("C0002", "tool result invalid"),
    SYSTEM_ERROR("S0001", "system error");

    private final String code;
    private final String message;

    ErrorCode(String code, String message) {
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
