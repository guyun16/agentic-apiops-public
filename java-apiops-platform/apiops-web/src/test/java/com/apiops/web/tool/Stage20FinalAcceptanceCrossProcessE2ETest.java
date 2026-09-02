package com.apiops.web.tool;

import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiResponseSchema;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.state.RunStatus;
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.Audit.AuditEvent;
import com.apiops.tool.gateway.AuditStatus;
import com.apiops.web.ApiOpsWebApplication;
import com.apiops.web.runner.rabbit.ExecutionRabbitProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.amqp.rabbit.core.RabbitAdmin;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Import;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.annotation.DirtiesContext;

import javax.sql.DataSource;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.ServerSocket;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.SQLException;
import java.time.Duration;
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

/** Deterministic Stage 20 final main-chain evidence across real Java/Python processes. */
@SpringBootTest(
        classes = ApiOpsWebApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "apiops.datasource.openapi.url=${APIOPS_OPENAPI_DB_URL}",
                "apiops.datasource.openapi.username=${APIOPS_OPENAPI_DB_USERNAME:root}",
                "apiops.datasource.openapi.password=${APIOPS_OPENAPI_DB_PASSWORD}",
                "apiops.datasource.runner.url=${APIOPS_RUNNER_DB_URL}",
                "apiops.datasource.runner.username=${APIOPS_RUNNER_DB_USERNAME:root}",
                "apiops.datasource.runner.password=${APIOPS_RUNNER_DB_PASSWORD}",
                "apiops.rabbitmq.execution.enabled=true",
                "apiops.rabbitmq.execution.exchange=apiops.stage20.final.exchange",
                "apiops.rabbitmq.execution.routing-key=apiops.stage20.final.run",
                "apiops.rabbitmq.execution.queue=apiops.stage20.final.queue",
                "apiops.rabbitmq.execution.dead-letter-exchange=apiops.stage20.final.dlx",
                "apiops.rabbitmq.execution.dead-letter-routing-key=apiops.stage20.final.dead",
                "apiops.rabbitmq.execution.dead-letter-queue=apiops.stage20.final.dlq",
                "apiops.rabbitmq.execution.max-attempts=1",
                "apiops.runner.progress.enabled=true",
                "apiops.runner.progress.ttl=60s",
                "apiops.runner.progress.sse-timeout=30s",
                "apiops.runner.executor.core-pool-size=1",
                "apiops.runner.executor.maximum-pool-size=1",
                "apiops.runner.executor.queue-capacity=2",
                "apiops.runner.executor.thread-name-prefix=stage20-final-",
                "spring.rabbitmq.host=${APIOPS_RABBITMQ_HOST:127.0.0.1}",
                "spring.rabbitmq.port=${APIOPS_RABBITMQ_PORT:5672}",
                "spring.rabbitmq.username=${APIOPS_RABBITMQ_USERNAME:guest}",
                "spring.rabbitmq.password=${APIOPS_RABBITMQ_PASSWORD:guest}",
                "spring.data.redis.host=${APIOPS_REDIS_HOST:127.0.0.1}",
                "spring.data.redis.port=${APIOPS_REDIS_PORT:6379}",
                "management.health.redis.enabled=false",
                "apiops.auth.jwt.issuer=stage20-final",
                "apiops.auth.jwt.access-token-ttl=15m",
                "apiops.auth.jwt.secret=dGVzdC1vbmx5LWp3dC1zZWNyZXQtbWF0ZXJpYWwtMjAyNi0wOC0wNw=="
        })
@DirtiesContext
@Import({
        Stage17RagToolGatewayIntegrationTest.Stage17TestConfiguration.class
})
@EnabledIfEnvironmentVariable(named = "APIOPS_OPENAPI_DB_URL", matches = ".+")
@EnabledIfEnvironmentVariable(named = "APIOPS_OPENAPI_DB_PASSWORD", matches = ".+")
@EnabledIfEnvironmentVariable(named = "APIOPS_RUNNER_DB_URL", matches = ".+")
@EnabledIfEnvironmentVariable(named = "APIOPS_RUNNER_DB_PASSWORD", matches = ".+")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_PASSWORD", matches = ".+")
class Stage20FinalAcceptanceCrossProcessE2ETest {

    private static final long USER_ID = 7L;
    private static final long PROJECT_ID = 20_205_001L;
    private static final String USERNAME = "stage17-project-a";
    private static final String API_DOC_ID = "stage20-final-demo-order";
    private static final String API_ID = "stage20-final-list-products";

    @LocalServerPort
    private int serverPort;

    @Autowired
    private JwtTokenService jwtTokenService;

    @Autowired
    private OpenApiMetadataRepository metadataRepository;

    @Autowired
    private ExecutionFactRepository executionFacts;

    @Autowired
    private Audit audit;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private RabbitAdmin rabbitAdmin;

    @Autowired
    private ExecutionRabbitProperties rabbitProperties;

    @Autowired
    private StringRedisTemplate redis;

    @Autowired
    @Qualifier("openApiDataSource")
    private DataSource openApiDataSource;

    @Autowired
    @Qualifier("runnerDataSource")
    private DataSource runnerDataSource;

    @BeforeEach
    void prepareInfrastructure() throws SQLException {
        rabbitAdmin.purgeQueue(rabbitProperties.getQueue(), false);
        rabbitAdmin.purgeQueue(rabbitProperties.getDeadLetterQueue(), false);
        deleteRunnerFacts();
        deleteMetadata();
    }

    @AfterEach
    void cleanInfrastructure() throws SQLException {
        rabbitAdmin.purgeQueue(rabbitProperties.getQueue(), false);
        rabbitAdmin.purgeQueue(rabbitProperties.getDeadLetterQueue(), false);
        redis.delete(redis.keys("apiops:runner:progress:" + PROJECT_ID + ":*"));
        deleteRunnerFacts();
        deleteMetadata();
        rabbitAdmin.deleteQueue(rabbitProperties.getQueue());
        rabbitAdmin.deleteQueue(rabbitProperties.getDeadLetterQueue());
        rabbitAdmin.deleteExchange(rabbitProperties.getExchange());
        rabbitAdmin.deleteExchange(rabbitProperties.getDeadLetterExchange());
    }

    @Test
    void fullMainChainPreservesJavaAuthoritiesAndSameContextAudit() throws Exception {
        Path demoLog = Files.createTempFile("stage20-demo-order-", ".log");
        demoLog.toFile().deleteOnExit();
        DemoRuntime demo = startDemoOrderService(demoLog);
        try {
            String demoBaseUrl = awaitDemoOrder(demo);
            seedMetadata(demoBaseUrl);
            String token = jwtTokenService.generateAccessToken(new ApiOpsPrincipal(
                    USER_ID,
                    USERNAME,
                    "test-password-hash",
                    true,
                    List.of(new SimpleGrantedAuthority("TOOL_READ"))));
            String traceId = "stage20-final-" + UUID.randomUUID();
            JsonNode result = runPython(token, traceId, demoBaseUrl);

            JsonNode identity = result.path("identity");
            long runId = identity.path("runId").asLong();
            String reportId = requiredText(identity, "reportId");
            String toolCallId = requiredText(identity, "toolCallId");
            String agentRunId = requiredText(identity, "agentRunId");
            assertEquals(traceId, identity.path("traceId").asText());
            assertTrue(runId > 0);
            assertEquals("report:" + runId, reportId);
            assertNotEquals(traceId, agentRunId);
            assertNotEquals(traceId, Long.toString(runId));
            assertNotEquals(traceId, toolCallId);
            assertNotEquals(Long.toString(runId), toolCallId);

            assertEquals("OpenApiMetadataDetail", result.path("metadata").path("typed").asText());
            assertEquals("listProducts", result.path("metadata").path("operationId").asText());
            assertEquals("TestCaseDSL", result.path("generation").path("validatedDsl").asText());
            assertEquals("SUCCESS", result.path("runner").path("terminalStatus").asText());
            assertEquals("SUCCESS", result.path("report").path("status").asText());
            assertEquals(toolCallId, result.path("tool").path("toolCallId").asText());
            assertEquals(toolCallId, result.path("tool").path("traceToolCallId").asText());
            assertEquals("SUCCESS", result.path("tool").path("status").asText());
            assertEquals(1, result.path("toolCallCount").asInt());
            assertEquals(0, result.path("retryCount").asInt());
            assertFalse(result.path("rawFallbackUsed").asBoolean(true));

            JsonNode diagnosis = result.path("diagnosisReport");
            assertEquals(PROJECT_ID, diagnosis.path("projectId").asLong());
            assertEquals(runId, diagnosis.path("runId").asLong());
            assertEquals(reportId, diagnosis.path("reportId").asText());
            assertEquals(RunStatus.SUCCESS,
                    executionFacts.findRun(PROJECT_ID, runId).orElseThrow().status());

            AuditEvent event = audit.events().stream()
                    .filter(candidate -> toolCallId.equals(candidate.toolCallId()))
                    .findFirst()
                    .orElseThrow(() -> new AssertionError("same-context Java AuditEvent missing"));
            assertEquals(PROJECT_ID, event.projectId());
            assertEquals("rag.search", event.toolName());
            assertEquals(AuditStatus.SUCCESS, event.status());

            Set<String> requestIds = new HashSet<>();
            for (JsonNode request : result.path("httpRequests")) {
                assertEquals(traceId, request.path("requestTraceId").asText());
                assertEquals(traceId, request.path("responseTraceId").asText());
                String requestId = requiredText(request, "responseRequestId");
                assertNotEquals(traceId, requestId);
                assertTrue(requestIds.add(requestId), "requestId must be unique per HTTP request");
            }
            assertTrue(requestIds.size() >= 5);

            System.out.printf(
                    "STAGE20_FINAL_SUCCESS traceId=%s agentRunId=%s runId=%d reportId=%s "
                            + "toolCallId=%s ragQueryId=%s auditStatus=%s diagnosisEvidence=%s%n",
                    traceId,
                    agentRunId,
                    runId,
                    reportId,
                    toolCallId,
                    result.path("tool").path("ragQueryId").asText("NOT_PRESENT"),
                    event.status(),
                    diagnosis.path("sufficientEvidence").asBoolean());
            System.out.println("STAGE20_FINAL_CORRELATION " + result);
        } finally {
            stop(demo.process());
        }
    }

    private JsonNode runPython(String token, String traceId, String demoBaseUrl) throws Exception {
        Path pythonProject = findPythonProject();
        ProcessBuilder builder = new ProcessBuilder(
                "uv", "run", "python", "scripts/stage20_real_e2e.py", "--final-e2e");
        builder.directory(pythonProject.toFile());
        builder.environment().put("JAVA_APIOPS_BASE_URL", "http://127.0.0.1:" + serverPort);
        builder.environment().put("JAVA_APIOPS_TOKEN", token);
        builder.environment().put("STAGE20_PROJECT_ID", Long.toString(PROJECT_ID));
        builder.environment().put("STAGE20_API_ID", API_ID);
        builder.environment().put("STAGE20_TRACE_ID", traceId);
        builder.environment().put("STAGE20_DEMO_ORDER_BASE_URL", demoBaseUrl);
        builder.environment().put("STAGE20_RUNNER_READBACK_DEADLINE_SECONDS", "60");
        builder.environment().put("PYTHONUTF8", "1");
        Process process = builder.start();
        CompletableFuture<String> stdout = readAsync(process.getInputStream());
        CompletableFuture<String> stderr = readAsync(process.getErrorStream());
        if (!process.waitFor(120, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            fail("Python Stage 20 final E2E exceeded the 120 second deadline");
        }
        String output = stdout.join().trim();
        String errors = stderr.join().trim();
        assertFalse(output.contains(token), "Python stdout must not expose JWT");
        assertFalse(errors.contains(token), "Python stderr must not expose JWT");
        assertEquals(0, process.exitValue(), () -> "Python Stage 20 final E2E failed: " + errors);
        return objectMapper.readTree(output);
    }

    private DemoRuntime startDemoOrderService(Path log) throws IOException {
        Path jar = findRepositoryRoot().resolve(
                "java-apiops-platform/apiops-demo-order-service/target/"
                        + "apiops-demo-order-service-0.1.0-SNAPSHOT.jar");
        assertTrue(Files.isRegularFile(jar),
                "Package apiops-demo-order-service before the final E2E test");
        int port;
        try (ServerSocket socket = new ServerSocket(0)) {
            port = socket.getLocalPort();
        }
        ProcessBuilder builder = new ProcessBuilder(
                javaExecutable(),
                "-jar",
                jar.toString(),
                "--spring.profiles.active=local",
                "--server.port=" + port);
        builder.environment().put("STAGE20_DEMO_ORDER_PORT", Integer.toString(port));
        builder.redirectErrorStream(true);
        builder.redirectOutput(log.toFile());
        return new DemoRuntime(builder.start(), "http://127.0.0.1:" + port);
    }

    private static String awaitDemoOrder(DemoRuntime runtime) throws Exception {
        Process process = runtime.process();
        String baseUrl = runtime.baseUrl();
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build();
        Instant deadline = Instant.now().plusSeconds(30);
        while (Instant.now().isBefore(deadline)) {
            if (!process.isAlive()) {
                throw new AssertionError("demo-order-service exited before becoming ready");
            }
            try {
                HttpResponse<Void> response = client.send(
                        HttpRequest.newBuilder(URI.create(baseUrl + "/products"))
                                .timeout(Duration.ofSeconds(2))
                                .GET()
                                .build(),
                        HttpResponse.BodyHandlers.discarding());
                if (response.statusCode() == 200) return baseUrl;
            } catch (IOException ignored) {
                // The child process is still starting.
            }
            Thread.sleep(250);
        }
        throw new AssertionError("demo-order-service did not become ready within 30 seconds");
    }

    private void seedMetadata(String demoBaseUrl) {
        Instant now = Instant.now();
        metadataRepository.save(new ApiDocument(
                0, API_DOC_ID, PROJECT_ID, "stage20-final-demo-order",
                "demo-order-service-openapi.json", "3.0.3", "Demo Order Service", "1.0.0",
                "JSON", "a".repeat(64), "{\"fixture\":\"stage20-final\"}", 1,
                "IMPORTED", USER_ID, now, now));
        metadataRepository.save(new ApiEndpoint(
                0, API_ID, API_DOC_ID, PROJECT_ID, "listProducts", "GET", "/products",
                "List products", "Deterministic Stage 20 final endpoint", "[\"Products\"]",
                "[{\"url\":\"" + demoBaseUrl + "\"}]", "[]", false, now, now));
        metadataRepository.save(new ApiResponseSchema(
                0, API_ID, PROJECT_ID, "200", "Product page returned",
                "application/json", "{\"type\":\"object\"}", now));
    }

    private void deleteRunnerFacts() throws SQLException {
        deleteByProject(runnerDataSource, List.of(
                "step_result", "case_result", "test_batch_run", "test_batch", "test_run",
                "test_task"));
    }

    private void deleteMetadata() throws SQLException {
        deleteByProject(openApiDataSource, List.of(
                "api_example", "api_response_schema", "api_request_schema", "api_parameter",
                "api_endpoint", "api_document"));
    }

    private static void deleteByProject(DataSource source, List<String> tables) throws SQLException {
        try (Connection connection = source.getConnection()) {
            connection.setAutoCommit(false);
            for (String table : tables) {
                try (var statement = connection.prepareStatement(
                        "DELETE FROM " + table + " WHERE project_id = ?")) {
                    statement.setLong(1, PROJECT_ID);
                    statement.executeUpdate();
                }
            }
            connection.commit();
        }
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

    private static Path findPythonProject() {
        return findRepositoryRoot().resolve("python-apiops-agentlab");
    }

    private static Path findRepositoryRoot() {
        Path current = Path.of("").toAbsolutePath();
        while (current != null) {
            if (Files.isRegularFile(current.resolve("python-apiops-agentlab/pyproject.toml"))
                    && Files.isRegularFile(current.resolve("java-apiops-platform/pom.xml"))) {
                return current;
            }
            current = current.getParent();
        }
        throw new IllegalStateException("Agentic APIOps repository root was not found");
    }

    private static String javaExecutable() {
        String executable = System.getProperty("os.name").toLowerCase().contains("win")
                ? "java.exe" : "java";
        return Path.of(System.getProperty("java.home"), "bin", executable).toString();
    }

    private static void stop(Process process) throws InterruptedException {
        if (!process.isAlive()) return;
        process.destroy();
        if (!process.waitFor(5, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            process.waitFor(5, TimeUnit.SECONDS);
        }
    }

    private static String requiredText(JsonNode node, String field) {
        String value = node.path(field).asText();
        assertFalse(value.isBlank(), () -> field + " must be present");
        return value;
    }

    private record DemoRuntime(Process process, String baseUrl) {
    }

}
