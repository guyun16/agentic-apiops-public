package com.apiops.rag.context;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class ContextDeduplicator {

    public List<ContextItem> deduplicate(List<ContextItem> items) {
        Map<String, ContextItem> retained = new LinkedHashMap<>();
        int uniqueSequence = 0;
        for (ContextItem item : items) {
            String key = deduplicationKey(item);
            if (key == null) {
                retained.put("unique:" + uniqueSequence++, item);
            } else {
                retained.merge(key, item, ContextDeduplicator::preferred);
            }
        }
        return List.copyOf(new ArrayList<>(retained.values()));
    }

    private static String deduplicationKey(ContextItem item) {
        if (item.source() == ContextSource.RAG_DOCUMENT) {
            return item.source() + ":chunk:" + item.citation().chunkId();
        }
        if (item.contentHash() != null) {
            return item.source() + ":hash:" + item.contentHash();
        }
        return null;
    }

    private static ContextItem preferred(ContextItem left, ContextItem right) {
        if (left.source() == ContextSource.RAG_DOCUMENT) {
            int score = Double.compare(left.relevanceScore(), right.relevanceScore());
            if (score != 0) {
                return score > 0 ? left : right;
            }
        }
        int content = left.content().compareTo(right.content());
        if (content != 0) {
            return content < 0 ? left : right;
        }
        return left.itemId().compareTo(right.itemId()) <= 0 ? left : right;
    }
}
