package com.apiops.tool.gateway;

import java.lang.reflect.Array;
import java.util.ArrayList;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Removes sensitive fields before a result can reach the model or Audit. */
public class ResultSanitizer {

    public static final String REDACTED_MARKER = "[REDACTED]";

    private static final Set<String> SENSITIVE_NAMES = Set.of(
            "token", "password", "secret", "authorization", "cookie",
            "api_key", "api-key", "api key", "apikey");
    private static final Pattern SENSITIVE_TEXT = Pattern.compile(
            "(?i)([A-Za-z0-9_-]*(?:token|password|secret|authorization|cookie|api[_ -]?key)"
                    + "\\s*[:=]\\s*)(\"[^\"]*\"|'[^']*'|[^\\r\\n,;\\]}]+)");

    public SanitizedResult sanitize(Object rawResult) {
        State state = new State();
        Object value = sanitize(rawResult, new IdentityHashMap<>(), state);
        return new SanitizedResult(value, state.redacted);
    }

    private Object sanitize(
            Object value,
            IdentityHashMap<Object, Boolean> seen,
            State state
    ) {
        if (value == null || value instanceof Number || value instanceof Boolean
                || value instanceof Enum<?>) {
            return value;
        }
        if (value instanceof String string) {
            return sanitizeText(string, state);
        }
        if (value instanceof Map<?, ?> map) {
            if (seen.put(value, Boolean.TRUE) != null) {
                return "[CYCLE]";
            }
            Map<Object, Object> sanitized = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                Object key = entry.getKey();
                if (isSensitiveName(key)) {
                    state.redacted = true;
                    sanitized.put(key, REDACTED_MARKER);
                } else {
                    sanitized.put(key, sanitize(entry.getValue(), seen, state));
                }
            }
            seen.remove(value);
            return Collections.unmodifiableMap(sanitized);
        }
        if (value instanceof Iterable<?> iterable) {
            if (seen.put(value, Boolean.TRUE) != null) {
                return "[CYCLE]";
            }
            List<Object> sanitized = new ArrayList<>();
            for (Object item : iterable) {
                sanitized.add(sanitize(item, seen, state));
            }
            seen.remove(value);
            return Collections.unmodifiableList(sanitized);
        }
        if (value.getClass().isArray()) {
            if (seen.put(value, Boolean.TRUE) != null) {
                return "[CYCLE]";
            }
            List<Object> sanitized = new ArrayList<>(Array.getLength(value));
            for (int index = 0; index < Array.getLength(value); index++) {
                sanitized.add(sanitize(Array.get(value, index), seen, state));
            }
            seen.remove(value);
            return Collections.unmodifiableList(sanitized);
        }

        // Unknown objects are not serialized through toString: that could expose fields.
        return "[UNSUPPORTED_RESULT]";
    }

    private static boolean isSensitiveName(Object key) {
        if (!(key instanceof String name)) {
            return false;
        }
        String normalized = name.toLowerCase(java.util.Locale.ROOT);
        return SENSITIVE_NAMES.stream().anyMatch(normalized::contains);
    }

    private static String sanitizeText(String value, State state) {
        Matcher matcher = SENSITIVE_TEXT.matcher(value);
        StringBuffer sanitized = new StringBuffer();
        boolean redacted = false;
        while (matcher.find()) {
            redacted = true;
            matcher.appendReplacement(
                    sanitized,
                    Matcher.quoteReplacement(matcher.group(1) + REDACTED_MARKER));
        }
        matcher.appendTail(sanitized);
        if (redacted) {
            state.redacted = true;
        }
        return sanitized.toString();
    }

    private static final class State {
        private boolean redacted;
    }

    public record SanitizedResult(Object value, boolean redacted) {
    }
}
