package com.apiops.rag.domain;

import java.util.Map;
import java.util.Objects;

/** A stable, ordered retrieval unit that remains owned by a project-scoped document. */
public record DocumentChunk(
        String chunkId,
        String documentId,
        long projectId,
        int ordinal,
        String content,
        String contentHash,
        Map<String, String> metadata
) {
    public DocumentChunk {
        Objects.requireNonNull(chunkId, "chunkId must not be null");
        Objects.requireNonNull(documentId, "documentId must not be null");
        Objects.requireNonNull(content, "content must not be null");
        Objects.requireNonNull(contentHash, "contentHash must not be null");
        metadata = Map.copyOf(Objects.requireNonNull(metadata, "metadata must not be null"));
    }

    @Override
    public String toString() {
        return "DocumentChunk[chunkId=" + chunkId
                + ", documentId=" + documentId
                + ", projectId=" + projectId
                + ", ordinal=" + ordinal
                + ", contentHash=" + contentHash
                + ", contentLength=" + content.length()
                + ", metadata=" + metadata + "]";
    }
}
