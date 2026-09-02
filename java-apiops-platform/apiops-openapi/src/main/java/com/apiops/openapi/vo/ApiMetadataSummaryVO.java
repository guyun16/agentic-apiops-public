package com.apiops.openapi.vo;

import com.fasterxml.jackson.databind.JsonNode;

public record ApiMetadataSummaryVO(
        String apiId,
        String apiDocId,
        String operationId,
        String method,
        String path,
        String summary,
        JsonNode tags,
        boolean deprecated
) {
}
