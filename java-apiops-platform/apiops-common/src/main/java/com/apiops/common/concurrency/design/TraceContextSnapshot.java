package com.apiops.common.concurrency.design;

public record TraceContextSnapshot(
        String traceId,
        String requestId,
        String taskId,
        String caseId,
        String toolCallId
) {
}