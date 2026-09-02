package com.apiops.agent.generation;

import com.apiops.agent.model.AgentModelRequest;
import com.apiops.agent.prompt.PromptTemplateService;
import com.apiops.agent.structured.BoundedStructuredOutputRepair;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** Generates one structurally valid TestCase candidate; it never accepts or executes it. */
public final class GenerateTestCaseAgent {

    public static final String PROMPT_NAME = "generate-testcase";
    public static final String PROMPT_VERSION = "v1";

    private final PromptTemplateService prompts;
    private final BoundedStructuredOutputRepair<com.apiops.runner.dsl.TestCase> structuredOutput;
    private final ObjectMapper objectMapper;

    public GenerateTestCaseAgent(
            PromptTemplateService prompts,
            BoundedStructuredOutputRepair<com.apiops.runner.dsl.TestCase> structuredOutput,
            ObjectMapper objectMapper) {
        this.prompts = Objects.requireNonNull(prompts, "prompts");
        this.structuredOutput = Objects.requireNonNull(structuredOutput, "structuredOutput");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper");
    }

    public GenerateTestCaseResult generate(
            long projectId,
            ApiMetadataDetailVO metadata,
            GenerationIntent intent,
            String trustedBaseUrl) {
        Objects.requireNonNull(metadata, "metadata");
        Objects.requireNonNull(intent, "intent");
        String agentRunId = UUID.randomUUID().toString();
        AgentModelRequest request = prompts.load(PROMPT_NAME, PROMPT_VERSION).render(
                Map.of(
                        "projectId", Long.toString(projectId),
                        "apiId", metadata.apiId(),
                        "task", intent.promptTask()),
                context(metadata, trustedBaseUrl));
        var generated = structuredOutput.callWithResult(request, candidate -> candidate);
        return new GenerateTestCaseResult(
                agentRunId,
                request.promptName(), request.promptVersion(),
                generated.modelCalls(), generated.candidate());
    }

    private String context(ApiMetadataDetailVO metadata, String trustedBaseUrl) {
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("trustedBaseUrl", trustedBaseUrl);
        context.put("apiId", metadata.apiId());
        context.put("operationId", metadata.operationId());
        context.put("method", metadata.method());
        context.put("path", metadata.path());
        context.put("parameters", metadata.parameters());
        context.put("requestSchemas", metadata.requestSchemas());
        context.put("responseSchemas", metadata.responseSchemas());
        context.put("examples", metadata.examples());
        context.put("security", metadata.security());
        try {
            return objectMapper.writeValueAsString(context);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Unable to serialize trusted API metadata");
        }
    }
}
