package com.apiops.tool.gateway;

import com.apiops.common.enums.ToolStatus;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.time.Duration;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

@Testcontainers(disabledWithoutDocker = true)
class RedisReadIntegrationTest {

    private static final String PROGRESS_KEY = "apiops:runner:progress:42:99001";
    private static final String STRING_KEY = "apiops:runner:progress:42:99002";

    @Container
    private static final GenericContainer<?> REDIS = new GenericContainer<>("redis:7-alpine")
            .withExposedPorts(6379);

    @Test void readsRealStage9HashThroughGateway() {
        seedProgressEvidence();
        String host = REDIS.getHost();
        int port = REDIS.getMappedPort(6379);
        String password = "";
        RedisGuard guard = new RedisGuard();
        RedisReadExecutor executor = new RedisReadExecutor(guard,
                new SocketRedisReadClient(host, port, password, Duration.ofSeconds(2)));
        ToolCallIntent intent = new ToolCallIntent(RedisGuard.TOOL_NAME, Map.of(
                "command", "HMGET",
                "keys", List.of(PROGRESS_KEY),
                "fields", List.of("projectId", "status")));
        try (var bundle = ToolSecurityTestSupport.gateway(RedisReadTool.definition(), guard)) {
            var result = RedisReadTool.execute(bundle.gateway(), executor,
                    ToolSecurityTestSupport.context("redis-real"), intent);
            assertEquals(ToolStatus.SUCCESS, result.getStatus());
            assertEquals("42", ((List<?>) ((Map<?, ?>) result.getData())
                    .get(PROGRESS_KEY)).get(0));
            var hget = RedisReadTool.execute(bundle.gateway(), executor,
                    ToolSecurityTestSupport.context("redis-real-hget"),
                    new ToolCallIntent(RedisGuard.TOOL_NAME, Map.of(
                            "command", "HGET",
                            "keys", List.of(PROGRESS_KEY),
                            "fields", List.of("status"))));
            assertEquals(ToolStatus.SUCCESS, hget.getStatus());
            assertEquals("RUNNING", ((Map<?, ?>) hget.getData()).get(PROGRESS_KEY));
            var get = RedisReadTool.execute(bundle.gateway(), executor,
                    ToolSecurityTestSupport.context("redis-real-get"),
                    new ToolCallIntent(RedisGuard.TOOL_NAME, Map.of(
                            "command", "GET",
                            "keys", List.of(STRING_KEY),
                            "fields", List.of())));
            assertEquals(ToolStatus.SUCCESS, get.getStatus());
            assertEquals("READY", ((Map<?, ?>) get.getData()).get(STRING_KEY));
            var ttl = RedisReadTool.execute(bundle.gateway(), executor,
                    ToolSecurityTestSupport.context("redis-real-ttl"),
                    new ToolCallIntent(RedisGuard.TOOL_NAME, Map.of(
                            "command", "TTL",
                            "keys", List.of(PROGRESS_KEY),
                            "fields", List.of())));
            assertEquals(ToolStatus.SUCCESS, ttl.getStatus());
            assertEquals(true, ((Number) ((Map<?, ?>) ttl.getData())
                    .get(PROGRESS_KEY)).longValue() > 0);
        }
    }

    private static void seedProgressEvidence() {
        assertTrue(exec("HSET", PROGRESS_KEY, "projectId", "42", "status", "RUNNING"));
        assertTrue(exec("SET", STRING_KEY, "READY"));
        assertTrue(exec("EXPIRE", PROGRESS_KEY, "60"));
    }

    private static boolean exec(String... command) {
        try {
            return REDIS.execInContainer(concat("redis-cli", command)).getExitCode() == 0;
        } catch (Exception exception) {
            throw new IllegalStateException("could not seed Redis container", exception);
        }
    }

    private static String[] concat(String first, String[] rest) {
        String[] command = new String[rest.length + 1];
        command[0] = first;
        System.arraycopy(rest, 0, command, 1, rest.length);
        return command;
    }
}
