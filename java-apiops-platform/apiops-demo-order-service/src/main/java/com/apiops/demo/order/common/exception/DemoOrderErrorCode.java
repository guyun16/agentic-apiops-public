package com.apiops.demo.order.common.exception;

public enum DemoOrderErrorCode {

    SUCCESS("ORDER_SUCCESS", "success"),
    TOKEN_EXPIRED("ORDER_TOKEN_EXPIRED", "token expired"),
    PARAM_INVALID("ORDER_PARAM_INVALID", "request parameter invalid"),
    RESOURCE_NOT_FOUND("ORDER_RESOURCE_NOT_FOUND", "resource not found"),
    BUSINESS_CONFLICT("ORDER_BUSINESS_CONFLICT", "business conflict"),
    SYSTEM_ERROR("ORDER_SYSTEM_ERROR", "internal server error");

    private final String code;
    private final String message;

    DemoOrderErrorCode(String code, String message) {
        this.code = code;
        this.message = message;
    }

    public String getCode() {
        return code;
    }

    public String getMessage() {
        return message;
    }
}
