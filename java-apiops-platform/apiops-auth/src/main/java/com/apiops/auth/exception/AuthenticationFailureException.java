package com.apiops.auth.exception;

import com.apiops.auth.enums.AuthErrorCode;

/**
 * Stable, non-enumerating public meaning for every username/password failure.
 */
public final class AuthenticationFailureException extends RuntimeException {

    private final AuthErrorCode errorCode;

    public AuthenticationFailureException() {
        super(AuthErrorCode.AUTHENTICATION_FAILED.getMessage());
        this.errorCode = AuthErrorCode.AUTHENTICATION_FAILED;
    }

    public AuthErrorCode getErrorCode() {
        return errorCode;
    }
}
