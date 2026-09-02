package com.apiops.common.enums;

public enum CaseStatus implements BaseEnum {

    PENDING("PENDING", "case is pending"),
    RUNNING("RUNNING", "case is running"),
    SUCCESS("SUCCESS", "case succeeded"),
    ASSERTION_FAILED("ASSERTION_FAILED", "case assertion failed"),
    EXECUTION_FAILED("EXECUTION_FAILED", "case execution failed"),
    TIMEOUT("TIMEOUT", "case timed out"),
    SKIPPED("SKIPPED", "case skipped");

    private final String code;
    private final String message;

    CaseStatus(String code, String message) {
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