package com.apiops.tool.gateway;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/** Executes a guarded logical log query and applies a byte ceiling before model output. */
public final class LogSearchExecutor {
    private final LogGuard guard;
    private final LogSource source;

    public LogSearchExecutor(LogGuard guard, LogSource source) {
        this.guard = Objects.requireNonNull(guard);
        this.source = Objects.requireNonNull(source);
    }

    public Object execute(ToolExecutionContext context, ToolCallIntent intent) throws Exception {
        LogGuard.Validation validation = guard.validate(intent);
        if (!validation.allowed()) throw new IllegalStateException("Log denied: " + validation.reason());
        List<String> raw = source.search(validation.service(), validation.query(), validation.from(),
                validation.to(), validation.maxLines());
        List<String> bounded = new ArrayList<>();
        int bytes = 0;
        for (String line : raw == null ? List.<String>of() : raw) {
            int lineBytes = Objects.toString(line, "").getBytes(StandardCharsets.UTF_8).length;
            if (bytes + lineBytes > LogGuard.MAX_RESULT_BYTES) {
                bounded.add(ResultLimiter.TRUNCATED_MARKER);
                break;
            }
            bounded.add(line); bytes += lineBytes;
            if (bounded.size() >= validation.maxLines()) break;
        }
        return List.copyOf(bounded);
    }
}
