package com.apiops.web.runner;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.common.enums.FailureType;
import com.apiops.common.enums.ToolStatus;
import com.apiops.report.assembler.TestReportAssembler;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.controller.TestReportController;
import com.apiops.report.vo.TestReportVO;
import com.apiops.runner.application.BatchCancelResult;
import com.apiops.runner.application.RunnerMetrics;
import com.apiops.runner.dsl.EnvironmentSpec;
import com.apiops.runner.dsl.RequestSpec;
import com.apiops.runner.dsl.StatusCodeAssertionSpec;
import com.apiops.runner.dsl.TestCase;
import com.apiops.runner.dsl.TestStep;
import com.apiops.runner.messaging.BatchExecutionMessage;
import com.apiops.runner.messaging.BatchExecutionProducer;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.JdbcExecutionFactRepository;
import com.apiops.runner.progress.BatchProgressIdentity;
import com.apiops.runner.progress.TaskProgressSnapshot;
import com.apiops.runner.progress.TaskProgressStore;
import com.apiops.runner.state.RunStatus;
import com.apiops.web.runner.config.RabbitExecutionConfiguration;
import com.apiops.web.runner.config.RunnerExecutionConfiguration;
import com.apiops.web.runner.config.TaskProgressConfiguration;
import com.apiops.web.runner.controller.AsyncBatchController;
import com.apiops.web.runner.rabbit.ExecutionRabbitProperties;
import com.apiops.web.runner.vo.AsyncBatchSubmission;
import com.apiops.web.runner.progress.SseEmitterRegistry;
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.AuditStatus;
import com.apiops.tool.gateway.Metrics;
import com.apiops.tool.gateway.ParamValidator;
import com.apiops.tool.gateway.ResourceGuard;
import com.apiops.tool.gateway.ResultLimiter;
import com.apiops.tool.gateway.ResultSanitizer;
import com.apiops.tool.gateway.RagSearchTool;
import com.apiops.tool.gateway.ToolAuth;
import com.apiops.tool.gateway.ToolCallIntent;
import com.apiops.tool.gateway.ToolExecutionContext;
import com.apiops.tool.gateway.ToolExecutionLimiter;
import com.apiops.tool.gateway.ToolGateway;
import com.apiops.tool.gateway.ToolRegistry;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.amqp.rabbit.core.RabbitAdmin;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.AnonymousAuthenticationFilter;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.web.filter.OncePerRequestFilter;
import com.apiops.web.config.ApiOpsProperties;
import com.apiops.web.infrastructure.web.TraceIdFilter;

import javax.sql.DataSource;
import java.io.IOException;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Properties;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

@SpringBootTest(
        classes = Stage9RealE2EAcceptanceTest.TestApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "apiops.datasource.runner.url=${APIOPS_RUNNER_DB_URL}",
                "apiops.rabbitmq.execution.enabled=true",
                "apiops.rabbitmq.execution.exchange=apiops.stage9.acceptance.exchange",
                "apiops.rabbitmq.execution.routing-key=apiops.stage9.acceptance.run",
                "apiops.rabbitmq.execution.queue=apiops.stage9.acceptance.queue",
                "apiops.rabbitmq.execution.dead-letter-exchange=apiops.stage9.acceptance.dlx",
                "apiops.rabbitmq.execution.dead-letter-routing-key=apiops.stage9.acceptance.dead",
                "apiops.rabbitmq.execution.dead-letter-queue=apiops.stage9.acceptance.dlq",
                "apiops.rabbitmq.execution.max-attempts=3",
                "apiops.runner.progress.enabled=true",
                "apiops.runner.progress.ttl=60s",
                "apiops.runner.progress.sse-timeout=30s",
                "apiops.runner.executor.core-pool-size=2",
                "apiops.runner.executor.maximum-pool-size=2",
                "apiops.runner.executor.queue-capacity=2",
                "apiops.runner.executor.thread-name-prefix=stage9-e2e-runner-",
                "spring.rabbitmq.host=localhost",
                "spring.rabbitmq.port=5672",
                "spring.data.redis.host=127.0.0.1",
                "spring.data.redis.port=6379",
                "management.health.redis.enabled=false"
        })
@DirtiesContext
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@ExtendWith(OutputCaptureExtension.class)
@EnabledIfEnvironmentVariable(named = "APIOPS_STAGE9_REAL_E2E", matches = "true")
@EnabledIfEnvironmentVariable(named = "APIOPS_RUNNER_DB_URL", matches = ".+")
class Stage9RealE2EAcceptanceTest {

    private static final String RUNTIME_TRACE_ID = "stage13-runtime-http-trace";
    private static final Pattern REQUEST_ID_PATTERN =
            Pattern.compile("\\[requestId=([^]]+)]");

    @org.springframework.beans.factory.annotation.Autowired BatchExecutionProducer producer;
    @org.springframework.beans.factory.annotation.Autowired ExecutionFactRepository repository;
    @org.springframework.beans.factory.annotation.Autowired TaskProgressStore progressStore;
    @org.springframework.beans.factory.annotation.Autowired RabbitAdmin rabbitAdmin;
    @org.springframework.beans.factory.annotation.Autowired ExecutionRabbitProperties rabbit;
    @org.springframework.beans.factory.annotation.Autowired StringRedisTemplate redis;
    @org.springframework.beans.factory.annotation.Autowired SseEmitterRegistry emitterRegistry;
    @org.springframework.beans.factory.annotation.Autowired ObjectMapper mapper;
    @org.springframework.beans.factory.annotation.Autowired MeterRegistry meterRegistry;
    @org.springframework.beans.factory.annotation.Autowired ToolGateway toolGateway;
    @org.springframework.beans.factory.annotation.Autowired ToolAuth toolAuth;
    @LocalServerPort int webPort;

    private final AtomicInteger httpRequests = new AtomicInteger();
    private final AtomicInteger sequence = new AtomicInteger();
    private final List<Long> projects = new ArrayList<>();
    private HttpServer target;
    private ExecutorService targetExecutor;
    private volatile CountDownLatch slowStarted;
    private volatile CountDownLatch slowRelease;

    @BeforeAll
    void startRealHttpBoundary() throws IOException {
        target = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        targetExecutor = Executors.newCachedThreadPool(
                Thread.ofPlatform().name("stage9-e2e-http-", 0).factory());
        target.setExecutor(targetExecutor);
        target.createContext("/success", exchange -> respond(exchange, 200));
        target.createContext("/slow", exchange -> {
            httpRequests.incrementAndGet();
            if (slowStarted != null) slowStarted.countDown();
            try {
                if (slowRelease == null || !slowRelease.await(10, TimeUnit.SECONDS)) {
                    respondWithoutCounting(exchange, 504);
                    return;
                }
                respondWithoutCounting(exchange, 200);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                respondWithoutCounting(exchange, 500);
            }
        });
        target.start();
    }

    @BeforeEach
    void resetInfrastructure() {
        httpRequests.set(0);
        rabbitAdmin.purgeQueue(rabbit.getQueue(), false);
        rabbitAdmin.purgeQueue(rabbit.getDeadLetterQueue(), false);
        slowStarted = null;
        slowRelease = null;
    }

    @AfterEach
    void cleanFactsAndProjection() throws SQLException {
        if (slowRelease != null) slowRelease.countDown();
        for (long projectId : projects) {
            redis.delete(redis.keys("apiops:runner:progress:" + projectId + ":*"));
            deleteProjectFacts(projectId);
        }
        projects.clear();
    }

    @AfterAll
    void stopInfrastructure() {
        if (target != null) target.stop(0);
        if (targetExecutor != null) targetExecutor.shutdownNow();
        rabbitAdmin.deleteQueue(rabbit.getQueue());
        rabbitAdmin.deleteQueue(rabbit.getDeadLetterQueue());
        rabbitAdmin.deleteExchange(rabbit.getExchange());
        rabbitAdmin.deleteExchange(rabbit.getDeadLetterExchange());
    }

    @Test
    void realMqNormalDuplicateProgressSseFactsAndReport(CapturedOutput capturedOutput)
            throws Exception {
        long projectId = project();
        long runnerCountBefore = runnerSuccessCount();
        HttpResponse<String> submissionResponse = submit(projectId, List.of(
                testCase(projectId, "normal", "/success", 200)));
        assertEquals(202, submissionResponse.statusCode());
        String traceId = submissionResponse.headers()
                .firstValue("X-Trace-Id").orElseThrow();
        assertEquals(RUNTIME_TRACE_ID, traceId);
        AsyncBatchSubmission submission = submission(submissionResponse);
        long runId = submission.runIds().getFirst();
        SseCapture firstConnection = connectSse(projectId, runId);
        BatchExecutionMessage message = message(projectId, submission.batchId());

        producer.publish(message);
        ExecutionFactRepository.RunExecutionFacts facts = awaitTerminal(projectId, runId);
        awaitCondition(() -> runnerSuccessCount() >= runnerCountBefore + 1,
                Duration.ofSeconds(10));
        long runnerCountAfter = runnerSuccessCount();
        List<String> events = firstConnection.awaitTerminal();

        assertEquals(RunStatus.SUCCESS, facts.status());
        assertEquals(1, facts.caseResults().size());
        assertEquals(1, facts.caseResults().getFirst().stepResults().size());
        assertEquals(1, httpRequests.get());
        assertTrue(events.contains("event:current"));
        assertTrue(events.contains("event:progress"));
        assertTrue(events.contains("event:terminal"));
        TaskProgressSnapshot progress = progressStore.find(projectId, runId).orElseThrow();
        assertEquals(1, progress.total());
        assertEquals(1, progress.completed());
        assertEquals(0, progress.running());
        assertEquals(1, progress.success());
        assertEquals(RunStatus.SUCCESS, progress.status());
        assertTrue(redis.getExpire(progressKey(projectId, runId), TimeUnit.MILLISECONDS) > 0);

        TestReportVO report = new TestReportAssembler(mapper).assemble(facts);
        assertEquals(runId, report.runId());
        assertEquals(RunStatus.SUCCESS, report.status());
        assertEquals(1, report.summary().totalCases());
        HttpResponse<String> reportResponse = HttpClient.newHttpClient().send(
                HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + webPort
                                + "/api/v1/projects/" + projectId + "/test-runs/" + runId
                                + "/report"))
                        .GET().build(),
                HttpResponse.BodyHandlers.ofString());
        assertEquals(200, reportResponse.statusCode());
        assertTrue(reportResponse.body().contains("\"runId\":" + runId));
        assertTrue(reportResponse.body().contains("\"status\":\"SUCCESS\""));

        producer.publish(message);
        awaitCondition(() -> rabbitAdmin.getQueueProperties(rabbit.getQueue()) != null
                && queueMessageCount(rabbit.getQueue()) == 0, Duration.ofSeconds(10));
        assertEquals(1, httpRequests.get());
        ExecutionFactRepository.RunExecutionFacts afterDuplicate =
                repository.findRun(projectId, runId).orElseThrow();
        assertEquals(1, afterDuplicate.caseResults().size());
        assertEquals(1, afterDuplicate.caseResults().getFirst().stepResults().size());
        assertEquals(0, queueMessageCount(rabbit.getDeadLetterQueue()));

        long assertionRunId = submission(submit(projectId, List.of(testCase(
                projectId, "normal-assertion-failure", "/success", 201))))
                .runIds().getFirst();
        assertEquals(RunStatus.ASSERTION_FAILED,
                awaitTerminal(projectId, assertionRunId).status());
        assertEquals(2, httpRequests.get());
        assertEquals(0, queueMessageCount(rabbit.getDeadLetterQueue()));

        SseCapture reconnect = connectSse(projectId, runId);
        List<String> reconnectEvents = reconnect.awaitTerminal();
        assertTrue(reconnectEvents.contains("event:current"));
        assertTrue(reconnectEvents.contains("event:terminal"));

        String correlationLog = capturedOutput.getOut().lines()
                .filter(line -> line.contains("Accepted execution batch")
                        && line.contains("runIds=[" + runId + "]"))
                .findFirst()
                .orElseThrow(() -> new AssertionError(
                        "accepted batch correlation log was not captured"));
        assertTrue(correlationLog.contains("[traceId=" + traceId + "]"));
        Matcher requestId = REQUEST_ID_PATTERN.matcher(correlationLog);
        assertTrue(requestId.find());
        assertFalse(requestId.group(1).isBlank());
        System.out.printf(
                "[STAGE13-RUNTIME] runner meter apiops_runner_executions_seconds_count "
                        + "before=%d after=%d traceId=%s requestId=%s runId=%d%n",
                runnerCountBefore, runnerCountAfter, traceId, requestId.group(1), runId);
    }

    @Test
    void realToolGatewayUpdatesApplicationMetersAndAudit() throws Exception {
        long projectId = project();
        ToolExecutionContext context = new ToolExecutionContext(
                1L, projectId, Set.of("TOOL_READ"), "caller-tool-id", "stage13-runtime");
        ToolCallIntent intent = new ToolCallIntent(
                "rag.search", Map.of("query", "runtime", "topK", 1));

        long toolCountBefore = toolSuccessCount();
        var allowed = toolGateway.execute(
                context, intent, (trusted, ignored) -> Map.of("evidence", "runtime"));
        long toolCountAfter = toolSuccessCount();
        assertEquals(ToolStatus.SUCCESS, allowed.getStatus());
        assertEquals(toolCountBefore + 1, toolCountAfter);

        long safetyCountBefore = safetyViolationCount();
        Audit audit = new Audit();
        String safetyToolCallId;
        try (ToolGateway rejectingGateway = rejectingGateway(audit)) {
            var rejected = rejectingGateway.execute(
                    context,
                    intent,
                    (trusted, ignored) -> {
                        throw new AssertionError("rejected tool must not execute");
                    });
            assertEquals(ToolStatus.FORBIDDEN, rejected.getStatus());
            assertEquals(1, audit.events().size());
            Audit.AuditEvent event = audit.events().getFirst();
            assertEquals(AuditStatus.SAFETY_VIOLATION, event.status());
            assertEquals(projectId, event.projectId());
            assertEquals(rejected.getToolCallId(), event.toolCallId());
            assertFalse(event.toolCallId().isBlank());
            safetyToolCallId = event.toolCallId();
        }
        long safetyCountAfter = safetyViolationCount();
        assertEquals(safetyCountBefore + 1, safetyCountAfter);

        String prometheus = prometheusBody();
        assertTrue(prometheus.contains("apiops_runner_executions_seconds_count"));
        assertTrue(prometheus.contains("apiops_tool_calls_seconds_count"));
        assertTrue(prometheus.contains("apiops_tool_safety_violations_total"));
        System.out.printf(
                "[STAGE13-RUNTIME] tool meter apiops_tool_calls_seconds_count "
                        + "before=%d after=%d; safety meter "
                        + "apiops_tool_safety_violations_total before=%d after=%d "
                        + "toolCallId=%s%n",
                toolCountBefore, toolCountAfter, safetyCountBefore, safetyCountAfter,
                safetyToolCallId);
    }

    @Test
    void realMixedBatchKeepsAllFactsAndAggregatesExecutionFailure() throws Exception {
        long projectId = project();
        AsyncBatchSubmission batch = submission(submit(projectId, List.of(
                testCase(projectId, "mixed-success", "/success", 200),
                testCase(projectId, "mixed-assertion", "/success", 201),
                testCase(projectId, "mixed-execution", "http://127.0.0.1:1",
                        "/unreachable", 200))));
        List<Long> runIds = batch.runIds();
        for (long runId : runIds) awaitTerminal(projectId, runId);
        awaitBatchTerminal(projectId, batch.batchId());

        assertEquals(RunStatus.EXECUTION_FAILED,
                repository.findBatch(projectId, batch.batchId()).orElseThrow().status());
        assertEquals(List.of(RunStatus.SUCCESS, RunStatus.ASSERTION_FAILED,
                        RunStatus.EXECUTION_FAILED), runIds.stream()
                .map(runId -> repository.findRun(projectId, runId).orElseThrow().status())
                .toList());
        assertEquals(2, httpRequests.get());
        for (long runId : runIds) {
            ExecutionFactRepository.RunExecutionFacts facts =
                    repository.findRun(projectId, runId).orElseThrow();
            assertTrue(facts.status().isTerminal());
            assertEquals(1, facts.caseResults().size());
            assertEquals(1, facts.caseResults().getFirst().stepResults().size());
            assertEquals(runId, new TestReportAssembler(mapper).assemble(facts).runId());
        }
        TaskProgressSnapshot progress = progressStore.find(projectId, runIds.getFirst())
                .orElseThrow();
        assertEquals(3, progress.total());
        assertEquals(3, progress.completed());
        assertEquals(0, progress.running());
        assertEquals(1, progress.success());
        assertEquals(1, progress.assertionFailed());
        assertEquals(1, progress.executionFailed());
        assertEquals(RunStatus.EXECUTION_FAILED, progress.status());
    }

    @Test
    void realCooperativeCancelFinishesStartedAndCancelsUnstartedRuns() throws Exception {
        long projectId = project();
        List<TestCase> cases = new ArrayList<>();
        for (int index = 0; index < 10; index++) {
            cases.add(testCase(projectId, "cancel-" + index, "/slow", 200));
        }
        slowStarted = new CountDownLatch(2);
        slowRelease = new CountDownLatch(1);
        AsyncBatchSubmission batch = submission(submit(projectId, cases));
        List<Long> runIds = batch.runIds();
        HttpResponse<InputStream> disconnected = connectSseStream(
                projectId, runIds.getFirst());
        assertEquals(1, emitterRegistry.size(projectId, runIds.getFirst()));
        disconnected.body().close();
        assertTrue(slowStarted.await(10, TimeUnit.SECONDS));

        assertEquals(BatchCancelResult.REQUESTED, cancel(projectId, batch.batchId()));
        assertEquals(BatchCancelResult.ALREADY_REQUESTED, cancel(projectId, batch.batchId()));
        assertFalse(repository.findBatch(projectId, batch.batchId()).orElseThrow()
                .status().isTerminal());
        slowRelease.countDown();
        awaitBatchTerminal(projectId, batch.batchId());

        ExecutionFactRepository.BatchExecutionFacts batchFacts =
                repository.findBatch(projectId, batch.batchId()).orElseThrow();
        assertEquals(RunStatus.CANCELLED, batchFacts.status());
        assertTrue(batchFacts.cancelRequested());
        assertEquals(2, httpRequests.get());
        assertEquals(2, runIds.stream().filter(runId -> repository.findRun(projectId, runId)
                .orElseThrow().status() == RunStatus.SUCCESS).count());
        assertEquals(8, runIds.stream().filter(runId -> repository.findRun(projectId, runId)
                .orElseThrow().status() == RunStatus.CANCELLED).count());
        assertEquals(BatchCancelResult.TERMINAL, cancel(projectId, batch.batchId()));
        for (long runId : runIds) {
            assertTrue(repository.findRun(projectId, runId).orElseThrow().status().isTerminal());
        }
        TaskProgressSnapshot progress = progressStore.find(
                projectId, runIds.getFirst()).orElseThrow();
        assertEquals(10, progress.total());
        assertEquals(10, progress.completed());
        assertEquals(0, progress.running());
        assertEquals(2, progress.success());
        assertEquals(8, progress.cancelled());
        assertEquals(RunStatus.CANCELLED, progress.status());
        assertEquals(0, emitterRegistry.size(projectId, runIds.getFirst()));
    }

    private long runnerSuccessCount() {
        Timer timer = meterRegistry.find(RunnerMetrics.EXECUTION_TIMER)
                .tags("status", RunStatus.SUCCESS.name(),
                        "failureType", FailureType.NONE.name())
                .timer();
        return timer == null ? 0L : timer.count();
    }

    private long toolSuccessCount() {
        Timer timer = meterRegistry.find(Metrics.TOOL_CALL_TIMER)
                .tags("tool", "rag.search", "status", "SUCCESS")
                .timer();
        return timer == null ? 0L : timer.count();
    }

    private long safetyViolationCount() {
        Counter counter = meterRegistry.find(Metrics.SAFETY_VIOLATION_COUNTER)
                .tags("tool", "rag.search", "violationCode", "RESOURCE_GUARD_REJECTED")
                .counter();
        return counter == null ? 0L : (long) counter.count();
    }

    private String prometheusBody() throws Exception {
        HttpResponse<String> response = HttpClient.newHttpClient().send(
                HttpRequest.newBuilder(URI.create(
                                "http://127.0.0.1:" + webPort + "/actuator/prometheus"))
                        .GET().build(),
                HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode());
        return response.body();
    }

    private ToolGateway rejectingGateway(Audit audit) {
        return new ToolGateway(
                toolAuth,
                new ParamValidator(),
                (context, definition, intent) -> ResourceGuard.Decision.reject(
                        "stage13-runtime-safety"),
                new ToolExecutionLimiter(Duration.ofSeconds(3), 50, 2),
                new ResultSanitizer(),
                new ResultLimiter(100_000),
                audit,
                new Metrics(meterRegistry));
    }

    private TestCase testCase(long projectId, String caseId, String path, int expected) {
        return testCase(projectId, caseId, baseUrl(), path, expected);
    }

    private TestCase testCase(
            long projectId, String caseId, String baseUrl, String path, int expected) {
        return new TestCase("1.0.0", caseId, projectId, "stage9-e2e-api", caseId,
                new EnvironmentSpec(baseUrl, Map.of()), null, List.of("stage9", "real-e2e"),
                List.of(new TestStep(caseId + "-step", caseId + " step",
                        new RequestSpec("GET", path, null, null, null, null),
                        List.of(new StatusCodeAssertionSpec(expected)), List.of())));
    }

    private String baseUrl() {
        return "http://127.0.0.1:" + target.getAddress().getPort();
    }

    private BatchExecutionMessage message(long projectId, UUID batchId) {
        return new BatchExecutionMessage(BatchExecutionMessage.CURRENT_VERSION, UUID.randomUUID(),
                projectId, batchId, 1L, "stage9-real-e2e", Instant.now());
    }

    private HttpResponse<String> submit(long projectId, List<TestCase> cases) throws Exception {
        String body = mapper.writeValueAsString(Map.of("testCases", cases));
        return HttpClient.newHttpClient().send(HttpRequest.newBuilder(URI.create(
                "http://127.0.0.1:" + webPort + "/api/v1/projects/" + projectId
                                + "/test-batches"))
                .header("Content-Type", "application/json")
                .header("X-Trace-Id", RUNTIME_TRACE_ID)
                .POST(HttpRequest.BodyPublishers.ofString(body)).build(),
                HttpResponse.BodyHandlers.ofString());
    }

    private AsyncBatchSubmission submission(HttpResponse<String> response) throws Exception {
        assertEquals(202, response.statusCode());
        return mapper.treeToValue(mapper.readTree(response.body()).get("data"),
                AsyncBatchSubmission.class);
    }

    private BatchCancelResult cancel(long projectId, UUID batchId) throws Exception {
        HttpResponse<String> response = HttpClient.newHttpClient().send(
                HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + webPort
                                + "/api/v1/projects/" + projectId + "/test-batches/"
                                + batchId + "/cancel"))
                        .POST(HttpRequest.BodyPublishers.noBody()).build(),
                HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode());
        return BatchCancelResult.valueOf(mapper.readTree(response.body()).get("data").asText());
    }

    private void awaitBatchTerminal(long projectId, UUID batchId) throws Exception {
        awaitCondition(() -> repository.findBatch(projectId, batchId)
                .map(batch -> batch.status().isTerminal()).orElse(false), Duration.ofSeconds(20));
    }

    private ExecutionFactRepository.RunExecutionFacts awaitTerminal(long projectId, long runId)
            throws Exception {
        awaitCondition(() -> repository.findRun(projectId, runId)
                .map(facts -> facts.status().isTerminal()).orElse(false), Duration.ofSeconds(20));
        return repository.findRun(projectId, runId).orElseThrow();
    }

    private SseCapture connectSse(long projectId, long runId) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + webPort
                        + "/api/v1/projects/" + projectId + "/test-runs/" + runId
                        + "/progress/events"))
                .header("Accept", "text/event-stream").GET().build();
        HttpResponse<Stream<String>> response = HttpClient.newHttpClient().send(
                request, HttpResponse.BodyHandlers.ofLines());
        assertEquals(200, response.statusCode());
        FutureTask<List<String>> reader = new FutureTask<>(() -> {
            try (Stream<String> lines = response.body()) {
                List<String> values = new ArrayList<>();
                var iterator = lines.iterator();
                while (iterator.hasNext()) {
                    String line = iterator.next();
                    values.add(line);
                    if ("event:terminal".equals(line)) return values;
                }
                return values;
            }
        });
        Thread.ofPlatform().name("stage9-e2e-sse-reader").start(reader);
        return new SseCapture(reader);
    }

    private HttpResponse<InputStream> connectSseStream(long projectId, long runId)
            throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + webPort
                        + "/api/v1/projects/" + projectId + "/test-runs/" + runId
                        + "/progress/events"))
                .header("Accept", "text/event-stream").GET().build();
        HttpResponse<InputStream> response = HttpClient.newHttpClient().send(
                request, HttpResponse.BodyHandlers.ofInputStream());
        assertEquals(200, response.statusCode());
        return response;
    }

    private void respond(HttpExchange exchange, int status) throws IOException {
        httpRequests.incrementAndGet();
        respondWithoutCounting(exchange, status);
    }

    private void respondWithoutCounting(HttpExchange exchange, int status) throws IOException {
        byte[] body = "{}".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, body.length);
        exchange.getResponseBody().write(body);
        exchange.close();
    }

    private long project() {
        long value = 9_000_000L + System.currentTimeMillis() % 100_000L
                + sequence.incrementAndGet();
        projects.add(value);
        return value;
    }

    private String progressKey(long projectId, long runId) {
        return "apiops:runner:progress:" + projectId + ":" + runId;
    }

    private int queueMessageCount(String queue) {
        Properties properties = rabbitAdmin.getQueueProperties(queue);
        return properties == null ? -1
                : (Integer) properties.get(RabbitAdmin.QUEUE_MESSAGE_COUNT);
    }

    private void deleteProjectFacts(long projectId) throws SQLException {
        try (Connection connection = TestApplication.dataSource().getConnection()) {
            connection.setAutoCommit(false);
            for (String sql : List.of(
                    "DELETE FROM step_result WHERE project_id = ?",
                    "DELETE FROM case_result WHERE project_id = ?",
                    "DELETE FROM test_batch_run WHERE project_id = ?",
                    "DELETE FROM test_batch WHERE project_id = ?",
                    "DELETE FROM test_run WHERE project_id = ?",
                    "DELETE FROM test_task WHERE project_id = ?")) {
                try (PreparedStatement statement = connection.prepareStatement(sql)) {
                    statement.setLong(1, projectId);
                    statement.executeUpdate();
                }
            }
            connection.commit();
        }
    }

    private static void awaitCondition(CheckedBoolean condition, Duration timeout)
            throws Exception {
        long deadline = System.nanoTime() + timeout.toNanos();
        while (!condition.getAsBoolean()) {
            if (System.nanoTime() >= deadline) throw new AssertionError("condition timed out");
            Thread.sleep(25);
        }
    }

    private record SseCapture(FutureTask<List<String>> reader) {
        List<String> awaitTerminal() throws Exception {
            return reader.get(20, TimeUnit.SECONDS);
        }
    }

    @FunctionalInterface
    private interface CheckedBoolean {
        boolean getAsBoolean() throws Exception;
    }

    @SpringBootConfiguration
    @EnableAutoConfiguration
    @EnableConfigurationProperties(ApiOpsProperties.class)
    @Import({RunnerExecutionConfiguration.class, RabbitExecutionConfiguration.class,
            TaskProgressConfiguration.class, AsyncBatchController.class})
    static class TestApplication {
        private static final DataSource DATA_SOURCE = dataSource();

        static DataSource dataSource() {
            return new DataSource() {
                public Connection getConnection() throws SQLException {
                    return DriverManager.getConnection(System.getenv("APIOPS_RUNNER_DB_URL"),
                            System.getenv("APIOPS_RUNNER_DB_USERNAME"),
                            System.getenv("APIOPS_RUNNER_DB_PASSWORD"));
                }
                public Connection getConnection(String username, String password)
                        throws SQLException {
                    return DriverManager.getConnection(
                            System.getenv("APIOPS_RUNNER_DB_URL"), username, password);
                }
                public <T> T unwrap(Class<T> iface) throws SQLException { throw new SQLException(); }
                public boolean isWrapperFor(Class<?> iface) { return false; }
                public java.io.PrintWriter getLogWriter() { return null; }
                public void setLogWriter(java.io.PrintWriter out) { }
                public void setLoginTimeout(int seconds) { }
                public int getLoginTimeout() { return 0; }
                public java.util.logging.Logger getParentLogger() {
                    return java.util.logging.Logger.getGlobal();
                }
            };
        }

        @Bean(name = "runnerDataSource") DataSource runnerDataSource() { return DATA_SOURCE; }

        @Bean ExecutionFactRepository executionFactRepository(ObjectMapper objectMapper) {
            return new JdbcExecutionFactRepository(DATA_SOURCE, objectMapper);
        }

        @Bean ProjectAuthorizationService projectAuthorizationService() {
            ProjectMembershipRepository memberships = (userId, projectId) ->
                    Optional.of(ProjectRole.EDITOR);
            return new ProjectAuthorizationService(memberships);
        }

        @Bean ToolRegistry toolRegistry(ProjectAuthorizationService authorization) {
            ToolRegistry registry = new ToolRegistry(authorization);
            RagSearchTool.register(registry);
            return registry;
        }

        @Bean ToolAuth toolAuth(
                ToolRegistry registry, ProjectAuthorizationService authorization) {
            return new ToolAuth(registry, authorization);
        }

        @Bean ToolGateway toolGateway(ToolAuth toolAuth, MeterRegistry meterRegistry) {
            return new ToolGateway(toolAuth, meterRegistry);
        }

        @Bean TraceIdFilter traceIdFilter(ApiOpsProperties properties) {
            return new TraceIdFilter(properties);
        }

        @Bean TestReportAssembler testReportAssembler(ObjectMapper mapper) {
            return new TestReportAssembler(mapper);
        }

        @Bean TestReportQueryService testReportQueryService(
                ProjectAuthorizationService authorization,
                ExecutionFactRepository repository,
                TestReportAssembler assembler) {
            return new TestReportQueryService(authorization, repository, assembler);
        }

        @Bean TestReportController testReportController(TestReportQueryService query) {
            return new TestReportController(query);
        }

        @Bean SecurityFilterChain stage9AcceptanceSecurity(HttpSecurity http) throws Exception {
            return http.csrf(csrf -> csrf.disable())
                    .authorizeHttpRequests(auth -> auth.anyRequest().permitAll())
                    .addFilterBefore(new OncePerRequestFilter() {
                        @Override
                        protected void doFilterInternal(
                                jakarta.servlet.http.HttpServletRequest request,
                                jakarta.servlet.http.HttpServletResponse response,
                                jakarta.servlet.FilterChain filterChain)
                                throws jakarta.servlet.ServletException, IOException {
                            var principal = new com.apiops.auth.security.ApiOpsPrincipal(
                                    1L, "stage9-e2e", "unused", true, List.of());
                            SecurityContextHolder.getContext().setAuthentication(
                                    UsernamePasswordAuthenticationToken.authenticated(
                                            principal, null, principal.getAuthorities()));
                            filterChain.doFilter(request, response);
                        }
                    }, AnonymousAuthenticationFilter.class)
                    .build();
        }
    }
}
