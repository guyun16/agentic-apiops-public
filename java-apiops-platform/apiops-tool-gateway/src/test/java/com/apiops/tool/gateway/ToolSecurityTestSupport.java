package com.apiops.tool.gateway;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.ProjectMembershipRepository;

import java.time.Duration;
import java.util.Optional;
import java.util.Set;

final class ToolSecurityTestSupport {
    static final long USER_ID = 7L;
    static final long PROJECT_ID = 42L;

    private ToolSecurityTestSupport() {}

    static Bundle gateway(ToolDefinition definition, ResourceGuard guard) {
        return gateway(definition, guard, (userId, projectId) ->
                userId == USER_ID && projectId == PROJECT_ID
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
    }

    static Bundle gateway(
            ToolDefinition definition,
            ResourceGuard guard,
            ProjectMembershipRepository membershipRepository) {
        ProjectAuthorizationService auth = new ProjectAuthorizationService(
                membershipRepository);
        ToolRegistry registry = new ToolRegistry(auth);
        registry.register(definition);
        Audit audit = new Audit();
        ToolGateway gateway = new ToolGateway(
                new ToolAuth(registry, auth), new ParamValidator(), guard,
                new ToolExecutionLimiter(Duration.ofSeconds(3), 50, 2),
                new ResultSanitizer(), new ResultLimiter(100_000), audit, new Metrics());
        return new Bundle(gateway, audit);
    }

    static ToolExecutionContext context(String runId) {
        return new ToolExecutionContext(USER_ID, PROJECT_ID, Set.of("TOOL_READ"),
                "caller-id", runId);
    }

    record Bundle(ToolGateway gateway, Audit audit) implements AutoCloseable {
        @Override public void close() { gateway.close(); }
    }
}
