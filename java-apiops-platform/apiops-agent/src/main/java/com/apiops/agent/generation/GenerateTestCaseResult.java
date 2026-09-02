package com.apiops.agent.generation;

import com.apiops.agent.model.ModelCallIdentity;
import com.apiops.runner.dsl.TestCase;

import java.util.List;
import java.util.Objects;

public record GenerateTestCaseResult(
        String agentRunId,
        String promptName,
        String promptVersion,
        List<ModelCallIdentity> modelCalls,
        TestCase candidate
) {
    public GenerateTestCaseResult {
        Objects.requireNonNull(agentRunId, "agentRunId");
        Objects.requireNonNull(promptName, "promptName");
        Objects.requireNonNull(promptVersion, "promptVersion");
        modelCalls = List.copyOf(modelCalls);
        Objects.requireNonNull(candidate, "candidate");
        if (modelCalls.isEmpty() || modelCalls.size() > 2) {
            throw new IllegalArgumentException("modelCalls must contain one or two calls");
        }
    }

    public int modelCallCount() {
        return modelCalls.size();
    }
}
