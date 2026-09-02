package com.apiops.tool.gateway;

import java.util.Objects;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.Consumer;

/** Audit sink that receives only a sanitized summary, never raw tool output. */
public final class Audit {

    private final Consumer<AuditEvent> sink;
    private final List<AuditEvent> inMemoryEvents;

    public Audit() {
        this.inMemoryEvents = new CopyOnWriteArrayList<>();
        this.sink = inMemoryEvents::add;
    }

    public Audit(Consumer<AuditEvent> sink) {
        this.sink = Objects.requireNonNull(sink, "sink must not be null");
        this.inMemoryEvents = null;
    }

    public void record(AuditEvent event) {
        sink.accept(Objects.requireNonNull(event, "event must not be null"));
    }

    /** Returns the default in-memory facts; externally supplied sinks return an empty view. */
    public List<AuditEvent> events() {
        return inMemoryEvents == null ? List.of() : List.copyOf(inMemoryEvents);
    }

    public record AuditEvent(
            String toolCallId,
            long projectId,
            String toolName,
            AuditStatus status,
            String violationCode,
            String sanitizedSummary,
            long latencyNanos,
            Long requestedTargetProjectId
    ) {

        public AuditEvent(
                String toolCallId,
                long projectId,
                String toolName,
                AuditStatus status,
                String violationCode,
                String sanitizedSummary,
                long latencyNanos
        ) {
            this(toolCallId, projectId, toolName, status, violationCode, sanitizedSummary,
                    latencyNanos, null);
        }

        /**
         * Compatibility constructor for observational callers that do not have a
         * trusted project context. Gateway-produced events use the full constructor.
         */
        public AuditEvent(
                String toolCallId,
                String toolName,
                AuditStatus status,
                String sanitizedSummary,
                long latencyNanos
        ) {
            this(toolCallId, 0L, toolName, status, "UNSPECIFIED", sanitizedSummary,
                    latencyNanos, null);
        }

        public AuditEvent {
            requireText(toolCallId, "toolCallId");
            if (projectId < 0) {
                throw new IllegalArgumentException("projectId must not be negative");
            }
            requireText(toolName, "toolName");
            Objects.requireNonNull(status, "status must not be null");
            requireText(violationCode, "violationCode");
            requireText(sanitizedSummary, "sanitizedSummary");
            if (latencyNanos < 0) {
                throw new IllegalArgumentException("latencyNanos must not be negative");
            }
            if (requestedTargetProjectId != null && requestedTargetProjectId < 1) {
                throw new IllegalArgumentException(
                        "requestedTargetProjectId must be positive when present");
            }
        }

        private static void requireText(String value, String name) {
            Objects.requireNonNull(value, name + " must not be null");
            if (value.isBlank()) {
                throw new IllegalArgumentException(name + " must not be blank");
            }
        }
    }
}
