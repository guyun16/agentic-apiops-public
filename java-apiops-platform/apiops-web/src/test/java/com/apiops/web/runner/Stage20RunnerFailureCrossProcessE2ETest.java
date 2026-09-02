package com.apiops.web.runner;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.repository.AuthUserRepository;
import com.apiops.auth.repository.GlobalRbacRepository;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.security.ApiOpsUserDetailsService;
import com.apiops.common.enums.FailureType;
import com.apiops.report.config.TestReportConfiguration;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.state.RunStatus;
import com.apiops.web.config.ApiOpsDataSourceConfiguration;
import com.apiops.web.config.ApiOpsProperties;
import com.apiops.web.infrastructure.web.TraceIdFilter;
import com.apiops.web.runner.config.RabbitExecutionConfiguration;
import com.apiops.web.runner.config.RunnerExecutionConfiguration;
import com.apiops.web.runner.config.TaskProgressConfiguration;
import com.apiops.web.runner.controller.AsyncBatchController;
import com.apiops.web.runner.rabbit.ExecutionRabbitProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.amqp.rabbit.core.RabbitAdmin;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.test.annotation.DirtiesContext;

import javax.sql.DataSource;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

/**
 * Real Runner terminal-failure evidence across the Python/Java process boundary.
 *
 * <p>The test uses the production HTTP controller, JWT filter, project authorization,
 * Rabbit consumer, JDBC execution facts, progress SSE, and report readback.  Only the
 * target API is a test-scope JDK HTTP server so a 200 response can deterministically
 * mismatch the validated status-code assertion.</p>
 */
@SpringBootTest(
        classes = Stage20RunnerFailureCrossProcessE2ETest.TestApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "apiops.datasource.runner.url=${APIOPS_RUNNER_DB_URL}",
                "apiops.datasource.runner.username=${APIOPS_RUNNER_DB_USERNAME:root}",
                "apiops.datasource.runner.password=${APIOPS_RUNNER_DB_PASSWORD}",
                "apiops.rabbitmq.execution.enabled=true",
                "apiops.rabbitmq.execution.exchange=apiops.stage20.runner-failure.exchange",
                "apiops.rabbitmq.execution.routing-key=apiops.stage20.runner-failure.run",
                "apiops.rabbitmq.execution.queue=apiops.stage20.runner-failure.queue",
                "apiops.rabbitmq.execution.dead-letter-exchange=apiops.stage20.runner-failure.dlx",
                "apiops.rabbitmq.execution.dead-letter-routing-key=apiops.stage20.runner-failure.dead",
                "apiops.rabbitmq.execution.dead-letter-queue=apiops.stage20.runner-failure.dlq",
                "apiops.rabbitmq.execution.max-attempts=1",
                "apiops.runner.progress.enabled=true",
                "apiops.runner.progress.ttl=60s",
                "apiops.runner.progress.sse-timeout=30s",
                "apiops.runner.executor.core-pool-size=1",
                "apiops.runner.executor.maximum-pool-size=1",
                "apiops.runner.executor.queue-capacity=2",
                "apiops.runner.executor.thread-name-prefix=stage20-runner-failure-",
                "spring.rabbitmq.host=127.0.0.1",
                "spring.rabbitmq.port=5672",
                "spring.rabbitmq.username=guest",
                "spring.rabbitmq.password=guest",
                "spring.data.redis.host=127.0.0.1",
                "spring.data.redis.port=6379",
                "management.health.redis.enabled=false",
                "apiops.auth.jwt.issuer=stage20-runner-failure",
                "apiops.auth.jwt.access-token-ttl=15m",
                "apiops.auth.jwt.secret=dGVzdC1vbmx5LWp3dC1zZWNyZXQtbWF0ZXJpYWwtMjAyNi0wOC0wNw=="
        })
@DirtiesContext
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@EnabledIfEnvironmentVariable(named = "APIOPS_RUNNER_DB_URL", matches = ".+")
@EnabledIfEnvironmentVariable(named = "APIOPS_RUNNER_DB_PASSWORD", matches = ".+")
class Stage20RunnerFailureCrossProcessE2ETest {

    private static final long USER_ID = 7L;
    private static final String USERNAME = "stage20-runner-failure";
    private static final long PROJECT_ID = 20_204_004L;
    private static final String QUEUE = "apiops.stage20.runner-failure.queue";

    @org.springframework.beans.factory.annotation.Autowired
    private JwtTokenService jwtTokenService;

    @org.springframework.beans.factory.annotation.Autowired
    private ObjectMapper objectMapper;

    @org.springframework.beans.factory.annotation.Autowired
    private ExecutionFactRepository repository;

    @org.springframework.beans.factory.annotation.Autowired
    private RabbitAdmin rabbitAdmin;

    @org.springframework.beans.factory.annotation.Autowired
    private ExecutionRabbitProperties rabbitProperties;

    @org.springframework.beans.factory.annotation.Autowired
    private StringRedisTemplate redis;

    @org.springframework.beans.factory.annotation.Autowired
    @org.springframework.beans.factory.annotation.Qualifier("runnerDataSource")
    private DataSource runnerDataSource;

    @LocalServerPort
    private int webPort;

    @BeforeEach
    void resetExecutionInfrastructure() throws SQLException {
        rabbitAdmin.purgeQueue(rabbitProperties.getQueue(), false);
        rabbitAdmin.purgeQueue(rabbitProperties.getDeadLetterQueue(), false);
        deleteProjectFacts();
    }

    @AfterEach
    void cleanExecutionInfrastructure() throws SQLException {
        rabbitAdmin.purgeQueue(rabbitProperties.getQueue(), false);
        rabbitAdmin.purgeQueue(rabbitProperties.getDeadLetterQueue(), false);
        redis.delete(redis.keys("apiops:runner:progress:" + PROJECT_ID + ":*"));
        deleteProjectFacts();
        rabbitAdmin.deleteQueue(rabbitProperties.getQueue());
        rabbitAdmin.deleteQueue(rabbitProperties.getDeadLetterQueue());
        rabbitAdmin.deleteExchange(rabbitProperties.getExchange());
        rabbitAdmin.deleteExchange(rabbitProperties.getDeadLetterExchange());
    }

    @Test
    void realSubmitCreatesRunAndPreservesAssertionFailureThroughReportReadback() throws Exception {
        AtomicInteger targetRequests = new AtomicInteger();
        HttpServer target = HttpServer.create(new java.net.InetSocketAddress("127.0.0.1", 0), 0);
        target.createContext("/assertion", exchange -> {
            targetRequests.incrementAndGet();
            respond(exchange, 200);
        });
        target.start();

        String traceId = "stage20-runner-failure-" + UUID.randomUUID();
        String token = jwtTokenService.generateAccessToken(new ApiOpsPrincipal(
                USER_ID, USERNAME, "test-password-hash", true, List.of()));
        String testcase = testcase(target.getAddress().getPort());
        ProcessBuilder builder = new ProcessBuilder(
                "uv", "run", "python", "scripts/stage20_real_e2e.py",
                "--runner-failure-e2e");
        builder.directory(findPythonProject().toFile());
        builder.environment().put("JAVA_APIOPS_BASE_URL", "http://127.0.0.1:" + serverPort());
        builder.environment().put("JAVA_APIOPS_TOKEN", token);
        builder.environment().put("STAGE20_PROJECT_ID", Long.toString(PROJECT_ID));
        builder.environment().put("STAGE20_TRACE_ID", traceId);
        builder.environment().put("STAGE20_TESTCASE_JSON", testcase);
        builder.environment().put("STAGE20_RUNNER_READBACK_DEADLINE_SECONDS", "60");
        builder.environment().put("PYTHONUTF8", "1");

        try {
            Process process = builder.start();
            CompletableFuture<String> stdout = readAsync(process.getInputStream());
            CompletableFuture<String> stderr = readAsync(process.getErrorStream());
            assertTrue(process.waitFor(90, TimeUnit.SECONDS),
                    "Python Runner failure E2E exceeded its deadline");
            String output = stdout.join().trim();
            String errors = stderr.join().trim();
            assertFalse(output.contains(token), "Python stdout must not expose JWT");
            assertFalse(errors.contains(token), "Python stderr must not expose JWT");
            assertEquals(0, process.exitValue(), () -> "Python Runner failure E2E failed: " + errors);

            JsonNode result = objectMapper.readTree(output);
            assertEquals("ASSERTION_FAILED", result.path("failureScenario").asText());
            assertEquals(PROJECT_ID, result.path("projectId").asLong());
            assertEquals(traceId, result.path("traceId").asText());
            assertEquals("ASSERTION_FAILED", result.path("status").asText());
            assertEquals("ASSERTION_MISMATCH", result.path("failureType").asText());
            assertEquals(0, result.path("resubmitCount").asInt());
            assertFalse(result.path("rawFallbackUsed").asBoolean(true));

            long taskId = result.path("taskId").asLong();
            long runId = result.path("runId").asLong();
            String reportId = requiredText(result, "reportId");
            assertTrue(taskId > 0);
            assertTrue(runId > 0);
            assertEquals("report:" + runId, reportId);
            assertNotNull(repository.findRun(PROJECT_ID, runId).orElse(null));
            assertEquals(RunStatus.ASSERTION_FAILED,
                    repository.findRun(PROJECT_ID, runId).orElseThrow().status());
            assertEquals(FailureType.ASSERTION_MISMATCH,
                    repository.findRun(PROJECT_ID, runId).orElseThrow().failureType());

            JsonNode report = result.path("report");
            assertEquals(PROJECT_ID, report.path("projectId").asLong());
            assertEquals(taskId, report.path("taskId").asLong());
            assertEquals(runId, report.path("runId").asLong());
            assertEquals(reportId, report.path("reportId").asText());
            assertEquals("ASSERTION_FAILED", report.path("status").asText());
            assertEquals("ASSERTION_MISMATCH", report.path("failureType").asText());

            JsonNode sse = result.path("sse");
            assertEquals("ASSERTION_FAILED", sse.path("terminalStatus").asText());
            assertEquals(60, sse.path("overallDeadlineSeconds").asInt());

            JsonNode requests = result.path("httpRequests");
            assertTrue(requests.isArray());
            assertEquals(1, requests.findValuesAsText("path").stream()
                    .filter(path -> path.endsWith("/test-batches"))
                    .count());
            assertTrue(requests.findValuesAsText("path").stream()
                    .anyMatch(path -> path.endsWith("/progress/events")));
            assertTrue(requests.findValuesAsText("path").stream()
                    .anyMatch(path -> path.endsWith("/report")));
            Set<String> requestIds = new java.util.HashSet<>();
            for (JsonNode request : requests) {
                assertEquals(traceId, request.path("requestTraceId").asText());
                assertEquals(traceId, request.path("responseTraceId").asText());
                String requestId = requiredText(request, "responseRequestId");
                assertFalse(requestId.equals(traceId));
                requestIds.add(requestId);
                System.out.printf(
                        "STAGE20_RUNNER_FAILURE_REQUEST path=%s requestId=%s%n",
                        request.path("path").asText(),
                        requestId);
            }
            assertEquals(requests.size(), requestIds.size());

            JsonNode references = result.path("traceReferences");
            assertEquals(3, references.size());
            for (JsonNode reference : references) {
                assertEquals(traceId, reference.path("traceId").asText());
                assertEquals(runId, reference.path("runId").asLong());
                assertEquals(taskId, reference.path("taskId").asLong());
            }

            System.out.printf(
                    "STAGE20_RUNNER_FAILURE_CORRELATION traceId=%s submitRequestIds=%s "
                            + "taskId=%d runId=%d reportId=%s status=%s failureType=%s "
                            + "targetRequests=%d%n",
                    traceId,
                    requestIds.stream().sorted().collect(java.util.stream.Collectors.joining(",")),
                    taskId,
                    runId,
                    reportId,
                    result.path("status").asText(),
                    result.path("failureType").asText(),
                    targetRequests.get());
            assertEquals(1, targetRequests.get(), "one real Runner execution must call the target once");
        } finally {
            target.stop(0);
        }
    }

    private String testcase(int targetPort) throws Exception {
        return objectMapper.writeValueAsString(java.util.Map.of(
                "schemaVersion", "1.0.0",
                "caseId", "stage20-runner-assertion-failure",
                "projectId", PROJECT_ID,
                "apiId", "stage20-runner-failure-api",
                "name", "Stage 20 deterministic assertion failure",
                "environment", java.util.Map.of(
                        "baseUrl", "http://127.0.0.1:" + targetPort,
                        "variables", java.util.Map.of()),
                "steps", List.of(java.util.Map.of(
                        "stepId", "assertion-mismatch",
                        "name", "Expect a deliberately wrong status",
                        "request", java.util.Map.of("method", "GET", "path", "/assertion"),
                        "assertions", List.of(java.util.Map.of(
                                "type", "STATUS_CODE", "expected", 201)),
                        "extractors", List.of()))));
    }

    private void deleteProjectFacts() throws SQLException {
        try (Connection connection = dataSource().getConnection()) {
            connection.setAutoCommit(false);
            for (String sql : List.of(
                    "DELETE FROM step_result WHERE project_id = ?",
                    "DELETE FROM case_result WHERE project_id = ?",
                    "DELETE FROM test_batch_run WHERE project_id = ?",
                    "DELETE FROM test_batch WHERE project_id = ?",
                    "DELETE FROM test_run WHERE project_id = ?",
                    "DELETE FROM test_task WHERE project_id = ?")) {
                try (var statement = connection.prepareStatement(sql)) {
                    statement.setLong(1, PROJECT_ID);
                    statement.executeUpdate();
                }
            }
            connection.commit();
        }
    }

    private DataSource dataSource() {
        return runnerDataSource;
    }

    private int serverPort() {
        return webPort;
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

    private static String requiredText(JsonNode node, String field) {
        String value = node.path(field).asText();
        assertFalse(value.isBlank(), () -> field + " must be present");
        return value;
    }

    private static void respond(HttpExchange exchange, int status) throws IOException {
        byte[] body = "{}".getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, body.length);
        exchange.getResponseBody().write(body);
        exchange.close();
    }

    @SpringBootConfiguration
    @EnableAutoConfiguration
    @EnableConfigurationProperties(ApiOpsProperties.class)
    @Import({
            ApiOpsDataSourceConfiguration.class,
            com.apiops.auth.config.ApiOpsSecurityConfiguration.class,
            RunnerExecutionConfiguration.class,
            RabbitExecutionConfiguration.class,
            TaskProgressConfiguration.class,
            TestReportConfiguration.class,
            AsyncBatchController.class
    })
    static class TestApplication {

        @Bean
        @Primary
        AuthUserRepository stage20AuthUsers() {
            ApiOpsPrincipal principal = new ApiOpsPrincipal(
                    USER_ID, USERNAME, "test-password-hash", true, List.of());
            return username -> USERNAME.equals(username)
                    ? Optional.of(principal) : Optional.empty();
        }

        @Bean
        @Primary
        UserDetailsService stage20UserDetails(AuthUserRepository users) {
            return new ApiOpsUserDetailsService(users);
        }

        @Bean
        @Primary
        GlobalRbacRepository stage20GlobalPermissions() {
            return new GlobalRbacRepository() {
                @Override
                public Set<String> findRoleCodesByUserId(long userId) {
                    return Set.of();
                }

                @Override
                public Set<String> findPermissionCodesByUserId(long userId) {
                    return Set.of();
                }
            };
        }

        @Bean
        @Primary
        ProjectMembershipRepository stage20ProjectMemberships() {
            return (userId, projectId) -> userId == USER_ID
                    ? Optional.of(ProjectRole.EDITOR) : Optional.empty();
        }

        @Bean
        TraceIdFilter traceIdFilter(ApiOpsProperties properties) {
            return new TraceIdFilter(properties);
        }

    }
}
