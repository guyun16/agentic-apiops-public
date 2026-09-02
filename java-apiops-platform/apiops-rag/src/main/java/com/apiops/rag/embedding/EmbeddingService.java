package com.apiops.rag.embedding;

import java.util.List;

/** Provider-agnostic text-to-vector boundary. */
public interface EmbeddingService {

    EmbeddingModel model();

    List<EmbeddingVector> embed(List<String> texts) throws EmbeddingException;

    default EmbeddingVector embed(String text) throws EmbeddingException {
        List<EmbeddingVector> values = embed(List.of(text));
        if (values.size() != 1) {
            throw new EmbeddingException("Embedding provider returned an invalid result count");
        }
        return values.getFirst();
    }
}
