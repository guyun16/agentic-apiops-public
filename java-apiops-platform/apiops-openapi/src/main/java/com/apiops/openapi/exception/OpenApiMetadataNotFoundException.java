package com.apiops.openapi.exception;

public final class OpenApiMetadataNotFoundException extends RuntimeException {

    public OpenApiMetadataNotFoundException(String resourceType, String businessId) {
        super(resourceType + " not found: " + businessId);
    }
}
