package com.apiops.web.tool;

import com.apiops.common.tool.ToolResult;
import com.apiops.tool.gateway.RedisReadTool;
import com.apiops.tool.gateway.ToolCallIntent;

import java.util.Map;

/** Sole mapper between the shared public contract and Java's internal Gateway intent. */
final class ToolGatewayContractMapper {

    static final String TOOL_CALL_SCHEMA_VERSION = "0.2.0";
    static final String TOOL_RESULT_SCHEMA_VERSION = "0.1.0";

    private static final Map<String, String> PUBLIC_TO_INTERNAL_TOOL = Map.of(
            "openapi.metadata.read", "metadata.read",
            "testcase.validate", "testcase.validate",
            "runner.submit", "runner.submit",
            "report.read", "report.read",
            "sql.read", "sql.read",
            "redis.read", "redis.read",
            "log.search", "log.search",
            "rag.search", "rag.search");

    String validationError(ToolCallRequest request, long pathProjectId, String traceId) {
        if (request == null) {
            return "tool call request is required";
        }
        if (!TOOL_CALL_SCHEMA_VERSION.equals(request.schemaVersion())) {
            return "unsupported ToolCall schemaVersion";
        }
        if (request.toolCallId() != null) {
            return "caller toolCallId is forbidden";
        }
        if (!hasText(request.agentRunId()) || !hasText(request.projectId())
                || !hasText(request.toolName()) || request.params() == null
                || !hasText(request.traceId())) {
            return "required ToolCall field is missing";
        }
        if (request.agentStepId() != null && !hasText(request.agentStepId())) {
            return "agentStepId must not be blank";
        }
        if (!Long.toString(pathProjectId).equals(request.projectId())) {
            return "ToolCall projectId does not match the trusted path scope";
        }
        if (!request.traceId().equals(traceId)) {
            return "ToolCall traceId does not match the request trace";
        }
        if (!PUBLIC_TO_INTERNAL_TOOL.containsKey(request.toolName())) {
            return "unknown canonical tool name";
        }
        return null;
    }

    ToolCallIntent toInternalIntent(ToolCallRequest request, long trustedProjectId) {
        ToolCallIntent intent = new ToolCallIntent(
                PUBLIC_TO_INTERNAL_TOOL.get(request.toolName()),
                request.params());
        return RedisReadTool.normalizePublicIntent(trustedProjectId, intent);
    }

    ToolCallIntent invalidAuditIntent(ToolCallRequest request) {
        String name = request == null || !hasText(request.toolName())
                ? "invalid.contract"
                : request.toolName();
        Map<String, Object> params = request == null || request.params() == null
                ? Map.of()
                : request.params();
        return new ToolCallIntent(name, params);
    }

    ToolResultResponse toPublicResult(ToolResult<Object> result, String traceId) {
        Map<String, Object> error = result.isSuccess()
                ? null
                : Map.of("code", result.getCode(), "message", result.getMessage());
        return new ToolResultResponse(
                TOOL_RESULT_SCHEMA_VERSION,
                result.getToolCallId(),
                result.getStatus().name(),
                result.getData(),
                error,
                true,
                traceId);
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }
}
