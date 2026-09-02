package com.apiops.rag.vector;

import com.apiops.rag.embedding.EmbeddingVector;

import java.util.List;

/** Provider-agnostic vector index boundary. Every operation is project-scoped. */
public interface VectorStoreService {

    /** Atomically replaces the indexed entries for the given project document. */
    void upsert(long projectId, String documentId, List<VectorEntry> entries)
            throws VectorStoreException;

    /**
     * Returns at most {@code topK} matches from the requested project only. Match scores use
     * the provider-normalized higher-is-better relevance direction.
     */
    List<VectorSearchMatch> search(long projectId, EmbeddingVector queryVector, int topK)
            throws VectorStoreException;

    /**
     * Atomically removes the project document index. A failure must not expose a partial delete.
     */
    void deleteByDocument(long projectId, String documentId) throws VectorStoreException;
}
