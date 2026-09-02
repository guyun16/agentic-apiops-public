package com.apiops.rag.context;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

public class ContextRanker {

    private static final Comparator<ContextItem> ORDER = (left, right) -> {
        int authority = Integer.compare(authority(left.source()), authority(right.source()));
        if (authority != 0) {
            return authority;
        }
        if (left.source() == ContextSource.RAG_DOCUMENT) {
            int score = Double.compare(right.relevanceScore(), left.relevanceScore());
            if (score != 0) {
                return score;
            }
            int document = left.citation().documentId().compareTo(right.citation().documentId());
            if (document != 0) {
                return document;
            }
            int chunk = left.citation().chunkId().compareTo(right.citation().chunkId());
            if (chunk != 0) {
                return chunk;
            }
        }
        int item = left.itemId().compareTo(right.itemId());
        if (item != 0) {
            return item;
        }
        return left.content().compareTo(right.content());
    };

    public List<ContextItem> rank(List<ContextItem> items) {
        List<ContextItem> ranked = new ArrayList<>(items);
        ranked.sort(ORDER);
        return List.copyOf(ranked);
    }

    private static int authority(ContextSource source) {
        return switch (source) {
            case TEST_REPORT -> 0;
            case OPENAPI_METADATA -> 1;
            case RAG_DOCUMENT -> 2;
        };
    }
}
