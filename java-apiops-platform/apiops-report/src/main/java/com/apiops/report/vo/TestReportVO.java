package com.apiops.report.vo;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.assertion.AssertionResult;
import com.apiops.runner.state.RunStatus;

import java.time.Instant;
import java.util.List;
import java.util.Objects;

/** Read model assembled from persisted runner execution facts. */
public record TestReportVO(
        long projectId,
        long taskId,
        long runId,
        String reportId,
        RunStatus status,
        Instant startedAt,
        Instant finishedAt,
        Summary summary,
        List<CaseReport> cases
) {
    /**
     * Keeps compatibility for internal callers that construct the read model
     * positionally while making the report identity a Java-owned value.
     */
    public TestReportVO(
            long projectId,
            long taskId,
            long runId,
            RunStatus status,
            Instant startedAt,
            Instant finishedAt,
            Summary summary,
            List<CaseReport> cases) {
        this(projectId, taskId, runId, reportIdForRun(runId), status,
                startedAt, finishedAt, summary, cases);
    }

    public TestReportVO {
        Objects.requireNonNull(reportId, "reportId must not be null");
        if (reportId.isBlank()) {
            throw new IllegalArgumentException("reportId must not be blank");
        }
        if (!reportId.equals(reportIdForRun(runId))) {
            throw new IllegalArgumentException("reportId must identify this run");
        }
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(startedAt, "startedAt must not be null");
        Objects.requireNonNull(summary, "summary must not be null");
        cases = List.copyOf(Objects.requireNonNull(cases, "cases must not be null"));
    }

    /** Stable, namespaced identity for the report read model of one run. */
    public static String reportIdForRun(long runId) {
        if (runId <= 0) {
            throw new IllegalArgumentException("runId must be positive");
        }
        return "report:" + runId;
    }

    public record Summary(
            int totalCases,
            int totalSteps,
            int totalAssertions,
            int passedAssertions,
            int failedAssertions,
            FailureType failureType
    ) {
        public Summary {
            Objects.requireNonNull(failureType, "failureType must not be null");
        }
    }

    public record CaseReport(
            String caseId,
            RunStatus status,
            FailureType failureType,
            List<StepReport> steps
    ) {
        public CaseReport {
            Objects.requireNonNull(caseId, "caseId must not be null");
            Objects.requireNonNull(status, "status must not be null");
            Objects.requireNonNull(failureType, "failureType must not be null");
            steps = List.copyOf(Objects.requireNonNull(steps, "steps must not be null"));
        }
    }

    public record StepReport(
            String stepId,
            RunStatus status,
            FailureType failureType,
            Integer responseStatusCode,
            Long durationMs,
            List<AssertionResult> assertionResults
    ) {
        public StepReport {
            Objects.requireNonNull(stepId, "stepId must not be null");
            Objects.requireNonNull(status, "status must not be null");
            Objects.requireNonNull(failureType, "failureType must not be null");
            assertionResults = List.copyOf(Objects.requireNonNull(
                    assertionResults, "assertionResults must not be null"));
        }
    }
}
