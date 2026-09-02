package com.apiops.tool.gateway;

import com.apiops.auth.security.ApiOpsPrincipal;
import org.springframework.security.core.GrantedAuthority;

import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.Objects;
import java.util.Set;

/** Java-owned identity, authority, run, and model-call context; model arguments are never copied here. */
public record ToolExecutionContext(
        long userId,
        long projectId,
        Set<String> authorities,
        String toolCallId,
        String agentRunId,
        String modelCallId
) {

    public ToolExecutionContext(
            long userId,
            long projectId,
            Set<String> authorities,
            String toolCallId
    ) {
        this(userId, projectId, authorities, toolCallId,
                "legacy-run:" + toolCallId,
                "legacy-model-call:" + toolCallId);
    }

    public ToolExecutionContext(
            long userId,
            long projectId,
            Set<String> authorities,
            String toolCallId,
            String agentRunId
    ) {
        this(userId, projectId, authorities, toolCallId, agentRunId,
                "legacy-model-call:" + toolCallId);
    }

    public ToolExecutionContext {
        if (userId <= 0 || projectId <= 0) {
            throw new IllegalArgumentException("userId and projectId must be positive");
        }
        authorities = normalizeAuthorityNames(authorities);
        toolCallId = requireText(toolCallId, "toolCallId");
        agentRunId = requireText(agentRunId, "agentRunId");
        modelCallId = requireText(modelCallId, "modelCallId");
    }

    /** Builds trusted context from the authenticated Java principal. */
    public static ToolExecutionContext fromPrincipal(
            ApiOpsPrincipal principal,
            long projectId,
            String toolCallId
    ) {
        Objects.requireNonNull(principal, "principal must not be null");
        return new ToolExecutionContext(
                principal.getUserId(),
                projectId,
                normalizeGrantedAuthorities(principal.getAuthorities()),
                toolCallId,
                "legacy-run:" + toolCallId,
                "legacy-model-call:" + toolCallId
        );
    }

    /** Builds trusted context with an explicit Java-owned Agent Run budget key. */
    public static ToolExecutionContext fromPrincipal(
            ApiOpsPrincipal principal,
            long projectId,
            String toolCallId,
            String agentRunId
    ) {
        Objects.requireNonNull(principal, "principal must not be null");
        return new ToolExecutionContext(
                principal.getUserId(),
                projectId,
                normalizeGrantedAuthorities(principal.getAuthorities()),
                toolCallId,
                agentRunId,
                "legacy-model-call:" + toolCallId
        );
    }

    /** Builds trusted context when the Java model boundary already has a model call identity. */
    public static ToolExecutionContext fromPrincipal(
            ApiOpsPrincipal principal,
            long projectId,
            String toolCallId,
            String agentRunId,
            String modelCallId
    ) {
        Objects.requireNonNull(principal, "principal must not be null");
        return new ToolExecutionContext(
                principal.getUserId(),
                projectId,
                normalizeGrantedAuthorities(principal.getAuthorities()),
                toolCallId,
                agentRunId,
                modelCallId
        );
    }

    /** Returns a copy with a gateway-generated call id and the same trusted identity. */
    public ToolExecutionContext withToolCallId(String generatedToolCallId) {
        return new ToolExecutionContext(
                userId,
                projectId,
                authorities,
                generatedToolCallId,
                agentRunId,
                modelCallId
        );
    }

    private static Set<String> normalizeAuthorityNames(
            Collection<? extends String> values
    ) {
        if (values == null || values.isEmpty()) {
            return Set.of();
        }
        Set<String> normalized = new LinkedHashSet<>();
        for (String value : values) {
            normalized.add(requireText(value, "authority"));
        }
        return Set.copyOf(normalized);
    }

    private static Set<String> normalizeGrantedAuthorities(
            Collection<? extends GrantedAuthority> values
    ) {
        if (values == null || values.isEmpty()) {
            return Set.of();
        }
        Set<String> normalized = new LinkedHashSet<>();
        for (GrantedAuthority authority : values) {
            Objects.requireNonNull(authority, "authority must not be null");
            normalized.add(requireText(authority.getAuthority(), "authority"));
        }
        return Set.copyOf(normalized);
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
