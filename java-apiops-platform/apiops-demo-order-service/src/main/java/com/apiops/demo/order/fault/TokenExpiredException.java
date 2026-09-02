package com.apiops.demo.order.fault;

/**
 * Thrown to simulate an expired authentication token.
 * Mapped to HTTP 401 UNAUTHORIZED with {@code TOKEN_EXPIRED} by
 * {@link com.apiops.demo.order.common.web.GlobalExceptionHandler}.
 */
public class TokenExpiredException extends RuntimeException {

    public TokenExpiredException() {
        super("token expired");
    }
}
