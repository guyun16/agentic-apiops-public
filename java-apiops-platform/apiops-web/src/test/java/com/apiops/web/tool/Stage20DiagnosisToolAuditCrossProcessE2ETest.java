package com.apiops.web.tool;

import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.common.enums.FailureType;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.ExecutionFactRepository.CaseExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.RunExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.StepExecutionFacts;
import com.apiops.runner.state.RunStatus;
import com.apiops.tool.gateway.Audit;
import com.apiops.web.ApiOpsWebApplication;
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
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Cross-process Stage 20.3 authority evidence.
 *
 * <p>The embedded server owns the real JWT filter, project authorization, Tool Gateway,
 * ToolAuth/ResourceGuard path, handler, and shared Audit bean. The Python subprocess obtains
 * TestReport and ToolResult only through public HTTP boundaries.</p>
 */
@SpringBootTest(
        classes = ApiOpsWebApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
@Import({
        Stage17RagToolGatewayIntegrationTest.Stage17TestConfiguration.class,
        Stage20DiagnosisToolAuditCrossProcessE2ETest.ReportFixtureConfiguration.class
})
class Stage20DiagnosisToolAuditCrossProcessE2ETest {

    private static final long USER_ID = 7L;
    private static final long PROJECT_ID = 42L;
    private static final long TASK_ID = 301L;
    private static final long RUN_ID = 701L;
    private static final String USERNAME = "stage17-project-a";
    private static final long PROCESS_TIMEOUT_SECONDS = 60L;

    @LocalServerPort
    private int serverPort;

    @Autowired
    private JwtTokenService jwtTokenService;

    @Autowired
    private Audit audit;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void pythonTraceJavaResultAndSameContextAuditShareToolCallId() throws Exception {
        String token = jwtTokenService.generateAccessToken(new ApiOpsPrincipal(
                USER_ID,
                USERNAME,
                "test-password-hash",
                true,
                List.of(new SimpleGrantedAuthority("TOOL_READ"))));
        String traceId = "stage20-cross-process-" + UUID.randomUUID();
        Path pythonProject = findPythonProject();
        ProcessBuilder builder = new ProcessBuilder(
                "uv", "run", "python", "scripts/stage20_real_e2e.py", "--diagnosis-e2e");
        builder.directory(pythonProject.toFile());
        builder.environment().put("JAVA_APIOPS_BASE_URL", "http://127.0.0.1:" + serverPort);
        builder.environment().put("JAVA_APIOPS_TOKEN", token);
        builder.environment().put("STAGE20_PROJECT_ID", Long.toString(PROJECT_ID));
        builder.environment().put("STAGE20_RUN_ID", Long.toString(RUN_ID));
        builder.environment().put("STAGE20_TRACE_ID", traceId);
        copyOptionalEnvironment(builder, "STAGE20_TOOL_QUERY");
        copyOptionalEnvironment(builder, "STAGE20_TOOL_TOP_K");
        builder.environment().put("PYTHONUTF8", "1");

        Process process = builder.start();
        CompletableFuture<String> stdout = readAsync(process.getInputStream());
        CompletableFuture<String> stderr = readAsync(process.getErrorStream());
        boolean completed = process.waitFor(PROCESS_TIMEOUT_SECONDS, TimeUnit.SECONDS);
        if (!completed) {
            process.destroyForcibly();
            fail("Python Stage 20 E2E subprocess exceeded the 60 second deadline");
        }
        String output = stdout.join().trim();
        String errors = stderr.join().trim();
        assertFalse(output.contains(token), "Python stdout must not expose JWT");
        assertFalse(errors.contains(token), "Python stderr must not expose JWT");
        assertEquals(0, process.exitValue(), () -> "Python E2E failed: " + errors);

        JsonNode python = objectMapper.readTree(output);
        String traceToolCallId = requiredText(python, "toolCallId");
        String resultToolCallId = requiredText(python, "toolResultToolCallId");
        String toolName = requiredText(python, "toolName");
        String toolStatus = requiredText(python, "toolStatus");
        assertEquals(traceToolCallId, resultToolCallId);
        assertEquals(PROJECT_ID, python.path("projectId").asLong());
        assertEquals(TASK_ID, python.path("taskId").asLong());
        assertEquals(RUN_ID, python.path("runId").asLong());
        assertEquals("report:" + RUN_ID, requiredText(python, "reportId"));
        assertNotEquals(Long.toString(RUN_ID), requiredText(python, "reportId"));
        assertEquals("ASSERTION_FAILED", python.path("testReportStatus").asText());
        assertEquals("ASSERTION_MISMATCH", python.path("failureType").asText());
        assertEquals(traceId, requiredText(python, "traceId"));
        assertNotEquals(Long.toString(RUN_ID), requiredText(python, "agentRunId"));
        assertNotEquals(traceId, traceToolCallId);
        assertNotEquals(Long.toString(RUN_ID), traceToolCallId);
        assertEquals(1, python.path("toolCallCount").asInt());
        assertEquals(0, python.path("retryCount").asInt());
        assertFalse(python.path("rawFallbackUsed").asBoolean(true));
        assertTrue(python.path("guardedEvidenceCount").asInt() > 0);

        JsonNode httpRequests = python.path("httpRequests");
        assertTrue(httpRequests.isArray());
        assertTrue(httpRequests.size() >= 2);
        Set<String> requestIds = new HashSet<>();
        for (JsonNode request : httpRequests) {
            assertEquals(traceId, request.path("requestTraceId").asText());
            assertEquals(traceId, request.path("responseTraceId").asText());
            String requestId = requiredText(request, "responseRequestId");
            assertFalse(requestId.equals(traceId));
            requestIds.add(requestId);
        }
        assertEquals(httpRequests.size(), requestIds.size(),
                "each inbound HTTP request must have a distinct requestId");

        JsonNode diagnosis = python.path("diagnosisReport");
        assertEquals(PROJECT_ID, diagnosis.path("projectId").asLong());
        assertEquals(RUN_ID, diagnosis.path("runId").asLong());
        assertEquals("report:" + RUN_ID, requiredText(diagnosis, "reportId"));

        Audit.AuditEvent event = audit.events().stream()
                .filter(candidate -> candidate.toolCallId().equals(resultToolCallId))
                .findFirst()
                .orElseThrow();
        assertEquals(PROJECT_ID, event.projectId());
        assertEquals(toolName, event.toolName());
        assertEquals(toolStatus, event.status().name());
        assertEquals(traceToolCallId, event.toolCallId());

        String requestIdSummary = requestIds.stream().sorted().collect(java.util.stream.Collectors.joining(","));

        System.out.printf(
                "STAGE20_CROSS_PROCESS_CORRELATION traceId=%s agentRunId=%s agentStepId=%s "
                        + "runId=%d reportId=%s toolCallId=%s toolName=%s status=%s "
                        + "ragQueryId=%s requestIds=%s sufficientEvidence=%s%n",
                traceId,
                requiredText(python, "agentRunId"),
                requiredText(python, "agentStepId"),
                RUN_ID,
                "report:" + RUN_ID,
                traceToolCallId,
                toolName,
                toolStatus,
                python.path("ragQueryId").asText("NOT_PRESENT"),
                requestIdSummary,
                diagnosis.path("sufficientEvidence").asBoolean());
        System.out.println("STAGE20_DIAGNOSIS_CORRELATION " + python);
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

    private static void copyOptionalEnvironment(ProcessBuilder builder, String name) {
        String value = System.getenv(name);
        if (value != null && !value.isBlank()) {
            builder.environment().put(name, value);
        }
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
        ExecutionFactRepository stage20ExecutionFactRepository() {
            ExecutionFactRepository repository = mock(ExecutionFactRepository.class);
            when(repository.findRun(PROJECT_ID, RUN_ID)).thenReturn(Optional.of(completedFacts()));
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
                    "case-failed",
                    RunStatus.ASSERTION_FAILED,
                    FailureType.ASSERTION_MISMATCH,
                    started,
                    finished,
                    List.of(step));
            return new RunExecutionFacts(
                    PROJECT_ID,
                    TASK_ID,
                    RUN_ID,
                    "case-failed",
                    "orders-api",
                    "Stage 20 completed fixture",
                    RunStatus.ASSERTION_FAILED,
                    FailureType.ASSERTION_MISMATCH,
                    started,
                    finished,
                    List.of(testCase));
        }
    }
}
