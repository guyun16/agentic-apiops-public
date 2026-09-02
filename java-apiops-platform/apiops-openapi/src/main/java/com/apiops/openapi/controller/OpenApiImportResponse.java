package com.apiops.openapi.controller;

public record OpenApiImportResponse(
        long projectId,
        String sourceKey,
        String filename,
        long fileSize,
        String contentHash,
        String openapiVersion
) {
}
