package com.apiops.tool.gateway;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;

/** Executes only a RedisGuard-approved read through a capability-limited client. */
public final class RedisReadExecutor {
    private final RedisGuard guard;
    private final RedisReadClient client;

    public RedisReadExecutor(RedisGuard guard, RedisReadClient client) {
        this.guard = Objects.requireNonNull(guard);
        this.client = Objects.requireNonNull(client);
    }

    public Object execute(ToolExecutionContext context, ToolCallIntent intent) throws Exception {
        RedisGuard.Validation validation = guard.validate(context, intent);
        if (!validation.allowed()) {
            throw new IllegalStateException("Redis denied: " + validation.reason());
        }
        Map<String, Object> result = new LinkedHashMap<>();
        for (String key : validation.keys()) {
            Object value = switch (validation.command()) {
                case "GET" -> client.get(key);
                case "HGET" -> client.hget(key, validation.fields().get(0));
                case "HMGET" -> client.hmget(key, validation.fields());
                case "TTL" -> client.ttl(key);
                default -> throw new IllegalStateException("guard admitted an unknown command");
            };
            result.put(key, value);
            if (result.toString().getBytes(StandardCharsets.UTF_8).length
                    > RedisGuard.MAX_RESULT_BYTES) {
                throw new IllegalStateException("Redis result exceeds byte limit");
            }
        }
        return java.util.Collections.unmodifiableMap(result);
    }
}
