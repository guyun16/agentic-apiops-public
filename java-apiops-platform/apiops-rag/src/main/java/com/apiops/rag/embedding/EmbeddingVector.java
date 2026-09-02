package com.apiops.rag.embedding;

import java.util.List;
import java.util.Objects;

public record EmbeddingVector(EmbeddingModel model, List<Float> values) {

    public EmbeddingVector {
        Objects.requireNonNull(model, "model must not be null");
        values = List.copyOf(Objects.requireNonNull(values, "values must not be null"));
        if (values.size() != model.dimension()) {
            throw new IllegalArgumentException(
                    "vector dimension does not match embedding model");
        }
        if (values.stream().anyMatch(Objects::isNull)) {
            throw new IllegalArgumentException("vector values must not contain null");
        }
    }
}
