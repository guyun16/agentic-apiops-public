package com.apiops.runner.application;

import com.apiops.runner.application.BatchCaseOutcome.Disposition;
import com.apiops.runner.state.RunStatus;
import com.apiops.runner.progress.BatchProgressIdentity;
import com.apiops.runner.progress.TaskProgressListener;
import com.apiops.runner.progress.TaskProgressSnapshot;
import com.apiops.runner.progress.TaskProgressStore;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.BooleanSupplier;

/** Coordinates independent persisted TestCase runs without changing the Stage 8 boundary. */
public final class BatchExecutionCoordinator {

    private final ThreadPoolExecutor runnerExecutor;
    private final CaseOperations caseOperations;
    private final BatchExecutionAggregator aggregator;
    private final int submissionWindow;
    private final TaskProgressStore progressStore;
    private final TaskProgressListener progressListener;
    private final Map<UUID, BatchContext> batches = new ConcurrentHashMap<>();

    public BatchExecutionCoordinator(
            ThreadPoolExecutor runnerExecutor,
            RunExecutionService runExecutionService) {
        this(runnerExecutor, new RunExecutionCaseOperations(runExecutionService), null,
                TaskProgressListener.noop());
    }

    public BatchExecutionCoordinator(ThreadPoolExecutor runnerExecutor,
            RunExecutionService runExecutionService, TaskProgressStore progressStore,
            TaskProgressListener progressListener) {
        this(runnerExecutor, new RunExecutionCaseOperations(runExecutionService), progressStore,
                progressListener);
    }

    BatchExecutionCoordinator(
            ThreadPoolExecutor runnerExecutor,
            CaseOperations caseOperations) {
        this(runnerExecutor, caseOperations, null, TaskProgressListener.noop());
    }

    BatchExecutionCoordinator(ThreadPoolExecutor runnerExecutor, CaseOperations caseOperations,
            TaskProgressStore progressStore, TaskProgressListener progressListener) {
        this.runnerExecutor = Objects.requireNonNull(
                runnerExecutor, "runnerExecutor must not be null");
        this.caseOperations = Objects.requireNonNull(
                caseOperations, "caseOperations must not be null");
        this.aggregator = new BatchExecutionAggregator();
        this.progressStore = progressStore;
        this.progressListener = Objects.requireNonNull(progressListener);
        this.submissionWindow = runnerExecutor.getMaximumPoolSize();
    }

    /**
     * Runs one batch on the caller's coordination thread. Case work always uses runnerExecutor.
     */
    public BatchExecutionResult execute(UUID batchId, List<Long> runIds) {
        return executeInternal(batchId, runIds, null);
    }

    public BatchExecutionResult execute(UUID batchId, List<Long> runIds,
            BatchProgressIdentity progressIdentity) {
        Objects.requireNonNull(progressIdentity, "progressIdentity must not be null");
        return executeInternal(batchId, runIds, progressIdentity, () -> false);
    }

    public BatchExecutionResult execute(UUID batchId, List<Long> runIds,
            BatchProgressIdentity progressIdentity, BooleanSupplier cancellationRequested) {
        Objects.requireNonNull(progressIdentity, "progressIdentity must not be null");
        return executeInternal(batchId, runIds, progressIdentity,
                Objects.requireNonNull(cancellationRequested));
    }

    private BatchExecutionResult executeInternal(UUID batchId, List<Long> runIds,
            BatchProgressIdentity progressIdentity) {
        return executeInternal(batchId, runIds, progressIdentity, () -> false);
    }

    private BatchExecutionResult executeInternal(UUID batchId, List<Long> runIds,
            BatchProgressIdentity progressIdentity, BooleanSupplier cancellationRequested) {
        Objects.requireNonNull(batchId, "batchId must not be null");
        List<Long> cases = validatedRunIds(runIds);
        BatchContext context = new BatchContext();
        if (batches.putIfAbsent(batchId, context) != null) {
            throw new IllegalStateException("Batch already exists: " + batchId);
        }
        if (cancellationRequested.getAsBoolean()) context.cancelRequested.set(true);
        safeProgress(() -> progressStore.create(progressIdentity.projectId(),
                progressIdentity.taskId(), progressIdentity.runId(), cases.size()), false,
                progressIdentity);

        List<IndexedFuture> active = new ArrayList<>();
        List<CompletableFuture<IndexedOutcome>> allFutures = new ArrayList<>();
        BatchCaseOutcome[] outcomes = new BatchCaseOutcome[cases.size()];
        int next = 0;
        try {
            while (next < cases.size() || !active.isEmpty()) {
                if (cancellationRequested.getAsBoolean()) {
                    context.cancelRequested.set(true);
                }
                while (next < cases.size()
                        && active.size() < submissionWindow
                        && !context.cancelRequested.get()) {
                    long runId = cases.get(next);
                    CompletableFuture<IndexedOutcome> future = submitCase(
                            context, next, runId, progressIdentity);
                    active.add(new IndexedFuture(future));
                    allFutures.add(future);
                    next++;
                }

                if (context.cancelRequested.get() && next < cases.size()) {
                    for (; next < cases.size(); next++) {
                        long runId = cases.get(next);
                        IndexedOutcome cancelled = new IndexedOutcome(
                                next,
                                cancelBeforeStart(runId));
                        outcomes[next] = cancelled.outcome();
                        recordCompletion(progressIdentity, cancelled.outcome());
                    }
                }

                if (!active.isEmpty()) {
                    try {
                        CompletableFuture.anyOf(active.stream()
                                        .map(IndexedFuture::future)
                                        .toArray(CompletableFuture[]::new))
                                .join();
                    } catch (java.util.concurrent.CompletionException failure) {
                        if (failure.getCause() instanceof UnresolvedRunningExecutionException unresolved) {
                            throw unresolved;
                        }
                        throw failure;
                    }
                    for (int index = active.size() - 1; index >= 0; index--) {
                        IndexedFuture candidate = active.get(index);
                        if (candidate.future().isDone()) {
                            IndexedOutcome completed = candidate.future().join();
                            outcomes[completed.index()] = completed.outcome();
                            recordCompletion(progressIdentity, completed.outcome());
                            active.remove(index);
                        }
                    }
                }
            }

            CompletableFuture.allOf(allFutures.toArray(CompletableFuture[]::new)).join();
            List<BatchCaseOutcome> caseOutcomes = List.of(outcomes);
            boolean cancellationOwned = context.cancelRequested.get()
                    || cancellationRequested.getAsBoolean();
            if (cancellationOwned) context.cancelRequested.set(true);
            BatchExecutionResult result = new BatchExecutionResult(
                    batchId,
                    aggregator.aggregate(cancellationOwned, caseOutcomes),
                    cancellationOwned,
                    caseOutcomes);
            safeProgress(() -> progressStore.terminal(progressIdentity.projectId(),
                    progressIdentity.runId(), result.status()), true, progressIdentity);
            context.terminal.set(true);
            return result;
        } finally {
            context.terminal.set(true);
        }
    }

    private void safeProgress(java.util.function.Supplier<TaskProgressSnapshot> update,
            boolean terminal, BatchProgressIdentity identity) {
        if (progressStore == null || identity == null) return;
        try {
            TaskProgressSnapshot snapshot = update.get();
            if (terminal) progressListener.terminal(snapshot);
            else progressListener.progress(snapshot);
        } catch (RuntimeException ignored) {
            // Projection/notification failure never changes authoritative execution facts.
        }
    }

    public BatchCancelResult requestCancel(UUID batchId) {
        Objects.requireNonNull(batchId, "batchId must not be null");
        BatchContext context = batches.get(batchId);
        if (context == null) {
            return BatchCancelResult.NOT_FOUND;
        }
        if (context.terminal.get()) {
            return BatchCancelResult.TERMINAL;
        }
        return context.cancelRequested.compareAndSet(false, true)
                ? BatchCancelResult.REQUESTED
                : BatchCancelResult.ALREADY_REQUESTED;
    }

    public void forget(UUID batchId) {
        batches.remove(Objects.requireNonNull(batchId, "batchId must not be null"));
    }

    private CompletableFuture<IndexedOutcome> submitCase(
            BatchContext context, int index, long runId,
            BatchProgressIdentity progressIdentity) {
        try {
            return CompletableFuture.supplyAsync(
                            () -> context.cancelRequested.get()
                                    ? cancelBeforeStart(runId)
                                    : executeCase(runId, progressIdentity),
                            runnerExecutor)
                    .handle((outcome, failure) -> failure == null
                            ? new IndexedOutcome(index, outcome)
                            : handleFailure(index, runId, failure));
        } catch (RejectedExecutionException rejection) {
            return CompletableFuture.completedFuture(new IndexedOutcome(
                    index,
                    rejected(runId, rejection)));
        }
    }

    private IndexedOutcome handleFailure(int index, long runId, Throwable failure) {
        Throwable cause = failure instanceof java.util.concurrent.CompletionException completion
                && completion.getCause() != null ? completion.getCause() : failure;
        if (cause instanceof UnresolvedRunningExecutionException unresolved) {
            throw unresolved;
        }
        return new IndexedOutcome(index, unexpectedFailure(runId, cause));
    }

    private BatchCaseOutcome executeCase(long runId, BatchProgressIdentity progressIdentity) {
        safeProgress(() -> progressStore.caseStarted(progressIdentity.projectId(),
                progressIdentity.runId()), false, progressIdentity);
        RunStatus status = caseOperations.execute(runId);
        return new BatchCaseOutcome(runId, status, Disposition.EXECUTED);
    }

    private void recordCompletion(BatchProgressIdentity identity, BatchCaseOutcome outcome) {
        safeProgress(() -> progressStore.caseCompleted(identity.projectId(), identity.runId(),
                outcome.status()), false, identity);
    }

    private BatchCaseOutcome cancelBeforeStart(long runId) {
        try {
            RunStatus status = caseOperations.cancelBeforeStart(runId);
            return new BatchCaseOutcome(
                    runId, status, Disposition.CANCELLED_BEFORE_START);
        } catch (RuntimeException cancellationFailure) {
            return unexpectedFailure(runId, cancellationFailure);
        }
    }

    private BatchCaseOutcome rejected(long runId, Throwable rejection) {
        try {
            RunStatus status = caseOperations.failBeforeStart(runId, rejection);
            return new BatchCaseOutcome(runId, status, Disposition.REJECTED);
        } catch (RuntimeException normalizationFailure) {
            rejection.addSuppressed(normalizationFailure);
            return new BatchCaseOutcome(
                    runId, RunStatus.EXECUTION_FAILED, Disposition.REJECTED);
        }
    }

    private BatchCaseOutcome unexpectedFailure(long runId, Throwable failure) {
        try {
            RunStatus status = caseOperations.failBeforeStart(runId, failure);
            return new BatchCaseOutcome(runId, status, Disposition.UNEXPECTED_FAILURE);
        } catch (RuntimeException normalizationFailure) {
            failure.addSuppressed(normalizationFailure);
            return new BatchCaseOutcome(
                    runId, RunStatus.EXECUTION_FAILED, Disposition.UNEXPECTED_FAILURE);
        }
    }

    private List<Long> validatedRunIds(List<Long> runIds) {
        Objects.requireNonNull(runIds, "runIds must not be null");
        if (runIds.isEmpty()) {
            throw new IllegalArgumentException("runIds must not be empty");
        }
        List<Long> values = List.copyOf(runIds);
        Set<Long> unique = new HashSet<>();
        for (Long runId : values) {
            if (runId == null || runId <= 0) {
                throw new IllegalArgumentException("runId must be positive");
            }
            if (!unique.add(runId)) {
                throw new IllegalArgumentException("runIds must not contain duplicates");
            }
        }
        return values;
    }

    interface CaseOperations {
        RunStatus execute(long runId);

        RunStatus cancelBeforeStart(long runId);

        RunStatus failBeforeStart(long runId, Throwable cause);
    }

    private record RunExecutionCaseOperations(RunExecutionService service)
            implements CaseOperations {
        private RunExecutionCaseOperations {
            Objects.requireNonNull(service, "service must not be null");
        }

        @Override
        public RunStatus execute(long runId) {
            return service.executeBatchCase(runId);
        }

        @Override
        public RunStatus cancelBeforeStart(long runId) {
            return service.cancelBeforeStart(runId);
        }

        @Override
        public RunStatus failBeforeStart(long runId, Throwable cause) {
            return service.failBeforeStart(runId);
        }
    }

    private static final class BatchContext {
        private final AtomicBoolean cancelRequested = new AtomicBoolean();
        private final AtomicBoolean terminal = new AtomicBoolean();
    }

    private record IndexedFuture(CompletableFuture<IndexedOutcome> future) {
    }

    private record IndexedOutcome(int index, BatchCaseOutcome outcome) {
    }
}
