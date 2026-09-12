package com.apiops.tool.gateway;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.common.enums.ToolStatus;
import com.apiops.common.tool.ToolResult;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Meter;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ToolGatewayTest {

    private static final long USER_ID = 7L;
    private static final long PROJECT_ID = 42L;

    @Test
    void authRejectsBeforeHandlerAndUsesTrustedIdentityOnly() {
        AtomicInteger executions = new AtomicInteger();
        List<Audit.AuditEvent> events = new ArrayList<>();
        try (ToolGateway gateway = gateway(
                readableDefinition(),
                (userId, projectId) -> Optional.empty(),
                ResourceGuard.allowAll(),
                new ResultSanitizer(),
                new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(events::add),
                new Metrics())) {

            ToolResult<Object> result = gateway.execute(
                    context("run-auth"),
                    intent("ok"),
                    (trusted, modelIntent) -> {
                        executions.incrementAndGet();
                        return "must-not-run";
                    });

            assertEquals(ToolStatus.FORBIDDEN, result.getStatus());
            assertEquals(0, executions.get());
            assertEquals(AuditStatus.DENIED, events.get(0).status());
        }
    }

    @Test
    void toolAuthRejectsCrossProjectBeforeExecutor() {
        AtomicInteger executions = new AtomicInteger();
        try (ToolGateway gateway = gateway(
                readableDefinition(),
                viewerMembership(),
                ResourceGuard.allowAll(),
                new ResultSanitizer(),
                new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(),
                new Metrics())) {

            ToolResult<Object> result = gateway.execute(
                    contextAtProject("run-cross-project", 999L),
                    intent("ok"),
                    (trusted, modelIntent) -> {
                        executions.incrementAndGet();
                        return "must-not-run";
                    });

            assertEquals(ToolStatus.FORBIDDEN, result.getStatus());
            assertEquals(0, executions.get());
        }
    }

    @Test
    void toolAuthRejectsForbiddenToolBeforeExecutor() {
        AtomicInteger executions = new AtomicInteger();
        ToolDefinition ownerOnly = new ToolDefinition(
                "safe.read",
                "Owner-only test contract",
                Set.of("TOOL_READ"),
                Set.of(ProjectRole.OWNER),
                Map.of("query", String.class)
        );
        try (ToolGateway gateway = gateway(
                ownerOnly,
                viewerMembership(),
                ResourceGuard.allowAll(),
                new ResultSanitizer(),
                new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(),
                new Metrics())) {

            ToolResult<Object> result = gateway.execute(
                    context("run-forbidden-tool"),
                    intent("ok"),
                    (trusted, modelIntent) -> {
                        executions.incrementAndGet();
                        return "must-not-run";
                    });

            assertEquals(ToolStatus.FORBIDDEN, result.getStatus());
            assertEquals(0, executions.get());
        }
    }

    @Test
    void gatewayOwnsUniqueCallIdsForSuccessInvalidAndDeniedInvocations() {
        AtomicBoolean authorized = new AtomicBoolean(true);
        AtomicInteger executions = new AtomicInteger();
        List<Audit.AuditEvent> events = new ArrayList<>();
        try (ToolGateway gateway = gateway(
                readableDefinition(),
                (userId, projectId) -> authorized.get()
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty(),
                ResourceGuard.allowAll(),
                new ResultSanitizer(),
                new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(events::add),
                new Metrics())) {

            ToolResult<Object> success = gateway.execute(
                    context("run-call-id-success"), intent("ok"),
                    (trusted, modelIntent) -> {
                        executions.incrementAndGet();
                        return "ok";
                    });
            ToolResult<Object> invalid = gateway.execute(
                    context("run-call-id-invalid"),
                    new ToolCallIntent("safe.read", Map.of()),
                    (trusted, modelIntent) -> {
                        executions.incrementAndGet();
                        return "must-not-run";
                    });
            authorized.set(false);
            ToolResult<Object> denied = gateway.execute(
                    context("run-call-id-denied"), intent("ok"),
                    (trusted, modelIntent) -> {
                        executions.incrementAndGet();
                        return "must-not-run";
                    });

            assertEquals(ToolStatus.SUCCESS, success.getStatus());
            assertEquals(ToolStatus.PARAM_INVALID, invalid.getStatus());
            assertEquals(ToolStatus.FORBIDDEN, denied.getStatus());
            assertNotNull(success.getToolCallId());
            assertNotNull(invalid.getToolCallId());
            assertNotNull(denied.getToolCallId());
            assertTrue(!success.getToolCallId().isBlank());
            assertTrue(!invalid.getToolCallId().isBlank());
            assertTrue(!denied.getToolCallId().isBlank());
            assertNotEquals(success.getToolCallId(), invalid.getToolCallId());
            assertNotEquals(invalid.getToolCallId(), denied.getToolCallId());
            assertNotEquals(success.getToolCallId(), denied.getToolCallId());
            assertNotEquals("caller-supplied-id", success.getToolCallId());
            assertEquals(1, executions.get());

            assertEquals(3, events.size());
            assertEquals(success.getToolCallId(), events.get(0).toolCallId());
            assertEquals(invalid.getToolCallId(), events.get(1).toolCallId());
            assertEquals(denied.getToolCallId(), events.get(2).toolCallId());
            assertEquals(AuditStatus.SUCCESS, events.get(0).status());
            assertEquals(AuditStatus.INVALID, events.get(1).status());
            assertEquals(AuditStatus.DENIED, events.get(2).status());
        }
    }

    @Test
    void invalidParametersStopBeforeGuardAndHandler() {
        AtomicInteger guardCalls = new AtomicInteger();
        AtomicInteger executions = new AtomicInteger();
        try (ToolGateway gateway = gateway(
                readableDefinition(),
                viewerMembership(),
                (context, definition, intent) -> {
                    guardCalls.incrementAndGet();
                    return ResourceGuard.Decision.allow();
                },
                new ResultSanitizer(),
                new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(),
                new Metrics())) {

            ToolResult<Object> result = gateway.execute(
                    context("run-invalid"),
                    new ToolCallIntent("safe.read", Map.of("query", 42)),
                    (trusted, modelIntent) -> {
                        executions.incrementAndGet();
                        return "must-not-run";
                    });

            assertEquals(ToolStatus.PARAM_INVALID, result.getStatus());
            assertEquals(0, guardCalls.get());
            assertEquals(0, executions.get());
        }
    }

    @Test
    void guardRejectsBeforeLimiterAndHandler() {
        AtomicInteger executions = new AtomicInteger();
        List<Audit.AuditEvent> events = new ArrayList<>();
        try (ToolGateway gateway = gateway(
                readableDefinition(),
                viewerMembership(),
                (context, definition, intent) -> ResourceGuard.Decision.reject("blocked"),
                new ResultSanitizer(),
                new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(events::add),
                new Metrics())) {

            ToolResult<Object> result = gateway.execute(
                    context("run-guard"),
                    intent("ok"),
                    (trusted, modelIntent) -> {
                        executions.incrementAndGet();
                        return "must-not-run";
                    });

            assertEquals(ToolStatus.FORBIDDEN, result.getStatus());
            assertEquals(0, executions.get());
            assertEquals(AuditStatus.SAFETY_VIOLATION, events.get(0).status());
        }
    }

    @Test
    void basicRateLimitRejectsBeforeExecutor() {
        AtomicInteger executions = new AtomicInteger();
        List<Audit.AuditEvent> events = new ArrayList<>();
        try (ToolGateway gateway = gateway(
                readableDefinition(),
                viewerMembership(),
                ResourceGuard.allowAll(),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new ToolRateLimiter(1, Duration.ofMinutes(1)),
                new ResultSanitizer(),
                new ResultLimiter(1_000),
                new Audit(events::add),
                new Metrics())) {

            ToolResult<Object> first = gateway.execute(
                    context("run-rate-limit"),
                    intent("ok"),
                    (trusted, modelIntent) -> {
                        executions.incrementAndGet();
                        return "ok";
                    });
            ToolResult<Object> second = gateway.execute(
                    context("run-rate-limit"),
                    intent("ok"),
                    (trusted, modelIntent) -> {
                        executions.incrementAndGet();
                        return "must-not-run";
                    });

            assertEquals(ToolStatus.SUCCESS, first.getStatus());
            assertEquals(ToolStatus.FORBIDDEN, second.getStatus());
            assertEquals(1, executions.get());
            assertEquals(AuditStatus.DENIED, events.get(1).status());
            assertTrue(events.get(1).sanitizedSummary().contains("basic rate limit"));
        }
    }

    @Test
    void modelProjectAndRoleCannotOverrideTrustedContext() {
        AtomicLong authorizedUserId = new AtomicLong();
        AtomicLong authorizedProjectId = new AtomicLong();
        AtomicReference<ToolExecutionContext> handlerContext = new AtomicReference<>();
        ProjectMembershipRepository membership = (userId, projectId) -> {
            authorizedUserId.set(userId);
            authorizedProjectId.set(projectId);
            return userId == USER_ID && projectId == PROJECT_ID
                    ? Optional.of(ProjectRole.VIEWER)
                    : Optional.empty();
        };
        ToolDefinition definition = new ToolDefinition(
                "safe.read",
                "Test read contract",
                Set.of("TOOL_READ"),
                Set.of(ProjectRole.VIEWER),
                Map.of("query", String.class, "projectId", Long.class, "role", String.class)
        );

        try (ToolGateway gateway = gateway(
                definition,
                membership,
                ResourceGuard.allowAll(),
                new ResultSanitizer(),
                new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(),
                new Metrics())) {

            ToolResult<Object> result = gateway.execute(
                    context("run-spoof"),
                    new ToolCallIntent(
                            "safe.read",
                            Map.of("query", "ok", "projectId", 999L, "role", "OWNER")),
                    (trusted, modelIntent) -> {
                        handlerContext.set(trusted);
                        return "trusted";
                    });

            assertEquals(ToolStatus.SUCCESS, result.getStatus());
            assertEquals(USER_ID, authorizedUserId.get());
            assertEquals(PROJECT_ID, authorizedProjectId.get());
            assertEquals(USER_ID, handlerContext.get().userId());
            assertEquals(PROJECT_ID, handlerContext.get().projectId());
            assertNotEquals("caller-supplied-id", result.getToolCallId());
            assertEquals(result.getToolCallId(), handlerContext.get().toolCallId());
        }
    }

    @Test
    void successResultIsSanitizedBeforeReturnAndAudit() {
        List<Object> sanitizerInputs = new ArrayList<>();
        List<Audit.AuditEvent> events = new ArrayList<>();
        ResultSanitizer sanitizer = new ResultSanitizer() {
            @Override
            public SanitizedResult sanitize(Object rawResult) {
                sanitizerInputs.add(rawResult);
                return super.sanitize(rawResult);
            }
        };
        Map<String, Object> raw = new LinkedHashMap<>();
        raw.put("token", "raw-token");
        raw.put("nested", Map.of("password", "raw-password", "visible", "ok"));
        raw.put("message", "access_token=raw-token-2 secret=raw-secret");

        try (ToolGateway gateway = gateway(
                readableDefinition(),
                viewerMembership(),
                ResourceGuard.allowAll(),
                sanitizer,
                new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(events::add),
                new Metrics())) {

            ToolResult<Object> result = gateway.execute(
                    context("run-sanitize"),
                    intent("ok"),
                    (trusted, modelIntent) -> raw);

            assertEquals(ToolStatus.SUCCESS, result.getStatus());
            assertSame(raw, sanitizerInputs.get(0));
            String modelResult = String.valueOf(result.getData());
            assertFalse(modelResult.contains("raw-token"));
            assertFalse(modelResult.contains("raw-password"));
            assertFalse(modelResult.contains("raw-secret"));
            assertFalse(modelResult.contains("raw-token-2"));
            assertTrue(modelResult.contains(ResultSanitizer.REDACTED_MARKER));
            assertFalse(events.get(0).sanitizedSummary().contains("raw-token"));
            assertFalse(events.get(0).sanitizedSummary().contains("raw-password"));
            assertFalse(events.get(0).sanitizedSummary().contains("raw-secret"));
            assertFalse(events.get(0).sanitizedSummary().contains("raw-token-2"));
        }
    }

    @Test
    void timeoutDoesNotRetry() throws Exception {
        AtomicInteger executions = new AtomicInteger();
        CountDownLatch started = new CountDownLatch(1);
        ToolExecutionLimiter limiter = new ToolExecutionLimiter(
                Duration.ofMillis(40), 5, 1);
        try (ToolGateway gateway = gateway(
                readableDefinition(),
                viewerMembership(),
                ResourceGuard.allowAll(),
                new ResultSanitizer(),
                new ResultLimiter(1_000),
                limiter,
                new Audit(),
                new Metrics())) {

            ToolResult<Object> result = gateway.execute(
                    context("run-timeout"),
                    intent("ok"),
                    (trusted, modelIntent) -> {
                        executions.incrementAndGet();
                        started.countDown();
                        try {
                            Thread.sleep(500);
                        } catch (InterruptedException exception) {
                            Thread.currentThread().interrupt();
                        }
                        return "late";
                    });

            assertTrue(started.await(1, TimeUnit.SECONDS));
            assertEquals(ToolStatus.TIMEOUT, result.getStatus());
            assertEquals(1, executions.get());
            assertEquals(0, limiter.retryCount());
        }
    }

    @Test
    void concurrentTimeoutsRemainTimeoutWithoutRetry() throws Exception {
        int concurrency = 4;
        AtomicInteger executions = new AtomicInteger();
        CountDownLatch allStarted = new CountDownLatch(concurrency);
        CountDownLatch release = new CountDownLatch(1);
        ExecutorService callers = Executors.newFixedThreadPool(concurrency);
        ToolExecutionLimiter limiter = new ToolExecutionLimiter(
                Duration.ofMillis(100), 8, concurrency);
        try (ToolGateway gateway = gateway(
                readableDefinition(),
                viewerMembership(),
                ResourceGuard.allowAll(),
                new ResultSanitizer(),
                new ResultLimiter(1_000),
                limiter,
                new Audit(),
                new Metrics())) {

            List<Future<ToolResult<Object>>> calls = new ArrayList<>();
            for (int index = 0; index < concurrency; index++) {
                int callIndex = index;
                calls.add(callers.submit(() -> gateway.execute(
                        context("run-timeout-concurrent-" + callIndex),
                        intent("ok"),
                        (trusted, modelIntent) -> {
                            executions.incrementAndGet();
                            allStarted.countDown();
                            try {
                                release.await();
                            } catch (InterruptedException exception) {
                                Thread.currentThread().interrupt();
                            }
                            return "late";
                        })));
            }

            assertTrue(allStarted.await(2, TimeUnit.SECONDS));
            int timeoutResults = 0;
            int unexpectedResults = 0;
            for (Future<ToolResult<Object>> call : calls) {
                ToolResult<Object> result = call.get(2, TimeUnit.SECONDS);
                if (result.getStatus() == ToolStatus.TIMEOUT) {
                    timeoutResults++;
                } else {
                    unexpectedResults++;
                }
            }

            assertEquals(concurrency, timeoutResults);
            assertEquals(0, unexpectedResults);
            assertEquals(concurrency, executions.get());
            assertEquals(0, limiter.retryCount());
        } finally {
            release.countDown();
            callers.shutdownNow();
            assertTrue(callers.awaitTermination(2, TimeUnit.SECONDS));
        }
    }

    @Test
    void agentRunBudgetStopsFurtherCalls() {
        AtomicInteger executions = new AtomicInteger();
        ToolExecutionLimiter limiter = new ToolExecutionLimiter(
                Duration.ofMillis(100), 2, 1);
        try (ToolGateway gateway = gateway(
                readableDefinition(),
                viewerMembership(),
                ResourceGuard.allowAll(),
                new ResultSanitizer(),
                new ResultLimiter(1_000),
                limiter,
                new Audit(),
                new Metrics())) {

            ToolResult<Object> first = execute(gateway, "run-budget", executions);
            ToolResult<Object> second = execute(gateway, "run-budget", executions);
            ToolResult<Object> third = execute(gateway, "run-budget", executions);

            assertEquals(ToolStatus.SUCCESS, first.getStatus());
            assertEquals(ToolStatus.SUCCESS, second.getStatus());
            assertEquals(ToolStatus.FORBIDDEN, third.getStatus());
            assertEquals(2, executions.get());
        }
    }

    @Test
    void boundedConcurrencyAllowsOnlyConfiguredActiveCalls() throws Exception {
        ToolExecutionLimiter limiter = new ToolExecutionLimiter(
                Duration.ofMillis(500), 5, 1);
        ExecutorService callers = Executors.newFixedThreadPool(2);
        CountDownLatch firstStarted = new CountDownLatch(1);
        CountDownLatch releaseFirst = new CountDownLatch(1);
        AtomicInteger active = new AtomicInteger();
        AtomicInteger maxActive = new AtomicInteger();
        try {
            Future<Integer> first = callers.submit(() -> limiter.execute("run-a", () -> {
                int now = active.incrementAndGet();
                maxActive.updateAndGet(previous -> Math.max(previous, now));
                firstStarted.countDown();
                releaseFirst.await();
                active.decrementAndGet();
                return 1;
            }));
            assertTrue(firstStarted.await(1, TimeUnit.SECONDS));

            Future<Integer> second = callers.submit(() -> limiter.execute("run-b", () -> {
                int now = active.incrementAndGet();
                maxActive.updateAndGet(previous -> Math.max(previous, now));
                active.decrementAndGet();
                return 2;
            }));

            Thread.sleep(30);
            assertFalse(second.isDone());
            assertEquals(1, maxActive.get());
            releaseFirst.countDown();
            assertEquals(1, first.get());
            assertEquals(2, second.get());
            assertEquals(1, maxActive.get());
        } finally {
            releaseFirst.countDown();
            callers.shutdownNow();
            limiter.close();
        }
    }

    @Test
    void auditRecordsEveryPipelineOutcomeAndAuditFailureDoesNotRetry() {
        List<Audit.AuditEvent> events = new ArrayList<>();

        try (ToolGateway success = gateway(
                readableDefinition(), viewerMembership(), ResourceGuard.allowAll(),
                new ResultSanitizer(), new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(events::add), new Metrics())) {
            success.execute(context("audit-success"), intent("ok"), (c, i) -> "ok");
        }
        try (ToolGateway denied = gateway(
                readableDefinition(), (userId, projectId) -> Optional.empty(), ResourceGuard.allowAll(),
                new ResultSanitizer(), new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(events::add), new Metrics())) {
            denied.execute(context("audit-denied"), intent("ok"), (c, i) -> "never");
        }
        try (ToolGateway invalid = gateway(
                readableDefinition(), viewerMembership(), ResourceGuard.allowAll(),
                new ResultSanitizer(), new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(events::add), new Metrics())) {
            invalid.execute(context("audit-invalid"), new ToolCallIntent("safe.read", Map.of()),
                    (c, i) -> "never");
        }
        try (ToolGateway safety = gateway(
                readableDefinition(), viewerMembership(),
                (c, d, i) -> ResourceGuard.Decision.reject("safety"),
                new ResultSanitizer(), new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(events::add), new Metrics())) {
            safety.execute(context("audit-safety"), intent("ok"), (c, i) -> "never");
        }
        try (ToolGateway timeout = gateway(
                readableDefinition(), viewerMembership(), ResourceGuard.allowAll(),
                new ResultSanitizer(), new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(20), 5, 1),
                new Audit(events::add), new Metrics())) {
            timeout.execute(context("audit-timeout"), intent("ok"), (c, i) -> {
                Thread.sleep(200);
                return "late";
            });
        }
        try (ToolGateway failed = gateway(
                readableDefinition(), viewerMembership(), ResourceGuard.allowAll(),
                new ResultSanitizer(), new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(events::add), new Metrics())) {
            failed.execute(context("audit-failed"), intent("ok"), (c, i) -> {
                throw new IllegalStateException("failed");
            });
        }

        assertTrue(events.stream().map(Audit.AuditEvent::status).toList()
                .containsAll(Set.of(
                        AuditStatus.SUCCESS,
                        AuditStatus.DENIED,
                        AuditStatus.INVALID,
                        AuditStatus.SAFETY_VIOLATION,
                        AuditStatus.TIMEOUT,
                        AuditStatus.FAILED)));
        assertEquals(6, events.size());
        assertTrue(events.stream().allMatch(event -> event.projectId() == PROJECT_ID));
        assertTrue(events.stream().allMatch(event -> !event.toolCallId().isBlank()));
        assertTrue(events.stream().allMatch(event -> !event.violationCode().isBlank()));
        assertTrue(events.stream().allMatch(event -> !event.sanitizedSummary().isBlank()));

        AtomicInteger executions = new AtomicInteger();
        try (ToolGateway auditFails = gateway(
                readableDefinition(), viewerMembership(), ResourceGuard.allowAll(),
                new ResultSanitizer(), new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(event -> { throw new IllegalStateException("audit down"); }),
                new Metrics())) {
            ToolResult<Object> result = auditFails.execute(
                    context("audit-failure-isolated"), intent("ok"), (c, i) -> {
                        executions.incrementAndGet();
                        return "ok";
                    });
            assertEquals(ToolStatus.SUCCESS, result.getStatus());
        }
        assertEquals(1, executions.get());
    }

    @Test
    void metricsRecordCallsOutcomeCountersAndLatency() {
        Metrics metrics = new Metrics();
        try (ToolGateway success = gateway(
                readableDefinition(), viewerMembership(), ResourceGuard.allowAll(),
                new ResultSanitizer(), new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(), metrics)) {
            success.execute(context("metrics-success"), intent("ok"), (c, i) -> "ok");
        }
        try (ToolGateway denied = gateway(
                readableDefinition(), (userId, projectId) -> Optional.empty(), ResourceGuard.allowAll(),
                new ResultSanitizer(), new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(), metrics)) {
            denied.execute(context("metrics-denied"), intent("ok"), (c, i) -> "never");
        }
        try (ToolGateway safety = gateway(
                readableDefinition(), viewerMembership(),
                (context, definition, intent) -> ResourceGuard.Decision.reject("blocked"),
                new ResultSanitizer(), new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(), metrics)) {
            safety.execute(context("metrics-safety"), intent("ok"), (c, i) -> "never");
        }

        Metrics.Snapshot snapshot = metrics.snapshot();
        assertEquals(3, snapshot.calls());
        assertEquals(1, snapshot.success());
        assertEquals(1, snapshot.denied());
        assertEquals(0, snapshot.invalid());
        assertEquals(1, snapshot.safetyViolations());
        assertEquals(0, snapshot.timeouts());
        assertEquals(0, snapshot.failed());
        assertTrue(snapshot.latencyNanos() >= 0);
    }

    @Test
    void micrometerTimerAndSafetyCounterUseOnlyStableLowCardinalityTags() {
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        Metrics metrics = new Metrics(registry);
        try (ToolGateway success = gateway(
                readableDefinition(), viewerMembership(), ResourceGuard.allowAll(),
                new ResultSanitizer(), new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(), metrics);
             ToolGateway safety = gateway(
                     readableDefinition(), viewerMembership(),
                     (context, definition, intent) -> ResourceGuard.Decision.reject("blocked"),
                     new ResultSanitizer(), new ResultLimiter(1_000),
                     new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                     new Audit(), metrics)) {
            ToolResult<Object> successResult = success.execute(
                    context("micrometer-success"), intent("ok"), (c, i) -> "ok");
            ToolResult<Object> safetyResult = safety.execute(
                    context("micrometer-safety"), intent("ok"), (c, i) -> "never");

            assertEquals(ToolStatus.SUCCESS, successResult.getStatus());
            assertEquals(ToolStatus.FORBIDDEN, safetyResult.getStatus());
        }

        assertEquals(1, registry.get(Metrics.TOOL_CALL_TIMER)
                .tags("tool", "safe.read", "status", "SUCCESS")
                .timer().count());
        Counter safetyCounter = registry.get(Metrics.SAFETY_VIOLATION_COUNTER)
                .tags("tool", "safe.read", "violationCode", "RESOURCE_GUARD_REJECTED")
                .counter();
        assertEquals(1.0, safetyCounter.count());

        Set<String> forbiddenTags = Set.of(
                "traceId", "requestId", "taskId", "runId", "agentRunId", "modelCallId",
                "toolCallId", "ragQueryId", "projectId", "username", "sql", "url",
                "prompt", "secret", "token", "cookie");
        for (Meter meter : registry.getMeters()) {
            assertTrue(meter.getId().getTags().stream()
                    .noneMatch(tag -> forbiddenTags.contains(tag.getKey())));
        }
    }

    @Test
    void defaultAuditRetainsSanitizedFacts() {
        Audit audit = new Audit();
        try (ToolGateway gateway = gateway(
                readableDefinition(), viewerMembership(), ResourceGuard.allowAll(),
                new ResultSanitizer(), new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                audit, new Metrics())) {
            gateway.execute(context("audit-default"), intent("ok"),
                    (c, i) -> Map.of("secret", "raw-secret"));
        }

        assertEquals(1, audit.events().size());
        assertFalse(audit.events().get(0).sanitizedSummary().contains("raw-secret"));
    }

    @Test
    void parameterValidatorChecksRequiredTypeAndUnknownArguments() {
        ToolDefinition definition = readableDefinition();
        ParamValidator validator = new ParamValidator();

        assertTrue(validator.validate(intent("ok"), definition).valid());
        assertFalse(validator.validate(
                new ToolCallIntent("safe.read", Map.of()), definition).valid());
        assertFalse(validator.validate(
                new ToolCallIntent("safe.read", Map.of("query", 1)), definition).valid());
        assertFalse(validator.validate(
                new ToolCallIntent("safe.read", Map.of("query", "ok", "extra", true)),
                definition).valid());
    }

    @Test
    void parameterValidatorChecksEnumValues() {
        ToolDefinition definition = constrainedDefinition(Map.of(
                "mode", ToolDefinition.ParameterContract.enumValues(
                        String.class, Set.of("safe", "fast"))));
        ParamValidator validator = new ParamValidator();

        assertTrue(validator.validate(
                new ToolCallIntent("safe.constraints", Map.of("mode", "safe")),
                definition).valid());
        assertFalse(validator.validate(
                new ToolCallIntent("safe.constraints", Map.of("mode", "unsafe")),
                definition).valid());
    }

    @Test
    void parameterValidatorChecksStringAndCollectionLength() {
        ToolDefinition stringDefinition = constrainedDefinition(Map.of(
                "query", ToolDefinition.ParameterContract.length(String.class, 2, 4)));
        ToolDefinition collectionDefinition = ToolDefinition.withParameterContracts(
                "safe.collection",
                "Collection length contract",
                Set.of("TOOL_READ"),
                Set.of(ProjectRole.VIEWER),
                Map.of("items", ToolDefinition.ParameterContract.length(Collection.class, 2, null))
        );
        ParamValidator validator = new ParamValidator();

        assertTrue(validator.validate(
                new ToolCallIntent("safe.constraints", Map.of("query", "ok")),
                stringDefinition).valid());
        assertFalse(validator.validate(
                new ToolCallIntent("safe.constraints", Map.of("query", "tool-too-long")),
                stringDefinition).valid());
        assertFalse(validator.validate(
                new ToolCallIntent("safe.constraints", Map.of("query", "x")),
                stringDefinition).valid());
        assertTrue(validator.validate(
                new ToolCallIntent("safe.collection", Map.of("items", List.of("a", "b"))),
                collectionDefinition).valid());
        assertFalse(validator.validate(
                new ToolCallIntent("safe.collection", Map.of("items", List.of("a"))),
                collectionDefinition).valid());
    }

    @Test
    void parameterValidatorChecksNumberRange() {
        ToolDefinition definition = constrainedDefinition(Map.of(
                "limit", ToolDefinition.ParameterContract.range(Integer.class, 1, 10)));
        ParamValidator validator = new ParamValidator();

        assertTrue(validator.validate(
                new ToolCallIntent("safe.constraints", Map.of("limit", 10)),
                definition).valid());
        assertFalse(validator.validate(
                new ToolCallIntent("safe.constraints", Map.of("limit", 11)),
                definition).valid());
        assertFalse(validator.validate(
                new ToolCallIntent("safe.constraints", Map.of("limit", 0)),
                definition).valid());
    }

    @Test
    void constraintInvalidStopsBeforeGuardAndExecutor() {
        AtomicInteger guardCalls = new AtomicInteger();
        AtomicInteger executions = new AtomicInteger();
        try (ToolGateway gateway = gateway(
                constrainedDefinition(Map.of(
                        "mode", ToolDefinition.ParameterContract.enumValues(
                                String.class, Set.of("safe")))),
                viewerMembership(),
                (context, definition, intent) -> {
                    guardCalls.incrementAndGet();
                    return ResourceGuard.Decision.allow();
                },
                new ResultSanitizer(),
                new ResultLimiter(1_000),
                new ToolExecutionLimiter(Duration.ofMillis(100), 5, 1),
                new Audit(),
                new Metrics())) {
            ToolResult<Object> result = gateway.execute(
                    context("constraint-invalid"),
                    new ToolCallIntent("safe.constraints", Map.of("mode", "unsafe")),
                    (trusted, modelIntent) -> {
                        executions.incrementAndGet();
                        return "never";
                    });

            assertEquals(ToolStatus.PARAM_INVALID, result.getStatus());
        }

        assertEquals(0, guardCalls.get());
        assertEquals(0, executions.get());
    }

    @Test
    void resultLimiterMarksTruncatedOutput() {
        ResultLimiter.LimitedResult limited = new ResultLimiter(8).limit("0123456789");

        assertTrue(limited.truncated());
        assertTrue(String.valueOf(limited.value()).contains(ResultLimiter.TRUNCATED_MARKER));
    }

    @Test
    void resultLimiterKeepsStructuredCollectionItemsAtomicAndMarksOnlyTopLevel() {
        Map<String, Object> first = new LinkedHashMap<>();
        first.put("id", "one");
        first.put("value", "ok");
        Map<String, Object> second = new LinkedHashMap<>();
        second.put("id", "two");
        second.put("value", "x".repeat(50));
        Map<String, Object> ragResult = new LinkedHashMap<>();
        ragResult.put("ragQueryId", "q");
        ragResult.put("results", List.of(first, second));

        ResultLimiter.LimitedResult limited = new ResultLimiter(10).limit(ragResult);

        assertTrue(limited.truncated());
        Map<?, ?> data = (Map<?, ?>) limited.value();
        assertEquals("q", data.get("ragQueryId"));
        assertEquals(List.of(first), data.get("results"));
        assertEquals(true, data.get(ResultLimiter.TRUNCATED_FIELD));
        assertFalse(first.containsKey(ResultLimiter.TRUNCATED_FIELD));
        assertFalse(data.get("results").toString().contains(ResultLimiter.TRUNCATED_MARKER));
    }

    @Test
    void applicationOwnedExecutionTimeoutIsAppliedWithoutRemovingTheDeadline() {
        Duration configuredTimeout = Duration.ofSeconds(2);
        ProjectAuthorizationService authorization =
                new ProjectAuthorizationService(viewerMembership());
        ToolRegistry registry = new ToolRegistry(authorization);
        registry.register(readableDefinition());

        try (ToolGateway gateway = new ToolGateway(
                new ToolAuth(registry, authorization),
                ResourceGuard.allowAll(),
                new Audit(),
                null,
                configuredTimeout)) {
            assertEquals(configuredTimeout, gateway.executionTimeout());

            ToolResult<Object> result = gateway.execute(
                    context("configured-timeout"),
                    intent("ok"),
                    (trusted, modelIntent) -> {
                        Thread.sleep(1_100);
                        return "ok";
                    });

            assertEquals(ToolStatus.SUCCESS, result.getStatus());
        }
    }

    private static ToolResult<Object> execute(
            ToolGateway gateway,
            String agentRunId,
            AtomicInteger executions
    ) {
        return gateway.execute(
                context(agentRunId),
                intent("ok"),
                (trusted, modelIntent) -> {
                    executions.incrementAndGet();
                    return "ok";
                });
    }

    private static ToolGateway gateway(
            ToolDefinition definition,
            ProjectMembershipRepository membership,
            ResourceGuard guard,
            ResultSanitizer sanitizer,
            ResultLimiter resultLimiter,
            ToolExecutionLimiter limiter,
            Audit audit,
            Metrics metrics
    ) {
        return gateway(
                definition,
                membership,
                guard,
                limiter,
                ToolRateLimiter.defaultLimiter(),
                sanitizer,
                resultLimiter,
                audit,
                metrics
        );
    }

    private static ToolGateway gateway(
            ToolDefinition definition,
            ProjectMembershipRepository membership,
            ResourceGuard guard,
            ToolExecutionLimiter limiter,
            ToolRateLimiter rateLimiter,
            ResultSanitizer sanitizer,
            ResultLimiter resultLimiter,
            Audit audit,
            Metrics metrics
    ) {
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(membership);
        ToolRegistry registry = new ToolRegistry(authorization);
        registry.register(definition);
        return new ToolGateway(
                new ToolAuth(registry, authorization),
                new ParamValidator(),
                guard,
                limiter,
                rateLimiter,
                sanitizer,
                resultLimiter,
                audit,
                metrics
        );
    }

    private static ToolDefinition readableDefinition() {
        return new ToolDefinition(
                "safe.read",
                "Test read contract",
                Set.of("TOOL_READ"),
                Set.of(ProjectRole.VIEWER),
                Map.of("query", String.class)
        );
    }

    private static ToolDefinition constrainedDefinition(
            Map<String, ToolDefinition.ParameterContract> parameterContracts
    ) {
        return ToolDefinition.withParameterContracts(
                "safe.constraints",
                "Constraint test contract",
                Set.of("TOOL_READ"),
                Set.of(ProjectRole.VIEWER),
                parameterContracts
        );
    }

    private static ProjectMembershipRepository viewerMembership() {
        return (userId, projectId) -> userId == USER_ID && projectId == PROJECT_ID
                ? Optional.of(ProjectRole.VIEWER)
                : Optional.empty();
    }

    private static ToolExecutionContext context(String agentRunId) {
        return contextAtProject(agentRunId, PROJECT_ID);
    }

    private static ToolExecutionContext contextAtProject(String agentRunId, long projectId) {
        return new ToolExecutionContext(
                USER_ID,
                projectId,
                Set.of("TOOL_READ"),
                "caller-supplied-id",
                agentRunId
        );
    }

    private static ToolCallIntent intent(String query) {
        return new ToolCallIntent("safe.read", Map.of("query", query));
    }
}
