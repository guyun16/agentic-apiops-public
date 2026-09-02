package com.apiops.tool.gateway;

import com.apiops.common.enums.ToolStatus;
import com.apiops.common.tool.ToolResult;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

class RedisReadToolTest {
    private static final String KEY = "apiops:runner:progress:42:301";

    @Test void allowedProjectKeyReadsAndSanitizes() {
        RecordingClient client = new RecordingClient("password=redis-secret");
        RedisGuard guard = new RedisGuard();
        try (var bundle = ToolSecurityTestSupport.gateway(RedisReadTool.definition(), guard)) {
            ToolResult<Object> result = RedisReadTool.execute(bundle.gateway(),
                    new RedisReadExecutor(guard, client), ToolSecurityTestSupport.context("redis-ok"),
                    intent("HGET", List.of(KEY), List.of("status")));
            assertEquals(ToolStatus.SUCCESS, result.getStatus());
            assertEquals(1, client.calls.get());
            assertFalse(result.getData().toString().contains("redis-secret"));
            assertTrue(result.getData().toString().contains(ResultSanitizer.REDACTED_MARKER));
            assertFalse(bundle.audit().events().getFirst().sanitizedSummary().contains("redis-secret"));
        }
    }

    @Test void crossProjectAndForbiddenNamespacesStopBeforeClient() {
        RecordingClient client = new RecordingClient("unused");
        RedisGuard guard = new RedisGuard();
        try (var bundle = ToolSecurityTestSupport.gateway(RedisReadTool.definition(), guard)) {
            for (String key : List.of("apiops:runner:progress:43:301", "apiops:auth:user:42")) {
                ToolResult<Object> result = RedisReadTool.execute(bundle.gateway(),
                        new RedisReadExecutor(guard, client), ToolSecurityTestSupport.context("redis-deny-" + key),
                        intent("TTL", List.of(key), List.of()));
                assertEquals(ToolStatus.FORBIDDEN, result.getStatus());
            }
        }
        assertEquals(0, client.calls.get());
    }

    @Test void writeEvalKeysAndScanAreRejectedBeforeClient() {
        RecordingClient client = new RecordingClient("unused");
        RedisGuard guard = new RedisGuard();
        try (var bundle = ToolSecurityTestSupport.gateway(RedisReadTool.definition(), guard)) {
            for (String command : List.of("SET", "DEL", "EVAL", "EVALSHA", "KEYS", "SCAN")) {
                ToolResult<Object> result = RedisReadTool.execute(bundle.gateway(),
                        new RedisReadExecutor(guard, client), ToolSecurityTestSupport.context("redis-" + command),
                        intent(command, List.of(KEY), List.of()));
                assertEquals(ToolStatus.PARAM_INVALID, result.getStatus());
            }
        }
        assertEquals(0, client.calls.get());
    }

    @Test void malformedAndOversizedRequestsDoNotReachClient() {
        RecordingClient client = new RecordingClient("unused");
        RedisGuard guard = new RedisGuard();
        try (var bundle = ToolSecurityTestSupport.gateway(RedisReadTool.definition(), guard)) {
            ToolResult<Object> malformed = bundle.gateway().execute(
                    ToolSecurityTestSupport.context("redis-malformed"),
                    new ToolCallIntent(RedisGuard.TOOL_NAME, Map.of("command", "TTL", "keys", List.of(KEY))),
                    new RedisReadExecutor(guard, client)::execute);
            assertEquals(ToolStatus.PARAM_INVALID, malformed.getStatus());

            ToolResult<Object> oversized = RedisReadTool.execute(bundle.gateway(),
                    new RedisReadExecutor(guard, client), ToolSecurityTestSupport.context("redis-large-request"),
                    intent("HMGET", List.of(KEY), List.of("x".repeat(200))));
            assertEquals(ToolStatus.FORBIDDEN, oversized.getStatus());
        }
        assertEquals(0, client.calls.get());
    }

    @Test void forgedProjectAndRoleArgumentsCannotOverrideTrustedContext() {
        RecordingClient client = new RecordingClient("unused");
        RedisGuard guard = new RedisGuard();
        Map<String, Object> forged = new java.util.LinkedHashMap<>(
                intent("TTL", List.of("apiops:runner:progress:43:301"), List.of()).arguments());
        forged.put("projectId", 43L);
        forged.put("role", "OWNER");
        try (var bundle = ToolSecurityTestSupport.gateway(RedisReadTool.definition(), guard)) {
            ToolResult<Object> result = RedisReadTool.execute(bundle.gateway(),
                    new RedisReadExecutor(guard, client), ToolSecurityTestSupport.context("redis-forged"),
                    new ToolCallIntent(RedisGuard.TOOL_NAME, forged));
            assertEquals(ToolStatus.PARAM_INVALID, result.getStatus());
        }
        assertEquals(0, client.calls.get());
    }

    @Test void oversizedResultFailsClosed() {
        RecordingClient client = new RecordingClient("x".repeat(RedisGuard.MAX_RESULT_BYTES + 1));
        RedisGuard guard = new RedisGuard();
        try (var bundle = ToolSecurityTestSupport.gateway(RedisReadTool.definition(), guard)) {
            ToolResult<Object> result = RedisReadTool.execute(bundle.gateway(),
                    new RedisReadExecutor(guard, client), ToolSecurityTestSupport.context("redis-large-result"),
                    intent("HGET", List.of(KEY), List.of("status")));
            assertEquals(ToolStatus.FAILED, result.getStatus());
        }
        assertEquals(1, client.calls.get());
    }

    private static ToolCallIntent intent(String command, List<String> keys, List<String> fields) {
        return new ToolCallIntent(RedisGuard.TOOL_NAME,
                Map.of("command", command, "keys", keys, "fields", fields));
    }

    private static final class RecordingClient implements RedisReadClient {
        private final AtomicInteger calls = new AtomicInteger();
        private final Object value;
        private RecordingClient(Object value) { this.value = value; }
        @Override public Object get(String key) { calls.incrementAndGet(); return value; }
        @Override public Object hget(String key, String field) { calls.incrementAndGet(); return value; }
        @Override public Object hmget(String key, List<String> fields) { calls.incrementAndGet(); return List.of(value); }
        @Override public Object ttl(String key) { calls.incrementAndGet(); return 60L; }
    }
}
