package com.apiops.tool.gateway;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.common.tool.ToolResult;

import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Stable redis.read contract and adapter to ToolGateway. */
public final class RedisReadTool {
    private static final Pattern LOGICAL_PROGRESS_KEY =
            Pattern.compile("runner:([1-9][0-9]{0,18})");

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

    /**
     * Normalize the single public logical alias without weakening the physical contract.
     *
     * <p>The caller can name only a positive runner id. Java supplies the trusted project
     * namespace and the fixed read operation. Invalid, mixed, or extra arguments are left
     * unchanged so the existing {@link ParamValidator} returns PARAM_INVALID.
     */
    public static ToolCallIntent normalizePublicIntent(
            long trustedProjectId,
            ToolCallIntent intent
    ) {
        Objects.requireNonNull(intent, "intent must not be null");
        if (!RedisGuard.TOOL_NAME.equals(intent.toolName())
                || !intent.arguments().keySet().equals(Set.of("key"))) {
            return intent;
        }
        Object rawKey = intent.arguments().get("key");
        if (!(rawKey instanceof String logicalKey)) {
            return intent;
        }
        Matcher match = LOGICAL_PROGRESS_KEY.matcher(logicalKey);
        if (!match.matches()) {
            return intent;
        }
        long runId;
        try {
            runId = Long.parseLong(match.group(1));
        } catch (NumberFormatException ignored) {
            return intent;
        }
        return new ToolCallIntent(
                RedisGuard.TOOL_NAME,
                Map.of(
                        "command", "HGET",
                        "keys", List.of(RedisGuard.projectPrefix(trustedProjectId) + runId),
                        "fields", List.of("status")
                ));
    }

    public static ToolResult<Object> execute(ToolGateway gateway, RedisReadExecutor executor,
                                             ToolExecutionContext context, ToolCallIntent intent) {
        Objects.requireNonNull(gateway);
        Objects.requireNonNull(executor);
        return gateway.execute(context, intent, executor::execute);
    }
}
