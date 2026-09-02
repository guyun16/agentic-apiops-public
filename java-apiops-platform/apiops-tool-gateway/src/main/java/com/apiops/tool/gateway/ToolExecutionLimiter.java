package com.apiops.tool.gateway;

import java.time.Duration;
import java.util.Objects;
import java.util.concurrent.CancellationException;
import java.util.concurrent.Callable;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/** Timeout, per-Agent-Run budget, and bounded concurrency without retry. */
public final class ToolExecutionLimiter implements AutoCloseable {

    private static final int RETRY_COUNT = 0;

    private final Duration timeout;
    private final int maxCallsPerAgentRun;
    private final Semaphore permits;
    private final ExecutorService executor;
    // ponytail: lifecycle eviction belongs to the Agent Run owner; keep this boundary minimal.
    private final ConcurrentHashMap<String, AtomicInteger> callsByRun = new ConcurrentHashMap<>();

    public ToolExecutionLimiter(
            Duration timeout,
            int maxCallsPerAgentRun,
            int maxConcurrency
    ) {
        if (timeout == null || timeout.isZero() || timeout.isNegative()) {
            throw new IllegalArgumentException("timeout must be positive");
        }
        if (maxCallsPerAgentRun <= 0 || maxConcurrency <= 0) {
            throw new IllegalArgumentException("limits must be positive");
        }
        this.timeout = timeout;
        this.maxCallsPerAgentRun = maxCallsPerAgentRun;
        this.permits = new Semaphore(maxConcurrency, true);
        this.executor = Executors.newFixedThreadPool(maxConcurrency, runnable -> {
            Thread thread = new Thread(runnable, "apiops-tool-gateway");
            thread.setDaemon(true);
            return thread;
        });
    }

    public <T> T execute(String agentRunId, Callable<T> operation) throws Exception {
        Objects.requireNonNull(operation, "operation must not be null");
        reserveBudget(agentRunId);

        boolean acquired;
        try {
            acquired = permits.tryAcquire(timeout.toNanos(), TimeUnit.NANOSECONDS);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new ToolTimeoutException("tool concurrency wait timed out", exception);
        }
        if (!acquired) {
            throw new ToolTimeoutException("tool concurrency wait timed out");
        }

        AtomicBoolean released = new AtomicBoolean();
        AtomicBoolean started = new AtomicBoolean();
        Future<T> future;
        try {
            future = executor.submit(() -> {
                started.set(true);
                try {
                    return operation.call();
                } finally {
                    releasePermit(released);
                }
            });
        } catch (RejectedExecutionException exception) {
            releasePermit(released);
            throw exception;
        }

        try {
            return future.get(timeout.toNanos(), TimeUnit.NANOSECONDS);
        } catch (TimeoutException | CancellationException exception) {
            future.cancel(true);
            if (!started.get()) {
                releasePermit(released);
            }
            throw new ToolTimeoutException("tool execution timed out", exception);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            future.cancel(true);
            if (!started.get()) {
                releasePermit(released);
            }
            throw new ToolTimeoutException("tool execution interrupted", exception);
        } catch (ExecutionException exception) {
            Throwable cause = exception.getCause();
            if (cause instanceof Exception checkedException) {
                throw checkedException;
            }
            if (cause instanceof Error error) {
                throw error;
            }
            throw new IllegalStateException("tool execution failed", cause);
        }
    }

    public Duration timeout() {
        return timeout;
    }

    public int maxCallsPerAgentRun() {
        return maxCallsPerAgentRun;
    }

    public int retryCount() {
        return RETRY_COUNT;
    }

    private void reserveBudget(String agentRunId) {
        if (agentRunId == null || agentRunId.isBlank()) {
            throw new IllegalArgumentException("agentRunId must not be blank");
        }
        AtomicInteger calls = callsByRun.computeIfAbsent(
                agentRunId, ignored -> new AtomicInteger());
        if (calls.incrementAndGet() > maxCallsPerAgentRun) {
            calls.decrementAndGet();
            throw new BudgetExceededException("Agent Run tool-call budget exceeded");
        }
    }

    private void releasePermit(AtomicBoolean released) {
        if (released.compareAndSet(false, true)) {
            permits.release();
        }
    }

    @Override
    public void close() {
        executor.shutdownNow();
    }

    public static final class BudgetExceededException extends RuntimeException {
        public BudgetExceededException(String message) {
            super(message);
        }
    }

    public static final class ToolTimeoutException extends RuntimeException {
        public ToolTimeoutException(String message) {
            super(message);
        }

        public ToolTimeoutException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
