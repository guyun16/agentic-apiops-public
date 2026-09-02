package com.apiops.runner.messaging;

import java.time.Instant;
import java.util.UUID;

/** Immutable RabbitMQ trigger that references authoritative persisted execution input. */
public record BatchExecutionMessage(
        String messageVersion,
        UUID messageId,
        long projectId,
        UUID batchId,
        long requestedBy,
        String traceId,
        Instant createdAt
) {
    public static final String CURRENT_VERSION = "1.0";
}
