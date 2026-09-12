package com.apiops.web.runner.vo;

import com.apiops.common.enums.FailureType;
import com.apiops.report.vo.TestReportVO;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.state.RunStatus;

import java.time.Duration;
import java.time.Instant;
import java.util.Objects;

/** Exact project-scoped Run read model assembled from persisted Runner facts. */
public record RunDetailVO(
        long projectId,
        long taskId,
        long runId,
        String caseId,
        String apiId,
        String testCaseName,
        RunStatus status,
        FailureType failureType,
        Instant startedAt,
        Instant finishedAt,
        Long durationMs,
        String reportId
) {

    public static RunDetailVO from(ExecutionFactRepository.RunExecutionFacts facts) {
        Objects.requireNonNull(facts, "facts must not be null");
        return new RunDetailVO(
                facts.projectId(),
                facts.taskId(),
                facts.runId(),
                facts.caseId(),
                facts.apiId(),
                facts.taskName(),
                facts.status(),
                facts.failureType(),
                facts.startedAt(),
                facts.finishedAt(),
                facts.startedAt() == null || facts.finishedAt() == null
                        ? null
                        : Duration.between(facts.startedAt(), facts.finishedAt()).toMillis(),
                facts.startedAt() == null ? null : TestReportVO.reportIdForRun(facts.runId()));
    }
}
