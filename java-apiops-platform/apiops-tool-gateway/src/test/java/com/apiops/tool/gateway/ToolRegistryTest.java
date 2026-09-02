package com.apiops.tool.gateway;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.common.enums.ToolStatus;
import com.apiops.common.tool.ToolResult;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ToolRegistryTest {

    private static final long USER_ID = 7L;
    private static final long PROJECT_ID = 42L;

    @Test
    void rejectsDuplicateRegistrationAndUnknownLookup() {
        ToolRegistry registry = registry((userId, projectId) -> Optional.of(ProjectRole.VIEWER));
        ToolDefinition definition = definition("rag.search");
        registry.register(definition);

        assertThrows(IllegalArgumentException.class, () -> registry.register(definition));
        assertThrows(IllegalArgumentException.class, () -> registry.lookup("missing.tool"));
    }

    @Test
    void diagnosisDiscoversExactlyItsFourStableContracts() {
        ToolRegistry registry = registry((userId, projectId) -> Optional.of(ProjectRole.VIEWER));
        registerAll(registry);

        assertEquals(Set.of("rag.search", "sql.read", "redis.read", "log.search"),
                names(registry.discover(context(Set.of()), ToolRegistry.DIAGNOSIS)));
    }

    @Test
    void generateTestCaseDiscoversOnlyMetadataReadFixture() {
        ToolRegistry registry = registry((userId, projectId) -> Optional.of(ProjectRole.EDITOR));
        registerAll(registry);

        assertEquals(Set.of("metadata.read"),
                names(registry.discover(context(Set.of()), ToolRegistry.GENERATE_TEST_CASE)));
    }

    @Test
    void agentFilterCannotRestoreUserOrProjectDeniedTools() {
        ToolRegistry userDenied = registry((userId, projectId) -> Optional.of(ProjectRole.VIEWER));
        userDenied.register(new ToolDefinition(
                "sql.read", "Read SQL evidence", Set.of("TOOL_SQL_READ")));
        userDenied.register(definition("rag.search"));
        assertEquals(Set.of("rag.search"),
                names(userDenied.discover(context(Set.of()), ToolRegistry.DIAGNOSIS)));

        ToolRegistry projectDenied = registry((userId, projectId) -> Optional.empty());
        projectDenied.register(definition("rag.search"));
        assertTrue(projectDenied.discover(context(Set.of()), ToolRegistry.DIAGNOSIS).isEmpty());
    }

    @Test
    void nullUnknownAndUnconfiguredAgentTypesDiscoverNothing() {
        ToolRegistry registry = registry((userId, projectId) -> Optional.of(ProjectRole.VIEWER));
        registerAll(registry);
        ToolExecutionContext context = context(Set.of());

        assertTrue(registry.discover(context, null).isEmpty());
        assertTrue(registry.discover(context, "UNKNOWN").isEmpty());
        assertTrue(registry.discover(context, "").isEmpty());
    }

    @Test
    void modelProjectIdArgumentCannotOverrideTrustedContext() {
        AtomicLong authorizedProjectId = new AtomicLong();
        ToolRegistry registry = registry((userId, projectId) -> {
            authorizedProjectId.set(projectId);
            return projectId == PROJECT_ID ? Optional.of(ProjectRole.VIEWER) : Optional.empty();
        });
        registry.register(definition("rag.search"));

        ToolCallIntent intent = new ToolCallIntent(
                "rag.search", Map.of("projectId", 999L, "query", "failure"));
        ToolExecutionContext trusted = context(Set.of());

        assertEquals("rag.search", registry.lookup(intent).name());
        assertEquals(Set.of("rag.search"),
                names(registry.discover(trusted, ToolRegistry.DIAGNOSIS)));
        assertEquals(PROJECT_ID, authorizedProjectId.get());

        ToolResult<String> result = ToolResult.success(
                intent.toolName(), trusted.toolCallId(), "trusted-project-result");
        assertEquals(ToolStatus.SUCCESS, result.getStatus());
        assertEquals("tool-call-from-java", result.getToolCallId());
        assertEquals(PROJECT_ID, trusted.projectId());
    }

    private static ToolRegistry registry(ProjectMembershipRepository membership) {
        return new ToolRegistry(new ProjectAuthorizationService(membership));
    }

    private static void registerAll(ToolRegistry registry) {
        registry.register(definition("rag.search"));
        registry.register(definition("sql.read"));
        registry.register(definition("redis.read"));
        registry.register(definition("log.search"));
        registry.register(definition("metadata.read"));
    }

    private static ToolDefinition definition(String name) {
        return new ToolDefinition(name, "Test-only discovery definition");
    }

    private static ToolExecutionContext context(Set<String> authorities) {
        return new ToolExecutionContext(USER_ID, PROJECT_ID, authorities, "tool-call-from-java");
    }

    private static Set<String> names(List<ToolDefinition> definitions) {
        return definitions.stream().map(ToolDefinition::name).collect(java.util.stream.Collectors.toSet());
    }
}
