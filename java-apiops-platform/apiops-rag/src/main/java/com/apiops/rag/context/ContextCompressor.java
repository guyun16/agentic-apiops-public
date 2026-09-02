package com.apiops.rag.context;

import java.util.ArrayList;
import java.util.List;

public class ContextCompressor {

    private final int maxTotalChars;
    private final int maxRagItemChars;

    public ContextCompressor(ContextPackProperties properties) {
        this.maxTotalChars = properties.getMaxTotalChars();
        this.maxRagItemChars = properties.getMaxRagItemChars();
    }

    public List<ContextItem> compress(List<ContextItem> rankedItems) {
        List<ContextItem> retained = new ArrayList<>();
        int remaining = maxTotalChars;

        for (ContextItem item : rankedItems) {
            if (item.source() == ContextSource.RAG_DOCUMENT) {
                continue;
            }
            if (remaining == 0) {
                break;
            }
            ContextItem fitted = fit(item, remaining);
            retained.add(fitted);
            remaining -= fitted.content().length();
        }

        if (remaining == 0) {
            return List.copyOf(retained);
        }

        for (ContextItem item : rankedItems) {
            if (item.source() != ContextSource.RAG_DOCUMENT) {
                continue;
            }
            if (remaining == 0) {
                break;
            }
            int itemBudget = Math.min(maxRagItemChars, remaining);
            ContextItem fitted = fit(item, itemBudget);
            if (!fitted.content().isEmpty()) {
                retained.add(fitted);
                remaining -= fitted.content().length();
            }
        }
        return List.copyOf(retained);
    }

    public int maxTotalChars() {
        return maxTotalChars;
    }

    private static ContextItem fit(ContextItem item, int availableChars) {
        if (item.content().length() <= availableChars) {
            return item.withContent(item.content());
        }
        return item.withContent(item.content().substring(0, availableChars));
    }
}
