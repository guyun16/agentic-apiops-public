package com.apiops.openapi.application;

import com.apiops.openapi.parser.ParsedOpenApiDocument;

public record OpenApiImportResult(
        long projectId,
        String sourceKey,
        String filename,
        long fileSize,
        String contentHash,
        ParsedOpenApiDocument parsedDocument,
        String apiDocId,
        int versionNo,
        boolean existing
) {
    public OpenApiImportResult(
            long projectId,
            String sourceKey,
            String filename,
            long fileSize,
            String contentHash,
            ParsedOpenApiDocument parsedDocument
    ) {
        this(projectId, sourceKey, filename, fileSize, contentHash,
                parsedDocument, null, 0, false);
    }
}
