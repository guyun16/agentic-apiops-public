package com.apiops.tool.gateway;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;

import java.util.concurrent.atomic.LongAdder;
import java.util.concurrent.TimeUnit;

/** Small in-process counter set; it is not a Stage 13 monitoring platform. */
public final class Metrics {

    public static final String TOOL_CALL_TIMER = "apiops.tool.calls";
    public static final String SAFETY_VIOLATION_COUNTER = "apiops.tool.safety.violations";
    private static final String UNKNOWN_TOOL = "unknown";
    private static final String UNSPECIFIED = "UNSPECIFIED";

    private final LongAdder calls = new LongAdder();
    private final LongAdder success = new LongAdder();
    private final LongAdder denied = new LongAdder();
    private final LongAdder invalid = new LongAdder();
    private final LongAdder safetyViolations = new LongAdder();
    private final LongAdder timeouts = new LongAdder();
    private final LongAdder failed = new LongAdder();
    private final LongAdder latencyNanos = new LongAdder();
    private final MeterRegistry meterRegistry;

    public Metrics() {
        this(null);
    }

    public Metrics(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;
    }

    public void record(AuditStatus status, long elapsedNanos) {
        record(UNKNOWN_TOOL, status, UNSPECIFIED, elapsedNanos);
    }

    /** Records the existing in-process facts and optional Micrometer observations. */
    public void record(
            String toolName,
            AuditStatus status,
            String violationCode,
            long elapsedNanos) {
        calls.increment();
        latencyNanos.add(Math.max(0, elapsedNanos));
        switch (status) {
            case SUCCESS -> success.increment();
            case DENIED -> denied.increment();
            case INVALID -> invalid.increment();
            case SAFETY_VIOLATION -> safetyViolations.increment();
            case TIMEOUT -> timeouts.increment();
            case FAILED -> failed.increment();
        }
        recordMicrometer(toolName, status, violationCode, elapsedNanos);
    }

    private void recordMicrometer(
            String toolName,
            AuditStatus status,
            String violationCode,
            long elapsedNanos) {
        if (meterRegistry == null) {
            return;
        }
        try {
            String stableTool = stableToolTag(toolName);
            String stableStatus = status == null ? UNSPECIFIED : status.name();
            Timer.builder(TOOL_CALL_TIMER)
                    .description("Tool Gateway call duration")
                    .tags("tool", stableTool, "status", stableStatus)
                    .register(meterRegistry)
                    .record(Math.max(0, elapsedNanos), TimeUnit.NANOSECONDS);
            if (status == AuditStatus.SAFETY_VIOLATION) {
                Counter.builder(SAFETY_VIOLATION_COUNTER)
                        .description("Tool Gateway safety violation count")
                        .tags("tool", stableTool, "violationCode", stableViolationCode(violationCode))
                        .register(meterRegistry)
                        .increment();
            }
        } catch (RuntimeException ignored) {
            // Metrics are observational and must never change ToolResult semantics.
        }
    }

    private static String stableToolTag(String toolName) {
        if (toolName == null || !toolName.matches("[a-z][a-z0-9_.-]{0,63}")) {
            return UNKNOWN_TOOL;
        }
        return toolName;
    }

    private static String stableViolationCode(String violationCode) {
        if (violationCode == null || !violationCode.matches("[A-Z][A-Z0-9_]{0,63}")) {
            return UNSPECIFIED;
        }
        return violationCode;
    }

    public Snapshot snapshot() {
        return new Snapshot(
                calls.sum(),
                success.sum(),
                denied.sum(),
                invalid.sum(),
                safetyViolations.sum(),
                timeouts.sum(),
                failed.sum(),
                latencyNanos.sum()
        );
    }

    public record Snapshot(
            long calls,
            long success,
            long denied,
            long invalid,
            long safetyViolations,
            long timeouts,
            long failed,
            long latencyNanos
    ) {
    }
}
