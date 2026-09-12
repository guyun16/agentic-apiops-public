package com.apiops.web.tool;

import com.sun.net.httpserver.HttpServer;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.AuditStatus;
import com.apiops.tool.gateway.ToolGateway;
import com.apiops.web.ApiOpsWebApplication;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
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
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.fail;

/**
 * Cross-process failure evidence for the existing Stage 20 public boundaries.
 *
 * <p>The Python process uses the real Java client. The embedded server keeps the
 * production JWT, project authorization, Tool Gateway and Audit wiring. Only the
 * handler outcome is controlled in test scope for the TIMEOUT/FAILED cases.</p>
 */
@SpringBootTest(
        classes = ApiOpsWebApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "apiops.tool.gateway.execution-timeout=1s")
@ActiveProfiles("test")
@Import({
        Stage17RagToolGatewayIntegrationTest.Stage17TestConfiguration.class,
        Stage20DiagnosisToolAuditCrossProcessE2ETest.ReportFixtureConfiguration.class,
        Stage20FailureCrossProcessE2ETest.FailureToolConfiguration.class
})
class Stage20FailureCrossProcessE2ETest {

    private static final long USER_ID = 7L;
    private static final long PROJECT_ID = 42L;
    private static final long RUN_ID = 701L;
    private static final long FORBIDDEN_PROJECT_ID = 43L;
    private static final String USERNAME = "stage17-project-a";
    private static final long PROCESS_TIMEOUT_SECONDS = 60L;
    private static final AtomicReference<String> TOOL_MODE = new AtomicReference<>("SUCCESS");

    @LocalServerPort
    private int serverPort;

    @Autowired
    private JwtTokenService jwtTokenService;

    @Autowired
    private Audit audit;

    @Autowired
    private ObjectMapper objectMapper;

    @BeforeEach
    void resetToolMode() {
        TOOL_MODE.set("SUCCESS");
    }

    @AfterEach
    void clearToolMode() {
        TOOL_MODE.set("SUCCESS");
    }

    @Test
    void realInvalidCredentialIs401AndNotAProjectForbidden() throws Exception {
        JsonNode result = runPython(
                "--failure-probe",
                "AUTH_401",
                "invalid-stage20-credential",
                PROJECT_ID,
                RUN_ID,
                null);

        assertEquals("AUTH_401", result.path("failureMode").asText());
        assertEquals(401, result.path("httpStatus").asInt());
        assertEquals("authentication_failure", result.path("semantic").asText());
        assertFalse(result.path("rawFallbackUsed").asBoolean(true));
    }

    @Test
    void realUnauthorizedProjectReturnsJavaForbiddenAndNoFallback() throws Exception {
        JsonNode result = runPython(
                "--failure-probe",
                "PROJECT_403",
                validToken(),
                PROJECT_ID,
                RUN_ID,
                null);

        String toolCallId = requiredText(result, "toolCallId");
        assertEquals("PROJECT_403", result.path("failureMode").asText());
        assertEquals(FORBIDDEN_PROJECT_ID, result.path("projectId").asLong());
        assertEquals("FORBIDDEN", result.path("toolStatus").asText());
        assertFalse(result.path("rawFallbackUsed").asBoolean(true));

        Audit.AuditEvent event = audit.events().stream()
                .filter(candidate -> candidate.toolCallId().equals(toolCallId))
                .findFirst()
                .orElseThrow();
        assertEquals(FORBIDDEN_PROJECT_ID, event.projectId());
        assertEquals("rag.search", event.toolName());
        assertEquals(AuditStatus.DENIED, event.status());
        System.out.println("STAGE21_TOOL_SAFETY_CORRELATION " + result);
    }

    @Test
    void realUnauthorizedProjectReportReturnsHttp403AndNotAuthenticationFailure() throws Exception {
        JsonNode result = runPython(
                "--failure-probe",
                "PROJECT_HTTP_403",
                validToken(),
                PROJECT_ID,
                RUN_ID,
                null);

        assertEquals("PROJECT_HTTP_403", result.path("failureMode").asText());
        assertEquals(403, result.path("httpStatus").asInt());
        assertEquals("project_authorization_failure", result.path("semantic").asText());
        assertEquals(FORBIDDEN_PROJECT_ID, result.path("projectId").asLong());
        assertFalse(result.path("rawFallbackUsed").asBoolean(true));
    }

    @Test
    void unavailableJavaBoundaryIsTransportFailureAndNotJavaBusinessFailure() throws Exception {
        JsonNode result = runPythonAt(
                "http://stage20.invalid",
                "--failure-probe",
                "JAVA_UNAVAILABLE",
                validToken(),
                PROJECT_ID,
                RUN_ID,
                null);

        assertEquals("JAVA_UNAVAILABLE", result.path("failureMode").asText());
        assertEquals("transport_unavailable", result.path("semantic").asText());
        assertFalse(result.has("httpStatus"));
        assertFalse(result.path("rawFallbackUsed").asBoolean(true));
    }

    @Test
    void realMissingMetadataIs404AndNotMalformedContract() throws Exception {
        JsonNode result = runPython(
                "--failure-probe",
                "NOT_FOUND",
                validToken(),
                PROJECT_ID,
                999_999L,
                null);

        assertEquals("NOT_FOUND", result.path("failureMode").asText());
        assertEquals(404, result.path("httpStatus").asInt());
        assertEquals("resource_not_found", result.path("semantic").asText());
    }

    @Test
    void controlledMalformedResponseIsStrictContractFailureNotJavaBusinessFailure()
            throws Exception {
        HttpServer malformedServer = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        malformedServer.createContext("/", exchange -> {
            byte[] body = "{\"success\":true,\"code\":\"00000\",\"data\":"
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            try (exchange) {
                exchange.getResponseBody().write(body);
            }
        });
        malformedServer.start();
        try {
            JsonNode result = runPythonAt(
                    "http://127.0.0.1:" + malformedServer.getAddress().getPort(),
                    "--failure-probe",
                    "MALFORMED_RESPONSE",
                    validToken(),
                    PROJECT_ID,
                    RUN_ID,
                    null);

            assertEquals("MALFORMED_RESPONSE", result.path("failureMode").asText());
            assertEquals("malformed_response", result.path("semantic").asText());
            assertEquals("JavaApiOpsMalformedResponseError", result.path("errorType").asText());
            assertFalse(result.has("httpStatus"));
            assertFalse(result.path("rawFallbackUsed").asBoolean(true));
        } finally {
            malformedServer.stop(0);
        }
    }

    @ParameterizedTest
    @ValueSource(strings = {"FAILED", "TIMEOUT"})
    void controlledJavaToolFailureKeepsStatusIdentityAndBoundedDiagnosis(String mode)
            throws Exception {
        TOOL_MODE.set(mode);
        JsonNode result = runPython(
                "--diagnosis-e2e",
                "TOOL_" + mode,
                validToken(),
                PROJECT_ID,
                RUN_ID,
                mode);

        String toolCallId = requiredText(result, "toolCallId");
        assertEquals(mode, result.path("toolStatus").asText());
        assertEquals(1, result.path("toolCallCount").asInt());
        assertEquals(0, result.path("retryCount").asInt());
        assertFalse(result.path("rawFallbackUsed").asBoolean(true));
        assertEquals(PROJECT_ID, result.path("projectId").asLong());
        assertEquals(RUN_ID, result.path("runId").asLong());
        assertEquals("report:" + RUN_ID, result.path("reportId").asText());
        assertEquals(PROJECT_ID, result.path("diagnosisReport").path("projectId").asLong());
        assertEquals(RUN_ID, result.path("diagnosisReport").path("runId").asLong());
        assertEquals("report:" + RUN_ID, result.path("diagnosisReport").path("reportId").asText());
        assertEquals(0, result.path("guardedEvidenceCount").asInt());

        Audit.AuditEvent event = audit.events().stream()
                .filter(candidate -> candidate.toolCallId().equals(toolCallId))
                .findFirst()
                .orElseThrow();
        assertEquals(PROJECT_ID, event.projectId());
        assertEquals("rag.search", event.toolName());
        assertEquals(mode, event.status().name());
    }

    private String validToken() {
        return jwtTokenService.generateAccessToken(new ApiOpsPrincipal(
                USER_ID,
                USERNAME,
                "test-password-hash",
                true,
                List.of(new SimpleGrantedAuthority("TOOL_READ"))));
    }

    private JsonNode runPython(
            String argument,
            String failureMode,
            String token,
            long projectId,
            long runId,
            String expectedToolStatus
    ) throws Exception {
        return runPythonAt(
                "http://127.0.0.1:" + serverPort,
                argument,
                failureMode,
                token,
                projectId,
                runId,
                expectedToolStatus);
    }

    private JsonNode runPythonAt(
            String baseUrl,
            String argument,
            String failureMode,
            String token,
            long projectId,
            long runId,
            String expectedToolStatus
    ) throws Exception {
        String traceId = "stage20-failure-" + UUID.randomUUID();
        Path pythonProject = findPythonProject();
        ProcessBuilder builder = new ProcessBuilder(
                "uv", "run", "python", "scripts/stage20_real_e2e.py", argument);
        builder.directory(pythonProject.toFile());
        builder.environment().put("JAVA_APIOPS_BASE_URL", baseUrl);
        builder.environment().put("JAVA_APIOPS_TOKEN", token);
        builder.environment().put("STAGE20_PROJECT_ID", Long.toString(projectId));
        builder.environment().put("STAGE20_RUN_ID", Long.toString(runId));
        builder.environment().put("STAGE20_TRACE_ID", traceId);
        builder.environment().put("STAGE20_FAILURE_MODE", failureMode);
        copyOptionalEnvironment(builder, "STAGE20_TOOL_QUERY");
        copyOptionalEnvironment(builder, "STAGE20_TOOL_TOP_K");
        if (expectedToolStatus == null) {
            builder.environment().remove("STAGE20_EXPECT_TOOL_STATUS");
        } else {
            builder.environment().put("STAGE20_EXPECT_TOOL_STATUS", expectedToolStatus);
        }
        builder.environment().put("PYTHONUTF8", "1");

        Process process = builder.start();
        CompletableFuture<String> stdout = readAsync(process.getInputStream());
        CompletableFuture<String> stderr = readAsync(process.getErrorStream());
        boolean completed = process.waitFor(PROCESS_TIMEOUT_SECONDS, TimeUnit.SECONDS);
        if (!completed) {
            process.destroyForcibly();
            fail("Python Stage 20 failure subprocess exceeded its deadline");
        }
        String output = stdout.join().trim();
        String errors = stderr.join().trim();
        assertFalse(output.contains(token), "Python stdout must not expose credential");
        assertFalse(errors.contains(token), "Python stderr must not expose credential");
        assertEquals(0, process.exitValue(), () -> "Python failure probe failed: " + errors);
        JsonNode result = objectMapper.readTree(output);
        assertEquals(traceId, result.path("traceId").asText());
        return result;
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
    static class FailureToolConfiguration {

        @Bean
        @Primary
        ToolGatewayRestApplicationService controlledFailureService(ToolGateway gateway) {
            return new ToolGatewayRestApplicationService(
                    gateway,
                    Map.of("rag.search", (context, intent) -> {
                        String mode = TOOL_MODE.get();
                        if ("FAILED".equals(mode)) {
                            throw new IllegalStateException("controlled Stage 20 handler failure");
                        }
                        if ("TIMEOUT".equals(mode)) {
                            Thread.sleep(2_500L);
                        }
                        return Map.of("results", List.of(), "ragQueryId", "controlled-success");
                    }));
        }
    }
}
