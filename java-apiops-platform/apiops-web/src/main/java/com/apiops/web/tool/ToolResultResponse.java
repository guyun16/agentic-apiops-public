package com.apiops.web.tool;

import java.util.Map;

/** Exact REST view of the shared ToolResult 0.1 contract. */
public record ToolResultResponse(
        String schemaVersion,
        String toolCallId,
        String status,
        Object data,
        Map<String, Object> error,
        boolean sanitized,
        String traceId
) {
}
