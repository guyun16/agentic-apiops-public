package com.apiops.openapi.parser;

import java.util.List;
import java.util.Objects;

public final class OpenApiParseException extends RuntimeException {

    private final OpenApiParseErrorType errorType;
    private final List<String> parserMessages;

    public OpenApiParseException(
            OpenApiParseErrorType errorType,
            List<String> parserMessages
    ) {
        super(errorType.name());
        this.errorType = Objects.requireNonNull(errorType, "errorType must not be null");
        this.parserMessages = List.copyOf(parserMessages);
    }

    public OpenApiParseException(
            OpenApiParseErrorType errorType,
            List<String> parserMessages,
            Throwable cause
    ) {
        super(errorType.name(), cause);
        this.errorType = Objects.requireNonNull(errorType, "errorType must not be null");
        this.parserMessages = List.copyOf(parserMessages);
    }

    public OpenApiParseErrorType errorType() {
        return errorType;
    }

    public List<String> parserMessages() {
        return parserMessages;
    }
}
