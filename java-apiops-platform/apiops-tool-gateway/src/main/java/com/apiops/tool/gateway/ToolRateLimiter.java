package com.apiops.tool.gateway;

import java.time.Duration;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;

/** Local fixed-window rate limit keyed by trusted user, project, and stable tool name. */
public final class ToolRateLimiter {

    private static final int DEFAULT_MAX_CALLS = 60;
    private static final Duration DEFAULT_WINDOW = Duration.ofMinutes(1);

    private final int maxCalls;
    private final Duration window;
    private final long windowNanos;
    private final ConcurrentHashMap<Key, WindowState> windows = new ConcurrentHashMap<>();

    public ToolRateLimiter(int maxCalls, Duration window) {
        if (maxCalls <= 0) {
            throw new IllegalArgumentException("maxCalls must be positive");
        }
        if (window == null || window.isZero() || window.isNegative()) {
            throw new IllegalArgumentException("window must be positive");
        }
        this.maxCalls = maxCalls;
        this.window = window;
        this.windowNanos = window.toNanos();
    }

    public static ToolRateLimiter defaultLimiter() {
        return new ToolRateLimiter(DEFAULT_MAX_CALLS, DEFAULT_WINDOW);
    }

    public Decision tryAcquire(
            ToolExecutionContext context,
            ToolDefinition definition
    ) {
        Objects.requireNonNull(context, "context must not be null");
        Objects.requireNonNull(definition, "definition must not be null");

        Key key = new Key(context.userId(), context.projectId(), definition.name());
        long now = System.nanoTime();
        WindowState state = windows.computeIfAbsent(key, ignored -> new WindowState(now));
        synchronized (state) {
            if (now - state.startedAtNanos >= windowNanos) {
                state.startedAtNanos = now;
                state.calls = 0;
            }
            if (state.calls >= maxCalls) {
                return Decision.reject("basic rate limit exceeded");
            }
            state.calls++;
            return Decision.allow();
        }
    }

    public int maxCalls() {
        return maxCalls;
    }

    public Duration window() {
        return window;
    }

    private record Key(long userId, long projectId, String toolName) {
    }

    private static final class WindowState {
        private long startedAtNanos;
        private int calls;

        private WindowState(long startedAtNanos) {
            this.startedAtNanos = startedAtNanos;
        }
    }

    public record Decision(boolean allowed, String reason) {

        public Decision {
            Objects.requireNonNull(reason, "reason must not be null");
        }

        private static Decision allow() {
            return new Decision(true, "allowed");
        }

        private static Decision reject(String reason) {
            return new Decision(false, reason);
        }
    }
}
