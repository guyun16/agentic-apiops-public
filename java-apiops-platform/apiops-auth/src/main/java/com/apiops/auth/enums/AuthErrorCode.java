package com.apiops.auth.enums;

import com.apiops.common.enums.BaseEnum;

/** Authentication-specific error codes kept out of apiops-common. */
public enum AuthErrorCode implements BaseEnum {

    AUTHENTICATION_FAILED("A0003", "authentication failed"),
    AUTHENTICATION_REQUIRED("A0004", "authentication required"),
    ACCESS_DENIED("A0005", "access denied");

    private final String code;
    private final String message;

    AuthErrorCode(String code, String message) {
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
