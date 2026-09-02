package com.apiops.rag.context;

import com.apiops.rag.domain.EvidenceCitation;

import java.util.Objects;

public record ContextItem(
        long projectId,
        ContextSource source,
        String itemId,
        String content,
        String contentHash,
        Double relevanceScore,
        EvidenceCitation citation
) {

    public ContextItem {
        if (projectId <= 0) {
            throw new IllegalArgumentException("projectId must be positive");
        }
        Objects.requireNonNull(source, "source");
        itemId = requireText(itemId, "itemId");
        content = Objects.requireNonNull(content, "content");
        if (contentHash != null && contentHash.isBlank()) {
            throw new IllegalArgumentException("contentHash must be null or non-blank");
        }
        if (source == ContextSource.RAG_DOCUMENT) {
            if (relevanceScore == null || !Double.isFinite(relevanceScore)) {
                throw new IllegalArgumentException("RAG relevanceScore must be finite");
            }
            Objects.requireNonNull(citation, "RAG citation");
            if (citation.projectId() != projectId) {
                throw new IllegalArgumentException("citation projectId must match context item projectId");
            }
            if (Double.compare(citation.score(), relevanceScore) != 0) {
                throw new IllegalArgumentException("citation score must match RAG relevanceScore");
            }
            if (!citation.excerpt().equals(content)) {
                throw new IllegalArgumentException("citation excerpt must match retained RAG content");
            }
        } else if (relevanceScore != null || citation != null) {
            throw new IllegalArgumentException("Only RAG context items may carry score and citation");
        }
    }

    public ContextItem withContent(String retainedContent) {
        EvidenceCitation retainedCitation = citation;
        if (citation != null) {
            retainedCitation = new EvidenceCitation(
                    citation.sourceType(),
                    citation.sourceId(),
                    citation.projectId(),
                    citation.documentId(),
                    citation.chunkId(),
                    citation.score(),
                    citation.title(),
                    citation.location(),
                    retainedContent
            );
        }
        return new ContextItem(
                projectId,
                source,
                itemId,
                retainedContent,
                contentHash,
                relevanceScore,
                retainedCitation
        );
    }

    private static String requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
        return value;
    }
}
