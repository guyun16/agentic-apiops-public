package com.apiops.demo.order.common.exception;

import java.util.Objects;

public class ResourceNotFoundException extends RuntimeException {

    public ResourceNotFoundException() {
        super(DemoOrderErrorCode.RESOURCE_NOT_FOUND.getMessage());
    }

    public ResourceNotFoundException(String safeMessage) {
        super(Objects.requireNonNull(safeMessage, "safeMessage must not be null"));
    }
}
