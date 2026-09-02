package com.apiops.agent.real;

import com.apiops.agent.generation.GenerateTestCaseAgent;
import com.apiops.agent.generation.GenerateTestCaseApplicationService;
import com.apiops.agent.generation.GenerationIntent;
import com.apiops.agent.prompt.PromptTemplateService;
import com.apiops.agent.structured.BoundedStructuredOutputRepair;
import com.apiops.agent.structured.TestCaseCandidateMapper;
import com.apiops.agent.structured.TestCaseTargetValidator;
import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.common.enums.FailureType;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.converter.OpenApiMetadataAssembler;
import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.assembler.TestReportAssembler;
import com.apiops.runner.application.RunExecutionService;
import com.apiops.runner.assertion.AssertionEngine;
import com.apiops.runner.assertion.AssertionEvaluatorRegistry;
import com.apiops.runner.assertion.HeaderAssertionEvaluator;
import com.apiops.runner.assertion.JsonPathAssertionEvaluator;
import com.apiops.runner.assertion.ResponseTimeAssertionEvaluator;
import com.apiops.runner.assertion.StatusCodeAssertionEvaluator;
import com.apiops.runner.execution.AssertionContextMapper;
import com.apiops.runner.execution.StepResult;
import com.apiops.runner.execution.TestStepRunner;
import com.apiops.runner.http.HttpRequestBuilder;
import com.apiops.runner.http.JdkHttpTransport;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.state.RunStatus;
import com.apiops.runner.validation.TestCaseDslValidator;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class Stage11RealModelE2ETest {

    private static final long PROJECT_ID = 11003L;
    private static final long USER_ID = 1103L;
    private static final String API_ID = "simulateTokenExpiredFault";
    private static final String OPERATION_ID = "simulateTokenExpiredFault";
    private static final String BASE_URL_ENV = "APIOPS_DEMO_ORDER_BASE_URL";
    private static final ObjectMapper MAPPER = JsonMapper.builder().build();

    @BeforeEach
    void authenticate() {
        var principal = new ApiOpsPrincipal(USER_ID, "stage11-real", "unused", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
    }

    @AfterEach
    void clearAuthentication() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void realMetadataToDeepSeekToExistingRunnerAndReport() {
        String baseUrl = System.getenv(BASE_URL_ENV);
        Assumptions.assumeTrue(baseUrl != null && !baseUrl.isBlank(),
                () -> "Set " + BASE_URL_ENV + " to a running demo-order-service");

        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> Optional.of(ProjectRole.EDITOR));
        RealMetadataRepository metadataRepository = new RealMetadataRepository();
        OpenApiQueryApplicationService metadataQueries = new OpenApiQueryApplicationService(
                authorization, metadataRepository, new OpenApiMetadataAssembler());
        TestCaseDslValidator dslValidator = new TestCaseDslValidator(MAPPER, schemaPath());
        var modelClient = DeepSeekRealTestSupport.client();
        GenerateTestCaseAgent agent = new GenerateTestCaseAgent(
                new PromptTemplateService(),
                new BoundedStructuredOutputRepair(
                        modelClient, new TestCaseCandidateMapper(dslValidator)),
                MAPPER);

        InMemoryExecutionFacts executionFacts = new InMemoryExecutionFacts();
        TestStepRunner stepRunner = new TestStepRunner(
                new HttpRequestBuilder(),
                new JdkHttpTransport(Duration.ofSeconds(5)),
                new AssertionContextMapper(MAPPER),
                new AssertionEngine(new AssertionEvaluatorRegistry(
                        new StatusCodeAssertionEvaluator(),
                        new HeaderAssertionEvaluator(),
                        new JsonPathAssertionEvaluator(),
                        new ResponseTimeAssertionEvaluator())));
        RunExecutionService runner = new RunExecutionService(
                executionFacts, stepRunner, MAPPER);
        GenerateTestCaseApplicationService service = new GenerateTestCaseApplicationService(
                metadataQueries, agent, runner, authorization, new TestCaseTargetValidator());

        var result = service.generateAndExecute(
                PROJECT_ID, API_ID, GenerationIntent.HAPPY_PATH, baseUrl);

        assertTrue(executionFacts.stage7Validated(dslValidator));
        assertTrue(executionFacts.targetValidated(baseUrl));
        assertTrue(result.testStatus().isTerminal());

        TestReportQueryService reports = new TestReportQueryService(
                authorization, executionFacts, new TestReportAssembler(MAPPER));
        var report = reports.getReport(PROJECT_ID, result.runId());
        assertEquals(result.testStatus(), report.status());
        assertFalse(report.cases().isEmpty());
        assertFalse(report.cases().getFirst().steps().isEmpty());
        assertTrue(report.summary().totalAssertions() > 0);

        System.out.println("REAL_STAGE11_E2E provider=DeepSeek"
                + " adapter=SpringAiAgentModelClient model=" + DeepSeekRealTestSupport.MODEL
                + " projectId=" + PROJECT_ID
                + " apiId=" + API_ID
                + " operationId=" + OPERATION_ID
                + " promptVersion=" + result.promptVersion()
                + " modelCallCount=" + result.modelCallCount()
                + " boundedRepair=" + (result.modelCallCount() == 2)
                + " modelCallIds=" + result.modelCalls().stream()
                        .map(call -> call.modelCallId()).toList()
                + " repairOf=" + result.modelCalls().stream()
                        .map(call -> call.repairOfModelCallId()).toList()
                + " stage7Validation=true targetValidation=true"
                + " runId=" + result.runId()
                + " runStatus=" + result.testStatus()
                + " reportCases=" + report.summary().totalCases()
                + " reportSteps=" + report.summary().totalSteps()
                + " reportAssertions=" + report.summary().totalAssertions()
                + " reportPassed=" + report.summary().passedAssertions()
                + " reportFailed=" + report.summary().failedAssertions()
                + " reportFailureType=" + report.summary().failureType());
    }

    private Path schemaPath() {
        Path current = Path.of("").toAbsolutePath().normalize();
        while (current != null) {
            Path schema = current.resolve("shared-schemas/testcase-dsl-schema.json");
            if (Files.isRegularFile(schema)) {
                return schema;
            }
            current = current.getParent();
        }
        throw new IllegalStateException("shared TestCase DSL schema was not found");
    }

    private static final class RealMetadataRepository implements OpenApiMetadataRepository {
        private static final Instant NOW = Instant.parse("2026-08-13T00:00:00Z");

        @Override
        public Optional<ApiEndpoint> findEndpoint(long projectId, String apiId) {
            if (projectId != PROJECT_ID || !API_ID.equals(apiId)) return Optional.empty();
            return Optional.of(new ApiEndpoint(
                    1L, API_ID, "demo-order-openapi", PROJECT_ID, OPERATION_ID,
                    "POST", "/api/faults/token-expired", "Simulate an expired-token response",
                    "Public local fault-injection endpoint that deliberately returns the service's 401 token-expired error envelope.",
                    "[\"Faults\"]", "[]", "[]", false, NOW, NOW));
        }

        @Override
        public List<ApiParameter> findParameters(long projectId, String apiId) {
            return List.of();
        }

        @Override
        public List<ApiResponseSchema> findResponseSchemas(long projectId, String apiId) {
            return List.of(new ApiResponseSchema(
                    21L, API_ID, PROJECT_ID, "401", "Simulated expired-token failure",
                    "application/json", "{\"type\":\"object\",\"required\":[\"success\",\"code\",\"message\",\"data\"]}", NOW));
        }

        @Override
        public List<ApiExample> findExamples(long projectId, String apiId) {
            return List.of(new ApiExample(
                    31L, API_ID, PROJECT_ID, "RESPONSE_SCHEMA", 21L,
                    "tokenExpired", "Expired-token error envelope", null,
                    "{\"success\":false,\"code\":\"ORDER_TOKEN_EXPIRED\",\"message\":\"token expired\",\"data\":null}", NOW));
        }

        @Override public List<ApiRequestSchema> findRequestSchemas(long projectId, String apiId) { return List.of(); }
        @Override public Optional<ApiDocument> findDocument(long projectId, String apiDocId) { return Optional.empty(); }
        @Override public Optional<ApiDocument> findDocument(long projectId, String sourceKey, String contentHash) { return Optional.empty(); }
        @Override public Optional<ApiDocument> findLatestDocument(long projectId, String sourceKey) { return Optional.empty(); }
        @Override public List<ApiDocument> findDocuments(long projectId) { return List.of(); }
        @Override public List<ApiEndpoint> findEndpoints(long projectId) { return findEndpoint(projectId, API_ID).stream().toList(); }
        @Override public ApiDocument save(ApiDocument document) { throw new UnsupportedOperationException(); }
        @Override public ApiEndpoint save(ApiEndpoint endpoint) { throw new UnsupportedOperationException(); }
        @Override public ApiParameter save(ApiParameter parameter) { throw new UnsupportedOperationException(); }
        @Override public ApiRequestSchema save(ApiRequestSchema requestSchema) { throw new UnsupportedOperationException(); }
        @Override public ApiResponseSchema save(ApiResponseSchema responseSchema) { throw new UnsupportedOperationException(); }
        @Override public ApiExample save(ApiExample example) { throw new UnsupportedOperationException(); }
    }

    private static final class InMemoryExecutionFacts implements ExecutionFactRepository {
        private final AtomicLong ids = new AtomicLong(110300L);
        private RunExecutionInput input;
        private RunExecutionFacts facts;

        boolean stage7Validated(TestCaseDslValidator validator) {
            return validator.validate(input.testCaseDslJson()).valid();
        }

        boolean targetValidated(String baseUrl) {
            try {
                var candidate = MAPPER.readValue(input.testCaseDslJson(), com.apiops.runner.dsl.TestCase.class);
                new TestCaseTargetValidator().validate(candidate, PROJECT_ID, API_ID, baseUrl);
                return true;
            } catch (Exception exception) {
                return false;
            }
        }

        @Override
        public long prepareRun(long projectId, String caseId, String apiId, String name, String json) {
            long taskId = ids.incrementAndGet();
            long runId = ids.incrementAndGet();
            input = new RunExecutionInput(projectId, taskId, runId, caseId, apiId, json);
            facts = new RunExecutionFacts(projectId, taskId, runId, caseId, apiId, name,
                    RunStatus.PENDING, FailureType.NONE, null, null, List.of());
            return runId;
        }

        @Override public Optional<RunExecutionInput> findExecutionInput(long runId) { return facts != null && facts.runId() == runId ? Optional.of(input) : Optional.empty(); }

        @Override
        public boolean tryClaim(long projectId, long runId, Instant startedAt) {
            if (facts == null || facts.projectId() != projectId || facts.runId() != runId || facts.status() != RunStatus.PENDING) return false;
            facts = new RunExecutionFacts(facts.projectId(), facts.taskId(), facts.runId(), facts.caseId(), facts.apiId(), facts.taskName(), RunStatus.RUNNING, FailureType.NONE, startedAt, null, List.of());
            return true;
        }

        @Override
        public void saveExecutionOutcome(RunExecutionOutcome outcome) {
            List<CaseExecutionFacts> cases = new ArrayList<>();
            long caseResultId = ids.incrementAndGet();
            List<StepExecutionFacts> steps = new ArrayList<>();
            for (StepExecutionOutcome value : outcome.stepResults()) {
                StepResult result = value.result();
                try {
                    steps.add(new StepExecutionFacts(
                            outcome.projectId(), outcome.runId(), caseResultId, ids.incrementAndGet(),
                            value.stepId(), result.status(), result.failureType(),
                            MAPPER.writeValueAsString(result.assertionResults()),
                            result.responseSnapshot() == null ? null : result.responseSnapshot().statusCode(),
                            result.responseSnapshot() == null ? null : result.responseSnapshot().durationMs(),
                            outcome.finishedAt()));
                } catch (Exception exception) {
                    throw new IllegalStateException("Unable to serialize assertion results", exception);
                }
            }
            cases.add(new CaseExecutionFacts(
                    outcome.projectId(), outcome.runId(), caseResultId, outcome.caseId(),
                    outcome.status(), outcome.failureType(), outcome.startedAt(), outcome.finishedAt(), steps));
            facts = new RunExecutionFacts(
                    facts.projectId(), facts.taskId(), facts.runId(), facts.caseId(), facts.apiId(), facts.taskName(),
                    outcome.status(), outcome.failureType(), outcome.startedAt(), outcome.finishedAt(), cases);
        }

        @Override
        public List<ExecutionFactRepository.RunSummary> findRecentRunSummaries(long projectId) {
            return List.of();
        }

        @Override public Optional<RunExecutionFacts> findRun(long projectId, long runId) { return facts != null && facts.projectId() == projectId && facts.runId() == runId ? Optional.of(facts) : Optional.empty(); }
        @Override public boolean completeRun(long runId, RunStatus status, FailureType failureType, Instant finishedAt) { return false; }
        @Override public boolean cancelPendingRun(long projectId, long runId, Instant finishedAt) { return false; }
        @Override public PreparedBatch prepareBatch(UUID batchId, long projectId, long requestedBy, List<PreparedRun> runs) { throw new UnsupportedOperationException(); }
        @Override public Optional<BatchExecutionFacts> findBatch(long projectId, UUID batchId) { return Optional.empty(); }
        @Override public boolean tryClaimBatch(long projectId, UUID batchId, Instant startedAt) { return false; }
        @Override public boolean requestBatchCancel(long projectId, UUID batchId) { return false; }
        @Override public boolean completeBatch(long projectId, UUID batchId, RunStatus status, Instant finishedAt) { return false; }
        @Override public long saveTask(long projectId, String caseId, String apiId, String name, String json) { throw new UnsupportedOperationException(); }
        @Override public long saveRun(long projectId, long taskId, RunStatus status, FailureType type, Instant startedAt, Instant finishedAt) { throw new UnsupportedOperationException(); }
        @Override public long saveCaseResult(long projectId, long runId, String caseId, RunStatus status, FailureType type, Instant startedAt, Instant finishedAt) { throw new UnsupportedOperationException(); }
        @Override public long saveStepResult(long projectId, long runId, long caseResultId, String stepId, StepResult result) { throw new UnsupportedOperationException(); }
    }
}
