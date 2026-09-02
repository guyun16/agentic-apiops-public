package com.apiops.tool.gateway;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.common.tool.ToolResult;

import java.util.Map;
import java.util.Objects;
import java.util.Set;

/** Stable logical log.search contract; no path argument exists. */
public final class LogSearchTool {
    private LogSearchTool() {}

    public static ToolDefinition definition() {
        return ToolDefinition.withParameterContracts(
                LogGuard.TOOL_NAME,
                "Search bounded untrusted diagnostic evidence from an allowlisted service log",
                Set.of("TOOL_READ"),
                Set.of(ProjectRole.OWNER, ProjectRole.EDITOR, ProjectRole.VIEWER),
                Map.of(
                        "service", ToolDefinition.ParameterContract.length(String.class, 1, 64),
                        "query", ToolDefinition.ParameterContract.length(
                                String.class, 1, LogGuard.MAX_QUERY_LENGTH),
                        "fromEpochMillis", ToolDefinition.ParameterContract.of(Number.class),
                        "toEpochMillis", ToolDefinition.ParameterContract.of(Number.class),
                        "maxLines", ToolDefinition.ParameterContract.range(
                                Number.class, 1, LogGuard.MAX_LINES)
                ));
    }

    public static void register(ToolRegistry registry) { registry.register(definition()); }

    public static ToolResult<Object> execute(ToolGateway gateway, LogSearchExecutor executor,
                                             ToolExecutionContext context, ToolCallIntent intent) {
        Objects.requireNonNull(gateway); Objects.requireNonNull(executor);
        return gateway.execute(context, intent, executor::execute);
    }
}
