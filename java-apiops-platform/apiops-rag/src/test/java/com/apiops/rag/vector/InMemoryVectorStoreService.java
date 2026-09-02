package com.apiops.rag.vector;

import com.apiops.rag.embedding.EmbeddingVector;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** Deterministic test double; deliberately excluded from the production artifact. */
public final class InMemoryVectorStoreService implements VectorStoreService {

    private final Map<Key, LinkedHashMap<String, VectorEntry>> entries = new LinkedHashMap<>();

    @Override
    public synchronized void upsert(
            long projectId, String documentId, List<VectorEntry> values) {
        Objects.requireNonNull(documentId, "documentId must not be null");
        Objects.requireNonNull(values, "entries must not be null");
        LinkedHashMap<String, VectorEntry> replacement = new LinkedHashMap<>();
        for (VectorEntry value : values) {
            if (value.projectId() != projectId || !value.documentId().equals(documentId)) {
                throw new VectorStoreException(
                        "Vector entry does not match the project document scope");
            }
            if (replacement.put(value.chunkId(), value) != null) {
                throw new VectorStoreException("Duplicate chunk vector identity");
            }
        }
        entries.put(new Key(projectId, documentId), replacement);
    }

    @Override
    public List<VectorSearchMatch> search(
            long projectId, EmbeddingVector queryVector, int topK) {
        Objects.requireNonNull(queryVector, "queryVector must not be null");
        if (topK <= 0) {
            throw new IllegalArgumentException("topK must be positive");
        }
        return entries.values().stream()
                .flatMap(values -> values.values().stream())
                .filter(entry -> entry.projectId() == projectId)
                .map(entry -> new VectorSearchMatch(
                        projectId, entry.documentId(), entry.chunkId(),
                        dot(queryVector, entry.embedding())))
                .sorted(java.util.Comparator
                        .comparingDouble(VectorSearchMatch::relevanceScore).reversed()
                        .thenComparing(VectorSearchMatch::documentId)
                        .thenComparing(VectorSearchMatch::chunkId))
                .limit(topK)
                .toList();
    }

    @Override
    public synchronized void deleteByDocument(long projectId, String documentId) {
        entries.remove(new Key(projectId, Objects.requireNonNull(documentId)));
    }

    public synchronized List<VectorEntry> entries(long projectId, String documentId) {
        Map<String, VectorEntry> values = entries.get(new Key(projectId, documentId));
        return values == null ? List.of() : List.copyOf(new ArrayList<>(values.values()));
    }

    private double dot(EmbeddingVector left, EmbeddingVector right) {
        if (!left.model().equals(right.model())) {
            throw new VectorStoreException("Embedding model does not match test index");
        }
        double score = 0;
        for (int index = 0; index < left.values().size(); index++) {
            score += left.values().get(index) * right.values().get(index);
        }
        return score;
    }

    private record Key(long projectId, String documentId) {
    }
}
