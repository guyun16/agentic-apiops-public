package com.apiops.rag.retrieval;

public final class RagRetrievalException extends RuntimeException {

    public RagRetrievalException(String message) {
        super(message);
    }

    public RagRetrievalException(String message, Throwable cause) {
        super(message, cause);
    }
}
