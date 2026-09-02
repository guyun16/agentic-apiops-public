package com.apiops.agent.diagnosis;

import com.apiops.agent.model.ModelCallIdentity;

import java.util.List;
import java.util.Objects;

public record DiagnosisAgentResult(
        String agentRunId,
        String promptName,
        String promptVersion,
        List<ModelCallIdentity> modelCalls,
        DiagnosisReport candidate
) {

    public DiagnosisAgentResult {
        Objects.requireNonNull(agentRunId, "agentRunId must not be null");
        Objects.requireNonNull(promptName, "promptName must not be null");
        Objects.requireNonNull(promptVersion, "promptVersion must not be null");
        modelCalls = List.copyOf(Objects.requireNonNull(modelCalls, "modelCalls"));
        candidate = Objects.requireNonNull(candidate, "candidate");
        if (modelCalls.isEmpty() || modelCalls.size() > 2) {
            throw new IllegalArgumentException("modelCalls must contain one or two calls");
        }
    }

    public int modelCallCount() {
        return modelCalls.size();
    }
}
