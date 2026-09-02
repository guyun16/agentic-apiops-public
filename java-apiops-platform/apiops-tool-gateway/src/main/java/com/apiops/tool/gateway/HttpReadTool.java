package com.apiops.tool.gateway;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.common.tool.ToolResult;

import java.util.Map;
import java.util.Objects;
import java.util.Set;

/** Stable http.read contract; it does not expose Stage 8 raw HttpTransport. */
public final class HttpReadTool {
    private HttpReadTool() {}

    public static ToolDefinition definition() {
        return ToolDefinition.withParameterContracts(
                HttpGuard.TOOL_NAME,
                "Read an exact server-allowlisted diagnostic HTTP endpoint",
                Set.of("TOOL_READ"),
                Set.of(ProjectRole.OWNER, ProjectRole.EDITOR, ProjectRole.VIEWER),
                Map.of(
                        "method", ToolDefinition.ParameterContract.enumValues(
                                String.class, HttpGuard.METHODS),
                        "url", ToolDefinition.ParameterContract.length(String.class, 1, 2_048),
                        "headers", ToolDefinition.ParameterContract.of(Map.class)
                ));
    }

    public static void register(ToolRegistry registry) { registry.register(definition()); }

    public static ToolResult<Object> execute(ToolGateway gateway, HttpReadExecutor executor,
                                             ToolExecutionContext context, ToolCallIntent intent) {
        Objects.requireNonNull(gateway); Objects.requireNonNull(executor);
        return gateway.execute(context, intent, executor::execute);
    }
}
