package com.apiops.rag.context;

import java.util.List;

public record ContextPack(
        long projectId,
        List<ContextItem> items,
        int totalChars,
        int maxTotalChars
) {

    public ContextPack {
        if (projectId <= 0) {
            throw new IllegalArgumentException("projectId must be positive");
        }
        items = List.copyOf(items);
        if (items.stream().anyMatch(item -> item.projectId() != projectId)) {
            throw new IllegalArgumentException("All context items must belong to the pack project");
        }
        int actualChars = items.stream().mapToInt(item -> item.content().length()).sum();
        if (totalChars != actualChars) {
            throw new IllegalArgumentException("totalChars must match retained context content");
        }
        if (maxTotalChars <= 0 || totalChars > maxTotalChars) {
            throw new IllegalArgumentException("Context pack exceeds its character budget");
        }
    }
}
