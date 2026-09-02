package com.apiops.agent.generation;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.agent.structured.TestCaseTargetValidator;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.runner.application.RunExecutionService;
import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Objects;

/** Deterministic orchestration from authorized metadata query to the existing Runner. */
public final class GenerateTestCaseApplicationService {

    private final OpenApiQueryApplicationService metadataQueries;
    private final GenerateTestCaseAgent agent;
    private final RunExecutionService runner;
    private final ProjectAuthorizationService authorization;
    private final TestCaseTargetValidator targetValidator;

    public GenerateTestCaseApplicationService(
            OpenApiQueryApplicationService metadataQueries,
            GenerateTestCaseAgent agent,
            RunExecutionService runner,
            ProjectAuthorizationService authorization,
            TestCaseTargetValidator targetValidator) {
        this.metadataQueries = Objects.requireNonNull(metadataQueries, "metadataQueries");
        this.agent = Objects.requireNonNull(agent, "agent");
        this.runner = Objects.requireNonNull(runner, "runner");
        this.authorization = Objects.requireNonNull(authorization, "authorization");
        this.targetValidator = Objects.requireNonNull(targetValidator, "targetValidator");
    }

    public GenerateTestCaseExecutionResult generateAndExecute(
            long projectId,
            String apiId,
            GenerationIntent intent,
            String trustedBaseUrl) {
        authorization.requireProjectEditable(principal().getUserId(), projectId);
        targetValidator.validateRequestedTarget(projectId, apiId, trustedBaseUrl);
        var metadata = metadataQueries.getApi(projectId, apiId);
        var generation = agent.generate(projectId, metadata, intent, trustedBaseUrl);
        var accepted = targetValidator.validate(
                generation.candidate(), projectId, apiId, trustedBaseUrl);
        long runId = runner.prepare(accepted);
        var testStatus = runner.executeBatchCase(runId);
        return new GenerateTestCaseExecutionResult(
                generation.agentRunId(),
                generation.promptName(), generation.promptVersion(),
                generation.modelCalls(),
                generation.candidate().caseId(), runId, testStatus);
    }

    /** Generates and validates a Shared TestCase DSL without submitting it to the Runner. */
    public GenerateTestCaseResult generateOnly(long projectId, String apiId) {
        return generateOnly(projectId, apiId, GenerationIntent.HAPPY_PATH);
    }

    public GenerateTestCaseResult generateOnly(
            long projectId,
            String apiId,
            GenerationIntent intent) {
        authorization.requireProjectReadable(principal().getUserId(), projectId);
        ApiMetadataDetailVO metadata = metadataQueries.getApi(projectId, apiId);
        String trustedBaseUrl = firstServerUrl(metadata);
        targetValidator.validateRequestedTarget(projectId, apiId, trustedBaseUrl);
        GenerationIntent requestedIntent = Objects.requireNonNull(intent, "intent");
        GenerateTestCaseResult generation = agent.generate(
                projectId, metadata, requestedIntent, trustedBaseUrl);
        var accepted = targetValidator.validate(
                generation.candidate(), projectId, apiId, trustedBaseUrl);
        return new GenerateTestCaseResult(
                generation.agentRunId(), generation.promptName(), generation.promptVersion(),
                generation.modelCalls(), accepted);
    }

    private String firstServerUrl(ApiMetadataDetailVO metadata) {
        JsonNode servers = metadata.servers();
        if (servers != null && servers.isArray()) {
            for (JsonNode server : servers) {
                JsonNode url = server == null ? null : server.get("url");
                if (url != null && url.isTextual() && !url.textValue().isBlank()) {
                    return url.textValue();
                }
            }
        }
        throw new IllegalArgumentException(
                "OpenAPI metadata does not contain a usable HTTP server URL");
    }

    private ApiOpsPrincipal principal() {
        Object value = SecurityContextHolder.getContext().getAuthentication().getPrincipal();
        if (!(value instanceof ApiOpsPrincipal principal)) {
            throw new AccessDeniedException("Authenticated ApiOpsPrincipal required");
        }
        return principal;
    }
}
