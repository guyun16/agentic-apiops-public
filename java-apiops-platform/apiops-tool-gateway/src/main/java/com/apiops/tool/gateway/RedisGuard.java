package com.apiops.tool.gateway;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Set;

/** Read-only policy for the Stage 9 task-progress Redis namespace. */
public final class RedisGuard implements ResourceGuard {

    public static final String TOOL_NAME = "redis.read";
    public static final Set<String> READ_COMMANDS = Set.of("GET", "HGET", "HMGET", "TTL");
    public static final int MAX_KEYS = 10;
    public static final int MAX_FIELDS = 20;
    public static final int MAX_REQUEST_BYTES = 4_096;
    public static final int MAX_RESULT_BYTES = 32_768;
    private static final String PREFIX = "apiops:runner:progress:";

    @Override
    public Decision check(ToolExecutionContext context, ToolDefinition definition,
                          ToolCallIntent intent) {
        if (definition == null || !TOOL_NAME.equals(definition.name())) {
            return Decision.allow();
        }
        Validation validation = validate(context, intent);
        return validation.allowed() ? Decision.allow() : Decision.reject(validation.reason());
    }

    public Validation validate(ToolExecutionContext context, ToolCallIntent intent) {
        if (context == null || intent == null) {
            return Validation.reject("trusted context and Redis intent are required");
        }
        Object rawCommand = intent.arguments().get("command");
        if (!(rawCommand instanceof String command)) {
            return Validation.reject("Redis command is required");
        }
        command = command.toUpperCase(Locale.ROOT);
        if (!READ_COMMANDS.contains(command)) {
            return Validation.reject("Redis command is not allowlisted");
        }
        List<String> keys = strings(intent.arguments().get("keys"));
        List<String> fields = strings(intent.arguments().get("fields"));
        if (keys == null || keys.isEmpty() || keys.size() > MAX_KEYS) {
            return Validation.reject("Redis key count is outside the allowed range");
        }
        if (fields == null || fields.size() > MAX_FIELDS) {
            return Validation.reject("Redis field count is outside the allowed range");
        }
        if ((command.equals("GET") || command.equals("TTL")) && !fields.isEmpty()
                || command.equals("HGET") && fields.size() != 1
                || command.equals("HMGET") && fields.isEmpty()) {
            return Validation.reject("Redis fields do not match the command contract");
        }
        int requestBytes = command.getBytes(StandardCharsets.UTF_8).length;
        for (String key : keys) {
            if (!allowedKey(context.projectId(), key)) {
                return Validation.reject("Redis key is outside the trusted project namespace");
            }
            requestBytes += key.getBytes(StandardCharsets.UTF_8).length;
        }
        for (String field : fields) {
            if (field.isBlank() || field.length() > 128) {
                return Validation.reject("Redis field is invalid");
            }
            requestBytes += field.getBytes(StandardCharsets.UTF_8).length;
        }
        if (requestBytes > MAX_REQUEST_BYTES) {
            return Validation.reject("Redis request is too large");
        }
        return new Validation(true, "allowed", command, keys, fields);
    }

    public static String projectPrefix(long projectId) {
        return PREFIX + projectId + ":";
    }

    private static boolean allowedKey(long projectId, String key) {
        if (key == null || key.length() > 256 || !key.startsWith(projectPrefix(projectId))) {
            return false;
        }
        String[] parts = key.split(":", -1);
        if (parts.length != 5 || !"apiops".equals(parts[0]) || !"runner".equals(parts[1])
                || !"progress".equals(parts[2])) {
            return false;
        }
        try {
            return Long.parseLong(parts[3]) == projectId && Long.parseLong(parts[4]) > 0;
        } catch (NumberFormatException exception) {
            return false;
        }
    }

    private static List<String> strings(Object value) {
        if (!(value instanceof List<?> list)) {
            return null;
        }
        java.util.ArrayList<String> values = new java.util.ArrayList<>();
        for (Object item : list) {
            if (!(item instanceof String text)) {
                return null;
            }
            values.add(text);
        }
        return List.copyOf(values);
    }

    public record Validation(boolean allowed, String reason, String command,
                             List<String> keys, List<String> fields) {
        public Validation {
            Objects.requireNonNull(reason);
            keys = keys == null ? List.of() : List.copyOf(keys);
            fields = fields == null ? List.of() : List.copyOf(fields);
        }

        static Validation reject(String reason) {
            return new Validation(false, reason, null, List.of(), List.of());
        }
    }
}
