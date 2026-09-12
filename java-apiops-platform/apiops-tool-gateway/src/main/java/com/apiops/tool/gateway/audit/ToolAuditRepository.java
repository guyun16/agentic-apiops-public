package com.apiops.tool.gateway.audit;

import com.apiops.tool.gateway.Audit;

import java.util.Optional;

/** Durable storage boundary for Java-owned Tool Gateway audit facts. */
public interface ToolAuditRepository {

    void save(Audit.AuditEvent event);

    Optional<Audit.AuditEvent> findByToolCallId(long projectId, String toolCallId);
}
