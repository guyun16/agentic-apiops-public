package com.apiops.runner.application;

import com.apiops.runner.application.BatchCaseOutcome.Disposition;
import com.apiops.runner.state.RunStatus;
import com.apiops.runner.progress.BatchProgressIdentity;
import com.apiops.runner.progress.TaskProgressListener;
import com.apiops.runner.progress.TaskProgressSnapshot;
import com.apiops.runner.progress.TaskProgressStore;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.FutureTask;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.time.Instant;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class BatchExecutionCoordinatorTest {

    private final List<ThreadPoolExecutor> executors = new ArrayList<>();

    @AfterEach
    void shutdownExecutors() throws InterruptedException {
        for (ThreadPoolExecutor executor : executors) {
            executor.shutdownNow();
            assertTrue(executor.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    @Test
    void caseCountAboveConcurrencyStaysBoundedAndUsesNamedRunnerThreads() {
        ThreadPoolExecutor executor = executor(2, 2, 2, "batch-runner-");
        RecordingOperations operations = new RecordingOperations();
        operations.delayMillis = 40;
        BatchExecutionCoordinator coordinator =
                new BatchExecutionCoordinator(executor, operations);

        BatchExecutionResult result = coordinator.execute(
                UUID.randomUUID(), List.of(1L, 2L, 3L, 4L, 5L, 6L));

        assertEquals(RunStatus.SUCCESS, result.status());
        assertTrue(operations.maxConcurrency.get() <= 2);
        assertEquals(2, operations.maxConcurrency.get());
        assertEquals(6, operations.threadNames.size());
        assertTrue(operations.threadNames.stream()
                .allMatch(name -> name.startsWith("batch-runner-")));
        assertFalse(operations.threadNames.stream()
                .anyMatch(name -> name.contains("ForkJoinPool.commonPool")));
    }

    @Test
    void boundedQueueSaturationIsRejectedAndNormalizedToExecutionFailure() throws Exception {
        ThreadPoolExecutor executor = executor(1, 1, 1, "saturated-runner-");
        CountDownLatch release = new CountDownLatch(1);
        CountDownLatch blockersDone = new CountDownLatch(2);
        executor.execute(() -> awaitAndFinish(release, blockersDone));
        executor.execute(() -> awaitAndFinish(release, blockersDone));
        RecordingOperations operations = new RecordingOperations();
        BatchExecutionCoordinator coordinator =
                new BatchExecutionCoordinator(executor, operations);

        BatchExecutionResult result = coordinator.execute(UUID.randomUUID(), List.of(10L));

        assertEquals(RunStatus.EXECUTION_FAILED, result.status());
        assertEquals(Disposition.REJECTED, result.caseOutcomes().getFirst().disposition());
        assertEquals(List.of(10L), operations.failedBeforeStart);
        assertTrue(executor.getQueue().remainingCapacity() == 0);
        release.countDown();
        assertTrue(blockersDone.await(5, TimeUnit.SECONDS));
    }

    @Test
    void assertionFailureDoesNotFailFastIndependentCases() {
        assertAggregate(
                Map.of(1L, RunStatus.SUCCESS,
                        2L, RunStatus.ASSERTION_FAILED,
                        3L, RunStatus.SUCCESS),
                RunStatus.ASSERTION_FAILED);
    }

    @Test
    void executionFailureWinsOverAssertionFailure() {
        assertAggregate(
                Map.of(1L, RunStatus.SUCCESS,
                        2L, RunStatus.ASSERTION_FAILED,
                        3L, RunStatus.EXECUTION_FAILED),
                RunStatus.EXECUTION_FAILED);
    }

    @Test
    void timeoutWinsOverAssertionFailure() {
        assertAggregate(
                Map.of(1L, RunStatus.SUCCESS,
                        2L, RunStatus.TIMEOUT,
                        3L, RunStatus.ASSERTION_FAILED),
                RunStatus.TIMEOUT);
    }

    @Test
    void unexpectedCaseExceptionBecomesFailureAndOtherCasesStillComplete() {
        ThreadPoolExecutor executor = executor(2, 2, 2, "unexpected-runner-");
        RecordingOperations operations = new RecordingOperations();
        operations.throwingRunId = 2L;
        BatchExecutionCoordinator coordinator =
                new BatchExecutionCoordinator(executor, operations);

        BatchExecutionResult result = coordinator.execute(
                UUID.randomUUID(), List.of(1L, 2L, 3L));

        assertEquals(RunStatus.EXECUTION_FAILED, result.status());
        assertEquals(List.of(1L, 2L, 3L), result.caseOutcomes().stream()
                .map(BatchCaseOutcome::runId)
                .toList());
        assertEquals(Disposition.UNEXPECTED_FAILURE,
                result.caseOutcomes().get(1).disposition());
        assertEquals(List.of(2L), operations.failedBeforeStart);
        assertTrue(operations.executed.containsAll(List.of(1L, 3L)));
    }

    @Test
    void unresolvedRunningIsNotNormalizedAsAnAckableCaseOutcome() {
        ThreadPoolExecutor executor = executor(1, 1, 1, "unresolved-runner-");
        BatchExecutionCoordinator coordinator = new BatchExecutionCoordinator(
                executor, new RecordingOperations() {
                    @Override public RunStatus execute(long runId) {
                        throw new UnresolvedRunningExecutionException("owner may be stale");
                    }
                });

        assertThrows(UnresolvedRunningExecutionException.class,
                () -> coordinator.execute(UUID.randomUUID(), List.of(1L)));
    }

    @Test
    void cooperativeCancelLetsStartedCaseFinishAndCancelsUnstartedCases() throws Exception {
        ThreadPoolExecutor executor = executor(1, 1, 2, "cancel-runner-");
        RecordingOperations operations = new RecordingOperations();
        operations.blockingRunId = 1L;
        BatchExecutionCoordinator coordinator =
                new BatchExecutionCoordinator(executor, operations);
        UUID batchId = UUID.randomUUID();
        FutureTask<BatchExecutionResult> batch = new FutureTask<>(() -> coordinator.execute(
                batchId, List.of(1L, 2L, 3L, 4L)));
        Thread coordinatorThread = Thread.ofPlatform()
                .name("batch-test-coordinator")
                .start(batch);
        assertTrue(operations.started.await(5, TimeUnit.SECONDS));

        assertEquals(BatchCancelResult.REQUESTED, coordinator.requestCancel(batchId));
        assertEquals(BatchCancelResult.ALREADY_REQUESTED, coordinator.requestCancel(batchId));
        assertFalse(batch.isDone());
        operations.release.countDown();
        BatchExecutionResult result = batch.get(5, TimeUnit.SECONDS);
        coordinatorThread.join(5000);

        assertEquals(RunStatus.CANCELLED, result.status());
        assertTrue(result.cancelRequested());
        assertEquals(List.of(1L), operations.executed);
        assertEquals(List.of(2L, 3L, 4L), operations.cancelled.stream().sorted().toList());
        assertEquals(RunStatus.SUCCESS, result.caseOutcomes().getFirst().status());
        assertTrue(result.caseOutcomes().subList(1, 4).stream()
                .allMatch(outcome -> outcome.status() == RunStatus.CANCELLED));
        assertEquals(BatchCancelResult.TERMINAL, coordinator.requestCancel(batchId));
    }

    @Test
    void unknownCancelDoesNotCreateBatch() {
        ThreadPoolExecutor executor = executor(1, 1, 1, "unknown-runner-");
        BatchExecutionCoordinator coordinator =
                new BatchExecutionCoordinator(executor, new RecordingOperations());

        assertEquals(BatchCancelResult.NOT_FOUND,
                coordinator.requestCancel(UUID.randomUUID()));
    }

    @Test
    void invalidExecutorPropertiesAndDuplicateRunIdsAreRejected() {
        assertThrows(IllegalArgumentException.class, () -> new RunnerExecutorProperties(
                2, 1, Duration.ZERO, 1, "runner-"));
        ThreadPoolExecutor executor = executor(1, 1, 1, "validation-runner-");
        BatchExecutionCoordinator coordinator =
                new BatchExecutionCoordinator(executor, new RecordingOperations());
        assertThrows(IllegalArgumentException.class, () -> coordinator.execute(
                UUID.randomUUID(), List.of(1L, 1L)));
    }

    @Test
    void projectionAndNotificationFailureNeverChangesOrRepeatsExecution() {
        ThreadPoolExecutor executor=executor(1,1,1,"projection-runner-");
        RecordingOperations operations=new RecordingOperations();
        TaskProgressStore failing=new TaskProgressStore(){
            public TaskProgressSnapshot create(long p,long t,long r,int total){throw new IllegalStateException("redis down");}
            public TaskProgressSnapshot caseStarted(long p,long r){throw new IllegalStateException("redis down");}
            public TaskProgressSnapshot caseCompleted(long p,long r,RunStatus s){throw new IllegalStateException("redis down");}
            public TaskProgressSnapshot terminal(long p,long r,RunStatus s){throw new IllegalStateException("redis down");}
            public Optional<TaskProgressSnapshot> find(long p,long r){throw new IllegalStateException("redis down");}
        };
        BatchExecutionCoordinator coordinator=new BatchExecutionCoordinator(executor,operations,
                failing,TaskProgressListener.noop());

        BatchExecutionResult result=coordinator.execute(UUID.randomUUID(),List.of(1L),
                new BatchProgressIdentity(101,201,301));

        assertEquals(RunStatus.SUCCESS,result.status());
        assertEquals(List.of(1L),operations.executed);
    }

    private void assertAggregate(Map<Long, RunStatus> statuses, RunStatus expected) {
        ThreadPoolExecutor executor = executor(2, 2, 2, "aggregate-runner-");
        RecordingOperations operations = new RecordingOperations();
        operations.statuses.putAll(statuses);
        BatchExecutionCoordinator coordinator =
                new BatchExecutionCoordinator(executor, operations);

        BatchExecutionResult result = coordinator.execute(
                UUID.randomUUID(), List.of(1L, 2L, 3L));

        assertEquals(expected, result.status());
        assertEquals(3, operations.executed.size());
    }

    private ThreadPoolExecutor executor(
            int core, int maximum, int queueCapacity, String prefix) {
        ThreadPoolExecutor executor = RunnerExecutorFactory.create(new RunnerExecutorProperties(
                core, maximum, Duration.ofSeconds(1), queueCapacity, prefix));
        executors.add(executor);
        return executor;
    }

    private static void await(CountDownLatch latch) {
        try {
            latch.await();
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(exception);
        }
    }

    private static void awaitAndFinish(CountDownLatch latch, CountDownLatch finished) {
        try {
            latch.await();
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
        } finally {
            finished.countDown();
        }
    }

    private static class RecordingOperations
            implements BatchExecutionCoordinator.CaseOperations {
        private final Map<Long, RunStatus> statuses = new ConcurrentHashMap<>();
        private final List<Long> executed = java.util.Collections.synchronizedList(
                new ArrayList<>());
        private final List<Long> cancelled = java.util.Collections.synchronizedList(
                new ArrayList<>());
        private final List<Long> failedBeforeStart = java.util.Collections.synchronizedList(
                new ArrayList<>());
        private final List<String> threadNames = java.util.Collections.synchronizedList(
                new ArrayList<>());
        private final AtomicInteger concurrency = new AtomicInteger();
        private final AtomicInteger maxConcurrency = new AtomicInteger();
        private final CountDownLatch started = new CountDownLatch(1);
        private final CountDownLatch release = new CountDownLatch(1);
        private volatile long delayMillis;
        private volatile Long throwingRunId;
        private volatile Long blockingRunId;

        @Override
        public RunStatus execute(long runId) {
            executed.add(runId);
            threadNames.add(Thread.currentThread().getName());
            int current = concurrency.incrementAndGet();
            maxConcurrency.accumulateAndGet(current, Math::max);
            started.countDown();
            try {
                if (Long.valueOf(runId).equals(blockingRunId)) {
                    await(release);
                }
                if (delayMillis > 0) {
                    Thread.sleep(delayMillis);
                }
                if (Long.valueOf(runId).equals(throwingRunId)) {
                    throw new IllegalStateException("unexpected case failure");
                }
                return statuses.getOrDefault(runId, RunStatus.SUCCESS);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(exception);
            } finally {
                concurrency.decrementAndGet();
            }
        }

        @Override
        public RunStatus cancelBeforeStart(long runId) {
            cancelled.add(runId);
            return statuses.compute(runId, (ignored, status) ->
                    status != null && status.isTerminal() ? status : RunStatus.CANCELLED);
        }

        @Override
        public RunStatus failBeforeStart(long runId, Throwable cause) {
            failedBeforeStart.add(runId);
            statuses.put(runId, RunStatus.EXECUTION_FAILED);
            return RunStatus.EXECUTION_FAILED;
        }
    }
}
