package com.apiops.runner.application;

import java.time.Duration;
import java.util.Objects;

/** Capacity settings for the dedicated HTTP runner executor. */
public record RunnerExecutorProperties(
        int corePoolSize,
        int maximumPoolSize,
        Duration keepAliveTime,
        int queueCapacity,
        String threadNamePrefix) {

    public RunnerExecutorProperties {
        if (corePoolSize <= 0) {
            throw new IllegalArgumentException("corePoolSize must be positive");
        }
        if (maximumPoolSize < corePoolSize) {
            throw new IllegalArgumentException(
                    "maximumPoolSize must be greater than or equal to corePoolSize");
        }
        Objects.requireNonNull(keepAliveTime, "keepAliveTime must not be null");
        if (keepAliveTime.isNegative()) {
            throw new IllegalArgumentException("keepAliveTime must not be negative");
        }
        if (queueCapacity <= 0) {
            throw new IllegalArgumentException("queueCapacity must be positive");
        }
        if (threadNamePrefix == null || threadNamePrefix.isBlank()) {
            throw new IllegalArgumentException("threadNamePrefix must not be blank");
        }
    }
}
