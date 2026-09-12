package com.apiops.web.tool;

import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.common.tool.ToolResult;
import com.apiops.tool.gateway.ToolCallIntent;
import com.apiops.tool.gateway.ToolExecutionContext;
import com.apiops.tool.gateway.ToolGateway;
import org.slf4j.MDC;
import org.springframework.security.core.GrantedAuthority;

import java.util.LinkedHashMap;
import java.util.Collection;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/** Project-scoped HTTP adapter for the existing ToolGateway boundary. */
public final class ToolGatewayRestApplicationService {

    private final ToolGateway gateway;
    private final Map<String, ToolGateway.ToolHandler> handlers;
    private final ToolGatewayContractMapper contractMapper = new ToolGatewayContractMapper();

    public ToolGatewayRestApplicationService(
            ToolGateway gateway,
            Map<String, ToolGateway.ToolHandler> handlers
    ) {
        this.gateway = Objects.requireNonNull(gateway, "gateway must not be null");
        this.handlers = Map.copyOf(new LinkedHashMap<>(
                Objects.requireNonNull(handlers, "handlers must not be null")));
    }

    public ToolResultResponse execute(
            ApiOpsPrincipal principal,
            long projectId,
            ToolCallRequest request
    ) {
        return execute(principal, projectId, request, principal.getAuthorities());
    }

    public ToolResultResponse execute(
            ApiOpsPrincipal principal,
            long projectId,
            ToolCallRequest request,
            Collection<? extends GrantedAuthority> authenticatedAuthorities
    ) {
        Objects.requireNonNull(principal, "principal must not be null");
        Objects.requireNonNull(authenticatedAuthorities,
                "authenticatedAuthorities must not be null");
        String requestId = valueOrGenerated(MDC.get("requestId"), "rest-request");
        String traceId = MDC.get("traceId");
        if (traceId == null || traceId.isBlank()) {
            traceId = request == null
                    ? valueOrGenerated(null, "rest-trace")
                    : valueOrGenerated(request.traceId(), "rest-trace");
        }
        ToolExecutionContext trustedContext = ToolExecutionContext.fromPrincipal(
                principal,
                projectId,
                "rest-context:" + UUID.randomUUID(),
                request == null || request.agentRunId() == null
                        ? "rest-run:" + requestId
                        : request.agentRunId(),
                "rest-model-call:" + UUID.randomUUID());
        trustedContext = new ToolExecutionContext(
                trustedContext.userId(),
                trustedContext.projectId(),
                authorityNames(authenticatedAuthorities),
                trustedContext.toolCallId(),
                trustedContext.agentRunId(),
                trustedContext.modelCallId());

        String validationError = contractMapper.validationError(request, projectId, traceId);
        if (validationError != null) {
            ToolResult<Object> invalid = gateway.invalidContract(
                    trustedContext,
                    contractMapper.invalidAuditIntent(request),
                    validationError);
            return contractMapper.toPublicResult(invalid, traceId);
        }

        ToolCallIntent intent = contractMapper.toInternalIntent(request, projectId);
        ToolGateway.ToolHandler handler = handlers.getOrDefault(
                intent.toolName(), unavailableHandler());
        return contractMapper.toPublicResult(
                gateway.execute(trustedContext, intent, handler),
                traceId);
    }

    private static Set<String> authorityNames(
            Collection<? extends GrantedAuthority> authenticatedAuthorities
    ) {
        return authenticatedAuthorities.stream()
                .map(GrantedAuthority::getAuthority)
                .filter(Objects::nonNull)
                .collect(java.util.stream.Collectors.toUnmodifiableSet());
    }

    private static ToolGateway.ToolHandler unavailableHandler() {
        return (ignoredContext, ignoredIntent) -> {
            throw new IllegalStateException("tool handler is not configured");
        };
    }

    private static String valueOrGenerated(String value, String prefix) {
        return value == null || value.isBlank()
                ? prefix + ":" + UUID.randomUUID()
                : value;
    }
}
