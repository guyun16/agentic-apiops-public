package com.apiops.agent.record;

import java.time.Instant;
import java.util.Objects;

/** Safe model-call fact: prompts, model output, headers, credentials, and ContextPack are excluded. */
public record ModelCallRecord(
        String modelCallId,
        String agentRunId,
        String agentStepId,
        long projectId,
        String agentType,
        String provider,
        String modelName,
        String promptName,
        String promptVersion,
        Instant startedAt,
        Instant finishedAt,
        long durationMs,
        AgentCallStatus status,
        ModelCallErrorType errorType,
        boolean structuredOutputValid,
        String repairOfModelCallId
) {
    public ModelCallRecord {
        requireText(modelCallId, "modelCallId");
        requireText(agentRunId, "agentRunId");
        requireText(agentStepId, "agentStepId");
        requireText(agentType, "agentType");
        requireText(provider, "provider");
        requireText(modelName, "modelName");
        requireText(promptName, "promptName");
        requireText(promptVersion, "promptVersion");
        Objects.requireNonNull(startedAt, "startedAt must not be null");
        Objects.requireNonNull(finishedAt, "finishedAt must not be null");
        Objects.requireNonNull(status, "status must not be null");
        if (projectId <= 0 || durationMs < 0) {
            throw new IllegalArgumentException("model call contains an invalid number");
        }
        if (finishedAt.isBefore(startedAt)) {
            throw new IllegalArgumentException("finishedAt must not precede startedAt");
        }
        if (status == AgentCallStatus.SUCCESS && errorType != null
                || status == AgentCallStatus.FAILURE && errorType == null) {
            throw new IllegalArgumentException("status does not match errorType");
        }
        if (modelCallId.equals(repairOfModelCallId)) {
            throw new IllegalArgumentException("repair call cannot reference itself");
        }
    }

    private static void requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
    }
}
