package com.apiops.tool.gateway;

import java.time.Duration;
import java.time.Instant;
import java.util.Locale;
import java.util.Objects;
import java.util.Set;

/** Policy for bounded logical-service log search; model arguments never contain paths. */
public final class LogGuard implements ResourceGuard {
    public static final String TOOL_NAME = "log.search";
    public static final int MAX_QUERY_LENGTH = 256;
    public static final int MAX_LINES = 200;
    public static final int MAX_RESULT_BYTES = 32_768;
    public static final Duration MAX_TIME_RANGE = Duration.ofHours(1);

    private final Set<String> services;

    public LogGuard(Set<String> services) {
        Objects.requireNonNull(services);
        if (services.isEmpty()) throw new IllegalArgumentException("log service allowlist is required");
        this.services = services.stream().map(LogGuard::serviceName)
                .collect(java.util.stream.Collectors.toUnmodifiableSet());
    }

    @Override
    public Decision check(ToolExecutionContext context, ToolDefinition definition,
                          ToolCallIntent intent) {
        if (definition == null || !TOOL_NAME.equals(definition.name())) return Decision.allow();
        Validation validation = validate(intent);
        return validation.allowed() ? Decision.allow() : Decision.reject(validation.reason());
    }

    public Validation validate(ToolCallIntent intent) {
        if (intent == null) return Validation.reject("log intent is required");
        Object serviceValue = intent.arguments().get("service");
        Object queryValue = intent.arguments().get("query");
        Object fromValue = intent.arguments().get("fromEpochMillis");
        Object toValue = intent.arguments().get("toEpochMillis");
        Object maxLinesValue = intent.arguments().get("maxLines");
        if (!(serviceValue instanceof String rawService) || !(queryValue instanceof String query)
                || !(fromValue instanceof Number fromNumber) || !(toValue instanceof Number toNumber)
                || !(maxLinesValue instanceof Number linesNumber)) {
            return Validation.reject("log arguments are malformed");
        }
        String service;
        try { service = serviceName(rawService); }
        catch (RuntimeException exception) { return Validation.reject("logical service is invalid"); }
        if (!services.contains(service)) return Validation.reject("logical service is not allowlisted");
        if (query.isBlank() || query.length() > MAX_QUERY_LENGTH) {
            return Validation.reject("log query length is outside the allowed range");
        }
        Long fromValueExact = exactLong(fromNumber);
        Long toValueExact = exactLong(toNumber);
        Long maxLinesExact = exactLong(linesNumber);
        if (fromValueExact == null || toValueExact == null || maxLinesExact == null) {
            return Validation.reject("log numeric arguments must be integral");
        }
        long from = fromValueExact;
        long to = toValueExact;
        long maxLines = maxLinesExact;
        if (from < 0 || to < from || maxLines < 1 || maxLines > MAX_LINES) {
            return Validation.reject("log range or maxLines is invalid");
        }
        Duration range;
        try { range = Duration.between(Instant.ofEpochMilli(from), Instant.ofEpochMilli(to)); }
        catch (RuntimeException exception) { return Validation.reject("log time range is invalid"); }
        if (range.compareTo(MAX_TIME_RANGE) > 0) {
            return Validation.reject("log time range exceeds the allowed maximum");
        }
        return new Validation(true, "allowed", service, query, Instant.ofEpochMilli(from),
                Instant.ofEpochMilli(to), (int) maxLines);
    }

    public Set<String> services() { return services; }

    private static Long exactLong(Number value) {
        try {
            return new java.math.BigDecimal(value.toString()).longValueExact();
        } catch (ArithmeticException | NumberFormatException exception) {
            return null;
        }
    }

    private static String serviceName(String value) {
        Objects.requireNonNull(value);
        String normalized = value.trim().toLowerCase(Locale.ROOT);
        if (normalized.isBlank() || normalized.length() > 64) {
            throw new IllegalArgumentException("invalid service name");
        }
        return normalized;
    }

    public record Validation(boolean allowed, String reason, String service, String query,
                             Instant from, Instant to, int maxLines) {
        public Validation { Objects.requireNonNull(reason); }
        static Validation reject(String reason) {
            return new Validation(false, reason, null, null, null, null, 0);
        }
    }
}
