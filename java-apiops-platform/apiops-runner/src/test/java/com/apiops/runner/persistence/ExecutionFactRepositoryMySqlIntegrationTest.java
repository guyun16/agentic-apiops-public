package com.apiops.runner.persistence;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.assertion.AssertionResult;
import com.apiops.runner.execution.StepResult;
import com.apiops.runner.http.HttpResponseSnapshot;
import com.apiops.runner.http.HttpExchangeCapture;
import com.apiops.runner.http.HttpRequestBuilder;
import com.apiops.runner.dsl.RequestSpec;
import com.apiops.runner.dsl.AssertionType;
import com.apiops.runner.state.RunStatus;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import javax.sql.DataSource;
import java.io.InputStream;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.logging.Logger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

@Testcontainers(disabledWithoutDocker = true)
class ExecutionFactRepositoryMySqlIntegrationTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Container
    private static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4")
            .withDatabaseName("apiops_runner")
            .withUsername("root")
            .withPassword("runner-test-password");

    @Test
    void durableBatchPreparationClaimAndCancelAreAtomicAndProjectScoped() throws Exception {
        DataSource dataSource = testDataSource();
        executeSchema(dataSource);
        JdbcExecutionFactRepository repository =
                new JdbcExecutionFactRepository(dataSource, MAPPER);
        long projectId = projectId();

        try {
            long tasksBefore = taskCount(dataSource, projectId);
            UUID rolledBackBatch = UUID.randomUUID();
            assertThrows(IllegalArgumentException.class, () -> repository.prepareBatch(
                    rolledBackBatch, projectId, 7L, List.of(
                            prepared("batch-first"),
                            new ExecutionFactRepository.PreparedRun(
                                    "batch-invalid", "api", " ", "{}"))));
            assertTrue(repository.findBatch(projectId, rolledBackBatch).isEmpty());
            assertEquals(tasksBefore, taskCount(dataSource, projectId));

            UUID dispatchFailedBatch = UUID.randomUUID();
            ExecutionFactRepository.PreparedBatch dispatchFailed = repository.prepareBatch(
                    dispatchFailedBatch, projectId, 7L, List.of(prepared("dispatch-failed")));
            Instant dispatchFailedAt = Instant.parse("2026-08-12T08:59:00Z");
            assertTrue(repository.completeBatch(projectId, dispatchFailedBatch,
                    RunStatus.EXECUTION_FAILED, dispatchFailedAt));
            ExecutionFactRepository.BatchExecutionFacts failedFacts =
                    repository.findBatch(projectId, dispatchFailedBatch).orElseThrow();
            assertEquals(RunStatus.EXECUTION_FAILED, failedFacts.status());
            assertEquals(dispatchFailedAt, failedFacts.finishedAt());
            assertFalse(repository.tryClaimBatch(
                    projectId, dispatchFailedBatch, dispatchFailedAt.plusSeconds(1)));
            var failedRun = repository.findRun(projectId,
                    dispatchFailed.members().getFirst().runId()).orElseThrow();
            assertEquals(RunStatus.EXECUTION_FAILED, failedRun.status());
            assertEquals(FailureType.SYSTEM_ERROR, failedRun.failureType());
            assertEquals(dispatchFailedAt, failedRun.finishedAt());
            assertNull(failedRun.startedAt());
            assertFalse(repository.completeBatch(projectId, dispatchFailedBatch,
                    RunStatus.CANCELLED, dispatchFailedAt.plusSeconds(2)));
            assertEquals(RunStatus.EXECUTION_FAILED, repository.findRun(projectId,
                    failedRun.runId()).orElseThrow().status());

            UUID batchId = UUID.randomUUID();
            ExecutionFactRepository.PreparedBatch prepared = repository.prepareBatch(
                    batchId, projectId, 7L,
                    List.of(prepared("batch-one"), prepared("batch-two")));
            assertEquals(2, prepared.members().size());
            ExecutionFactRepository.BatchExecutionFacts pending =
                    repository.findBatch(projectId, batchId).orElseThrow();
            assertEquals(RunStatus.PENDING, pending.status());
            assertFalse(pending.cancelRequested());
            assertNull(pending.startedAt());
            assertEquals(prepared.members(), pending.members());
            assertTrue(repository.findBatch(projectId + 1, batchId).isEmpty());
            for (ExecutionFactRepository.BatchMember member : pending.members()) {
                ExecutionFactRepository.RunExecutionFacts run =
                        repository.findRun(projectId, member.runId()).orElseThrow();
                assertEquals(RunStatus.PENDING, run.status());
                assertNull(run.startedAt());
            }

            Instant startedAt = Instant.parse("2026-08-12T09:00:00Z");
            assertTrue(repository.tryClaimBatch(projectId, batchId, startedAt));
            assertFalse(repository.tryClaimBatch(projectId, batchId, startedAt.plusMillis(1)));
            assertTrue(repository.requestBatchCancel(projectId, batchId));
            assertFalse(repository.requestBatchCancel(projectId, batchId));
            assertTrue(repository.completeBatch(
                    projectId, batchId, RunStatus.CANCELLED, startedAt.plusSeconds(1)));
            assertFalse(repository.tryClaimBatch(projectId, batchId, startedAt.plusSeconds(2)));
            assertFalse(repository.requestBatchCancel(projectId, batchId));
            assertEquals(RunStatus.CANCELLED,
                    repository.findBatch(projectId, batchId).orElseThrow().status());
            for (var member : prepared.members()) {
                var cancelled = repository.findRun(projectId, member.runId()).orElseThrow();
                assertEquals(RunStatus.CANCELLED, cancelled.status());
                assertEquals(FailureType.NONE, cancelled.failureType());
            }
        } finally {
            cleanup(dataSource, projectId);
        }
    }

    @Test
    void closingFailedBatchRollsBackTogetherAndPreservesStartedAndUnrelatedRuns() throws Exception {
        DataSource dataSource = testDataSource();
        executeSchema(dataSource);
        var repository = new JdbcExecutionFactRepository(dataSource, MAPPER);
        long projectId = projectId();
        UUID batchId = UUID.randomUUID();
        Instant now = Instant.parse("2026-09-09T01:00:00Z");
        try {
            var batch = repository.prepareBatch(batchId, projectId, 7L,
                    List.of(prepared("pending"), prepared("running"), prepared("finished")));
            long pending = batch.members().get(0).runId();
            long running = batch.members().get(1).runId();
            long finished = batch.members().get(2).runId();
            long unrelated = repository.prepareRun(projectId, "unrelated", "api", "unrelated", "{}");
            assertTrue(repository.tryClaim(projectId, running, now));
            assertTrue(repository.tryClaim(projectId, finished, now));
            assertTrue(repository.completeRun(finished, RunStatus.SUCCESS, FailureType.NONE, now));
            assertFalse(repository.completeBatch(projectId + 1, batchId, RunStatus.EXECUTION_FAILED, now));
            try (var connection = dataSource.getConnection(); var statement = connection.createStatement()) {
                statement.execute("""
                        CREATE TRIGGER reject_batch_member_close BEFORE UPDATE ON test_run
                        FOR EACH ROW
                        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'forced member update failure'
                        """);
            }
            try {
                assertThrows(RuntimeException.class,
                        () -> repository.completeBatch(projectId, batchId, RunStatus.EXECUTION_FAILED, now));
                assertEquals(RunStatus.PENDING, repository.findBatch(projectId, batchId).orElseThrow().status());
                assertEquals(RunStatus.PENDING, repository.findRun(projectId, pending).orElseThrow().status());
            } finally {
                try (var connection = dataSource.getConnection(); var statement = connection.createStatement()) {
                    statement.execute("DROP TRIGGER IF EXISTS reject_batch_member_close");
                }
            }
            assertTrue(repository.completeBatch(projectId, batchId, RunStatus.EXECUTION_FAILED, now));
            assertEquals(RunStatus.EXECUTION_FAILED, repository.findRun(projectId, pending).orElseThrow().status());
            assertEquals(RunStatus.RUNNING, repository.findRun(projectId, running).orElseThrow().status());
            assertEquals(RunStatus.SUCCESS, repository.findRun(projectId, finished).orElseThrow().status());
            assertEquals(RunStatus.PENDING, repository.findRun(projectId, unrelated).orElseThrow().status());
        } finally {
            cleanup(dataSource, projectId);
        }
    }

    @Test
    void listsRecentRunSummariesByProjectWithIdentityStatusAndFixedLimit() throws Exception {
        DataSource dataSource = testDataSource();
        executeSchema(dataSource);
        JdbcExecutionFactRepository repository =
                new JdbcExecutionFactRepository(dataSource, MAPPER);
        long projectId = projectId();
        long otherProjectId = projectId + 1;
        long limitProjectId = projectId + 2;
        Instant olderCreatedAt = Instant.parse("2026-08-13T09:00:00Z");
        Instant newerCreatedAt = olderCreatedAt.plusSeconds(10);
        Instant pendingCreatedAt = olderCreatedAt.plusSeconds(5);

        try {
            long olderRunId = repository.prepareRun(
                    projectId, "case-older", "api-older", "Older case", "{}");
            long newerRunId = repository.prepareRun(
                    projectId, "case-newer", "api-newer", "Newer case", "{}");
            long pendingRunId = repository.prepareRun(
                    projectId, "case-pending", "api-pending", "Pending case", "{}");
            long otherProjectRunId = repository.prepareRun(
                    otherProjectId, "case-other", "api-other", "Other case", "{}");

            assertTrue(repository.tryClaim(projectId, olderRunId, olderCreatedAt));
            assertTrue(repository.completeRun(
                    olderRunId, RunStatus.SUCCESS, FailureType.NONE,
                    olderCreatedAt.plusSeconds(2)));
            assertTrue(repository.tryClaim(projectId, newerRunId, newerCreatedAt));
            setCreatedAt(dataSource, projectId, olderRunId, olderCreatedAt);
            setCreatedAt(dataSource, projectId, newerRunId, newerCreatedAt);
            setCreatedAt(dataSource, projectId, pendingRunId, pendingCreatedAt);
            setCreatedAt(dataSource, otherProjectId, otherProjectRunId, newerCreatedAt);

            List<ExecutionFactRepository.RunSummary> summaries =
                    repository.findRecentRunSummaries(projectId);

            assertEquals(List.of(newerRunId, pendingRunId, olderRunId), summaries.stream()
                    .map(ExecutionFactRepository.RunSummary::runId)
                    .toList());
            ExecutionFactRepository.RunSummary newer = summaries.getFirst();
            assertEquals("case-newer", newer.caseId());
            assertEquals("api-newer", newer.apiId());
            assertEquals("Newer case", newer.testCaseName());
            assertEquals(RunStatus.RUNNING, newer.status());
            assertEquals(FailureType.NONE, newer.failureType());
            assertEquals(newerCreatedAt, newer.createdAt());
            assertEquals(newerCreatedAt, newer.startedAt());
            assertNull(newer.finishedAt());
            assertTrue(repository.findRecentRunSummaries(projectId).stream()
                    .noneMatch(summary -> summary.runId() == otherProjectRunId));

            for (int index = 0; index < 101; index++) {
                repository.prepareRun(
                        limitProjectId,
                        "case-limit-" + index,
                        "api-limit",
                        "Limit case " + index,
                        "{}");
            }
            assertEquals(100, repository.findRecentRunSummaries(limitProjectId).size());
            assertEquals("case-limit-0", repository
                    .findLatestRunSummary(limitProjectId, "case-limit-0")
                    .orElseThrow()
                    .caseId());
            assertTrue(repository.findLatestRunSummary(limitProjectId, "case-absent").isEmpty());
            assertTrue(repository.findRecentRunSummaries(projectId + 3).isEmpty());
        } finally {
            cleanup(dataSource, projectId);
            cleanup(dataSource, otherProjectId);
            cleanup(dataSource, limitProjectId);
        }
    }

    @Test
    void savesAndReadsSuccessAssertionFailedAndExecutionFailedFacts() throws Exception {
        DataSource dataSource = testDataSource();
        try (Connection connection = dataSource.getConnection()) {
            assertEquals("apiops_runner", connection.getCatalog());
        }
        long projectId = projectId();
        JdbcExecutionFactRepository repository = new JdbcExecutionFactRepository(dataSource, MAPPER);
        executeSchema(dataSource);

        try {
            String testCaseSnapshot =
                    "{\"schemaVersion\":\"1.0.0\",\"caseId\":\"case-order\"}";
            long successRunId = repository.prepareRun(
                    projectId,
                    "case-order",
                    "createOrder",
                    "create order execution",
                    testCaseSnapshot);
            Instant startedAt = Instant.parse("2026-08-10T12:00:00Z");

            ExecutionFactRepository.RunExecutionFacts pending =
                    repository.findRun(projectId, successRunId).orElseThrow();
            assertEquals(RunStatus.PENDING, pending.status());
            assertNull(pending.startedAt());
            ExecutionFactRepository.RunExecutionInput executionInput =
                    repository.findExecutionInput(successRunId).orElseThrow();
            long taskId = executionInput.taskId();
            assertEquals(projectId, executionInput.projectId());
            assertEquals("case-order", executionInput.caseId());
            assertEquals(testCaseSnapshot, executionInput.testCaseDslJson());
            assertTrue(repository.tryClaim(projectId, successRunId, startedAt));
            assertFalse(repository.tryClaim(projectId, successRunId, startedAt.plusMillis(1)));

            var snapshotSpec = new RequestSpec("GET", "/orders", null, null,
                    Map.of("Authorization", "Bearer secret"), null);
            var safeExchange = HttpExchangeCapture.capture(
                    new HttpRequestBuilder().build("http://localhost", snapshotSpec), snapshotSpec,
                    new HttpResponseSnapshot(200, Map.of("Content-Type", List.of("application/json")),
                            "{\"token\":\"secret\",\"count\":3}", 12L));
            StepResult successResult = new StepResult(
                            RunStatus.SUCCESS,
                            FailureType.NONE,
                            List.of(new AssertionResult(
                                    AssertionType.STATUS_CODE,
                                    true,
                                    200,
                                    200,
                                    "status matched"),
                                    new AssertionResult(
                                            AssertionType.HEADER,
                                            true,
                                            "Bearer secret",
                                            List.of("Bearer secret"),
                                            "header matched")),
                            new HttpResponseSnapshot(
                                    200,
                                    Map.of(
                                            "Authorization", List.of("Bearer secret"),
                                            "Set-Cookie", List.of("session=secret")),
                                    "{\"token\":\"secret\"}",
                                    12L), safeExchange);
            repository.saveExecutionOutcome(new ExecutionFactRepository.RunExecutionOutcome(
                    projectId,
                    successRunId,
                    "case-order",
                    RunStatus.SUCCESS,
                    FailureType.NONE,
                    startedAt,
                    startedAt.plusSeconds(1),
                    List.of(new ExecutionFactRepository.StepExecutionOutcome(
                            "step-success", successResult))));

            long assertionFailedRunId = repository.saveRun(
                    projectId, taskId, RunStatus.ASSERTION_FAILED,
                    FailureType.ASSERTION_MISMATCH, startedAt, startedAt.plusSeconds(2));
            long assertionFailedCaseId = repository.saveCaseResult(
                    projectId, assertionFailedRunId, "case-order",
                    RunStatus.ASSERTION_FAILED, FailureType.ASSERTION_MISMATCH,
                    startedAt, startedAt.plusSeconds(2));
            long assertionFailedStepId = repository.saveStepResult(
                    projectId, assertionFailedRunId, assertionFailedCaseId, "step-mismatch",
                    new StepResult(
                            RunStatus.ASSERTION_FAILED,
                            FailureType.ASSERTION_MISMATCH,
                            List.of(new AssertionResult(
                                    AssertionType.STATUS_CODE,
                                    false,
                                    201,
                                    200,
                                    "status did not match")),
                            new HttpResponseSnapshot(200, Map.of(), "{}", 20L)));

            long executionFailedRunId = repository.saveRun(
                    projectId, taskId, RunStatus.EXECUTION_FAILED,
                    FailureType.CONNECT_ERROR, startedAt, startedAt.plusSeconds(3));
            long executionFailedCaseId = repository.saveCaseResult(
                    projectId, executionFailedRunId, "case-order",
                    RunStatus.EXECUTION_FAILED, FailureType.CONNECT_ERROR,
                    startedAt, startedAt.plusSeconds(3));
            long executionFailedStepId = repository.saveStepResult(
                    projectId, executionFailedRunId, executionFailedCaseId, "step-connect-error",
                    new StepResult(
                            RunStatus.EXECUTION_FAILED,
                            FailureType.CONNECT_ERROR,
                            List.of(),
                            null));

            ExecutionFactRepository.RunExecutionFacts success =
                    repository.findRun(projectId, successRunId).orElseThrow();
            assertEquals(projectId, success.projectId());
            assertEquals(taskId, success.taskId());
            assertEquals(successRunId, success.runId());
            assertEquals(RunStatus.SUCCESS, success.status());
            assertEquals(FailureType.NONE, success.failureType());
            ExecutionFactRepository.CaseExecutionFacts successCase =
                    success.caseResults().getFirst();
            assertEquals(projectId, successCase.projectId());
            assertEquals(successRunId, successCase.runId());
            assertEquals(RunStatus.SUCCESS, successCase.status());
            assertEquals(FailureType.NONE, successCase.failureType());
            ExecutionFactRepository.StepExecutionFacts successStep =
                    successCase.stepResults().getFirst();
            assertEquals(projectId, successStep.projectId());
            assertEquals(successRunId, successStep.runId());
            assertEquals(successCase.caseResultId(), successStep.caseResultId());
            assertEquals(RunStatus.SUCCESS, successStep.status());
            assertEquals(FailureType.NONE, successStep.failureType());
            assertEquals(200, successStep.responseStatusCode());
            assertEquals(12L, successStep.durationMs());
            assertEquals(MAPPER.readTree(MAPPER.writeValueAsString(safeExchange)),
                    MAPPER.readTree(successStep.httpExchangeJson()));
            assertFalse(successStep.httpExchangeJson().contains("secret"));
            assertTrue(repository.findRun(projectId + 1, successRunId).isEmpty());
            JsonNode assertionJson = MAPPER.readTree(successStep.assertionResultsJson());
            assertEquals("STATUS_CODE", assertionJson.get(0).get("type").asText());
            assertEquals(200, assertionJson.get(0).get("actual").asInt());
            assertFalse(successStep.assertionResultsJson().contains("Bearer secret"));
            assertFalse(successStep.assertionResultsJson().contains("session=secret"));
            assertEquals("[REDACTED]", assertionJson.get(1).get("expected").asText());
            assertEquals("[REDACTED]", assertionJson.get(1).get("actual").asText());
            assertFalse(repository.tryClaim(projectId, successRunId, startedAt.plusSeconds(2)));

            long completedRunId = repository.saveRun(
                    projectId, taskId, RunStatus.PENDING, FailureType.NONE, null, null);
            assertTrue(repository.tryClaim(projectId, completedRunId, startedAt));
            assertTrue(repository.completeRun(
                    completedRunId,
                    RunStatus.TIMEOUT,
                    FailureType.TIMEOUT,
                    startedAt.plusSeconds(5)));
            assertFalse(repository.completeRun(
                    completedRunId,
                    RunStatus.TIMEOUT,
                    FailureType.TIMEOUT,
                    startedAt.plusSeconds(6)));
            assertFalse(repository.tryClaim(
                    projectId, completedRunId, startedAt.plusSeconds(6)));

            long cancelledRunId = repository.saveRun(
                    projectId, taskId, RunStatus.PENDING, FailureType.NONE, null, null);
            assertTrue(repository.cancelPendingRun(
                    projectId, cancelledRunId, startedAt.plusSeconds(6)));
            assertFalse(repository.cancelPendingRun(
                    projectId, cancelledRunId, startedAt.plusSeconds(7)));
            assertFalse(repository.tryClaim(
                    projectId, cancelledRunId, startedAt.plusSeconds(7)));
            ExecutionFactRepository.RunExecutionFacts cancelled =
                    repository.findRun(projectId, cancelledRunId).orElseThrow();
            assertEquals(RunStatus.CANCELLED, cancelled.status());
            assertNull(cancelled.startedAt());
            assertEquals(startedAt.plusSeconds(6), cancelled.finishedAt());

            long rollbackRunId = repository.saveRun(
                    projectId, taskId, RunStatus.PENDING, FailureType.NONE, null, null);
            assertTrue(repository.tryClaim(projectId, rollbackRunId, startedAt));
            assertTrue(repository.completeRun(
                    rollbackRunId,
                    RunStatus.EXECUTION_FAILED,
                    FailureType.SYSTEM_ERROR,
                    startedAt.plusSeconds(7)));
            assertThrows(IllegalStateException.class, () -> repository.saveExecutionOutcome(
                    new ExecutionFactRepository.RunExecutionOutcome(
                            projectId,
                            rollbackRunId,
                            "case-order",
                            RunStatus.SUCCESS,
                            FailureType.NONE,
                            startedAt,
                            startedAt.plusSeconds(8),
                            List.of(new ExecutionFactRepository.StepExecutionOutcome(
                                    "rolled-back-step", successResult)))));
            assertTrue(repository.findRun(projectId, rollbackRunId)
                    .orElseThrow()
                    .caseResults()
                    .isEmpty());

            long taskCountBeforeRejectedPrepare = taskCount(dataSource, projectId);
            installRejectRunTrigger(dataSource);
            try {
                assertThrows(IllegalStateException.class, () -> repository.prepareRun(
                        projectId,
                        "case-rollback",
                        "rollbackApi",
                        "rollback prepare",
                        "{\"caseId\":\"case-rollback\"}"));
            } finally {
                dropRejectRunTrigger(dataSource);
            }
            assertEquals(taskCountBeforeRejectedPrepare, taskCount(dataSource, projectId));

            ExecutionFactRepository.RunExecutionFacts assertionFailed =
                    repository.findRun(projectId, assertionFailedRunId).orElseThrow();
            assertEquals(projectId, assertionFailed.projectId());
            assertEquals(assertionFailedRunId, assertionFailed.runId());
            assertEquals(RunStatus.ASSERTION_FAILED, assertionFailed.status());
            assertEquals(FailureType.ASSERTION_MISMATCH, assertionFailed.failureType());
            ExecutionFactRepository.CaseExecutionFacts assertionFailedCase =
                    assertionFailed.caseResults().getFirst();
            assertEquals(projectId, assertionFailedCase.projectId());
            assertEquals(assertionFailedRunId, assertionFailedCase.runId());
            assertEquals(assertionFailedCaseId, assertionFailedCase.caseResultId());
            assertEquals(RunStatus.ASSERTION_FAILED, assertionFailedCase.status());
            assertEquals(FailureType.ASSERTION_MISMATCH, assertionFailedCase.failureType());
            ExecutionFactRepository.StepExecutionFacts assertionFailedStep =
                    assertionFailedCase.stepResults().getFirst();
            assertEquals(projectId, assertionFailedStep.projectId());
            assertEquals(assertionFailedRunId, assertionFailedStep.runId());
            assertEquals(assertionFailedCaseId, assertionFailedStep.caseResultId());
            assertEquals(assertionFailedStepId, assertionFailedStep.stepResultId());
            assertEquals(RunStatus.ASSERTION_FAILED, assertionFailedStep.status());
            assertEquals(FailureType.ASSERTION_MISMATCH, assertionFailedStep.failureType());
            JsonNode mismatchJson = MAPPER.readTree(assertionFailedStep.assertionResultsJson());
            assertEquals("STATUS_CODE", mismatchJson.get(0).get("type").asText());
            assertFalse(mismatchJson.get(0).get("passed").asBoolean());
            assertEquals(201, mismatchJson.get(0).get("expected").asInt());
            assertEquals(200, mismatchJson.get(0).get("actual").asInt());
            assertEquals(200, assertionFailedStep.responseStatusCode());
            assertEquals(20L, assertionFailedStep.durationMs());

            ExecutionFactRepository.RunExecutionFacts executionFailed =
                    repository.findRun(projectId, executionFailedRunId).orElseThrow();
            assertEquals(projectId, executionFailed.projectId());
            assertEquals(executionFailedRunId, executionFailed.runId());
            assertEquals(RunStatus.EXECUTION_FAILED, executionFailed.status());
            assertEquals(FailureType.CONNECT_ERROR, executionFailed.failureType());
            ExecutionFactRepository.CaseExecutionFacts executionFailedCase =
                    executionFailed.caseResults().getFirst();
            assertEquals(projectId, executionFailedCase.projectId());
            assertEquals(executionFailedRunId, executionFailedCase.runId());
            assertEquals(executionFailedCaseId, executionFailedCase.caseResultId());
            assertEquals(RunStatus.EXECUTION_FAILED, executionFailedCase.status());
            assertEquals(FailureType.CONNECT_ERROR, executionFailedCase.failureType());
            ExecutionFactRepository.StepExecutionFacts failedStep =
                    executionFailedCase.stepResults().getFirst();
            assertEquals(projectId, failedStep.projectId());
            assertEquals(executionFailedRunId, failedStep.runId());
            assertEquals(executionFailedCaseId, failedStep.caseResultId());
            assertEquals(executionFailedStepId, failedStep.stepResultId());
            assertEquals(RunStatus.EXECUTION_FAILED, failedStep.status());
            assertEquals(FailureType.CONNECT_ERROR, failedStep.failureType());
            assertTrue(MAPPER.readTree(failedStep.assertionResultsJson()).isEmpty());
            assertNull(failedStep.responseStatusCode());
            assertNull(failedStep.durationMs());

            assertTrue(repository.findRun(projectId + 1, successRunId).isEmpty());
            assertNotNull(success.startedAt());
        } finally {
            cleanup(dataSource, projectId);
        }
    }

    @Test
    void concurrentConsumersCannotBothClaimTheSamePendingRun() throws Exception {
        DataSource dataSource = testDataSource();
        JdbcExecutionFactRepository repository =
                new JdbcExecutionFactRepository(dataSource, MAPPER);
        executeSchema(dataSource);
        long projectId = projectId();

        try {
            long runId = repository.prepareRun(
                    projectId,
                    "case-concurrent-claim",
                    "concurrentApi",
                    "concurrent claim",
                    "{\"caseId\":\"case-concurrent-claim\"}");
            Instant startedAt = Instant.parse("2026-08-11T12:00:00Z");
            CountDownLatch ready = new CountDownLatch(2);
            CountDownLatch start = new CountDownLatch(1);
            AtomicInteger claims = new AtomicInteger();
            AtomicReference<Throwable> failure = new AtomicReference<>();
            Runnable contender = () -> {
                ready.countDown();
                try {
                    start.await();
                    if (repository.tryClaim(projectId, runId, startedAt)) {
                        claims.incrementAndGet();
                    }
                } catch (Throwable exception) {
                    failure.compareAndSet(null, exception);
                }
            };
            Thread first = Thread.ofVirtual().start(contender);
            Thread second = Thread.ofVirtual().start(contender);
            ready.await();
            start.countDown();
            first.join();
            second.join();

            assertNull(failure.get());
            assertEquals(1, claims.get());
            assertEquals(RunStatus.RUNNING,
                    repository.findRun(projectId, runId).orElseThrow().status());
            assertFalse(repository.tryClaim(
                    projectId + 1, runId, startedAt.plusMillis(1)));
        } finally {
            cleanup(dataSource, projectId);
        }
    }

    private static void executeSchema(DataSource dataSource) throws Exception {
        String script;
        try (InputStream input = Objects.requireNonNull(
                ExecutionFactRepositoryMySqlIntegrationTest.class
                        .getResourceAsStream("/db/runner-schema.sql"))) {
            script = new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
        try (Connection connection = dataSource.getConnection()) {
            for (String statementText : script.split(";")) {
                String sql = statementText.trim();
                if (!sql.isEmpty()) {
                    try (Statement statement = connection.createStatement()) {
                        statement.execute(sql);
                    }
                }
            }
        }
    }

    private static DataSource testDataSource() {
        return new DriverManagerDataSource(
                MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
    }

    private static long taskCount(DataSource dataSource, long projectId) throws SQLException {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "SELECT COUNT(*) FROM test_task WHERE project_id = ?")) {
            statement.setLong(1, projectId);
            try (var rows = statement.executeQuery()) {
                rows.next();
                return rows.getLong(1);
            }
        }
    }

    private static void setCreatedAt(
            DataSource dataSource, long projectId, long runId, Instant createdAt)
            throws SQLException {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "UPDATE test_run SET created_at = ? WHERE project_id = ? AND id = ?")) {
            statement.setTimestamp(1, java.sql.Timestamp.from(createdAt));
            statement.setLong(2, projectId);
            statement.setLong(3, runId);
            assertEquals(1, statement.executeUpdate());
        }
    }

    private static ExecutionFactRepository.PreparedRun prepared(String caseId) {
        return new ExecutionFactRepository.PreparedRun(caseId, "api", caseId, "{}");
    }

    private static void installRejectRunTrigger(DataSource dataSource) throws SQLException {
        dropRejectRunTrigger(dataSource);
        try (Connection connection = dataSource.getConnection();
             Statement statement = connection.createStatement()) {
            statement.execute("""
                    CREATE TRIGGER reject_test_run_prepare
                    BEFORE INSERT ON test_run
                    FOR EACH ROW
                    SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'forced prepare run failure'
                    """);
        }
    }

    private static void dropRejectRunTrigger(DataSource dataSource) throws SQLException {
        try (Connection connection = dataSource.getConnection();
             Statement statement = connection.createStatement()) {
            statement.execute("DROP TRIGGER IF EXISTS reject_test_run_prepare");
        }
    }

    private static void cleanup(DataSource dataSource, long projectId) throws SQLException {
        try (Connection connection = dataSource.getConnection()) {
            for (String table : List.of("step_result", "case_result", "test_batch_run",
                    "test_batch", "test_run", "test_task")) {
                try (PreparedStatement statement = connection.prepareStatement(
                        "DELETE FROM " + table + " WHERE project_id = ?")) {
                    statement.setLong(1, projectId);
                    statement.executeUpdate();
                }
            }
        }
    }

    private static long projectId() {
        return (UUID.randomUUID().getMostSignificantBits() & Long.MAX_VALUE) | 1L;
    }

    private static final class DriverManagerDataSource implements DataSource {
        private final String url;
        private final String username;
        private final String password;

        private DriverManagerDataSource(String url, String username, String password) {
            this.url = url;
            this.username = username;
            this.password = password;
        }

        @Override
        public Connection getConnection() throws SQLException {
            return DriverManager.getConnection(url, username, password);
        }

        @Override
        public Connection getConnection(String username, String password) throws SQLException {
            return DriverManager.getConnection(url, username, password);
        }

        @Override
        public <T> T unwrap(Class<T> iface) throws SQLException {
            throw new SQLException("Not a wrapper");
        }

        @Override
        public boolean isWrapperFor(Class<?> iface) {
            return false;
        }

        @Override
        public PrintWriter getLogWriter() {
            return null;
        }

        @Override
        public void setLogWriter(PrintWriter out) {
        }

        @Override
        public void setLoginTimeout(int seconds) {
        }

        @Override
        public int getLoginTimeout() {
            return 0;
        }

        @Override
        public Logger getParentLogger() {
            return Logger.getLogger(Logger.GLOBAL_LOGGER_NAME);
        }
    }
}
