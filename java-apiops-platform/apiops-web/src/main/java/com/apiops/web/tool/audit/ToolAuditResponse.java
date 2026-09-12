package com.apiops.web.tool.audit;

import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.AuditStatus;

/** Public projection of the already-sanitized Java Tool Audit fact. */
public record ToolAuditResponse(
        String toolCallId,
        long projectId,
        String toolName,
        AuditStatus status,
        String violationCode,
        String sanitizedSummary,
        long latencyNanos,
        Long requestedTargetProjectId
) {
    static ToolAuditResponse from(Audit.AuditEvent event) {
        return new ToolAuditResponse(
                event.toolCallId(),
                event.projectId(),
                event.toolName(),
                event.status(),
                event.violationCode(),
                event.sanitizedSummary(),
                event.latencyNanos(),
                event.requestedTargetProjectId());
    }
}
