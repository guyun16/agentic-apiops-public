package com.apiops.web.tool;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.AuthUserRepository;
import com.apiops.auth.repository.GlobalRbacRepository;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.security.ApiOpsUserDetailsService;
import com.apiops.common.enums.FailureType;
import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiResponseSchema;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.apiops.rag.retrieval.RagQueryRecord;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.ExecutionFactRepository.CaseExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.RunExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.StepExecutionFacts;
import com.apiops.runner.persistence.JdbcExecutionFactRepository;
import com.apiops.runner.state.RunStatus;
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.Audit.AuditEvent;
import com.apiops.tool.gateway.ResourceGuard;
import com.apiops.web.ApiOpsWebApplication;
import com.apiops.web.runner.rabbit.ExecutionRabbitProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Primary;

import javax.sql.DataSource;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
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
import java.util.List;
import java.util.Map;
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

/** Test-owned bridge for five real DeepSeek tasks inside one Java Spring lifecycle. */
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
                "apiops.rabbitmq.execution.exchange=apiops.stage21.representative.exchange",
                "apiops.rabbitmq.execution.routing-key=apiops.stage21.representative.run",
                "apiops.rabbitmq.execution.queue=apiops.stage21.representative.queue",
                "apiops.rabbitmq.execution.dead-letter-exchange=apiops.stage21.representative.dlx",
                "apiops.rabbitmq.execution.dead-letter-routing-key=apiops.stage21.representative.dead",
                "apiops.rabbitmq.execution.dead-letter-queue=apiops.stage21.representative.dlq",
                "apiops.rabbitmq.execution.max-attempts=1",
                "apiops.runner.progress.enabled=true",
                "apiops.runner.progress.ttl=60s",
                "apiops.runner.progress.sse-timeout=60s",
                "apiops.runner.executor.core-pool-size=1",
                "apiops.runner.executor.maximum-pool-size=1",
                "apiops.runner.executor.queue-capacity=4",
                "apiops.runner.executor.thread-name-prefix=stage21-representative-",
                "spring.rabbitmq.host=${APIOPS_RABBITMQ_HOST:127.0.0.1}",
                "spring.rabbitmq.port=${APIOPS_RABBITMQ_PORT:5672}",
                "spring.rabbitmq.username=${APIOPS_RABBITMQ_USERNAME:guest}",
                "spring.rabbitmq.password=${APIOPS_RABBITMQ_PASSWORD:guest}",
                "spring.data.redis.host=${APIOPS_REDIS_HOST:127.0.0.1}",
                 "spring.data.redis.port=${APIOPS_REDIS_PORT:6379}",
                 "management.health.redis.enabled=false",
                 "spring.main.allow-bean-definition-overriding=true",
                 "apiops.auth.jwt.issuer=stage21-representative",
                "apiops.auth.jwt.access-token-ttl=15m",
                "apiops.auth.jwt.secret=dGVzdC1vbmx5LWp3dC1zZWNyZXQtbWF0ZXJpYWwtMjAyNi0wOC0wNw=="
        })
@DirtiesContext
@Import({
        Stage17RagToolGatewayIntegrationTest.Stage17TestConfiguration.class,
        Stage21RealModelRepresentativeCrossProcessE2ETest.RepresentativeConfiguration.class
})
class Stage21RealModelRepresentativeCrossProcessE2ETest {

    private static final long NORMAL_USER_ID = 7L;
    private static final long SAFETY_41_USER_ID = 8L;
    private static final long SAFETY_42_USER_ID = 9L;
    private static final long USER_ID = NORMAL_USER_ID;
    private static final long PROJECT_ID = 41L;
    private static final long REPORT_PROJECT_ID = 42L;
    private static final long FIXTURE_RUN_ID = 701L;
    private static final String NORMAL_USERNAME = "stage21-normal";
    private static final String SAFETY_41_USERNAME = "stage21-safety41";
    private static final String SAFETY_42_USERNAME = "stage21-safety42";
    private static final String USERNAME = NORMAL_USERNAME;
    private static final String NORMAL_PASSWORD_ENV = "STAGE21_NORMAL_PASSWORD";
    private static final String SAFETY_41_PASSWORD_ENV = "STAGE21_SAFETY41_PASSWORD";
    private static final String SAFETY_42_PASSWORD_ENV = "STAGE21_SAFETY42_PASSWORD";
    private static final String API_DOC_ID = "stage21-representative-orders";
    private static final String API_ID = "api-api-1";
    private static final String QUEUE_EXCHANGE = "apiops.stage21.representative.exchange";
    private static final String OUTPUT_RELATIVE_PATH =
            "artifacts/stage21/real-model-representative-smoke";

    @LocalServerPort
    private int serverPort;

    @Autowired
    private OpenApiMetadataRepository metadataRepository;

    @Autowired
    private Stage17RagToolGatewayIntegrationTest.Stage17RagFixture ragFixture;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private Audit audit;

    @Autowired
    private ExecutionRabbitProperties rabbitProperties;

    @Autowired
    private org.springframework.amqp.rabbit.core.RabbitAdmin rabbitAdmin;

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
        deleteRunnerFacts(PROJECT_ID);
        deleteMetadata(PROJECT_ID);
        ragFixture.enableHits();
    }

    @AfterEach
    void cleanInfrastructure() throws SQLException {
        rabbitAdmin.purgeQueue(rabbitProperties.getQueue(), false);
        rabbitAdmin.purgeQueue(rabbitProperties.getDeadLetterQueue(), false);
        redis.delete(redis.keys("apiops:runner:progress:" + PROJECT_ID + ":*"));
        deleteRunnerFacts(PROJECT_ID);
        deleteMetadata(PROJECT_ID);
        rabbitAdmin.deleteQueue(rabbitProperties.getQueue());
        rabbitAdmin.deleteQueue(rabbitProperties.getDeadLetterQueue());
        rabbitAdmin.deleteExchange(QUEUE_EXCHANGE);
        rabbitAdmin.deleteExchange(rabbitProperties.getDeadLetterExchange());
    }

    @Test
    void fiveRepresentativeTasksUseRealModelAndJavaAuthorities() throws Exception {
        String apiKey = System.getenv("DEEPSEEK_API_KEY");
        assertTrue(apiKey != null && !apiKey.isBlank(),
                "DEEPSEEK_API_KEY must be supplied by the invoking environment");

        Path demoLog = Files.createTempFile("stage21-demo-order-", ".log");
        demoLog.toFile().deleteOnExit();
        DemoRuntime demo = startDemoOrderService(demoLog);
        try {
            String demoBaseUrl = awaitDemoOrder(demo);
            seedMetadata(demoBaseUrl);
            JsonNode output = runRepresentativePython();
            JsonNode summary = output.path("representative-smoke");
            assertEquals(5, summary.path("selected").asInt());
            assertEquals(5, summary.path("executed").asInt());
            assertEquals(5, summary.path("evaluated").asInt());

            Set<String> expectedIds = Set.of(
                    "bench_task_golden_testcase_happy",
                    "bench_task_golden_failure_diagnosis",
                    "bench_task_golden_tool_safety",
                    "bench_task_golden_rag_evidence",
                    "bench_task_golden_e2e_apiops");
            Set<String> actualIds = new java.util.HashSet<>();
            for (JsonNode result : summary.path("taskResults")) {
                String taskId = requiredText(result, "benchmarkTaskId");
                assertTrue(actualIds.add(taskId), "representative task IDs must be unique");
                assertEquals("REAL_MODEL", result.path("executionMode").asText());
                assertEquals("SUCCESS", result.path("status").asText(),
                        () -> "representative task failed: " + result);
                assertTrue(result.path("modelCallCount").asInt() >= 1);
                assertTrue(result.path("modelCallIds").size() >= 1);
                assertFalse(result.path("evaluationId").asText().isBlank());
                String expectedProfile = "bench_task_golden_tool_safety".equals(taskId)
                        ? "SAFETY_41_ISOLATED" : "NORMAL";
                long expectedPrincipalId = "SAFETY_41_ISOLATED".equals(expectedProfile)
                        ? SAFETY_41_USER_ID : NORMAL_USER_ID;
                assertEquals(expectedProfile, result.path("authProfile").asText());
                assertEquals(expectedPrincipalId, result.path("principalId").asLong());
            }
            assertEquals(expectedIds, actualIds);

            JsonNode generation = findTask(summary, "bench_task_golden_testcase_happy");
            assertEquals("EXECUTED", generation.path("javaExecutionStatus").asText());
            assertTrue(generation.path("runId").isNull());
            assertTrue(generation.path("reportId").isNull());

            JsonNode diagnosis = findTask(summary, "bench_task_golden_failure_diagnosis");
            assertEquals(FIXTURE_RUN_ID, diagnosis.path("runId").asLong());
            assertEquals("report:" + FIXTURE_RUN_ID, diagnosis.path("reportId").asText());

            JsonNode tool = findTask(summary, "bench_task_golden_tool_safety");
            String toolCallId = "N/A";
            String toolStatus = "NO_TOOL_INTENT";
            if (tool.path("toolCallIds").isArray() && tool.path("toolCallIds").size() > 0) {
                String observedToolCallId = requiredText(tool.path("toolCallIds").get(0));
                toolCallId = observedToolCallId;
                AuditEvent toolEvent = audit.events().stream()
                        .filter(event -> observedToolCallId.equals(event.toolCallId()))
                        .findFirst()
                        .orElseThrow(() -> new AssertionError("Java Tool Gateway audit is missing"));
                toolStatus = toolEvent.status().name();
            }

            JsonNode rag = findTask(summary, "bench_task_golden_rag_evidence");
            String ragQueryId = "N/A";
            if (rag.path("ragQueryIds").isArray() && rag.path("ragQueryIds").size() > 0) {
                String observedRagQueryId = requiredText(rag.path("ragQueryIds").get(0));
                ragQueryId = observedRagQueryId;
                assertTrue(ragFixture.recordsSnapshot().stream()
                        .anyMatch(record -> observedRagQueryId.equals(record.ragQueryId())
                                && record.projectId() == PROJECT_ID
                                && record.retrievedCount() > 0));
            }

            JsonNode e2e = findTask(summary, "bench_task_golden_e2e_apiops");
            assertTrue(e2e.path("modelCallCount").asInt() >= 2);
            long runId = e2e.path("runId").asLong();
            assertTrue(runId > 0);
            assertNotEquals(FIXTURE_RUN_ID, runId);
            assertEquals("report:" + runId, e2e.path("reportId").asText());
            assertTrue(e2e.path("modelCallIds").size() >= 2);

            System.out.printf(
                    "STAGE21_REPRESENTATIVE_CORRELATION selected=5 executed=5 "
                            + "generationModelCalls=%d diagnosisModelCalls=%d "
                            + "toolCallId=%s toolStatus=%s ragQueryId=%s e2eRunId=%d e2eReportId=%s%n",
                    generation.path("modelCallCount").asInt(),
                    diagnosis.path("modelCallCount").asInt(),
                    toolCallId,
                    toolStatus,
                    ragQueryId,
                    runId,
                    e2e.path("reportId").asText());
        } finally {
            stop(demo.process());
        }
    }

    private JsonNode runRepresentativePython() throws Exception {
        Path pythonProject = findPythonProject();
        Path outputRoot = findRepositoryRoot().resolve(OUTPUT_RELATIVE_PATH);
        String normalPassword = requiredEnvironment(NORMAL_PASSWORD_ENV);
        String safety41Password = requiredEnvironment(SAFETY_41_PASSWORD_ENV);
        String safety42Password = requiredEnvironment(SAFETY_42_PASSWORD_ENV);
        ProcessBuilder builder = new ProcessBuilder(
                "uv", "run", "python", "scripts/stage21_real_model_baseline.py",
                "representative-smoke", "--output-root", outputRoot.toString());
        builder.directory(pythonProject.toFile());
        builder.environment().put("JAVA_APIOPS_BASE_URL", "http://127.0.0.1:" + serverPort);
        builder.environment().remove("JAVA_APIOPS_TOKEN");
        builder.environment().put("STAGE21_NORMAL_USERNAME", NORMAL_USERNAME);
        builder.environment().put(NORMAL_PASSWORD_ENV, normalPassword);
        builder.environment().put("STAGE21_SAFETY41_USERNAME", SAFETY_41_USERNAME);
        builder.environment().put(SAFETY_41_PASSWORD_ENV, safety41Password);
        builder.environment().put("STAGE21_SAFETY42_USERNAME", SAFETY_42_USERNAME);
        builder.environment().put(SAFETY_42_PASSWORD_ENV, safety42Password);
        builder.environment().put("PYTHONUTF8", "1");
        Process process = builder.start();
        CompletableFuture<String> stdout = readAsync(process.getInputStream());
        CompletableFuture<String> stderr = readAsync(process.getErrorStream());
        if (!process.waitFor(900, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            fail("Stage 21 representative Python subprocess exceeded its deadline");
        }
        String output = stdout.join().trim();
        String errors = stderr.join().trim();
        assertFalse(output.contains(normalPassword), "Python stdout must not expose credentials");
        assertFalse(errors.contains(normalPassword), "Python stderr must not expose credentials");
        assertFalse(output.contains(safety41Password), "Python stdout must not expose credentials");
        assertFalse(errors.contains(safety41Password), "Python stderr must not expose credentials");
        assertFalse(output.contains(safety42Password), "Python stdout must not expose credentials");
        assertFalse(errors.contains(safety42Password), "Python stderr must not expose credentials");
        assertEquals(0, process.exitValue(), () ->
                "Stage 21 representative Python run failed: " + errors + "\n" + output);
        return objectMapper.readTree(output);
    }

    @Test
    void threeAuthProfilesLoginThroughJavaPublicBoundary() throws Exception {
        assertProfileLogin(NORMAL_USERNAME, NORMAL_PASSWORD_ENV, NORMAL_USER_ID);
        assertProfileLogin(SAFETY_41_USERNAME, SAFETY_41_PASSWORD_ENV, SAFETY_41_USER_ID);
        assertProfileLogin(SAFETY_42_USERNAME, SAFETY_42_PASSWORD_ENV, SAFETY_42_USER_ID);
    }

    private void assertProfileLogin(String username, String passwordEnv, long expectedUserId)
            throws Exception {
        String password = requiredEnvironment(passwordEnv);
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
        HttpRequest request = HttpRequest.newBuilder(
                        URI.create("http://127.0.0.1:" + serverPort + "/api/v1/auth/login"))
                .header("Content-Type", "application/json")
                .timeout(Duration.ofSeconds(5))
                .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(
                        Map.of("username", username, "password", password))))
                .build();
        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode(), "Java login must succeed for configured profile");
        JsonNode login = objectMapper.readTree(response.body());
        assertTrue(login.path("success").asBoolean());
        assertEquals(expectedUserId, login.path("data").path("userId").asLong());
        assertEquals(username, login.path("data").path("username").asText());
        String token = requiredText(login.path("data").path("accessToken"));

        HttpRequest meRequest = HttpRequest.newBuilder(
                        URI.create("http://127.0.0.1:" + serverPort + "/api/v1/auth/me"))
                .header("Authorization", "Bearer " + token)
                .timeout(Duration.ofSeconds(5))
                .GET()
                .build();
        HttpResponse<String> meResponse = client.send(
                meRequest, HttpResponse.BodyHandlers.ofString());
        assertEquals(200, meResponse.statusCode());
        JsonNode me = objectMapper.readTree(meResponse.body());
        assertEquals(expectedUserId, me.path("data").path("userId").asLong());
        assertEquals(username, me.path("data").path("username").asText());
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        assertTrue(value != null && !value.isBlank(), name + " must be supplied by the environment");
        return value;
    }

    private void seedMetadata(String demoBaseUrl) {
        Instant now = Instant.now();
        metadataRepository.save(new ApiDocument(
                0, API_DOC_ID, PROJECT_ID, "stage21-representative-orders",
                "stage21-representative-orders.json", "3.0.3", "Orders API", "1.0.0",
                "JSON", "a".repeat(64), "{\"fixture\":\"stage21-representative\"}", 1,
                "IMPORTED", USER_ID, now, now));
        metadataRepository.save(new ApiEndpoint(
                0, API_ID, API_DOC_ID, PROJECT_ID, "listProducts", "GET", "/products",
                "List products", "Stage 21 representative endpoint", "[\"Products\"]",
                "[{\"url\":\"" + demoBaseUrl + "\"}]", "[]", false, now, now));
        metadataRepository.save(new ApiResponseSchema(
                0, API_ID, PROJECT_ID, "200", "Product page returned",
                "application/json", "{\"type\":\"object\"}", now));
    }

    private void deleteRunnerFacts(long projectId) throws SQLException {
        deleteByProject(runnerDataSource, projectId, List.of(
                "step_result", "case_result", "test_batch_run", "test_batch", "test_run",
                "test_task"));
    }

    private void deleteMetadata(long projectId) throws SQLException {
        deleteByProject(openApiDataSource, projectId, List.of(
                "api_example", "api_response_schema", "api_request_schema", "api_parameter",
                "api_endpoint", "api_document"));
    }

    private static void deleteByProject(DataSource source, long projectId, List<String> tables)
            throws SQLException {
        try (Connection connection = source.getConnection()) {
            connection.setAutoCommit(false);
            for (String table : tables) {
                try (var statement = connection.prepareStatement(
                        "DELETE FROM " + table + " WHERE project_id = ?")) {
                    statement.setLong(1, projectId);
                    statement.executeUpdate();
                }
            }
            connection.commit();
        }
    }

    private DemoRuntime startDemoOrderService(Path log) throws IOException {
        Path jar = findRepositoryRoot().resolve(
                "java-apiops-platform/apiops-demo-order-service/target/"
                        + "apiops-demo-order-service-0.1.0-SNAPSHOT.jar");
        assertTrue(Files.isRegularFile(jar),
                "Package apiops-demo-order-service before the representative E2E test");
        int port;
        try (ServerSocket socket = new ServerSocket(0)) {
            port = socket.getLocalPort();
        }
        ProcessBuilder builder = new ProcessBuilder(
                javaExecutable(), "-jar", jar.toString(), "--spring.profiles.active=local",
                "--server.port=" + port);
        builder.environment().put("STAGE20_DEMO_ORDER_PORT", Integer.toString(port));
        builder.redirectErrorStream(true);
        builder.redirectOutput(log.toFile());
        return new DemoRuntime(builder.start(), "http://127.0.0.1:" + port);
    }

    private static String awaitDemoOrder(DemoRuntime runtime) throws Exception {
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build();
        Instant deadline = Instant.now().plusSeconds(30);
        while (Instant.now().isBefore(deadline)) {
            if (!runtime.process().isAlive()) {
                throw new AssertionError("demo-order-service exited before becoming ready");
            }
            try {
                HttpResponse<Void> response = client.send(
                        HttpRequest.newBuilder(URI.create(runtime.baseUrl() + "/products"))
                                .timeout(Duration.ofSeconds(2))
                                .GET()
                                .build(),
                        HttpResponse.BodyHandlers.discarding());
                if (response.statusCode() == 200) return runtime.baseUrl();
            } catch (IOException ignored) {
                // The child process is still starting.
            }
            Thread.sleep(250);
        }
        throw new AssertionError("demo-order-service did not become ready within 30 seconds");
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

    private static JsonNode findTask(JsonNode summary, String taskId) {
        for (JsonNode result : summary.path("taskResults")) {
            if (taskId.equals(result.path("benchmarkTaskId").asText())) return result;
        }
        throw new AssertionError("task result is missing: " + taskId);
    }

    private static String requiredText(JsonNode node) {
        String value = node == null ? "" : node.asText();
        assertFalse(value.isBlank(), "identity must be present");
        return value;
    }

    private static String requiredText(JsonNode object, String field) {
        return requiredText(object.path(field));
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

    private record DemoRuntime(Process process, String baseUrl) {
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class RepresentativeConfiguration {

        @Bean(name = "stage17AuthUserRepository")
        @Primary
        AuthUserRepository representativeAuthUserRepository(PasswordEncoder passwordEncoder) {
            List<ApiOpsPrincipal> principals = List.of(
                    representativePrincipal(
                            NORMAL_USER_ID, NORMAL_USERNAME, NORMAL_PASSWORD_ENV, passwordEncoder),
                    representativePrincipal(
                            SAFETY_41_USER_ID,
                            SAFETY_41_USERNAME,
                            SAFETY_41_PASSWORD_ENV,
                            passwordEncoder),
                    representativePrincipal(
                            SAFETY_42_USER_ID,
                            SAFETY_42_USERNAME,
                            SAFETY_42_PASSWORD_ENV,
                            passwordEncoder));
            return username -> principals.stream()
                    .filter(principal -> principal.getUsername().equals(username))
                    .findFirst();
        }

        @Bean(name = "stage17UserDetailsService")
        @Primary
        UserDetailsService representativeUserDetailsService(AuthUserRepository repository) {
            return new ApiOpsUserDetailsService(repository);
        }

        @Bean(name = "stage17GlobalRbacRepository")
        @Primary
        GlobalRbacRepository representativeGlobalRbacRepository() {
            return new GlobalRbacRepository() {
                @Override
                public Set<String> findRoleCodesByUserId(long userId) {
                    return Set.of();
                }

                @Override
                public Set<String> findPermissionCodesByUserId(long userId) {
                    return userId == NORMAL_USER_ID
                            || userId == SAFETY_41_USER_ID
                            || userId == SAFETY_42_USER_ID
                            ? Set.of("TOOL_READ")
                            : Set.of();
                }
            };
        }

        @Bean(name = "stage17ProjectMembershipRepository")
        @Primary
        ProjectMembershipRepository representativeProjectMembershipRepository() {
            return (userId, projectId) -> {
                if (userId == NORMAL_USER_ID && projectId == PROJECT_ID) {
                    return Optional.of(ProjectRole.EDITOR);
                }
                if (userId == NORMAL_USER_ID && projectId == REPORT_PROJECT_ID) {
                    return Optional.of(ProjectRole.VIEWER);
                }
                if (userId == NORMAL_USER_ID && projectId == 1001L) {
                    return Optional.of(ProjectRole.EDITOR);
                }
                if (userId == SAFETY_41_USER_ID && projectId == PROJECT_ID) {
                    return Optional.of(ProjectRole.VIEWER);
                }
                if (userId == SAFETY_42_USER_ID && projectId == REPORT_PROJECT_ID) {
                    return Optional.of(ProjectRole.VIEWER);
                }
                return Optional.empty();
            };
        }

        private static ApiOpsPrincipal representativePrincipal(
                long userId,
                String username,
                String passwordEnv,
                PasswordEncoder passwordEncoder) {
            return new ApiOpsPrincipal(
                    userId,
                    username,
                    passwordEncoder.encode(requiredEnvironment(passwordEnv)),
                    true,
                    List.of());
        }

        @Bean
        @Primary
        ResourceGuard representativeResourceGuard() {
            return (context, definition, intent) -> {
                if (context.projectId() == PROJECT_ID
                        && "rag.search".equals(intent.toolName())) {
                    return ResourceGuard.Decision.reject(
                            "controlled project-scope policy denies this cross-project intent");
                }
                return ResourceGuard.Decision.allow();
            };
        }

        @Bean
        @Primary
        ExecutionFactRepository representativeExecutionFacts(
                @Qualifier("runnerDataSource") DataSource dataSource,
                ObjectMapper objectMapper) {
            JdbcExecutionFactRepository delegate =
                    new JdbcExecutionFactRepository(dataSource, objectMapper);
            return (ExecutionFactRepository) Proxy.newProxyInstance(
                    ExecutionFactRepository.class.getClassLoader(),
                    new Class<?>[]{ExecutionFactRepository.class},
                    (proxy, method, args) -> {
                        if ("findRun".equals(method.getName())
                                && args != null && args.length == 2
                                && args[0] instanceof Long projectId
                                && args[1] instanceof Long runId
                                && runId == FIXTURE_RUN_ID
                                && (projectId == PROJECT_ID || projectId == REPORT_PROJECT_ID)) {
                            return Optional.of(completedFacts(projectId));
                        }
                        try {
                            return method.invoke(delegate, args);
                        } catch (InvocationTargetException exception) {
                            throw exception.getCause();
                        }
                    });
        }

        private static RunExecutionFacts completedFacts(long projectId) {
            Instant started = Instant.parse("2026-08-23T11:59:58Z");
            Instant finished = Instant.parse("2026-08-23T12:00:00Z");
            StepExecutionFacts step = new StepExecutionFacts(
                    projectId, FIXTURE_RUN_ID, 901L, 1001L, "step-failed",
                    RunStatus.ASSERTION_FAILED, FailureType.ASSERTION_MISMATCH,
                    "[{\"type\":\"STATUS_CODE\",\"passed\":false,"
                            + "\"expected\":200,\"actual\":500,"
                            + "\"message\":\"status mismatch\"}]",
                    500, 12L, finished);
            CaseExecutionFacts testCase = new CaseExecutionFacts(
                    projectId, FIXTURE_RUN_ID, 901L, "case-failed",
                    RunStatus.ASSERTION_FAILED, FailureType.ASSERTION_MISMATCH,
                    started, finished, List.of(step));
            return new RunExecutionFacts(
                    projectId, 301L, FIXTURE_RUN_ID, "case-failed", "orders-api",
                    "Stage 21 representative controlled report",
                    RunStatus.ASSERTION_FAILED, FailureType.ASSERTION_MISMATCH,
                    started, finished, List.of(testCase));
        }
    }
}
