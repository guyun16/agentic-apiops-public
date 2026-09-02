package com.apiops.tool.gateway;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;

import java.util.Objects;

/** Execution-time authorization; the model intent is never an authority source. */
public final class ToolAuth {

    private final ToolRegistry registry;
    private final ProjectAuthorizationService authorizationService;

    public ToolAuth(
            ToolRegistry registry,
            ProjectAuthorizationService authorizationService
    ) {
        this.registry = Objects.requireNonNull(registry, "registry must not be null");
        this.authorizationService = Objects.requireNonNull(
                authorizationService, "authorizationService must not be null");
    }

    public Decision authorize(
            ToolExecutionContext context,
            ToolCallIntent intent
    ) {
        if (context == null) {
            return Decision.denied("trusted execution context is required");
        }
        if (intent == null) {
            return Decision.denied("tool intent is required");
        }

        ToolDefinition definition;
        try {
            definition = registry.lookup(intent);
        } catch (RuntimeException exception) {
            return Decision.denied("unknown tool");
        }

        ProjectRole projectRole;
        try {
            projectRole = authorizationService
                    .findProjectRole(context.userId(), context.projectId())
                    .orElse(null);
        } catch (RuntimeException exception) {
            return Decision.denied("project authorization unavailable");
        }

        if (projectRole == null || !definition.isAllowedFor(context, projectRole)) {
            return Decision.denied("tool access denied");
        }
        return Decision.allowed(definition);
    }

    /**
     * Resolves a registry-owned name for metrics without exposing arbitrary model
     * input as a label value.
     */
    String metricToolName(String requestedToolName) {
        if (requestedToolName == null) {
            return "unknown";
        }
        try {
            return registry.lookup(requestedToolName).name();
        } catch (RuntimeException exception) {
            return "unknown";
        }
    }

    public record Decision(
            boolean allowed,
            ToolDefinition definition,
            String reason
    ) {

        public Decision {
            reason = Objects.requireNonNull(reason, "reason must not be null");
        }

        static Decision allowed(ToolDefinition definition) {
            return new Decision(true, Objects.requireNonNull(definition), "allowed");
        }

        static Decision denied(String reason) {
            return new Decision(false, null, reason);
        }
    }
}
