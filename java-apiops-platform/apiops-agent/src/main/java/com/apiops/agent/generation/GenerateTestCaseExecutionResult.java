package com.apiops.agent.generation;

import com.apiops.agent.model.ModelCallIdentity;
import com.apiops.runner.state.RunStatus;

import java.util.List;
import java.util.Objects;

public record GenerateTestCaseExecutionResult(
        String agentRunId,
        String promptName,
        String promptVersion,
        List<ModelCallIdentity> modelCalls,
        String caseId,
        long runId,
        RunStatus testStatus
) {
    public GenerateTestCaseExecutionResult {
        Objects.requireNonNull(agentRunId, "agentRunId");
        Objects.requireNonNull(promptName, "promptName");
        Objects.requireNonNull(promptVersion, "promptVersion");
        modelCalls = List.copyOf(modelCalls);
        Objects.requireNonNull(caseId, "caseId");
        Objects.requireNonNull(testStatus, "testStatus");
        if (modelCalls.isEmpty() || modelCalls.size() > 2) {
            throw new IllegalArgumentException("modelCalls must contain one or two calls");
        }
        if (runId <= 0 || !testStatus.isTerminal()) {
            throw new IllegalArgumentException("execution result must be terminal");
        }
    }

    public int modelCallCount() {
        return modelCalls.size();
    }
}
