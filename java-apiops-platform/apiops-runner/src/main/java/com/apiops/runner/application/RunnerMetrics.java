package com.apiops.runner.application;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.state.RunStatus;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;

import java.util.Objects;
import java.util.concurrent.TimeUnit;

/** Optional Micrometer observation for the existing Runner execution boundary. */
public final class RunnerMetrics {

    public static final String EXECUTION_TIMER = "apiops.runner.executions";

    private final MeterRegistry meterRegistry;

    public RunnerMetrics(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;
    }

    public void record(RunStatus status, FailureType failureType, long elapsedNanos) {
        if (meterRegistry == null) {
            return;
        }
        try {
            Timer.builder(EXECUTION_TIMER)
                    .description("Runner execution duration")
                    .tags(
                            "status", Objects.requireNonNull(status, "status").name(),
                            "failureType", Objects.requireNonNull(failureType, "failureType").name())
                    .register(meterRegistry)
                    .record(Math.max(0, elapsedNanos), TimeUnit.NANOSECONDS);
        } catch (RuntimeException ignored) {
            // Metrics are observational and must never change Runner state.
        }
    }
}
