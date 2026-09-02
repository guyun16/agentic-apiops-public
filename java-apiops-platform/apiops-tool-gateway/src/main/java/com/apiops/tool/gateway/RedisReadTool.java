package com.apiops.tool.gateway;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.common.tool.ToolResult;

import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/** Stable redis.read contract and adapter to ToolGateway. */
public final class RedisReadTool {
    private RedisReadTool() {}

    public static ToolDefinition definition() {
        return ToolDefinition.withParameterContracts(
                RedisGuard.TOOL_NAME,
                "Read bounded Stage 9 task-progress evidence from Redis",
                Set.of("TOOL_READ"),
                Set.of(ProjectRole.OWNER, ProjectRole.EDITOR, ProjectRole.VIEWER),
                Map.of(
                        "command", ToolDefinition.ParameterContract.enumValues(
                                String.class, RedisGuard.READ_COMMANDS),
                        "keys", ToolDefinition.ParameterContract.length(
                                List.class, 1, RedisGuard.MAX_KEYS),
                        "fields", ToolDefinition.ParameterContract.length(
                                List.class, 0, RedisGuard.MAX_FIELDS)
                ));
    }

    public static void register(ToolRegistry registry) { registry.register(definition()); }

    public static ToolResult<Object> execute(ToolGateway gateway, RedisReadExecutor executor,
                                             ToolExecutionContext context, ToolCallIntent intent) {
        Objects.requireNonNull(gateway);
        Objects.requireNonNull(executor);
        return gateway.execute(context, intent, executor::execute);
    }
}
