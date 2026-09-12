package com.apiops.web.tool;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.AuthUserRepository;
import com.apiops.auth.repository.GlobalRbacRepository;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.security.ApiOpsUserDetailsService;
import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.apiops.rag.retrieval.RagQueryRecord;
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.AuditStatus;
import com.apiops.tool.gateway.ResourceGuard;
import com.apiops.web.ApiOpsWebApplication;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.annotation.DirtiesContext;

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
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

/** Test-owned cross-process bridge for the exact four Stage 21 real-model E2Es. */
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
                "apiops.rabbitmq.execution.exchange=apiops.stage21.four-e2e.exchange",
                "apiops.rabbitmq.execution.routing-key=apiops.stage21.four-e2e.run",
                "apiops.rabbitmq.execution.queue=apiops.stage21.four-e2e.queue",
                "apiops.rabbitmq.execution.dead-letter-exchange=apiops.stage21.four-e2e.dlx",
                "apiops.rabbitmq.execution.dead-letter-routing-key=apiops.stage21.four-e2e.dead",
                "apiops.rabbitmq.execution.dead-letter-queue=apiops.stage21.four-e2e.dlq",
                "apiops.rabbitmq.execution.max-attempts=1",
                "apiops.runner.progress.enabled=true",
                "apiops.runner.progress.ttl=60s",
                "apiops.runner.progress.sse-timeout=60s",
                "apiops.runner.executor.core-pool-size=1",
                "apiops.runner.executor.maximum-pool-size=1",
                "apiops.runner.executor.queue-capacity=4",
                "apiops.runner.executor.thread-name-prefix=stage21-four-e2e-",
                "spring.rabbitmq.host=${APIOPS_RABBITMQ_HOST:127.0.0.1}",
                "spring.rabbitmq.port=${APIOPS_RABBITMQ_PORT:5672}",
                "spring.rabbitmq.username=${APIOPS_RABBITMQ_USERNAME:guest}",
                "spring.rabbitmq.password=${APIOPS_RABBITMQ_PASSWORD:guest}",
                "spring.data.redis.host=${APIOPS_REDIS_HOST:127.0.0.1}",
                "spring.data.redis.port=${APIOPS_REDIS_PORT:6379}",
                "management.health.redis.enabled=false",
                "spring.main.allow-bean-definition-overriding=true",
                "apiops.auth.jwt.issuer=stage21-four-e2e",
                "apiops.auth.jwt.access-token-ttl=15m",
                "apiops.auth.jwt.secret=dGVzdC1vbmx5LWp3dC1zZWNyZXQtbWF0ZXJpYWwtMjAyNi0wOC0wNw=="
        })
@DirtiesContext
@Import({
        Stage17RagToolGatewayIntegrationTest.Stage17TestConfiguration.class,
        Stage21RealModelFourE2ECrossProcessE2ETest.FourE2EConfiguration.class
})
class Stage21RealModelFourE2ECrossProcessE2ETest {

    private static final long NORMAL_USER_ID = 45L;
    private static final long SAFETY_41_USER_ID = 46L;
    private static final long SAFETY_42_USER_ID = 47L;
    private static final long PROJECT_41 = 41L;
    private static final long PROJECT_1001 = 1001L;
    private static final String NORMAL_USERNAME = "stage21-normal";
    private static final String SAFETY_41_USERNAME = "stage21-safety41";
    private static final String SAFETY_42_USERNAME = "stage21-safety42";
    private static final String NORMAL_PASSWORD_ENV = "STAGE21_NORMAL_PASSWORD";
    private static final String SAFETY_41_PASSWORD_ENV = "STAGE21_SAFETY41_PASSWORD";
    private static final String SAFETY_42_PASSWORD_ENV = "STAGE21_SAFETY42_PASSWORD";
    private static final String OUTPUT_RELATIVE_PATH = "artifacts/stage21/real-model-e2e";

    @LocalServerPort
    private int serverPort;

    @org.springframework.beans.factory.annotation.Autowired
    private FourE2EMetadataRepository metadataRepository;

    @org.springframework.beans.factory.annotation.Autowired
    private Stage17RagToolGatewayIntegrationTest.Stage17RagFixture ragFixture;

    @org.springframework.beans.factory.annotation.Autowired
    private Audit audit;

    @org.springframework.beans.factory.annotation.Autowired
    private ObjectMapper objectMapper;

    @org.springframework.beans.factory.annotation.Autowired
    private com.apiops.web.runner.rabbit.ExecutionRabbitProperties rabbitProperties;

    @org.springframework.beans.factory.annotation.Autowired
    private org.springframework.amqp.rabbit.core.RabbitAdmin injectedRabbitAdmin;

    @org.springframework.beans.factory.annotation.Autowired
    private StringRedisTemplate redis;

    @BeforeEach
    void prepareAuthorityState() {
        injectedRabbitAdmin.purgeQueue(rabbitProperties.getQueue(), false);
        injectedRabbitAdmin.purgeQueue(rabbitProperties.getDeadLetterQueue(), false);
        ragFixture.enableHits();
    }

    @AfterEach
    void cleanAuthorityState() {
        injectedRabbitAdmin.purgeQueue(rabbitProperties.getQueue(), false);
        injectedRabbitAdmin.purgeQueue(rabbitProperties.getDeadLetterQueue(), false);
        redis.delete(redis.keys("apiops:runner:progress:*"));
    }

    @Test
    void fourRealModelTasksUseFreshStage16CandidatesAndJavaAuthorities() throws Exception {
        requiredEnvironment("DEEPSEEK_API_KEY");
        assertProfileLogin(NORMAL_USERNAME, NORMAL_PASSWORD_ENV, NORMAL_USER_ID);
        assertProfileLogin(SAFETY_41_USERNAME, SAFETY_41_PASSWORD_ENV, SAFETY_41_USER_ID);
        assertProfileLogin(SAFETY_42_USERNAME, SAFETY_42_PASSWORD_ENV, SAFETY_42_USER_ID);

        List<String> blockers = new ArrayList<>();
        JsonNode golden = null;
        JsonNode remaining = null;
        DemoRuntime demo = null;
        try {
            Path demoLog = Files.createTempFile("stage21-four-e2e-demo-", ".log");
            demoLog.toFile().deleteOnExit();
            demo = startDemoOrderService(demoLog);
            String demoBaseUrl = awaitDemoOrder(demo);
            metadataRepository.seed(demoBaseUrl);

            try {
                golden = runPython("golden");
                validateSummary(golden, Set.of("bench_task_golden_e2e_apiops"));
                validateCommonTask(golden, "bench_task_golden_e2e_apiops");
                validateGoldenAuthority(golden);
                System.out.println("E2E_PHASE_2_GOLDEN_RUNTIME_PASS");
            } catch (Throwable exception) {
                blockers.add("golden: " + boundedMessage(exception));
                System.out.println("E2E_PHASE_2_GOLDEN_RUNTIME_BLOCKED");
            }

            try {
                remaining = runPython("remaining");
                validateSummary(remaining, Set.of(
                        "bench_task_e2e_generation_business_failure",
                        "bench_task_e2e_generation_runner_success",
                        "bench_task_formal_e2e_generation_diagnosis_guarded"));
                validateCommonTask(remaining, "bench_task_e2e_generation_business_failure");
                validateCommonTask(remaining, "bench_task_e2e_generation_runner_success");
                validateCommonTask(remaining,
                        "bench_task_formal_e2e_generation_diagnosis_guarded");
                validateFormalGuardAuthority(remaining);
                System.out.println("E2E_PHASE_3_REMAINING_PASS");
            } catch (Throwable exception) {
                blockers.add("remaining: " + boundedMessage(exception));
                System.out.println("E2E_PHASE_3_REMAINING_BLOCKED");
            }
        } catch (Throwable exception) {
            blockers.add("shared E2E setup: " + boundedMessage(exception));
            if (golden == null) System.out.println("E2E_PHASE_2_GOLDEN_RUNTIME_BLOCKED");
            if (remaining == null) System.out.println("E2E_PHASE_3_REMAINING_BLOCKED");
        } finally {
            if (demo != null) stop(demo.process());
        }

        Path artifact = writeRuntimeArtifact(golden, remaining, blockers);
        if (!blockers.isEmpty()) {
            fail("Stage 21 real-model E2E phase blocked; artifact=" + artifact
                    + " blockers=" + String.join(" | ", blockers));
        }
        System.out.printf(
                "STAGE21_REAL_MODEL_FOUR_E2E_RUNTIME_PASS artifact=%s goldenRunId=%d remainingTasks=%d%n",
                artifact,
                task(golden, "bench_task_golden_e2e_apiops").path("runId").asLong(),
                remaining.path("executed").asInt());
    }

    private void validateSummary(JsonNode summary, Set<String> expectedIds) {
        assertEquals(expectedIds.size(), summary.path("selected").asInt());
        assertEquals(expectedIds.size(), summary.path("executed").asInt());
        assertEquals(0, summary.path("fixtureFallbackCount").asInt());
        assertEquals(0, summary.path("expectedSideLeakage").asInt());
        assertEquals(0, summary.path("pythonBypassCount").asInt());
        assertTrue(summary.path("newGenerationPerTask").asBoolean());
        Set<String> actual = new java.util.HashSet<>();
        for (JsonNode row : summary.path("taskResults")) {
            assertTrue(actual.add(row.path("benchmarkTaskId").asText()));
        }
        assertEquals(expectedIds, actual);
    }

    private void validateCommonTask(JsonNode summary, String taskId) {
        JsonNode row = task(summary, taskId);
        assertEquals("NORMAL", row.path("authProfile").asText());
        assertEquals("REAL_MODEL_STAGE16", row.path("candidateSource").asText());
        assertTrue(row.path("candidateValid").asBoolean());
        assertFalse(row.path("fixtureFallbackUsed").asBoolean(true));
        assertTrue(row.path("candidateHash").asText().matches("[0-9a-f]{64}"));
        assertTrue(row.path("modelCallCount").asInt() >= 1);
        assertTrue(row.path("modelCallIds").size() >= 1);
        assertEquals("EXECUTED", row.path("javaExecutionStatus").asText());
        assertTrue(row.path("runId").asLong() > 0);
        assertFalse(row.path("reportId").asText().isBlank());
        assertFalse(row.path("reportId").asText().startsWith("fixture:"));
        assertEquals("SUCCESS", row.path("terminalStatus").asText());
        assertTrue(row.path("runtimeScenarioMatch").asBoolean());
        assertNotNull(row.get("evaluationResult"));
        assertNotNull(row.get("taskSuccess"));
    }

    private void validateGoldenAuthority(JsonNode summary) {
        JsonNode row = task(summary, "bench_task_golden_e2e_apiops");
        assertTrue(row.path("toolCallIds").size() >= 1);
        assertTrue(row.path("ragQueryIds").size() >= 1);
        String toolCallId = row.path("toolCallIds").get(0).asText();
        Audit.AuditEvent event = audit.events().stream()
                .filter(candidate -> toolCallId.equals(candidate.toolCallId()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("Golden ToolAuth audit is missing"));
        assertEquals(AuditStatus.SUCCESS, event.status());
        String ragQueryId = row.path("ragQueryIds").get(0).asText();
        assertTrue(ragFixture.recordsSnapshot().stream()
                .anyMatch(record -> ragQueryId.equals(record.ragQueryId())
                        && record.projectId() == PROJECT_41
                        && record.retrievedCount() > 0));
    }

    private void validateFormalGuardAuthority(JsonNode summary) {
        JsonNode row = task(summary, "bench_task_formal_e2e_generation_diagnosis_guarded");
        assertTrue(row.path("toolCallIds").size() >= 1);
        assertEquals(0, row.path("ragQueryIds").size());
        String toolCallId = row.path("toolCallIds").get(0).asText();
        Audit.AuditEvent event = audit.events().stream()
                .filter(candidate -> toolCallId.equals(candidate.toolCallId()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("formal ToolAuth audit is missing"));
        assertEquals(AuditStatus.DENIED, event.status());
    }

    private JsonNode runPython(String phase) throws Exception {
        Path root = findRepositoryRoot();
        Path pythonProject = root.resolve("python-apiops-agentlab");
        Path outputRoot = root.resolve(OUTPUT_RELATIVE_PATH);
        ProcessBuilder builder = new ProcessBuilder(
                "uv", "run", "python", "scripts/stage21_real_model_e2e.py",
                phase, "--output-root", outputRoot.toString());
        builder.directory(pythonProject.toFile());
        builder.environment().put("JAVA_APIOPS_BASE_URL", "http://127.0.0.1:" + serverPort);
        builder.environment().remove("JAVA_APIOPS_TOKEN");
        builder.environment().put("STAGE21_NORMAL_USERNAME", NORMAL_USERNAME);
        builder.environment().put("STAGE21_NORMAL_PASSWORD",
                requiredEnvironment(NORMAL_PASSWORD_ENV));
        builder.environment().put("STAGE21_SAFETY41_USERNAME", SAFETY_41_USERNAME);
        builder.environment().put("STAGE21_SAFETY41_PASSWORD",
                requiredEnvironment(SAFETY_41_PASSWORD_ENV));
        builder.environment().put("STAGE21_SAFETY42_USERNAME", SAFETY_42_USERNAME);
        builder.environment().put("STAGE21_SAFETY42_PASSWORD",
                requiredEnvironment(SAFETY_42_PASSWORD_ENV));
        builder.environment().put("DEEPSEEK_API_KEY", requiredEnvironment("DEEPSEEK_API_KEY"));
        builder.environment().put("PYTHONUTF8", "1");
        Process process = builder.start();
        CompletableFuture<String> stdout = readAsync(process.getInputStream());
        CompletableFuture<String> stderr = readAsync(process.getErrorStream());
        if (!process.waitFor(900, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            fail("Stage 21 " + phase + " Python subprocess exceeded its deadline");
        }
        String output = stdout.join().trim();
        String errors = stderr.join().trim();
        assertFalse(output.contains(requiredEnvironment(NORMAL_PASSWORD_ENV)));
        assertFalse(errors.contains(requiredEnvironment(NORMAL_PASSWORD_ENV)));
        assertFalse(output.contains(requiredEnvironment(SAFETY_41_PASSWORD_ENV)));
        assertFalse(errors.contains(requiredEnvironment(SAFETY_41_PASSWORD_ENV)));
        assertFalse(output.contains(requiredEnvironment(SAFETY_42_PASSWORD_ENV)));
        assertFalse(errors.contains(requiredEnvironment(SAFETY_42_PASSWORD_ENV)));
        assertEquals(0, process.exitValue(), () ->
                "Stage 21 " + phase + " Python run failed: " + bounded(errors));
        return objectMapper.readTree(output);
    }

    private void assertProfileLogin(String username, String passwordEnv, long userId)
            throws Exception {
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
        String body = objectMapper.writeValueAsString(Map.of(
                "username", username, "password", requiredEnvironment(passwordEnv)));
        HttpResponse<String> response = client.send(
                HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + serverPort
                                + "/api/v1/auth/login"))
                        .header("Content-Type", "application/json")
                        .timeout(Duration.ofSeconds(5))
                        .POST(HttpRequest.BodyPublishers.ofString(body))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode(), "configured Stage21 profile login must work");
        JsonNode login = objectMapper.readTree(response.body());
        assertTrue(login.path("success").asBoolean());
        assertEquals(userId, login.path("data").path("userId").asLong());
        assertEquals(username, login.path("data").path("username").asText());
    }

    private Path writeRuntimeArtifact(
            JsonNode golden,
            JsonNode remaining,
            List<String> blockers) throws IOException {
        Path path = findRepositoryRoot().resolve(OUTPUT_RELATIVE_PATH)
                .resolve("4-e2e-runtime-readiness.json");
        Files.createDirectories(path.getParent());
        var artifact = objectMapper.createObjectNode();
        artifact.put("schemaVersion", "stage21-real-model-e2e-runtime-v1");
        artifact.put("fullDatasetRun", false);
        artifact.put("fixtureFallbackCount", 0);
        artifact.put("expectedSideLeakage", 0);
        artifact.put("pythonBypassCount", 0);
        artifact.put("productionSpecialTuning", 0);
        artifact.set("phase2Golden", golden == null ? objectMapper.nullNode() : golden);
        artifact.set("phase3Remaining", remaining == null ? objectMapper.nullNode() : remaining);
        artifact.put("phaseBlockerCount", blockers.size());
        artifact.set("blockers", objectMapper.valueToTree(blockers));
        Files.writeString(path, objectMapper.writerWithDefaultPrettyPrinter()
                .writeValueAsString(artifact), StandardCharsets.UTF_8);
        return path;
    }

    private static JsonNode task(JsonNode summary, String taskId) {
        for (JsonNode result : summary.path("taskResults")) {
            if (taskId.equals(result.path("benchmarkTaskId").asText())) return result;
        }
        throw new AssertionError("task result is missing: " + taskId);
    }

    private static String boundedMessage(Throwable exception) {
        return bounded(exception.getMessage() == null
                ? exception.getClass().getSimpleName() : exception.getMessage());
    }

    private static String bounded(String value) {
        return value == null ? "" : value.replace('\n', ' ').replace('\r', ' ').substring(
                0, Math.min(value.length(), 600));
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        assertTrue(value != null && !value.isBlank(), name + " must be supplied");
        return value;
    }

    private static DemoRuntime startDemoOrderService(Path log) throws IOException {
        Path root = findRepositoryRoot();
        Path jar = root.resolve("java-apiops-platform/apiops-demo-order-service/target/"
                + "apiops-demo-order-service-0.1.0-SNAPSHOT.jar");
        assertTrue(Files.isRegularFile(jar), "package demo order service before this test");
        int port;
        try (ServerSocket socket = new ServerSocket(0)) {
            port = socket.getLocalPort();
        }
        ProcessBuilder builder = new ProcessBuilder(
                javaExecutable(), "-jar", jar.toString(), "--spring.profiles.active=local",
                "--server.port=" + port);
        builder.environment().put("APIOPS_ORDER_DB_URL",
                System.getenv().getOrDefault("APIOPS_ORDER_DB_URL",
                        "jdbc:mysql://127.0.0.1:3306/apiops_demo_order"));
        builder.environment().put("APIOPS_ORDER_DB_USERNAME",
                System.getenv().getOrDefault("APIOPS_ORDER_DB_USERNAME", "root"));
        builder.environment().put("APIOPS_ORDER_DB_PASSWORD",
                requiredEnvironment("APIOPS_ORDER_DB_PASSWORD"));
        builder.redirectErrorStream(true);
        builder.redirectOutput(log.toFile());
        return new DemoRuntime(builder.start(), "http://127.0.0.1:" + port);
    }

    private static String awaitDemoOrder(DemoRuntime runtime) throws Exception {
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build();
        Instant deadline = Instant.now().plusSeconds(30);
        while (Instant.now().isBefore(deadline)) {
            if (!runtime.process().isAlive()) {
                throw new AssertionError("demo order service exited before readiness");
            }
            try {
                HttpResponse<Void> response = client.send(
                        HttpRequest.newBuilder(URI.create(runtime.baseUrl() + "/products"))
                                .timeout(Duration.ofSeconds(2)).GET().build(),
                        HttpResponse.BodyHandlers.discarding());
                if (response.statusCode() == 200) return runtime.baseUrl();
            } catch (IOException ignored) {
                // The target service is still starting.
            }
            Thread.sleep(250);
        }
        throw new AssertionError("demo order service did not become ready within 30 seconds");
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

    private static Path findRepositoryRoot() {
        Path current = Path.of("").toAbsolutePath();
        while (current != null) {
            if (Files.isRegularFile(current.resolve("python-apiops-agentlab/pyproject.toml"))
                    && Files.isRegularFile(current.resolve("java-apiops-platform/pom.xml"))) {
                return current;
            }
            current = current.getParent();
        }
        throw new IllegalStateException("repository root was not found");
    }

    private static String javaExecutable() {
        String executable = System.getProperty("os.name").toLowerCase(Locale.ROOT).contains("win")
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
    static class FourE2EConfiguration {

        @Bean(name = "stage17AuthUserRepository")
        @Primary
        AuthUserRepository authUserRepository(PasswordEncoder encoder) {
            List<ApiOpsPrincipal> principals = List.of(
                    principal(NORMAL_USER_ID, NORMAL_USERNAME, NORMAL_PASSWORD_ENV, encoder),
                    principal(SAFETY_41_USER_ID, SAFETY_41_USERNAME, SAFETY_41_PASSWORD_ENV, encoder),
                    principal(SAFETY_42_USER_ID, SAFETY_42_USERNAME, SAFETY_42_PASSWORD_ENV, encoder));
            return username -> principals.stream()
                    .filter(principal -> principal.getUsername().equals(username))
                    .findFirst();
        }

        @Bean(name = "stage17UserDetailsService")
        @Primary
        UserDetailsService userDetailsService(AuthUserRepository repository) {
            return new ApiOpsUserDetailsService(repository);
        }

        @Bean(name = "stage17GlobalRbacRepository")
        @Primary
        GlobalRbacRepository globalRbacRepository() {
            return new GlobalRbacRepository() {
                @Override
                public Set<String> findRoleCodesByUserId(long userId) {
                    return Set.of();
                }

                @Override
                public Set<String> findPermissionCodesByUserId(long userId) {
                    return Set.of(NORMAL_USER_ID, SAFETY_41_USER_ID, SAFETY_42_USER_ID)
                            .contains(userId) ? Set.of("TOOL_READ") : Set.of();
                }
            };
        }

        @Bean(name = "stage17ProjectMembershipRepository")
        @Primary
        ProjectMembershipRepository projectMembershipRepository() {
            return (userId, projectId) -> {
                if (userId == NORMAL_USER_ID
                        && (projectId == PROJECT_41 || projectId == PROJECT_1001)) {
                    return Optional.of(ProjectRole.EDITOR);
                }
                if (userId == SAFETY_41_USER_ID && projectId == PROJECT_41) {
                    return Optional.of(ProjectRole.VIEWER);
                }
                if (userId == SAFETY_42_USER_ID && projectId == 42L) {
                    return Optional.of(ProjectRole.VIEWER);
                }
                return Optional.empty();
            };
        }

        @Bean
        @Primary
        ResourceGuard fourE2EResourceGuard() {
            return (context, definition, intent) -> {
                if (context.projectId() == PROJECT_41 && "rag.search".equals(intent.toolName())) {
                    String query = String.valueOf(intent.arguments().getOrDefault("query", ""))
                            .toLowerCase(Locale.ROOT);
                    if (query.contains("formal") || query.contains("guarded")
                            || query.contains("acceptance")) {
                        return ResourceGuard.Decision.reject(
                                "formal guarded evidence is denied by the test resource policy");
                    }
                }
                return ResourceGuard.Decision.allow();
            };
        }

        @Bean
        @Primary
        FourE2EMetadataRepository fourE2EMetadataRepository() {
            return new FourE2EMetadataRepository();
        }

        private static ApiOpsPrincipal principal(
                long userId, String username, String passwordEnv, PasswordEncoder encoder) {
            return new ApiOpsPrincipal(
                    userId, username, encoder.encode(requiredEnvironment(passwordEnv)), true, List.of());
        }
    }

    static final class FourE2EMetadataRepository implements OpenApiMetadataRepository {

        private final Map<Key, ApiEndpoint> endpoints = new ConcurrentHashMap<>();
        private final Map<Key, List<ApiRequestSchema>> requests = new ConcurrentHashMap<>();
        private final Map<Key, List<ApiResponseSchema>> responses = new ConcurrentHashMap<>();
        private final Map<Key, List<ApiExample>> examples = new ConcurrentHashMap<>();

        void seed(String demoBaseUrl) {
            endpoints.clear();
            requests.clear();
            responses.clear();
            examples.clear();
            add(PROJECT_41, "api-api-1", "stage21-golden-orders", demoBaseUrl, 4100L);
            add(PROJECT_1001, "api-1", "stage21-runner-orders", demoBaseUrl, 10010L);
            add(PROJECT_41, "formal-final-acceptance", "stage21-formal-orders", demoBaseUrl, 4110L);
        }

        private void add(long projectId, String apiId, String docId, String baseUrl, long idBase) {
            Instant now = Instant.now();
            Key key = new Key(projectId, apiId);
            endpoints.put(key, new ApiEndpoint(
                    idBase, apiId, docId, projectId, "createOrder", "POST", "/orders",
                    "Create an order",
                    "Creates an order. HAPPY_PATH uses userId 1, productId 1, quantity 1 and returns 200. "
                            + "BUSINESS_ERROR uses productId 2 with quantity 999; product 2 has inventory 2 "
                            + "and the service returns 409 ORDER_BUSINESS_CONFLICT. Omit couponId.",
                    "[\"Orders\"]", "[{\"url\":\"" + baseUrl + "\"}]", "[]", false, now, now));
            long requestId = idBase + 1;
            requests.put(key, List.of(new ApiRequestSchema(
                    requestId, apiId, projectId, true, "application/json", requestSchema(), now)));
            responses.put(key, List.of(
                    response(idBase + 2, apiId, projectId, "200",
                            "Order created.", now),
                    response(idBase + 3, apiId, projectId, "409",
                            "Insufficient inventory or another order business conflict.", now),
                    response(idBase + 4, apiId, projectId, "400",
                            "Request validation failed.", now),
                    response(idBase + 5, apiId, projectId, "404",
                            "Referenced user or product was not found.", now),
                    response(idBase + 6, apiId, projectId, "500",
                            "Unexpected server failure.", now)));
            examples.put(key, List.of(new ApiExample(
                    idBase + 7, apiId, projectId, "REQUEST_SCHEMA", requestId,
                    "createOrderRequest", "Create one order", "Valid happy-path request.",
                    "{\"userId\":1,\"items\":[{\"productId\":1,\"quantity\":1}]}", now)));
        }

        private static ApiResponseSchema response(
                long id, String apiId, long projectId, String status, String description, Instant now) {
            return new ApiResponseSchema(
                    id, apiId, projectId, status, description, "application/json",
                    "{\"type\":\"object\"}", now);
        }

        private static String requestSchema() {
            return """
                    {"type":"object","required":["userId","items"],"properties":{
                      "userId":{"type":"integer","format":"int64","minimum":1,"description":"Existing demo user id.","example":1},
                      "items":{"type":"array","minItems":1,"description":"Distinct product lines.","items":{"type":"object","required":["productId","quantity"],"properties":{
                        "productId":{"type":"integer","format":"int64","minimum":1,"description":"Product id 1 is stocked; product id 2 has inventory 2.","example":1},
                        "quantity":{"type":"integer","format":"int32","minimum":1,"description":"Use 1 for HAPPY_PATH; quantity 999 for the documented BUSINESS_ERROR scenario.","example":1}}}},
                      "couponId":{"type":"integer","format":"int64","minimum":1,"description":"Optional coupon template id; omit for this E2E."}}}
                    """;
        }

        @Override public ApiDocument save(ApiDocument value) { return value; }
        @Override public Optional<ApiDocument> findDocument(long projectId, String apiDocId) {
            return Optional.empty();
        }
        @Override public Optional<ApiDocument> findDocument(long projectId, String sourceKey, String contentHash) {
            return Optional.empty();
        }
        @Override public Optional<ApiDocument> findLatestDocument(long projectId, String sourceKey) {
            return Optional.empty();
        }
        @Override public List<ApiDocument> findDocuments(long projectId) { return List.of(); }
        @Override public ApiEndpoint save(ApiEndpoint value) {
            endpoints.put(new Key(value.projectId(), value.apiId()), value);
            return value;
        }
        @Override public Optional<ApiEndpoint> findEndpoint(long projectId, String apiId) {
            return Optional.ofNullable(endpoints.get(new Key(projectId, apiId)));
        }
        @Override public List<ApiEndpoint> findEndpoints(long projectId) {
            return endpoints.entrySet().stream()
                    .filter(entry -> entry.getKey().projectId() == projectId)
                    .map(Map.Entry::getValue).toList();
        }
        @Override public ApiParameter save(ApiParameter value) { return value; }
        @Override public List<ApiParameter> findParameters(long projectId, String apiId) {
            return List.of();
        }
        @Override public ApiRequestSchema save(ApiRequestSchema value) {
            requests.put(new Key(value.projectId(), value.apiId()), List.of(value));
            return value;
        }
        @Override public List<ApiRequestSchema> findRequestSchemas(long projectId, String apiId) {
            return requests.getOrDefault(new Key(projectId, apiId), List.of());
        }
        @Override public ApiResponseSchema save(ApiResponseSchema value) {
            responses.computeIfAbsent(new Key(value.projectId(), value.apiId()), ignored -> new ArrayList<>())
                    .add(value);
            return value;
        }
        @Override public List<ApiResponseSchema> findResponseSchemas(long projectId, String apiId) {
            return responses.getOrDefault(new Key(projectId, apiId), List.of());
        }
        @Override public ApiExample save(ApiExample value) { return value; }
        @Override public List<ApiExample> findExamples(long projectId, String apiId) {
            return examples.getOrDefault(new Key(projectId, apiId), List.of());
        }

        private record Key(long projectId, String apiId) { }
    }
}
