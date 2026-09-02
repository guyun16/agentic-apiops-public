package com.apiops.runner.application;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.assertion.AssertionEngine;
import com.apiops.runner.assertion.AssertionEvaluatorRegistry;
import com.apiops.runner.assertion.StatusCodeAssertionEvaluator;
import com.apiops.runner.dsl.EnvironmentSpec;
import com.apiops.runner.dsl.RequestSpec;
import com.apiops.runner.dsl.StatusCodeAssertionSpec;
import com.apiops.runner.dsl.TestCase;
import com.apiops.runner.dsl.TestStep;
import com.apiops.runner.execution.AssertionContextMapper;
import com.apiops.runner.execution.StepResult;
import com.apiops.runner.execution.TestStepRunner;
import com.apiops.runner.http.HttpRequestBuilder;
import com.apiops.runner.http.HttpResponseSnapshot;
import com.apiops.runner.messaging.BatchExecutionMessage;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.state.RunStatus;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;

import java.net.http.HttpRequest;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RunExecutionServiceTest {

    private static final Instant NOW = Instant.parse("2026-08-11T08:00:00Z");
    private static final ObjectMapper MAPPER = JsonMapper.builder().build();
    private static final UUID BATCH_ID = UUID.fromString(
            "81fd8850-76f5-4c52-a37a-d6523df70f4e");

    @Test
    void preparePersistsFullSnapshotAndPendingRunWithoutStartedAt() throws Exception {
        InMemoryRepository repository = new InMemoryRepository();
        RunExecutionService service = service(repository, request -> response(200), new ArrayList<>());
        TestCase testCase = testCase(step("step-1", "/first", 200));

        long runId = service.prepare(testCase);

        assertEquals(repository.runId, runId);
        assertEquals(RunStatus.PENDING, repository.status);
        assertEquals(FailureType.NONE, repository.failureType);
        assertNull(repository.startedAt);
        assertNull(repository.finishedAt);
        assertEquals(testCase, MAPPER.readValue(repository.snapshot, TestCase.class));
        assertEquals(testCase, MAPPER.readValue(
                repository.findExecutionInput(runId).orElseThrow().testCaseDslJson(),
                TestCase.class));
    }

    @Test
    void executeLoadsDatabaseSnapshotClaimsOnceAndPersistsStepsInDslOrder() {
        InMemoryRepository repository = new InMemoryRepository();
        List<String> requests = new ArrayList<>();
        RunExecutionService service = service(
                repository,
                request -> response(request.uri().getPath().equals("/first") ? 200 : 500),
                requests);
        long runId = service.prepare(testCase(
                step("step-1", "/first", 200),
                step("step-2", "/second", 200)));

        Optional<RunStatus> result = service.execute(runId);

        assertEquals(Optional.of(RunStatus.ASSERTION_FAILED), result);
        assertEquals(List.of("/first", "/second"), requests);
        assertEquals(List.of("step-1", "step-2"), repository.outcome.stepResults().stream()
                .map(ExecutionFactRepository.StepExecutionOutcome::stepId)
                .toList());
        assertEquals(RunStatus.ASSERTION_FAILED, repository.outcome.status());
        assertEquals(FailureType.ASSERTION_MISMATCH, repository.outcome.failureType());
        assertEquals(RunStatus.ASSERTION_FAILED, repository.status);

        assertTrue(service.execute(runId).isEmpty());
        assertEquals(List.of("/first", "/second"), requests);
        assertEquals(2, repository.claimAttempts);
        assertEquals(1, repository.outcomeWrites);
    }

    @Test
    void micrometerTimerReusesRunStatusAndFailureTypeWithoutChangingExecutionResult() {
        SimpleMeterRegistry registry = new SimpleMeterRegistry();

        InMemoryRepository successRepository = new InMemoryRepository();
        RunExecutionService successService = service(
                successRepository,
                request -> response(200),
                new ArrayList<>(),
                registry);
        long successRunId = successService.prepare(testCase(step("success", "/ok", 200)));

        assertEquals(Optional.of(RunStatus.SUCCESS), successService.execute(successRunId));
        assertEquals(1, registry.get(RunnerMetrics.EXECUTION_TIMER)
                .tags("status", "SUCCESS", "failureType", "NONE")
                .timer().count());

        InMemoryRepository assertionRepository = new InMemoryRepository();
        RunExecutionService assertionService = service(
                assertionRepository,
                request -> response(500),
                new ArrayList<>(),
                registry);
        long assertionRunId = assertionService.prepare(
                testCase(step("assertion", "/assertion", 200)));

        assertEquals(Optional.of(RunStatus.ASSERTION_FAILED),
                assertionService.execute(assertionRunId));
        assertEquals(1, registry.get(RunnerMetrics.EXECUTION_TIMER)
                .tags("status", "ASSERTION_FAILED", "failureType", "ASSERTION_MISMATCH")
                .timer().count());
        assertEquals(RunStatus.ASSERTION_FAILED, assertionRepository.outcome.status());
        assertEquals(FailureType.ASSERTION_MISMATCH, assertionRepository.outcome.failureType());
    }

    @Test
    void cooperativeCancelClosesOnlyPendingRunAndIsIdempotent() {
        InMemoryRepository repository = new InMemoryRepository();
        RunExecutionService service = service(
                repository, request -> response(200), new ArrayList<>());
        long runId = service.prepare(testCase(step("step-1", "/first", 200)));

        assertEquals(RunStatus.CANCELLED, service.cancelBeforeStart(runId));
        assertEquals(RunStatus.CANCELLED, service.cancelBeforeStart(runId));
        assertEquals(RunStatus.CANCELLED, repository.status);
        assertEquals(0, repository.successfulClaims);
        assertTrue(service.execute(runId).isEmpty());
    }

    @Test
    void executorRejectionCanBePersistedWithoutExecutingHttp() {
        InMemoryRepository repository = new InMemoryRepository();
        List<String> requests = new ArrayList<>();
        RunExecutionService service = service(
                repository, request -> response(200), requests);
        long runId = service.prepare(testCase(step("step-1", "/first", 200)));

        assertEquals(RunStatus.EXECUTION_FAILED, service.failBeforeStart(runId));

        assertTrue(requests.isEmpty());
        assertEquals(RunStatus.EXECUTION_FAILED, repository.status);
        assertEquals(FailureType.SYSTEM_ERROR, repository.failureType);
        assertEquals(1, repository.successfulClaims);
        assertEquals(1, repository.outcomeWrites);
        assertTrue(repository.outcome.stepResults().isEmpty());
        assertEquals(RunStatus.EXECUTION_FAILED, service.failBeforeStart(runId));
        assertEquals(1, repository.successfulClaims);
    }

    @Test
    void aggregationUsesDeterministicStage8FailurePrecedence() {
        InMemoryRepository repository = new InMemoryRepository();
        List<String> requests = new ArrayList<>();
        RunExecutionService service = service(
                repository,
                request -> switch (request.uri().getPath()) {
                    case "/assertion" -> response(500);
                    case "/execution" -> throw new com.apiops.runner.http.HttpTransportException(
                            FailureType.CONNECT_ERROR,
                            "connection failed",
                            new RuntimeException());
                    case "/timeout" -> throw new com.apiops.runner.http.HttpTransportException(
                            FailureType.TIMEOUT,
                            "timed out",
                            new RuntimeException());
                    default -> throw new AssertionError("Unexpected request");
                },
                requests);
        long runId = service.prepare(testCase(
                step("step-assertion", "/assertion", 200),
                step("step-execution", "/execution", 200),
                step("step-timeout", "/timeout", 200)));

        assertEquals(Optional.of(RunStatus.TIMEOUT), service.execute(runId));
        assertEquals(List.of("/assertion", "/execution", "/timeout"), requests);
        assertEquals(RunStatus.TIMEOUT, repository.outcome.status());
        assertEquals(FailureType.TIMEOUT, repository.outcome.failureType());
    }

    @Test
    void postClaimUnexpectedRunnerExceptionTerminalizesOnceWithoutSecondHttpExecution() {
        InMemoryRepository repository = new InMemoryRepository();
        List<String> requests = new ArrayList<>();
        RunExecutionService service = service(
                repository,
                request -> throwUnexpectedExecutionFailure(),
                requests);
        long runId = service.prepare(testCase(step("step-1", "/failure", 200)));

        assertEquals(RunStatus.EXECUTION_FAILED, service.executeBatchCase(runId));
        assertEquals(1, repository.successfulClaims);
        assertEquals(List.of("/failure"), requests);
        assertEquals(RunStatus.EXECUTION_FAILED, repository.status);
        assertEquals(FailureType.SYSTEM_ERROR, repository.failureType);
        assertTrue(repository.status.isTerminal());
        assertTrue(repository.startedAt != null);
        assertTrue(repository.finishedAt != null);
        assertEquals(1, repository.outcomeWrites);
        assertEquals(RunStatus.EXECUTION_FAILED, repository.outcome.status());
        assertEquals(FailureType.SYSTEM_ERROR, repository.outcome.failureType());
        assertTrue(repository.outcome.stepResults().isEmpty());

        assertEquals(RunStatus.EXECUTION_FAILED, service.executeBatchCase(runId));
        assertEquals(1, repository.successfulClaims);
        assertEquals(1, repository.outcomeWrites);
        assertEquals(List.of("/failure"), requests);
    }

    @Test
    void postClaimPersistenceFailureClosesRunAndDoesNotRequireListenerRetry() {
        InMemoryRepository repository = new InMemoryRepository();
        repository.failOutcomeWrite = true;
        RunExecutionService service = service(
                repository,
                request -> response(200),
                new ArrayList<>());
        long runId = service.prepare(testCase(step("step-1", "/first", 200)));

        assertEquals(Optional.of(RunStatus.EXECUTION_FAILED), service.execute(runId));
        assertEquals(RunStatus.EXECUTION_FAILED, repository.status);
        assertEquals(FailureType.SYSTEM_ERROR, repository.failureType);
        assertTrue(service.execute(runId).isEmpty());
    }

    @Test
    void postClaimHardDatabaseFailureRemainsUnresolvedAndCannotBeAckedAsDuplicate() {
        InMemoryRepository repository = new InMemoryRepository();
        repository.failOutcomeWrite = true;
        repository.failCompletion = true;
        List<String> requests = new ArrayList<>();
        RunExecutionService runService = service(
                repository,
                request -> response(200),
                requests);
        long runId = runService.prepare(testCase(step("step-1", "/once", 200)));
        AsyncExecutionApplicationService asyncService = asyncService(repository, runService);
        BatchExecutionMessage message = message(runId);

        assertThrows(UnresolvedRunningExecutionException.class,
                () -> asyncService.execute(message));
        assertEquals(RunStatus.RUNNING, repository.status);
        assertThrows(UnresolvedRunningExecutionException.class,
                () -> asyncService.execute(message));
        assertEquals(List.of("/once"), requests);
        assertEquals(1, repository.successfulClaims);
    }

    @Test
    void preClaimTransientFailureDoesNotAcquireExecutionOwnership() {
        InMemoryRepository repository = new InMemoryRepository();
        RunExecutionService runService = service(
                repository,
                request -> response(200),
                new ArrayList<>());
        long runId = runService.prepare(testCase(step("step-1", "/never", 200)));
        repository.failFindBatch = true;
        AsyncExecutionApplicationService asyncService = asyncService(repository, runService);

        assertThrows(IllegalStateException.class,
                () -> asyncService.execute(message(runId)));
        assertEquals(RunStatus.PENDING, repository.status);
        assertEquals(0, repository.claimAttempts);
    }

    @Test
    void asyncDuplicateDeliveryInvokesStage8RunnerOnlyOnce() {
        InMemoryRepository repository = new InMemoryRepository();
        List<String> requests = new ArrayList<>();
        RunExecutionService runService = service(
                repository,
                request -> response(200),
                requests);
        long runId = runService.prepare(testCase(step("step-1", "/once", 200)));
        AsyncExecutionApplicationService asyncService = asyncService(repository, runService);
        BatchExecutionMessage message = message(runId);

        AsyncExecutionResult first = asyncService.execute(message);
        assertEquals(1, repository.batchClaimAttempts);
        assertEquals(1, repository.claimAttempts);
        assertEquals(1, repository.successfulClaims);
        AsyncExecutionResult duplicate = asyncService.execute(message);

        assertEquals(AsyncExecutionResult.Disposition.EXECUTED, first.disposition());
        assertEquals(RunStatus.SUCCESS, first.status());
        assertEquals(AsyncExecutionResult.Disposition.DUPLICATE_TERMINAL,
                duplicate.disposition());
        assertEquals(List.of("/once"), requests);
        assertEquals(1, repository.batchClaimAttempts);
        assertEquals(1, repository.successfulClaims);
    }

    @Test
    void asyncContractRejectsUnsupportedVersionAndMissingIdentity() {
        InMemoryRepository repository = new InMemoryRepository();
        RunExecutionService runService = service(
                repository,
                request -> response(200),
                new ArrayList<>());
        long runId = runService.prepare(testCase(step("step-1", "/first", 200)));
        AsyncExecutionApplicationService asyncService = asyncService(repository, runService);
        BatchExecutionMessage valid = message(runId);

        assertThrows(PermanentExecutionMessageException.class, () -> asyncService.execute(
                new BatchExecutionMessage(
                        "2.0",
                        valid.messageId(),
                        valid.projectId(),
                        valid.batchId(),
                        valid.requestedBy(),
                        valid.traceId(),
                        valid.createdAt())));
        assertThrows(PermanentExecutionMessageException.class, () -> asyncService.execute(
                new BatchExecutionMessage(
                        BatchExecutionMessage.CURRENT_VERSION,
                        null,
                        valid.projectId(),
                        valid.batchId(),
                        valid.requestedBy(),
                        valid.traceId(),
                        valid.createdAt())));
        assertThrows(PermanentExecutionMessageException.class, () -> asyncService.execute(
                new BatchExecutionMessage(
                        BatchExecutionMessage.CURRENT_VERSION,
                        valid.messageId(),
                        0L,
                        valid.batchId(),
                        valid.requestedBy(),
                        valid.traceId(),
                        valid.createdAt())));
    }

    @Test
    void allStage8BusinessOutcomesCompleteWithoutMessageFailure() {
        assertAsyncOutcome(200, 200, null, RunStatus.SUCCESS);
        assertAsyncOutcome(500, 200, null, RunStatus.ASSERTION_FAILED);
        assertAsyncOutcome(0, 200, FailureType.CONNECT_ERROR, RunStatus.EXECUTION_FAILED);
        assertAsyncOutcome(0, 200, FailureType.TIMEOUT, RunStatus.TIMEOUT);
    }

    private void assertAsyncOutcome(
            int responseStatus,
            int expectedStatus,
            FailureType transportFailure,
            RunStatus expectedRunStatus) {
        InMemoryRepository repository = new InMemoryRepository();
        RunExecutionService runService = service(
                repository,
                request -> {
                    if (transportFailure != null) {
                        throw new com.apiops.runner.http.HttpTransportException(
                                transportFailure,
                                "expected test transport failure",
                                new RuntimeException());
                    }
                    return response(responseStatus);
                },
                new ArrayList<>());
        long runId = runService.prepare(testCase(
                step("step-1", "/business-result", expectedStatus)));
        AsyncExecutionApplicationService asyncService = asyncService(repository, runService);

        AsyncExecutionResult result = asyncService.execute(message(runId));

        assertEquals(AsyncExecutionResult.Disposition.EXECUTED, result.disposition());
        assertEquals(expectedRunStatus, result.status());
    }

    private BatchExecutionMessage message(long runId) {
        return new BatchExecutionMessage(
                BatchExecutionMessage.CURRENT_VERSION,
                UUID.randomUUID(),
                101L,
                BATCH_ID,
                401L,
                "trace-stage9",
                NOW);
    }

    private AsyncExecutionApplicationService asyncService(
            InMemoryRepository repository, RunExecutionService runService) {
        ThreadPoolExecutor executor = new ThreadPoolExecutor(
                1, 1, 0L, TimeUnit.MILLISECONDS,
                new ArrayBlockingQueue<>(1),
                task -> {
                    Thread thread = new Thread(task, "test-runner");
                    thread.setDaemon(true);
                    return thread;
                },
                new ThreadPoolExecutor.AbortPolicy());
        return new AsyncExecutionApplicationService(
                repository, new BatchExecutionCoordinator(executor, runService));
    }

    private static HttpResponseSnapshot throwUnexpectedExecutionFailure() {
        throw new IllegalStateException("unexpected runner failure");
    }

    private RunExecutionService service(
            InMemoryRepository repository,
            com.apiops.runner.http.HttpTransport transport,
            List<String> requests) {
        return service(repository, transport, requests, null);
    }

    private RunExecutionService service(
            InMemoryRepository repository,
            com.apiops.runner.http.HttpTransport transport,
            List<String> requests,
            MeterRegistry meterRegistry) {
        TestStepRunner runner = new TestStepRunner(
                new HttpRequestBuilder(),
                request -> {
                    requests.add(request.uri().getPath());
                    return transport.execute(request);
                },
                new AssertionContextMapper(MAPPER),
                new AssertionEngine(new AssertionEvaluatorRegistry(
                        new StatusCodeAssertionEvaluator())));
        return new RunExecutionService(
                repository,
                runner,
                MAPPER,
                Clock.fixed(NOW, ZoneOffset.UTC),
                meterRegistry);
    }

    private TestCase testCase(TestStep... steps) {
        return new TestCase(
                "1.0.0",
                "case-1",
                101L,
                "api-1",
                "application boundary case",
                new EnvironmentSpec("http://localhost:8080", Map.of()),
                null,
                List.of("stage9"),
                List.of(steps));
    }

    private TestStep step(String stepId, String path, int expectedStatus) {
        return new TestStep(
                stepId,
                stepId,
                new RequestSpec("GET", path, Map.of(), Map.of(), Map.of(), null),
                List.of(new StatusCodeAssertionSpec(expectedStatus)),
                List.of());
    }

    private static HttpResponseSnapshot response(int status) {
        return new HttpResponseSnapshot(status, Map.of(), "{}", 10L);
    }

    private static final class InMemoryRepository implements ExecutionFactRepository {
        private final long taskId = 201L;
        private final long runId = 301L;
        private long projectId;
        private String caseId;
        private String apiId;
        private String taskName;
        private String snapshot;
        private RunStatus status;
        private FailureType failureType;
        private Instant startedAt;
        private Instant finishedAt;
        private int claimAttempts;
        private int batchClaimAttempts;
        private int successfulClaims;
        private int outcomeWrites;
        private boolean failOutcomeWrite;
        private boolean failCompletion;
        private boolean failFindRun;
        private boolean failFindBatch;
        private RunStatus batchStatus;
        private boolean batchCancelRequested;
        private RunExecutionOutcome outcome;

        @Override
        public long prepareRun(
                long projectId,
                String caseId,
                String apiId,
                String name,
                String testCaseDslJson) {
            long preparedTaskId = saveTask(
                    projectId, caseId, apiId, name, testCaseDslJson);
            long preparedRunId = saveRun(
                    projectId,
                    preparedTaskId,
                    RunStatus.PENDING,
                    FailureType.NONE,
                    null,
                    null);
            batchStatus = RunStatus.PENDING;
            return preparedRunId;
        }

        @Override
        public PreparedBatch prepareBatch(
                UUID batchId, long projectId, long requestedBy, List<PreparedRun> runs) {
            throw new UnsupportedOperationException();
        }

        @Override
        public Optional<BatchExecutionFacts> findBatch(long projectId, UUID batchId) {
            if (failFindBatch) throw new IllegalStateException("temporary database outage");
            if (projectId != this.projectId || !BATCH_ID.equals(batchId)) return Optional.empty();
            return Optional.of(new BatchExecutionFacts(
                    BATCH_ID, projectId, 401L, batchStatus, batchCancelRequested,
                    startedAt, finishedAt, List.of(new BatchMember(taskId, runId))));
        }

        @Override
        public boolean tryClaimBatch(long projectId, UUID batchId, Instant startedAt) {
            batchClaimAttempts++;
            if (projectId != this.projectId || !BATCH_ID.equals(batchId)
                    || batchStatus != RunStatus.PENDING) return false;
            batchStatus = RunStatus.RUNNING;
            return true;
        }

        @Override
        public boolean requestBatchCancel(long projectId, UUID batchId) {
            if (projectId != this.projectId || !BATCH_ID.equals(batchId)
                    || batchStatus.isTerminal() || batchCancelRequested) return false;
            batchCancelRequested = true;
            return true;
        }

        @Override
        public boolean completeBatch(
                long projectId, UUID batchId, RunStatus terminalStatus, Instant finishedAt) {
            if (projectId != this.projectId || !BATCH_ID.equals(batchId)
                    || batchStatus != RunStatus.RUNNING) return false;
            batchStatus = batchCancelRequested ? RunStatus.CANCELLED : terminalStatus;
            return true;
        }

        @Override
        public long saveTask(
                long projectId,
                String caseId,
                String apiId,
                String name,
                String testCaseDslJson) {
            this.projectId = projectId;
            this.caseId = caseId;
            this.apiId = apiId;
            this.taskName = name;
            this.snapshot = testCaseDslJson;
            return taskId;
        }

        @Override
        public long saveRun(
                long projectId,
                long taskId,
                RunStatus status,
                FailureType failureType,
                Instant startedAt,
                Instant finishedAt) {
            this.status = status;
            this.failureType = failureType;
            this.startedAt = startedAt;
            this.finishedAt = finishedAt;
            return runId;
        }

        @Override
        public Optional<RunExecutionInput> findExecutionInput(long runId) {
            if (runId != this.runId) {
                return Optional.empty();
            }
            return Optional.of(new RunExecutionInput(
                    projectId, taskId, runId, caseId, apiId, snapshot));
        }

        @Override
        public boolean tryClaim(long projectId, long runId, Instant startedAt) {
            claimAttempts++;
            if (projectId != this.projectId
                    || runId != this.runId
                    || status != RunStatus.PENDING) {
                return false;
            }
            status = RunStatus.RUNNING;
            this.startedAt = startedAt;
            successfulClaims++;
            return true;
        }

        @Override
        public boolean cancelPendingRun(long projectId, long runId, Instant finishedAt) {
            if (projectId != this.projectId
                    || runId != this.runId
                    || status != RunStatus.PENDING) {
                return false;
            }
            status = RunStatus.CANCELLED;
            failureType = FailureType.NONE;
            this.finishedAt = finishedAt;
            return true;
        }

        @Override
        public boolean completeRun(
                long runId,
                RunStatus terminalStatus,
                FailureType failureType,
                Instant finishedAt) {
            if (failCompletion) {
                throw new IllegalStateException("terminal persistence unavailable");
            }
            if (runId != this.runId || status != RunStatus.RUNNING) {
                return false;
            }
            status = terminalStatus;
            this.failureType = failureType;
            this.finishedAt = finishedAt;
            return true;
        }

        @Override
        public void saveExecutionOutcome(RunExecutionOutcome outcome) {
            if (failOutcomeWrite) {
                throw new IllegalStateException("outcome persistence failed");
            }
            if (!completeRun(
                    outcome.runId(),
                    outcome.status(),
                    outcome.failureType(),
                    outcome.finishedAt())) {
                throw new IllegalStateException("run was not RUNNING");
            }
            this.outcome = outcome;
            outcomeWrites++;
        }

        @Override
        public List<ExecutionFactRepository.RunSummary> findRecentRunSummaries(long projectId) {
            return List.of();
        }

        @Override
        public long saveCaseResult(
                long projectId,
                long runId,
                String caseId,
                RunStatus status,
                FailureType failureType,
                Instant startedAt,
                Instant finishedAt) {
            throw new UnsupportedOperationException();
        }

        @Override
        public long saveStepResult(
                long projectId,
                long runId,
                long caseResultId,
                String stepId,
                StepResult result) {
            throw new UnsupportedOperationException();
        }

        @Override
        public Optional<RunExecutionFacts> findRun(long projectId, long runId) {
            if (failFindRun) {
                throw new IllegalStateException("temporary database outage");
            }
            if (projectId != this.projectId || runId != this.runId) {
                return Optional.empty();
            }
            return Optional.of(new RunExecutionFacts(
                    projectId,
                    taskId,
                    runId,
                    caseId,
                    apiId,
                    taskName,
                    status,
                    failureType,
                    startedAt,
                    finishedAt,
                    List.of()));
        }
    }
}
