package com.apiops.runner.progress;

public record BatchProgressIdentity(long projectId, long taskId, long runId) {
    public BatchProgressIdentity {
        if (projectId <= 0 || taskId <= 0 || runId <= 0) {
            throw new IllegalArgumentException("progress identity values must be positive");
        }
    }
}
