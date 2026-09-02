package com.apiops.tool.gateway;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.common.tool.ToolResult;

import java.util.Map;
import java.util.Objects;
import java.util.Set;

/** Stable sql.read definition and adapter to the existing ToolGateway. */
public final class SqlReadTool {

    private SqlReadTool() {
    }

    public static ToolDefinition definition() {
        return new ToolDefinition(
                SqlGuard.SQL_READ,
                "Read allowlisted diagnostic columns from the project datasource",
                Set.of("TOOL_READ"),
                Set.of(ProjectRole.OWNER, ProjectRole.EDITOR, ProjectRole.VIEWER),
                Map.of(SqlGuard.SQL_ARGUMENT, String.class)
        );
    }

    public static void register(ToolRegistry registry) {
        Objects.requireNonNull(registry, "registry must not be null").register(definition());
    }

    public static ToolResult<Object> execute(
            ToolGateway gateway,
            SqlReadExecutor executor,
            ToolExecutionContext context,
            ToolCallIntent intent
    ) {
        Objects.requireNonNull(gateway, "gateway must not be null");
        Objects.requireNonNull(executor, "executor must not be null");
        return gateway.execute(context, intent, executor::execute);
    }
}
