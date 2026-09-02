package com.apiops.rag.application;

import java.util.Objects;

public final class DocumentIngestionException extends RuntimeException {

    private final DocumentIngestionStage stage;

    public DocumentIngestionException(DocumentIngestionStage stage, String message) {
        super(message);
        this.stage = Objects.requireNonNull(stage, "stage must not be null");
    }

    public DocumentIngestionException(
            DocumentIngestionStage stage, String message, Throwable cause) {
        super(message, cause);
        this.stage = Objects.requireNonNull(stage, "stage must not be null");
    }

    public DocumentIngestionStage stage() {
        return stage;
    }
}
