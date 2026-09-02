package com.apiops.agent.diagnosis;

import com.apiops.agent.model.ModelCallIdentity;
import com.apiops.rag.context.ContextPack;

import java.util.List;
import java.util.Objects;

public record DiagnosisExecutionResult(
        String agentRunId,
        String promptName,
        String promptVersion,
        List<ModelCallIdentity> modelCalls,
        ContextPack contextPack,
        DiagnosisReport report
) {

    public DiagnosisExecutionResult {
        Objects.requireNonNull(agentRunId, "agentRunId");
        Objects.requireNonNull(promptName, "promptName");
        Objects.requireNonNull(promptVersion, "promptVersion");
        modelCalls = List.copyOf(Objects.requireNonNull(modelCalls, "modelCalls"));
        Objects.requireNonNull(contextPack, "contextPack");
        Objects.requireNonNull(report, "report");
    }

    public int modelCallCount() {
        return modelCalls.size();
    }
}
