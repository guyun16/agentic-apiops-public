package com.apiops.runner.progress;

import com.apiops.runner.state.RunStatus;

import java.time.Instant;
import java.util.Objects;

public record TaskProgressSnapshot(long projectId, long taskId, long runId, int total,
        int completed, int running, int success, int assertionFailed, int executionFailed,
        int timeout, int cancelled, RunStatus status, Instant updatedAt) {
    public TaskProgressSnapshot {
        if (projectId <= 0 || taskId <= 0 || runId <= 0 || total < 0) {
            throw new IllegalArgumentException("progress identity and total must be valid");
        }
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(updatedAt, "updatedAt must not be null");
    }
}
