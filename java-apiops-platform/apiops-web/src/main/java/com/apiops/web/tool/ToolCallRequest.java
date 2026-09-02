package com.apiops.web.tool;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/** Shared ToolCall 0.2 invocation request; execution identity is Java-owned. */
@JsonIgnoreProperties(ignoreUnknown = false)
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ToolCallRequest(
        String schemaVersion,
        String agentRunId,
        String agentStepId,
        String projectId,
        String toolName,
        Map<String, Object> params,
        String traceId,
        @JsonProperty(access = JsonProperty.Access.WRITE_ONLY) String toolCallId
) {
    public ToolCallRequest {
        params = params == null
                ? null
                : Collections.unmodifiableMap(new LinkedHashMap<>(params));
    }
}
