package com.apiops.agent.record;

import java.time.Instant;
import java.util.Objects;

/** Agent workflow step fact, intentionally separate from execution-test facts. */
public record AgentStepRecord(
        String agentStepId,
        String agentRunId,
        long projectId,
        String stepType,
        Instant startedAt,
        Instant finishedAt,
        long durationMs,
        AgentStepStatus status,
        String modelCallId
) {
    public AgentStepRecord {
        requireText(agentStepId, "agentStepId");
        requireText(agentRunId, "agentRunId");
        requireText(stepType, "stepType");
        Objects.requireNonNull(startedAt, "startedAt must not be null");
        Objects.requireNonNull(status, "status must not be null");
        if (projectId <= 0 || durationMs < 0) {
            throw new IllegalArgumentException("agent step contains an invalid number");
        }
        if (finishedAt != null && finishedAt.isBefore(startedAt)) {
            throw new IllegalArgumentException("finishedAt must not precede startedAt");
        }
        if (status == AgentStepStatus.RUNNING && finishedAt != null
                || status != AgentStepStatus.RUNNING && finishedAt == null) {
            throw new IllegalArgumentException("status does not match finishedAt");
        }
    }

    private static void requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
    }
}
