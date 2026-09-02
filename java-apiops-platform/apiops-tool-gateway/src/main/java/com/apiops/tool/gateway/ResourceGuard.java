package com.apiops.tool.gateway;

import com.apiops.auth.application.ProjectAuthorizationService;

import java.util.Objects;

/** Extension point for tool-specific resource safety rules. */
@FunctionalInterface
public interface ResourceGuard {

    Decision check(
            ToolExecutionContext context,
            ToolDefinition definition,
            ToolCallIntent intent
    );

    static ResourceGuard allowAll() {
        return (context, definition, intent) -> Decision.allow();
    }

    /**
     * Authorizes the requested RAG project after ToolAuth has authorized the
     * trusted current project and before the retriever is invoked.
     */
    public static ResourceGuard projectReadable(ProjectAuthorizationService authorizationService) {
        Objects.requireNonNull(authorizationService, "authorizationService must not be null");
        return (context, definition, intent) -> {
            if (definition == null || !RagSearchTool.TOOL_NAME.equals(definition.name())) {
                return Decision.allow();
            }
            final long targetProjectId;
            try {
                targetProjectId = RagSearchTool.effectiveProjectId(context, intent);
            } catch (RuntimeException exception) {
                return Decision.reject("requested target project is invalid");
            }
            try {
                return authorizationService.findProjectRole(context.userId(), targetProjectId)
                        .isPresent()
                        ? Decision.allow()
                        : Decision.reject("requested target project access denied");
            } catch (RuntimeException exception) {
                return Decision.reject("requested target project authorization unavailable");
            }
        };
    }

    static ResourceGuard allOf(ResourceGuard... guards) {
        if (guards == null || guards.length == 0) {
            throw new IllegalArgumentException("at least one resource guard is required");
        }
        ResourceGuard[] copy = guards.clone();
        for (ResourceGuard guard : copy) {
            java.util.Objects.requireNonNull(guard, "resource guard must not be null");
        }
        return (context, definition, intent) -> {
            for (ResourceGuard guard : copy) {
                Decision decision = guard.check(context, definition, intent);
                if (decision == null || !decision.allowed()) {
                    return decision == null
                            ? Decision.reject("resource guard rejected")
                            : decision;
                }
            }
            return Decision.allow();
        };
    }

    record Decision(boolean allowed, String reason) {

        public Decision {
            if (reason == null || reason.isBlank()) {
                throw new IllegalArgumentException("guard reason must not be blank");
            }
        }

        public static Decision allow() {
            return new Decision(true, "allowed");
        }

        public static Decision reject(String reason) {
            return new Decision(false, reason);
        }
    }
}
