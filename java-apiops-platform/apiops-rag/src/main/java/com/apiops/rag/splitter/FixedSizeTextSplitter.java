package com.apiops.rag.splitter;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/** Deterministic character-window splitter with fixed overlap. */
public final class FixedSizeTextSplitter implements TextSplitter {

    private final TextSplitterConfig config;

    public FixedSizeTextSplitter(TextSplitterConfig config) {
        this.config = Objects.requireNonNull(config, "config must not be null");
    }

    @Override
    public List<String> split(String text) {
        if (text == null || text.isBlank()) {
            return List.of();
        }
        String value = text.strip();
        List<String> chunks = new ArrayList<>();
        int step = config.chunkSize() - config.chunkOverlap();
        for (int start = 0; start < value.length(); start += step) {
            int end = Math.min(start + config.chunkSize(), value.length());
            String chunk = value.substring(start, end);
            if (!chunk.isBlank()) {
                chunks.add(chunk);
            }
            if (end == value.length()) {
                break;
            }
        }
        return List.copyOf(chunks);
    }
}
