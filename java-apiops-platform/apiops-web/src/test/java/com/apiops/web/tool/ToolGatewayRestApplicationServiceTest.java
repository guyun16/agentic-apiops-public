package com.apiops.web.tool;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.Metrics;
import com.apiops.tool.gateway.ParamValidator;
import com.apiops.tool.gateway.RedisGuard;
import com.apiops.tool.gateway.RedisReadClient;
import com.apiops.tool.gateway.RedisReadExecutor;
import com.apiops.tool.gateway.RedisReadTool;
import com.apiops.tool.gateway.ResultLimiter;
import com.apiops.tool.gateway.ResultSanitizer;
import com.apiops.tool.gateway.ToolAuth;
import com.apiops.tool.gateway.ToolGateway;
import com.apiops.tool.gateway.ToolRegistry;
import com.apiops.tool.gateway.ToolExecutionLimiter;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class ToolGatewayRestApplicationServiceTest {

    @Test
    void allowedReadUsesGatewayAndCrossProjectKeyStopsBeforeRedisClient() {
        AtomicInteger redisCalls = new AtomicInteger();
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> userId == 7L && projectId == 42L
                        ? Optional.of(ProjectRole.VIEWER)
                        : Optional.empty());
        ToolRegistry registry = new ToolRegistry(authorization);
        RedisReadTool.register(registry);
        SimpleMeterRegistry meters = new SimpleMeterRegistry();
        ToolGateway gateway = new ToolGateway(
                new ToolAuth(registry, authorization),
                new ParamValidator(),
                new RedisGuard(),
                new ToolExecutionLimiter(Duration.ofSeconds(3), 16, 2),
                new ResultSanitizer(),
                new ResultLimiter(100_000),
                new Audit(),
                new Metrics(meters));
        RedisReadExecutor executor = new RedisReadExecutor(
                new RedisGuard(), new CountingRedisClient(redisCalls));
        ToolGatewayRestApplicationService service = new ToolGatewayRestApplicationService(
                gateway, Map.of(RedisGuard.TOOL_NAME, executor::execute));
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                7L, "user", "unused", true, List.of());

        try (gateway) {
            var allowed = service.execute(principal, 42L, request(
                    Map.of(
                            "command", "GET",
                            "keys", List.of("apiops:runner:progress:42:1"),
                            "fields", List.of())),
                    List.of(() -> "TOOL_READ"));

            assertEquals("0.1.0", allowed.schemaVersion());
            assertEquals("SUCCESS", allowed.status());
            assertEquals("trace-42", allowed.traceId());
            assertEquals(null, allowed.error());
            assertNotNull(allowed.toolCallId());
            assertFalse(allowed.toolCallId().isBlank());
            assertEquals(1, redisCalls.get());

            var denied = service.execute(principal, 42L, request(
                    Map.of(
                            "command", "GET",
                            "keys", List.of("apiops:runner:progress:99:1"),
                            "fields", List.of())),
                    List.of(() -> "TOOL_READ"));

            assertEquals("FORBIDDEN", denied.status());
            assertEquals("FORBIDDEN", denied.error().get("code"));
            assertNotNull(denied.toolCallId());
            assertFalse(denied.toolCallId().isBlank());
            assertFalse(allowed.toolCallId().equals(denied.toolCallId()));
            assertEquals(1, redisCalls.get());
            assertEquals(1, meters.get(
                    Metrics.SAFETY_VIOLATION_COUNTER)
                    .tag("tool", RedisGuard.TOOL_NAME)
                    .tag("violationCode", "RESOURCE_GUARD_REJECTED")
                    .counter().count(), 0.0);

            var legacy = service.execute(
                    principal,
                    42L,
                    request("RAG_SEARCH", "42", Map.of()),
                    List.of(() -> "TOOL_READ"));
            assertEquals("PARAM_INVALID", legacy.status());
            assertNotNull(legacy.toolCallId());
            assertFalse(legacy.toolCallId().isBlank());

            var drifted = service.execute(
                    principal,
                    42L,
                    request("redis.read", "99", Map.of()),
                    List.of(() -> "TOOL_READ"));
            assertEquals("PARAM_INVALID", drifted.status());
            assertNotNull(drifted.toolCallId());
            assertEquals(1, redisCalls.get());
        }
    }

    private static ToolCallRequest request(Map<String, Object> params) {
        return request("redis.read", "42", params);
    }

    private static ToolCallRequest request(
            String toolName,
            String projectId,
            Map<String, Object> params
    ) {
        return new ToolCallRequest(
                "0.2.0",
                "agent-run-42",
                null,
                projectId,
                toolName,
                params,
                "trace-42",
                null);
    }

    private static final class CountingRedisClient implements RedisReadClient {
        private final AtomicInteger calls;

        private CountingRedisClient(AtomicInteger calls) {
            this.calls = calls;
        }

        @Override
        public Object get(String key) {
            calls.incrementAndGet();
            return "progress";
        }

        @Override
        public Object hget(String key, String field) {
            calls.incrementAndGet();
            return "progress";
        }

        @Override
        public Object hmget(String key, List<String> fields) {
            calls.incrementAndGet();
            return List.of("progress");
        }

        @Override
        public Object ttl(String key) {
            calls.incrementAndGet();
            return 60L;
        }
    }
}
