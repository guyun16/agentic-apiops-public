package com.apiops.rag.embedding;

import java.util.Objects;

/** Compatibility identity required by a vector index. */
public record EmbeddingModel(String provider, String model, int dimension) {

    public EmbeddingModel {
        Objects.requireNonNull(provider, "provider must not be null");
        Objects.requireNonNull(model, "model must not be null");
        if (provider.isBlank()) {
            throw new IllegalArgumentException("provider must not be blank");
        }
        if (model.isBlank()) {
            throw new IllegalArgumentException("model must not be blank");
        }
        if (dimension <= 0) {
            throw new IllegalArgumentException("dimension must be positive");
        }
    }
}
