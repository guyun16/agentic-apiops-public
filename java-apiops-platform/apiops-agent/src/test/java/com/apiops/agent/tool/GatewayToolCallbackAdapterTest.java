package com.apiops.agent.tool;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.common.enums.ToolStatus;
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.ParamValidator;
import com.apiops.tool.gateway.ResourceGuard;
import com.apiops.tool.gateway.ResultLimiter;
import com.apiops.tool.gateway.ResultSanitizer;
import com.apiops.tool.gateway.ToolAuth;
import com.apiops.tool.gateway.ToolCallIntent;
import com.apiops.tool.gateway.ToolDefinition;
import com.apiops.tool.gateway.ToolExecutionContext;
import com.apiops.tool.gateway.ToolExecutionLimiter;
import com.apiops.tool.gateway.ToolGateway;
import com.apiops.tool.gateway.ToolRegistry;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class GatewayToolCallbackAdapterTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    void delegatesModelArgumentsToGatewayWithJavaTrustedContext() throws Exception {
        ToolDefinition definition = definition();
        ToolExecutionContext trusted = context(42L);
        ToolGateway gateway = gateway(definition, (userId, projectId) ->
                userId == trusted.userId() && projectId == trusted.projectId()
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
        AtomicReference<ToolExecutionContext> receivedContext = new AtomicReference<>();
        AtomicReference<ToolCallIntent> receivedIntent = new AtomicReference<>();
        try (gateway) {
            GatewayToolCallbackAdapter callback = new GatewayToolCallbackAdapter(
                    gateway,
                    definition,
                    () -> trusted,
                    (executionContext, intent) -> {
                        receivedContext.set(executionContext);
                        receivedIntent.set(intent);
                        return Map.of(
                                "trustedProjectId", executionContext.projectId(),
                                "trustedUserId", executionContext.userId(),
                                "query", intent.arguments().get("query"));
                    },
                    MAPPER);

            JsonNode result = MAPPER.readTree(callback.call("{\"query\":\"orders\"}"));

            assertEquals(ToolStatus.SUCCESS.name(), result.get("status").asText());
            assertEquals(42L, result.get("data").get("trustedProjectId").asLong());
            assertEquals(7L, result.get("data").get("trustedUserId").asLong());
            assertEquals("orders", result.get("data").get("query").asText());
            assertNotNull(receivedContext.get());
            assertEquals(7L, receivedContext.get().userId());
            assertEquals(42L, receivedContext.get().projectId());
            assertEquals("agent-run-42", receivedContext.get().agentRunId());
            assertNotNull(receivedContext.get().toolCallId());
            assertFalse(receivedContext.get().toolCallId().equals("caller-call"));
            assertEquals("test.read", receivedIntent.get().toolName());
            assertEquals(Map.of("query", "orders"), receivedIntent.get().arguments());
        }
    }

    @Test
    void modelProjectAndRoleArgumentsCannotOverrideTrustedContext() throws Exception {
        ToolDefinition definition = definition();
        ToolExecutionContext trusted = context(42L);
        ToolGateway gateway = gateway(definition, (userId, projectId) ->
                userId == trusted.userId() && projectId == trusted.projectId()
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
        AtomicInteger executions = new AtomicInteger();
        try (gateway) {
            GatewayToolCallbackAdapter callback = new GatewayToolCallbackAdapter(
                    gateway,
                    definition,
                    () -> trusted,
                    (executionContext, intent) -> {
                        executions.incrementAndGet();
                        return Map.of("projectId", executionContext.projectId());
                    },
                    MAPPER);

            JsonNode result = MAPPER.readTree(callback.call(
                    "{\"query\":\"orders\",\"projectId\":999,\"role\":\"OWNER\"}"));

            assertEquals(ToolStatus.PARAM_INVALID.name(), result.get("status").asText());
            assertEquals(0, executions.get());
        }
    }

    @Test
    void deniedContextStopsBeforeHandler() throws Exception {
        ToolDefinition definition = definition();
        ToolExecutionContext trusted = context(999L);
        ToolGateway gateway = gateway(definition, (userId, projectId) -> Optional.empty());
        AtomicInteger executions = new AtomicInteger();
        try (gateway) {
            GatewayToolCallbackAdapter callback = new GatewayToolCallbackAdapter(
                    gateway,
                    definition,
                    () -> trusted,
                    (executionContext, intent) -> {
                        executions.incrementAndGet();
                        return Map.of("unexpected", true);
                    },
                    MAPPER);

            JsonNode result = MAPPER.readTree(callback.call("{\"query\":\"orders\"}"));

            assertEquals(ToolStatus.FORBIDDEN.name(), result.get("status").asText());
            assertEquals(0, executions.get());
            assertNotNull(result.get("toolCallId"));
            assertTrue(!result.get("toolCallId").asText().isBlank());
        }
    }

    @Test
    void invalidArgumentsStopBeforeHandler() throws Exception {
        ToolDefinition definition = definition();
        ToolExecutionContext trusted = context(42L);
        ToolGateway gateway = gateway(definition, (userId, projectId) ->
                Optional.of(ProjectRole.VIEWER));
        AtomicInteger executions = new AtomicInteger();
        try (gateway) {
            GatewayToolCallbackAdapter callback = new GatewayToolCallbackAdapter(
                    gateway,
                    definition,
                    () -> trusted,
                    (executionContext, intent) -> {
                        executions.incrementAndGet();
                        return Map.of("unexpected", true);
                    },
                    MAPPER);

            JsonNode result = MAPPER.readTree(callback.call("{\"query\":7}"));

            assertEquals(ToolStatus.PARAM_INVALID.name(), result.get("status").asText());
            assertEquals(0, executions.get());
        }
    }

    @Test
    void exposesStableContractSchemaAndIgnoresSpringToolContext() throws Exception {
        ToolDefinition definition = definition();
        ToolExecutionContext trusted = context(42L);
        ToolGateway gateway = gateway(definition, (userId, projectId) ->
                Optional.of(ProjectRole.VIEWER));
        try (gateway) {
            GatewayToolCallbackAdapter callback = new GatewayToolCallbackAdapter(
                    gateway,
                    definition,
                    () -> trusted,
                    (executionContext, intent) -> Map.of("query", intent.arguments().get("query")),
                    MAPPER);

            // Spring AI's provider-facing function name is transport-safe; the
            // Gateway result still carries the stable test.read contract name.
            assertEquals("test_read", callback.getToolDefinition().name());
            JsonNode schema = MAPPER.readTree(callback.getToolDefinition().inputSchema());
            assertEquals(false, schema.get("additionalProperties").asBoolean());
            assertEquals("query", schema.get("required").get(0).asText());
            JsonNode result = MAPPER.readTree(callback.call(
                    "{\"query\":\"orders\"}", null));
            assertEquals(ToolStatus.SUCCESS.name(), result.get("status").asText());
            assertEquals("test.read", result.get("toolName").asText());
        }
    }

    @Test
    void adapterHasNoDirectResourceCallbackDependency() {
        for (Field field : GatewayToolCallbackAdapter.class.getDeclaredFields()) {
            String typeName = field.getType().getName();
            assertFalse(typeName.contains("RagRetriever"));
            assertFalse(typeName.contains("Repository"));
            assertFalse(typeName.contains("VectorStore"));
        }
    }

    private static ToolDefinition definition() {
        return new ToolDefinition(
                "test.read",
                "Test read tool",
                Set.of("TOOL_READ"),
                Set.of(ProjectRole.VIEWER),
                Map.of("query", String.class));
    }

    private static ToolExecutionContext context(long projectId) {
        return new ToolExecutionContext(
                7L,
                projectId,
                Set.of("TOOL_READ"),
                "caller-call",
                "agent-run-42");
    }

    private static ToolGateway gateway(
            ToolDefinition definition,
            ProjectMembershipRepository membership
    ) {
        ProjectAuthorizationService authorization =
                new ProjectAuthorizationService(membership);
        ToolRegistry registry = new ToolRegistry(authorization);
        registry.register(definition);
        return new ToolGateway(
                new ToolAuth(registry, authorization),
                new ParamValidator(),
                ResourceGuard.allowAll(),
                new ToolExecutionLimiter(Duration.ofSeconds(3), 50, 2),
                new ResultSanitizer(),
                new ResultLimiter(100_000),
                new Audit(),
                new com.apiops.tool.gateway.Metrics());
    }
}
