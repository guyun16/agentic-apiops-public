package com.apiops.rag.retrieval;

import java.util.List;
import java.util.Objects;

/** Results and durable fact identity produced by one retrieval. */
public record RagRetrieval(String ragQueryId, List<RagSearchResult> results) {
    public RagRetrieval {
        Objects.requireNonNull(ragQueryId, "ragQueryId must not be null");
        results = List.copyOf(Objects.requireNonNull(results, "results must not be null"));
    }
}
