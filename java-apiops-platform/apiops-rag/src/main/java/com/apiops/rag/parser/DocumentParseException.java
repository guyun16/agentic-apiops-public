package com.apiops.rag.parser;

import java.util.Objects;

public final class DocumentParseException extends RuntimeException {

    private final DocumentParseError error;

    public DocumentParseException(DocumentParseError error, String message) {
        super(message);
        this.error = Objects.requireNonNull(error, "error must not be null");
    }

    public DocumentParseException(
            DocumentParseError error, String message, Throwable cause) {
        super(message, cause);
        this.error = Objects.requireNonNull(error, "error must not be null");
    }

    public DocumentParseError error() {
        return error;
    }
}
