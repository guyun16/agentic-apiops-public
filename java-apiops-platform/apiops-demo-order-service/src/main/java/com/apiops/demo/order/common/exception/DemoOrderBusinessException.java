package com.apiops.demo.order.common.exception;

import java.util.Objects;

public class DemoOrderBusinessException extends RuntimeException {

    private final DemoOrderErrorCode errorCode;

    public DemoOrderBusinessException(DemoOrderErrorCode errorCode) {
        super(requireBusinessErrorCode(errorCode).getMessage());
        this.errorCode = errorCode;
    }

    public DemoOrderBusinessException(DemoOrderErrorCode errorCode, String safeMessage) {
        super(Objects.requireNonNull(safeMessage, "safeMessage must not be null"));
        this.errorCode = requireBusinessErrorCode(errorCode);
    }

    public DemoOrderErrorCode getErrorCode() {
        return errorCode;
    }

    private static DemoOrderErrorCode requireBusinessErrorCode(DemoOrderErrorCode errorCode) {
        Objects.requireNonNull(errorCode, "errorCode must not be null");
        if (errorCode != DemoOrderErrorCode.BUSINESS_CONFLICT) {
            throw new IllegalArgumentException(
                    "Only BUSINESS_CONFLICT can be raised as a business exception"
            );
        }
        return errorCode;
    }
}
