package com.apiops.runner.persistence;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.execution.StepResult;
import com.apiops.runner.state.RunStatus;

import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/** Persistence boundary for runner execution facts. */
public interface ExecutionFactRepository {

    PreparedBatch prepareBatch(
            UUID batchId,
            long projectId,
            long requestedBy,
            List<PreparedRun> runs);

    Optional<BatchExecutionFacts> findBatch(long projectId, UUID batchId);

    boolean tryClaimBatch(long projectId, UUID batchId, Instant startedAt);

    boolean requestBatchCancel(long projectId, UUID batchId);

    boolean completeBatch(
            long projectId,
            UUID batchId,
            RunStatus terminalStatus,
            Instant finishedAt);

    long prepareRun(
            long projectId,
            String caseId,
            String apiId,
            String name,
            String testCaseDslJson);

    long saveTask(
            long projectId,
            String caseId,
            String apiId,
            String name,
            String testCaseDslJson);

    long saveRun(
            long projectId,
            long taskId,
            RunStatus status,
            FailureType failureType,
            Instant startedAt,
            Instant finishedAt);

    Optional<RunExecutionInput> findExecutionInput(long runId);

    boolean tryClaim(long projectId, long runId, Instant startedAt);

    /** Atomically closes an unstarted run as cancelled. */
    boolean cancelPendingRun(long projectId, long runId, Instant finishedAt);

    boolean completeRun(
            long runId,
            RunStatus terminalStatus,
            FailureType failureType,
            Instant finishedAt);

    long saveCaseResult(
            long projectId,
            long runId,
            String caseId,
            RunStatus status,
            FailureType failureType,
            Instant startedAt,
            Instant finishedAt);

    long saveStepResult(
            long projectId,
            long runId,
            long caseResultId,
            String stepId,
            StepResult result);

    /** Persists one TestCase outcome and closes its RUNNING run atomically. */
    void saveExecutionOutcome(RunExecutionOutcome outcome);

    /** Returns the bounded, project-scoped Run summaries used by the Runs explorer. */
    List<RunSummary> findRecentRunSummaries(long projectId);

    Optional<RunExecutionFacts> findRun(long projectId, long runId);

    record RunSummary(
            long runId,
            String caseId,
            String apiId,
            String testCaseName,
            RunStatus status,
            FailureType failureType,
            Instant createdAt,
            Instant startedAt,
            Instant finishedAt
    ) {
        public RunSummary {
            Objects.requireNonNull(caseId, "caseId must not be null");
            Objects.requireNonNull(apiId, "apiId must not be null");
            Objects.requireNonNull(testCaseName, "testCaseName must not be null");
            Objects.requireNonNull(status, "status must not be null");
            Objects.requireNonNull(failureType, "failureType must not be null");
            Objects.requireNonNull(createdAt, "createdAt must not be null");
        }
    }

    record PreparedRun(
            String caseId,
            String apiId,
            String name,
            String testCaseDslJson
    ) {
        public PreparedRun {
            Objects.requireNonNull(caseId, "caseId must not be null");
            Objects.requireNonNull(apiId, "apiId must not be null");
            Objects.requireNonNull(name, "name must not be null");
            Objects.requireNonNull(testCaseDslJson, "testCaseDslJson must not be null");
        }
    }

    record BatchMember(long taskId, long runId) {
    }

    record PreparedBatch(
            UUID batchId,
            long projectId,
            List<BatchMember> members
    ) {
        public PreparedBatch {
            Objects.requireNonNull(batchId, "batchId must not be null");
            members = List.copyOf(Objects.requireNonNull(members, "members must not be null"));
        }
    }

    record BatchExecutionFacts(
            UUID batchId,
            long projectId,
            long requestedBy,
            RunStatus status,
            boolean cancelRequested,
            Instant startedAt,
            Instant finishedAt,
            List<BatchMember> members
    ) {
        public BatchExecutionFacts {
            Objects.requireNonNull(batchId, "batchId must not be null");
            Objects.requireNonNull(status, "status must not be null");
            members = List.copyOf(Objects.requireNonNull(members, "members must not be null"));
        }
    }

    record RunExecutionInput(
            long projectId,
            long taskId,
            long runId,
            String caseId,
            String apiId,
            String testCaseDslJson
    ) {
        public RunExecutionInput {
            Objects.requireNonNull(caseId, "caseId must not be null");
            Objects.requireNonNull(apiId, "apiId must not be null");
            Objects.requireNonNull(testCaseDslJson, "testCaseDslJson must not be null");
        }
    }

    record RunExecutionOutcome(
            long projectId,
            long runId,
            String caseId,
            RunStatus status,
            FailureType failureType,
            Instant startedAt,
            Instant finishedAt,
            List<StepExecutionOutcome> stepResults
    ) {
        public RunExecutionOutcome {
            Objects.requireNonNull(caseId, "caseId must not be null");
            Objects.requireNonNull(status, "status must not be null");
            Objects.requireNonNull(failureType, "failureType must not be null");
            Objects.requireNonNull(startedAt, "startedAt must not be null");
            Objects.requireNonNull(finishedAt, "finishedAt must not be null");
            stepResults = List.copyOf(
                    Objects.requireNonNull(stepResults, "stepResults must not be null"));
        }
    }

    record StepExecutionOutcome(String stepId, StepResult result) {
        public StepExecutionOutcome {
            Objects.requireNonNull(stepId, "stepId must not be null");
            Objects.requireNonNull(result, "result must not be null");
        }
    }

    record RunExecutionFacts(
            long projectId,
            long taskId,
            long runId,
            String caseId,
            String apiId,
            String taskName,
            RunStatus status,
            FailureType failureType,
            Instant startedAt,
            Instant finishedAt,
            List<CaseExecutionFacts> caseResults
    ) {
        public RunExecutionFacts {
            Objects.requireNonNull(caseId, "caseId must not be null");
            Objects.requireNonNull(apiId, "apiId must not be null");
            Objects.requireNonNull(taskName, "taskName must not be null");
            Objects.requireNonNull(status, "status must not be null");
            Objects.requireNonNull(failureType, "failureType must not be null");
            caseResults = List.copyOf(
                    Objects.requireNonNull(caseResults, "caseResults must not be null"));
        }
    }

    record CaseExecutionFacts(
            long projectId,
            long runId,
            long caseResultId,
            String caseId,
            RunStatus status,
            FailureType failureType,
            Instant startedAt,
            Instant finishedAt,
            List<StepExecutionFacts> stepResults
    ) {
        public CaseExecutionFacts {
            Objects.requireNonNull(caseId, "caseId must not be null");
            Objects.requireNonNull(status, "status must not be null");
            Objects.requireNonNull(failureType, "failureType must not be null");
            Objects.requireNonNull(startedAt, "startedAt must not be null");
            stepResults = List.copyOf(
                    Objects.requireNonNull(stepResults, "stepResults must not be null"));
        }
    }

    /** Stored response facts intentionally exclude raw headers and body. */
    record StepExecutionFacts(
            long projectId,
            long runId,
            long caseResultId,
            long stepResultId,
            String stepId,
            RunStatus status,
            FailureType failureType,
            String assertionResultsJson,
            Integer responseStatusCode,
            Long durationMs,
            Instant createdAt
    ) {
        public StepExecutionFacts {
            Objects.requireNonNull(stepId, "stepId must not be null");
            Objects.requireNonNull(status, "status must not be null");
            Objects.requireNonNull(failureType, "failureType must not be null");
            Objects.requireNonNull(assertionResultsJson, "assertionResultsJson must not be null");
            Objects.requireNonNull(createdAt, "createdAt must not be null");
        }
    }
}
