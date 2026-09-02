package com.apiops.tool.gateway;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Registry and discovery boundary for stable tool definitions.
 *
 * <p>Discovery is visibility shaping only. The agent allowlist is not
 * execution-time authorization; an execution boundary must still authorize
 * every call with the trusted context.</p>
 */
public final class ToolRegistry {

    public static final String DIAGNOSIS = "DIAGNOSIS";
    public static final String GENERATE_TEST_CASE = "GENERATE_TEST_CASE";

    private static final Map<String, Set<String>> AGENT_ALLOWLIST = Map.of(
            DIAGNOSIS, Set.of("rag.search", "sql.read", "redis.read", "log.search"),
            GENERATE_TEST_CASE, Set.of("metadata.read")
    );

    private final ProjectAuthorizationService authorizationService;
    private final Map<String, ToolDefinition> definitions = new LinkedHashMap<>();

    public ToolRegistry(ProjectAuthorizationService authorizationService) {
        this.authorizationService = Objects.requireNonNull(
                authorizationService, "authorizationService must not be null");
    }

    public void register(ToolDefinition definition) {
        Objects.requireNonNull(definition, "definition must not be null");
        if (definitions.putIfAbsent(definition.name(), definition) != null) {
            throw new IllegalArgumentException(
                    "Tool already registered: " + definition.name());
        }
    }

    public ToolDefinition lookup(String toolName) {
        ToolDefinition definition = definitions.get(toolName);
        if (definition == null) {
            throw new IllegalArgumentException("Unknown tool: " + toolName);
        }
        return definition;
    }

    public ToolDefinition lookup(ToolCallIntent intent) {
        Objects.requireNonNull(intent, "intent must not be null");
        return lookup(intent.toolName());
    }

    public List<ToolDefinition> discover(
            ToolExecutionContext context,
            String agentType
    ) {
        if (agentType == null) {
            return List.of();
        }
        Set<String> agentAllowed = AGENT_ALLOWLIST.get(agentType);
        if (agentAllowed == null) {
            return List.of();
        }
        Objects.requireNonNull(context, "context must not be null");

        ProjectRole projectRole = authorizationService
                .findProjectRole(context.userId(), context.projectId())
                .orElse(null);
        if (projectRole == null) {
            return List.of();
        }

        List<ToolDefinition> userProjectAllowed = definitions.values().stream()
                .filter(definition -> definition.isAllowedFor(context, projectRole))
                .toList();
        return userProjectAllowed.stream()
                .filter(definition -> agentAllowed.contains(definition.name()))
                .toList();
    }

    public static Map<String, Set<String>> agentAllowlist() {
        return AGENT_ALLOWLIST;
    }
}
