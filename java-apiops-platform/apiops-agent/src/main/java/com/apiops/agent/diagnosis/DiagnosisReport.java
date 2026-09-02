package com.apiops.agent.diagnosis;

import java.util.List;
import java.util.Objects;

/** Model reasoning output; it is never written into execution facts. */
public record DiagnosisReport(
        String schemaVersion,
        String reportId,
        String agentRunId,
        long projectId,
        long runId,
        String failureType,
        String summary,
        List<RootCauseHypothesis> rootCauseHypotheses,
        boolean sufficientEvidence,
        List<String> limitations,
        List<String> recommendedChecks,
        String traceId
) {

    public DiagnosisReport {
        schemaVersion = requireText(schemaVersion, "schemaVersion");
        reportId = requireText(reportId, "reportId");
        agentRunId = requireText(agentRunId, "agentRunId");
        failureType = requireText(failureType, "failureType");
        summary = requireText(summary, "summary");
        traceId = requireText(traceId, "traceId");
        if (projectId <= 0 || runId <= 0) {
            throw new IllegalArgumentException("projectId and runId must be positive");
        }
        rootCauseHypotheses = List.copyOf(Objects.requireNonNull(
                rootCauseHypotheses, "rootCauseHypotheses must not be null"));
        limitations = textList(limitations, "limitations");
        recommendedChecks = textList(recommendedChecks, "recommendedChecks");
    }

    private static List<String> textList(List<String> values, String field) {
        Objects.requireNonNull(values, field + " must not be null");
        List<String> copy = List.copyOf(values);
        if (copy.stream().anyMatch(value -> value == null || value.isBlank())) {
            throw new IllegalArgumentException(field + " must contain non-blank text");
        }
        return copy;
    }

    private static String requireText(String value, String field) {
        Objects.requireNonNull(value, field + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
        return value;
    }
}
