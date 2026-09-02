package com.apiops.web.tool;

import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.common.enums.FailureType;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.ExecutionFactRepository.CaseExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.RunExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.StepExecutionFacts;
import com.apiops.runner.state.RunStatus;
import com.apiops.web.ApiOpsWebApplication;
import com.apiops.web.project.domain.Project;
import com.apiops.web.project.repository.ProjectRepository;
import com.apiops.web.runner.application.RunQueryApplicationService;
import com.apiops.web.runner.controller.RunQueryController;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.context.ActiveProfiles;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** Real Java HTTP and real Python process evidence for the Historical Memory chain. */
@SpringBootTest(
        classes = ApiOpsWebApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
@Import({
        Stage17RagToolGatewayIntegrationTest.Stage17TestConfiguration.class,
        HistoricalMemoryDiagnosisCrossProcessE2ETest.ReportFixtureConfiguration.class,
        HistoricalMemoryDiagnosisCrossProcessE2ETest.RunQueryBoundaryConfiguration.class,
        HistoricalMemoryDiagnosisCrossProcessE2ETest.ProjectBoundaryConfiguration.class
})
class HistoricalMemoryDiagnosisCrossProcessE2ETest {

    private static final long USER_ID = 7L;
    private static final long PROJECT_ID = 42L;
    private static final long TASK_ID = 301L;
    private static final long RUN_ID = 701L;
    private static final String API_ID = "orders-api";
    private static final String CASE_ID = "case-failed";
    private static final String USERNAME = "stage17-project-a";
    private static final long PROCESS_TIMEOUT_SECONDS = 120L;

    @LocalServerPort
    private int serverPort;

    @Autowired
    private JwtTokenService jwtTokenService;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void historicalMemorySurvivesPythonRestartAndIsRecalledThroughHttpTrace() throws Exception {
        String token = jwtTokenService.generateAccessToken(new ApiOpsPrincipal(
                USER_ID,
                USERNAME,
                "test-password-hash",
                true,
                List.of(new SimpleGrantedAuthority("TOOL_READ"))));
        Path pythonProject = findPythonProject();
        ProcessBuilder builder = new ProcessBuilder(
                "uv", "run", "python", "scripts/historical_memory_live_e2e.py", "controlled");
        builder.directory(pythonProject.toFile());
        builder.environment().put("JAVA_APIOPS_BASE_URL", "http://127.0.0.1:" + serverPort);
        builder.environment().put("JAVA_APIOPS_TOKEN", token);
        builder.environment().put("STAGE_MEMORY_PROJECT_ID", Long.toString(PROJECT_ID));
        builder.environment().put("STAGE_MEMORY_RUN_ID", Long.toString(RUN_ID));
        builder.environment().put("STAGE_MEMORY_EXPECTED_API_ID", API_ID);
        builder.environment().put("PYTHONUTF8", "1");

        Process process = builder.start();
        CompletableFuture<String> stdout = readAsync(process.getInputStream());
        CompletableFuture<String> stderr = readAsync(process.getErrorStream());
        if (!process.waitFor(PROCESS_TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            fail("Historical Memory Python E2E exceeded the 120 second deadline");
        }
        String output = stdout.join().trim();
        String errors = stderr.join().trim();
        assertFalse(output.contains(token), "Python stdout must not expose JWT");
        assertFalse(errors.contains(token), "Python stderr must not expose JWT");
        assertEquals(0, process.exitValue(), () -> "Historical Memory Python E2E failed: " + errors);

        JsonNode result = objectMapper.readTree(output);
        assertEquals("PASS", requiredText(result, "status"));
        assertEquals(PROJECT_ID, result.path("projectId").asLong());
        assertEquals(RUN_ID, result.path("runId").asLong());
        assertEquals(API_ID, requiredText(result, "apiId"));
        assertEquals(0, result.path("preWriteRowCount").asInt());
        assertEquals("ACCEPT", requiredText(result, "writeOutcome"));
        assertEquals("IDEMPOTENT", requiredText(result, "duplicateOutcome"));
        assertTrue(result.path("invalidHypothesisStatus").asInt() >= 400);
        assertTrue(result.path("extraAuthorityStatus").asInt() >= 400);
        assertEquals(1, result.path("negativePostRowCount").asInt());
        assertEquals(1, result.path("postWriteRowCount").asInt());
        assertEquals(1, result.path("postRestartRowCount").asInt());
        assertTrue(result.path("pythonRestarted").asBoolean());
        assertNotNull(requiredText(result, "firstAgentRunId"));
        assertNotNull(requiredText(result, "secondAgentRunId"));
        assertNotNull(requiredText(result, "firstTraceId"));
        assertNotNull(requiredText(result, "secondTraceId"));
        assertTrue(requiredText(result, "memoryId").matches("memory_[0-9a-f]{64}"));
        assertEquals(1, result.path("historicalMemoryRetrievalCount").asInt());
        assertTrue(result.path("refinementModelCallPresent").asBoolean());
        assertEquals(0, result.path("toolCallCountAfterRestart").asInt());
        assertEquals(3, result.path("providerCallCount").asInt());
        assertEquals(2, result.path("providerInitialCallCount").asInt());
        assertEquals(1, result.path("providerRefinementCallCount").asInt());
        assertTrue(result.path("apiIdEqual").asBoolean());
        assertTrue(result.path("symptomsEqual").asBoolean());
        assertTrue(result.path("normalizedRootCauseEqual").asBoolean());
        assertTrue(result.path("fingerprintsEqual").asBoolean());

        System.out.println("HISTORICAL_MEMORY_CONTROLLED_E2E " + result);
    }

    private static CompletableFuture<String> readAsync(java.io.InputStream stream) {
        return CompletableFuture.supplyAsync(() -> {
            try (stream) {
                return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
            } catch (IOException exception) {
                throw new UncheckedIOException(exception);
            }
        });
    }

    private static String requiredText(JsonNode node, String field) {
        String value = node.path(field).asText();
        assertFalse(value.isBlank(), () -> field + " must be present");
        return value;
    }

    private static Path findPythonProject() {
        Path current = Path.of("").toAbsolutePath();
        while (current != null) {
            Path candidate = current.resolve("python-apiops-agentlab");
            if (Files.isRegularFile(candidate.resolve("pyproject.toml"))) {
                return candidate;
            }
            current = current.getParent();
        }
        throw new IllegalStateException("python-apiops-agentlab project was not found");
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class ReportFixtureConfiguration {

        @Bean
        @Primary
        ExecutionFactRepository historicalMemoryExecutionFactRepository() {
            ExecutionFactRepository repository = mock(ExecutionFactRepository.class);
            when(repository.findRun(PROJECT_ID, RUN_ID)).thenReturn(Optional.of(completedFacts()));
            when(repository.findRecentRunSummaries(PROJECT_ID)).thenReturn(List.of(
                    new ExecutionFactRepository.RunSummary(
                            RUN_ID,
                            CASE_ID,
                            API_ID,
                            "Historical Memory failure fixture",
                            RunStatus.ASSERTION_FAILED,
                            FailureType.ASSERTION_MISMATCH,
                            Instant.parse("2026-08-23T11:59:58Z"),
                            Instant.parse("2026-08-23T11:59:58Z"),
                            Instant.parse("2026-08-23T12:00:00Z"))));
            return repository;
        }

        private static RunExecutionFacts completedFacts() {
            Instant started = Instant.parse("2026-08-23T11:59:58Z");
            Instant finished = Instant.parse("2026-08-23T12:00:00Z");
            StepExecutionFacts step = new StepExecutionFacts(
                    PROJECT_ID,
                    RUN_ID,
                    901L,
                    1001L,
                    "step-failed",
                    RunStatus.ASSERTION_FAILED,
                    FailureType.ASSERTION_MISMATCH,
                    "[{\"type\":\"STATUS_CODE\",\"passed\":false,"
                            + "\"expected\":200,\"actual\":500,"
                            + "\"message\":\"status mismatch\"}]",
                    500,
                    12L,
                    finished);
            CaseExecutionFacts testCase = new CaseExecutionFacts(
                    PROJECT_ID,
                    RUN_ID,
                    901L,
                    CASE_ID,
                    RunStatus.ASSERTION_FAILED,
                    FailureType.ASSERTION_MISMATCH,
                    started,
                    finished,
                    List.of(step));
            return new RunExecutionFacts(
                    PROJECT_ID,
                    TASK_ID,
                    RUN_ID,
                    CASE_ID,
                    API_ID,
                    "Historical Memory failure fixture",
                    RunStatus.ASSERTION_FAILED,
                    FailureType.ASSERTION_MISMATCH,
                    started,
                    finished,
                    List.of(testCase));
        }
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class RunQueryBoundaryConfiguration {

        @Bean
        RunQueryApplicationService historicalMemoryRunQueryApplicationService(
                com.apiops.auth.application.ProjectAuthorizationService authorization,
                ExecutionFactRepository repository
        ) {
            return new RunQueryApplicationService(authorization, repository);
        }

        @Bean
        RunQueryController historicalMemoryRunQueryController(
                RunQueryApplicationService service
        ) {
            return new RunQueryController(service);
        }
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class ProjectBoundaryConfiguration {

        @Bean
        @Primary
        ProjectRepository historicalMemoryProjectRepository() {
            ProjectRepository repository = mock(ProjectRepository.class);
            when(repository.findById(PROJECT_ID)).thenReturn(Optional.of(new Project(
                    PROJECT_ID,
                    "historical-memory-fixture",
                    "Historical Memory fixture",
                    USER_ID,
                    "ACTIVE",
                    Instant.parse("2026-08-23T11:59:00Z"),
                    Instant.parse("2026-08-23T11:59:00Z"))));
            return repository;
        }
    }
}
