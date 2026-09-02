package com.apiops.common.enums;

public enum TaskStatus implements BaseEnum {

    PENDING("PENDING", "task is pending"),
    RUNNING("RUNNING", "task is running"),
    SUCCESS("SUCCESS", "task succeeded"),
    FAILED("FAILED", "task failed"),
    TIMEOUT("TIMEOUT", "task timed out"),
    CANCELLED("CANCELLED", "task cancelled");

    private final String code;
    private final String message;

    TaskStatus(String code, String message) {
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