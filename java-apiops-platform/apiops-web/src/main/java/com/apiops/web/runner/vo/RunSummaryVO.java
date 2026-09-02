package com.apiops.web.runner.vo;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.state.RunStatus;

import java.time.Duration;
import java.time.Instant;
import java.util.Objects;

/** Lightweight project-scoped read model for the Runs explorer. */
public record RunSummaryVO(
        long runId,
        String caseId,
        String apiId,
        String testCaseName,
        RunStatus status,
        FailureType failureType,
        Instant createdAt,
        Instant startedAt,
        Instant finishedAt,
        Long durationMs
) {

    public RunSummaryVO {
        if (runId <= 0) {
            throw new IllegalArgumentException("runId must be positive");
        }
        Objects.requireNonNull(caseId, "caseId must not be null");
        Objects.requireNonNull(apiId, "apiId must not be null");
        Objects.requireNonNull(testCaseName, "testCaseName must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(failureType, "failureType must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }

    public static RunSummaryVO from(ExecutionFactRepository.RunSummary summary) {
        Objects.requireNonNull(summary, "summary must not be null");
        return new RunSummaryVO(
                summary.runId(),
                summary.caseId(),
                summary.apiId(),
                summary.testCaseName(),
                summary.status(),
                summary.failureType(),
                summary.createdAt(),
                summary.startedAt(),
                summary.finishedAt(),
                durationMs(summary.startedAt(), summary.finishedAt()));
    }

    private static Long durationMs(Instant startedAt, Instant finishedAt) {
        return startedAt == null || finishedAt == null
                ? null
                : Duration.between(startedAt, finishedAt).toMillis();
    }
}
