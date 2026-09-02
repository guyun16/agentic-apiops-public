package com.apiops.rag.application;

import java.util.Arrays;

public record DocumentIngestionInput(
        String sourceKey,
        String sourceType,
        String title,
        String fileName,
        String mediaType,
        byte[] content
) {
    public DocumentIngestionInput {
        content = content == null ? null : Arrays.copyOf(content, content.length);
    }

    @Override
    public byte[] content() {
        return content == null ? null : Arrays.copyOf(content, content.length);
    }
}
