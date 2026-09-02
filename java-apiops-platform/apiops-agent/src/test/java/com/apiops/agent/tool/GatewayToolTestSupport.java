package com.apiops.agent.tool;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.tool.gateway.ResultLimiter;
import com.apiops.tool.gateway.ResultSanitizer;
import com.apiops.tool.gateway.ResourceGuard;
import com.apiops.tool.gateway.ToolAuth;
import com.apiops.tool.gateway.ToolDefinition;
import com.apiops.tool.gateway.ToolExecutionContext;
import com.apiops.tool.gateway.ToolExecutionLimiter;
import com.apiops.tool.gateway.ToolGateway;
import com.apiops.tool.gateway.ToolRegistry;
import com.apiops.tool.gateway.ParamValidator;
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.Metrics;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.time.Duration;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/** Test-only construction of the Stage 11 assertion callback through the Gateway. */
public final class GatewayToolTestSupport {

    public static final long USER_ID = 7L;
    public static final long PROJECT_ID = 42L;

    private GatewayToolTestSupport() {
    }

    public static Bundle assertionTypeCallback(
            ToolExecutionContext trustedContext,
            ToolGateway.ToolHandler handler
    ) {
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> userId == trustedContext.userId()
                        && projectId == trustedContext.projectId()
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
        ToolDefinition definition = new ToolDefinition(
                "isAllowedAssertionType",
                "Check whether a Stage 7 assertion type is allowed",
                Set.of("TOOL_READ"),
                Set.of(ProjectRole.VIEWER),
                Map.of("type", String.class));
        ToolRegistry registry = new ToolRegistry(authorization);
        registry.register(definition);
        ToolGateway gateway = new ToolGateway(
                new ToolAuth(registry, authorization),
                new ParamValidator(),
                ResourceGuard.allowAll(),
                new ToolExecutionLimiter(Duration.ofSeconds(3), 50, 2),
                new ResultSanitizer(),
                new ResultLimiter(100_000),
                new Audit(),
                new Metrics());
        GatewayToolCallbackAdapter callback = new GatewayToolCallbackAdapter(
                gateway,
                definition,
                () -> trustedContext,
                handler,
                new ObjectMapper());
        return new Bundle(gateway, callback);
    }

    public record Bundle(ToolGateway gateway, GatewayToolCallbackAdapter callback)
            implements AutoCloseable {
        @Override
        public void close() {
            gateway.close();
        }
    }
}
