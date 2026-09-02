package com.apiops.rag.repository;

import com.apiops.rag.domain.Document;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;

import java.util.List;
import java.util.Optional;

/** Formal project-scoped knowledge persistence boundary. */
public interface DocumentRepository {

    Optional<Document> findBySourceKey(long projectId, String sourceKey);

    Optional<Document> findById(long projectId, String documentId);

    List<DocumentChunk> findChunks(long projectId, String documentId);

    /** Atomically saves the document and replaces all of its formal chunks. */
    void saveKnowledge(Document document, List<DocumentChunk> chunks);

    /** Persists the complete status change before returning successfully. */
    void updateStatus(long projectId, String documentId, DocumentStatus status);

    /** Atomically marks the document deleted and removes its formal chunks. */
    void markDeleted(long projectId, String documentId);
}
