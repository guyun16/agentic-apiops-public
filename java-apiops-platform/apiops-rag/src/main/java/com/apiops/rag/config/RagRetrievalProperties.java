package com.apiops.rag.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Optional business-layer relevance cutoff; null preserves provider results. */
@ConfigurationProperties(prefix = "apiops.rag.retrieval")
public class RagRetrievalProperties {

    private Double minRelevanceScore;

    public Double getMinRelevanceScore() {
        return minRelevanceScore;
    }

    public void setMinRelevanceScore(Double minRelevanceScore) {
        if (minRelevanceScore != null
                && (!Double.isFinite(minRelevanceScore)
                || minRelevanceScore < 0.0
                || minRelevanceScore > 1.0)) {
            throw new IllegalArgumentException(
                    "apiops.rag.retrieval.min-relevance-score must be finite "
                            + "and between 0.0 and 1.0");
        }
        this.minRelevanceScore = minRelevanceScore;
    }
}
