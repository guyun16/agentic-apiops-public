package com.apiops.agent.diagnosis;

import com.apiops.agent.model.AgentModelRequest;
import com.apiops.agent.prompt.PromptTemplateService;
import com.apiops.agent.structured.BoundedStructuredOutputRepair;
import com.apiops.rag.context.ContextPack;
import com.apiops.report.vo.TestReportVO;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.function.Function;

/** Converts one bounded, pre-built ContextPack into a DiagnosisReport candidate. */
public final class DiagnosisAgent {

    public static final String PROMPT_NAME = "diagnosis";
    public static final String PROMPT_VERSION = "v1";

    private final PromptTemplateService prompts;
    private final BoundedStructuredOutputRepair<DiagnosisReport> structuredOutput;
    private final ObjectMapper objectMapper;

    public DiagnosisAgent(
            PromptTemplateService prompts,
            BoundedStructuredOutputRepair<DiagnosisReport> structuredOutput,
            ObjectMapper objectMapper) {
        this.prompts = Objects.requireNonNull(prompts, "prompts");
        this.structuredOutput = Objects.requireNonNull(structuredOutput, "structuredOutput");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper");
    }

    public DiagnosisAgentResult generate(
            long projectId,
            long runId,
            ContextPack contextPack,
            String task) {
        return generate(projectId, runId, TestReportVO.reportIdForRun(runId), contextPack, task);
    }

    public DiagnosisAgentResult generate(
            long projectId,
            long runId,
            ContextPack contextPack,
            String task,
            Function<DiagnosisReport, DiagnosisReport> businessValidator) {
        return generate(projectId, runId, TestReportVO.reportIdForRun(runId),
                contextPack, task, businessValidator);
    }

    public DiagnosisAgentResult generate(
            long projectId,
            long runId,
            String reportId,
            ContextPack contextPack,
            String task) {
        return generate(projectId, runId, reportId, contextPack, task, Function.identity());
    }

    public DiagnosisAgentResult generate(
            long projectId,
            long runId,
            String reportId,
            ContextPack contextPack,
            String task,
            Function<DiagnosisReport, DiagnosisReport> businessValidator) {
        if (projectId <= 0 || runId <= 0) {
            throw new IllegalArgumentException("projectId and runId must be positive");
        }
        Objects.requireNonNull(reportId, "reportId");
        if (reportId.isBlank()) {
            throw new IllegalArgumentException("reportId must not be blank");
        }
        Objects.requireNonNull(contextPack, "contextPack");
        if (contextPack.projectId() != projectId) {
            throw new DiagnosisIdentityValidationException(
                    "ContextPack projectId does not match requested projectId");
        }
        Objects.requireNonNull(task, "task");
        if (task.isBlank()) {
            throw new IllegalArgumentException("task must not be blank");
        }
        Objects.requireNonNull(businessValidator, "businessValidator");

        String agentRunId = "agent-run-" + UUID.randomUUID();
        String traceId = "trace-" + UUID.randomUUID();
        AgentModelRequest request = prompts.load(PROMPT_NAME, PROMPT_VERSION).render(
                Map.of(
                        "projectId", Long.toString(projectId),
                        "runId", Long.toString(runId),
                        "agentRunId", agentRunId,
                        "reportId", reportId,
                        "traceId", traceId,
                        "task", task),
                serialize(contextPack));
        var generated = structuredOutput.callWithResult(request, businessValidator);
        return new DiagnosisAgentResult(
                agentRunId,
                request.promptName(), request.promptVersion(),
                generated.modelCalls(), generated.candidate());
    }

    private String serialize(ContextPack contextPack) {
        try {
            return objectMapper.writeValueAsString(contextPack);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Unable to serialize ContextPack for diagnosis");
        }
    }
}
