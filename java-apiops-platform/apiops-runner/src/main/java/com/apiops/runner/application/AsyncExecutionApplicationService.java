package com.apiops.runner.application;

import com.apiops.runner.application.AsyncExecutionResult.Disposition;
import com.apiops.runner.messaging.BatchExecutionMessage;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.ExecutionFactRepository.BatchExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.BatchMember;
import com.apiops.runner.progress.BatchProgressIdentity;
import com.apiops.runner.state.RunStatus;

import java.time.Clock;
import java.util.List;
import java.util.Objects;

/** Loads one durable batch trigger and delegates its persisted members to the coordinator. */
public final class AsyncExecutionApplicationService {

    private final ExecutionFactRepository repository;
    private final BatchExecutionCoordinator coordinator;
    private final Clock clock;

    public AsyncExecutionApplicationService(
            ExecutionFactRepository repository, BatchExecutionCoordinator coordinator) {
        this(repository, coordinator, Clock.systemUTC());
    }

    AsyncExecutionApplicationService(
            ExecutionFactRepository repository,
            BatchExecutionCoordinator coordinator,
            Clock clock) {
        this.repository = Objects.requireNonNull(repository);
        this.coordinator = Objects.requireNonNull(coordinator);
        this.clock = Objects.requireNonNull(clock);
    }

    public AsyncExecutionResult execute(BatchExecutionMessage message) {
        validate(message);
        BatchExecutionFacts batch = findBatch(message);
        if (batch.status().isTerminal()) {
            return new AsyncExecutionResult(Disposition.DUPLICATE_TERMINAL, batch.status());
        }
        if (!repository.tryClaimBatch(message.projectId(), message.batchId(), clock.instant())) {
            BatchExecutionFacts current = findBatch(message);
            if (current.status().isTerminal()) {
                return new AsyncExecutionResult(
                        Disposition.DUPLICATE_TERMINAL, current.status());
            }
            throw new UnresolvedRunningExecutionException(
                    "Execution batch is RUNNING; its owner may be active or stale: "
                            + message.batchId());
        }

        BatchMember anchor = batch.members().getFirst();
        BatchExecutionResult result;
        try {
            result = coordinator.execute(
                    message.batchId(),
                    batch.members().stream().map(BatchMember::runId).toList(),
                    new BatchProgressIdentity(
                            message.projectId(), anchor.taskId(), anchor.runId()),
                    () -> repository.findBatch(message.projectId(), message.batchId())
                            .map(BatchExecutionFacts::cancelRequested)
                            .orElse(true));
        } catch (RuntimeException failure) {
            if (failure instanceof UnresolvedRunningExecutionException unresolved) {
                throw unresolved;
            }
            RunStatus terminal = complete(message, RunStatus.EXECUTION_FAILED, failure);
            coordinator.forget(message.batchId());
            return new AsyncExecutionResult(Disposition.EXECUTED, terminal);
        }
        RunStatus terminal = complete(message, result.status(), null);
        coordinator.forget(message.batchId());
        return new AsyncExecutionResult(Disposition.EXECUTED, terminal);
    }

    private RunStatus complete(
            BatchExecutionMessage message, RunStatus status, RuntimeException cause) {
        if (!repository.completeBatch(
                message.projectId(), message.batchId(), status, clock.instant())) {
            String detail = "Execution batch could not be persisted terminal: "
                    + message.batchId();
            if (cause == null) throw new UnresolvedRunningExecutionException(detail);
            throw new UnresolvedRunningExecutionException(detail, cause);
        }
        return repository.findBatch(message.projectId(), message.batchId())
                .map(BatchExecutionFacts::status)
                .filter(RunStatus::isTerminal)
                .orElseThrow(() -> new UnresolvedRunningExecutionException(
                        "Execution batch terminal state could not be confirmed: "
                                + message.batchId()));
    }

    private BatchExecutionFacts findBatch(BatchExecutionMessage message) {
        return repository.findBatch(message.projectId(), message.batchId())
                .filter(batch -> !batch.members().isEmpty())
                .orElseThrow(() -> new PermanentExecutionMessageException(
                        "message references an execution batch that does not exist"));
    }

    private void validate(BatchExecutionMessage message) {
        if (message == null) throw permanent("message must not be null");
        if (!BatchExecutionMessage.CURRENT_VERSION.equals(message.messageVersion())) {
            throw permanent("unsupported messageVersion: " + message.messageVersion());
        }
        if (message.messageId() == null) throw permanent("messageId must not be null");
        if (message.batchId() == null) throw permanent("batchId must not be null");
        requirePositive(message.projectId(), "projectId");
        requirePositive(message.requestedBy(), "requestedBy");
        if (message.traceId() == null || message.traceId().isBlank()) {
            throw permanent("traceId must not be blank");
        }
        if (message.createdAt() == null) throw permanent("createdAt must not be null");
    }

    private void requirePositive(long value, String field) {
        if (value <= 0) throw permanent(field + " must be positive");
    }

    private PermanentExecutionMessageException permanent(String message) {
        return new PermanentExecutionMessageException(message);
    }
}
