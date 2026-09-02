package com.apiops.rag.retrieval;

import java.time.Instant;
import java.util.List;
import java.util.Objects;

/** Minimal durable fact for one project-scoped retrieval attempt. */
public record RagQueryRecord(
        String ragQueryId,
        long projectId,
        String queryText,
        int topK,
        int retrievedCount,
        List<RagResultReference> resultReferences,
        RagQueryStatus status,
        Instant startedAt,
        Instant finishedAt,
        long durationMs
) {
    public RagQueryRecord {
        Objects.requireNonNull(ragQueryId, "ragQueryId must not be null");
        Objects.requireNonNull(queryText, "queryText must not be null");
        resultReferences = List.copyOf(Objects.requireNonNull(
                resultReferences, "resultReferences must not be null"));
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(startedAt, "startedAt must not be null");
        Objects.requireNonNull(finishedAt, "finishedAt must not be null");
        if (projectId <= 0 || topK <= 0 || retrievedCount < 0 || durationMs < 0) {
            throw new IllegalArgumentException("RAG query fact contains an invalid number");
        }
        if (retrievedCount != resultReferences.size()) {
            throw new IllegalArgumentException(
                    "retrievedCount must match resultReferences");
        }
        if (status == RagQueryStatus.SUCCESS_WITH_RESULTS && retrievedCount == 0
                || status != RagQueryStatus.SUCCESS_WITH_RESULTS && retrievedCount != 0) {
            throw new IllegalArgumentException(
                    "RAG query status does not match retrievedCount");
        }
        if (finishedAt.isBefore(startedAt)) {
            throw new IllegalArgumentException("finishedAt must not precede startedAt");
        }
    }
}
