package com.apiops.rag.embedding;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class EmbeddingServiceContractTest {

    private static final EmbeddingModel MODEL =
            new EmbeddingModel("fake", "deterministic-test", 3);

    @Test
    void embedsSingleTextWithoutProviderTypes() {
        EmbeddingVector result = fake(false).embed("orders");

        assertEquals(MODEL, result.model());
        assertEquals(List.of(6.0F, 6.0F, 6.0F), result.values());
    }

    @Test
    void preservesBatchOrderAndCardinality() {
        List<EmbeddingVector> results = fake(false).embed(List.of("a", "orders"));

        assertEquals(2, results.size());
        assertEquals(1.0F, results.get(0).values().getFirst());
        assertEquals(6.0F, results.get(1).values().getFirst());
    }

    @Test
    void exposesStableProviderFailureBoundary() {
        assertThrows(EmbeddingException.class,
                () -> fake(true).embed(List.of("orders")));
    }

    @Test
    void rejectsVectorDimensionMismatch() {
        assertThrows(IllegalArgumentException.class,
                () -> new EmbeddingVector(MODEL, List.of(1.0F, 2.0F)));
    }

    private EmbeddingService fake(boolean fail) {
        return new EmbeddingService() {
            @Override
            public EmbeddingModel model() {
                return MODEL;
            }

            @Override
            public List<EmbeddingVector> embed(List<String> texts) {
                if (fail) {
                    throw new EmbeddingException("fake provider failed");
                }
                return texts.stream()
                        .map(String::length)
                        .map(length -> new EmbeddingVector(
                                MODEL, List.of((float) length, (float) length, (float) length)))
                        .toList();
            }
        };
    }
}
