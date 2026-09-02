package com.apiops.openapi.normalizer;

import java.util.Objects;

/** Stable failure for invalid OpenAPI metadata. */
public final class OpenApiNormalizationException extends RuntimeException {

    public enum Reason {
        BLANK_OPERATION_ID,
        DUPLICATE_OPERATION_ID,
        MISSING_INTERNAL_REFERENCE,
        REMOTE_REFERENCE_NOT_ALLOWED
    }

    private final Reason reason;

    private OpenApiNormalizationException(Reason reason, String message) {
        super(message);
        this.reason = Objects.requireNonNull(reason, "reason must not be null");
    }

    static OpenApiNormalizationException blankOperationId(String method, String path) {
        return new OpenApiNormalizationException(
                Reason.BLANK_OPERATION_ID,
                "BLANK_OPERATION_ID: operationId is blank at " + method + " " + path
        );
    }

    static OpenApiNormalizationException duplicateOperationId(
            String operationId,
            String method,
            String path,
            String firstMethod,
            String firstPath
    ) {
        return new OpenApiNormalizationException(
                Reason.DUPLICATE_OPERATION_ID,
                "DUPLICATE_OPERATION_ID: '" + operationId + "' at " + method + " " + path
                        + " duplicates " + firstMethod + " " + firstPath
        );
    }

    static OpenApiNormalizationException missingInternalReference(String reference) {
        return new OpenApiNormalizationException(
                Reason.MISSING_INTERNAL_REFERENCE,
                "MISSING_INTERNAL_REFERENCE: '" + reference + "'"
        );
    }

    static OpenApiNormalizationException remoteReference(String reference) {
        return new OpenApiNormalizationException(
                Reason.REMOTE_REFERENCE_NOT_ALLOWED,
                "REMOTE_REFERENCE_NOT_ALLOWED: '" + reference + "'"
        );
    }

    public Reason reason() {
        return reason;
    }
}
