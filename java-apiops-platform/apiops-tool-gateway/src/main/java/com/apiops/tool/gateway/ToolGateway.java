package com.apiops.tool.gateway;

import com.apiops.common.enums.ToolStatus;
import com.apiops.common.tool.ToolResult;
import io.micrometer.core.instrument.MeterRegistry;

import java.time.Duration;
import java.util.Objects;
import java.util.UUID;

/** Public safety pipeline; the handler is an extension point, not a concrete Tool implementation. */
public final class ToolGateway implements AutoCloseable {

    private static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(1);
    private static final int DEFAULT_RUN_BUDGET = 16;
    private static final int DEFAULT_CONCURRENCY = 4;
    private static final int DEFAULT_RESULT_LIMIT = 4_096;

    private final ToolAuth toolAuth;
    private final ParamValidator paramValidator;
    private final ResourceGuard resourceGuard;
    private final ToolExecutionLimiter limiter;
    private final ToolRateLimiter rateLimiter;
    private final ResultSanitizer resultSanitizer;
    private final ResultLimiter resultLimiter;
    private final Audit audit;
    private final Metrics metrics;

    public ToolGateway(ToolAuth toolAuth) {
        this(toolAuth, null);
    }

    /** Creates the default pipeline with an optional application MeterRegistry. */
    public ToolGateway(ToolAuth toolAuth, MeterRegistry meterRegistry) {
        this(toolAuth, ResourceGuard.allowAll(), meterRegistry);
    }

    /** Creates the default pipeline with an application-supplied resource guard. */
    public ToolGateway(
            ToolAuth toolAuth,
            ResourceGuard resourceGuard,
            MeterRegistry meterRegistry) {
        this(toolAuth, resourceGuard, new Audit(), meterRegistry);
    }

    /** Creates the default pipeline with an application-supplied audit sink. */
    public ToolGateway(
            ToolAuth toolAuth,
            ResourceGuard resourceGuard,
            Audit audit,
            MeterRegistry meterRegistry) {
        this(
                toolAuth,
                new ParamValidator(),
                Objects.requireNonNull(resourceGuard, "resourceGuard must not be null"),
                new ToolExecutionLimiter(
                        DEFAULT_TIMEOUT, DEFAULT_RUN_BUDGET, DEFAULT_CONCURRENCY),
                ToolRateLimiter.defaultLimiter(),
                new ResultSanitizer(),
                new ResultLimiter(DEFAULT_RESULT_LIMIT),
                audit,
                new Metrics(meterRegistry)
        );
    }

    public ToolGateway(
            ToolAuth toolAuth,
            ParamValidator paramValidator,
            ResourceGuard resourceGuard,
            ToolExecutionLimiter limiter,
            ResultSanitizer resultSanitizer,
            ResultLimiter resultLimiter,
            Audit audit,
            Metrics metrics
    ) {
        this(
                toolAuth,
                paramValidator,
                resourceGuard,
                limiter,
                ToolRateLimiter.defaultLimiter(),
                resultSanitizer,
                resultLimiter,
                audit,
                metrics
        );
    }

    public ToolGateway(
            ToolAuth toolAuth,
            ParamValidator paramValidator,
            ResourceGuard resourceGuard,
            ToolExecutionLimiter limiter,
            ToolRateLimiter rateLimiter,
            ResultSanitizer resultSanitizer,
            ResultLimiter resultLimiter,
            Audit audit,
            Metrics metrics
    ) {
        this.toolAuth = Objects.requireNonNull(toolAuth, "toolAuth must not be null");
        this.paramValidator = Objects.requireNonNull(
                paramValidator, "paramValidator must not be null");
        this.resourceGuard = Objects.requireNonNull(
                resourceGuard, "resourceGuard must not be null");
        this.limiter = Objects.requireNonNull(limiter, "limiter must not be null");
        this.rateLimiter = Objects.requireNonNull(
                rateLimiter, "rateLimiter must not be null");
        this.resultSanitizer = Objects.requireNonNull(
                resultSanitizer, "resultSanitizer must not be null");
        this.resultLimiter = Objects.requireNonNull(
                resultLimiter, "resultLimiter must not be null");
        this.audit = Objects.requireNonNull(audit, "audit must not be null");
        this.metrics = Objects.requireNonNull(metrics, "metrics must not be null");
    }

    /**
     * Fixed order: call id → registry/auth → validation → guard → basic rate limit
     * → bulkhead/budget limiter → handler → sanitize → limit → audit/metrics.
     */
    public ToolResult<Object> execute(
            ToolExecutionContext context,
            ToolCallIntent intent,
            ToolHandler handler
    ) {
        String toolCallId = UUID.randomUUID().toString();
        long started = System.nanoTime();
        String toolName = intent == null ? "<unknown>" : intent.toolName();
        ToolExecutionContext callContext = context == null
                ? null
                : context.withToolCallId(toolCallId);

        Outcome outcome;
        Long requestedTargetProjectId = RagSearchTool.requestedTargetProjectId(intent);
        try {
            if (intent == null) {
                outcome = invalid(
                        toolName, toolCallId, "INTENT_INVALID", "tool intent is required");
            } else if (callContext == null) {
                outcome = denied(
                        toolName, toolCallId, "TRUSTED_CONTEXT_REQUIRED",
                        "trusted execution context is required");
            } else if (handler == null) {
                outcome = failed(
                        toolName, toolCallId, "HANDLER_MISSING", "tool handler is required");
            } else {
                ToolAuth.Decision authorization = toolAuth.authorize(callContext, intent);
                if (!authorization.allowed()) {
                    outcome = denied(
                            toolName, toolCallId, "AUTH_DENIED", authorization.reason());
                } else {
                    ParamValidator.Validation validation = paramValidator.validate(
                            intent, authorization.definition());
                    if (!validation.valid()) {
                        outcome = invalid(
                                toolName, toolCallId, "PARAM_INVALID", validation.reason());
                    } else {
                        outcome = executeGuarded(
                                callContext, intent, authorization.definition(), handler);
                    }
                }
            }
        } catch (ToolExecutionLimiter.BudgetExceededException exception) {
            outcome = denied(
                    toolName, toolCallId, "BUDGET_EXCEEDED",
                    "Agent Run tool-call budget exceeded");
        } catch (ToolExecutionLimiter.ToolTimeoutException exception) {
            outcome = timeout(toolName, toolCallId, "TIMEOUT", "tool execution timed out");
        } catch (Exception exception) {
            outcome = failed(
                    toolName, toolCallId, "EXECUTOR_FAILED", safeExceptionMessage(exception));
        }

        return finish(context, toolName, toolCallId, started, requestedTargetProjectId, outcome);
    }

    /** Returns an auditable Java-owned PARAM_INVALID result before authorization/execution. */
    public ToolResult<Object> invalidContract(
            ToolExecutionContext context,
            ToolCallIntent intent,
            String reason
    ) {
        String toolCallId = UUID.randomUUID().toString();
        long started = System.nanoTime();
        String toolName = intent == null ? "<unknown>" : intent.toolName();
        Long requestedTargetProjectId = RagSearchTool.requestedTargetProjectId(intent);
        return finish(
                context,
                toolName,
                toolCallId,
                started,
                requestedTargetProjectId,
                invalid(toolName, toolCallId, "PUBLIC_CONTRACT_INVALID", reason));
    }

    private ToolResult<Object> finish(
            ToolExecutionContext context,
            String toolName,
            String toolCallId,
            long started,
            Long requestedTargetProjectId,
            Outcome outcome
    ) {
        long elapsed = Math.max(0, System.nanoTime() - started);
        safeAudit(new Audit.AuditEvent(
                toolCallId,
                context == null ? 0L : context.projectId(),
                toolName,
                outcome.auditStatus(),
                outcome.violationCode(),
                outcome.sanitizedSummary(),
                elapsed,
                requestedTargetProjectId
        ));
        safeMetrics(
                toolAuth.metricToolName(toolName),
                outcome.auditStatus(),
                outcome.violationCode(),
                elapsed);
        return outcome.result();
    }

    private Outcome executeGuarded(
            ToolExecutionContext context,
            ToolCallIntent intent,
            ToolDefinition definition,
            ToolHandler handler
    ) throws Exception {
        ResourceGuard.Decision guardDecision;
        try {
            guardDecision = resourceGuard.check(context, definition, intent);
        } catch (RuntimeException exception) {
            return safetyViolation(intent.toolName(), context.toolCallId(),
                    "RESOURCE_GUARD_FAILED",
                    "resource guard failed");
        }
        if (guardDecision == null || !guardDecision.allowed()) {
            return safetyViolation(
                    intent.toolName(),
                    context.toolCallId(),
                    "RESOURCE_GUARD_REJECTED",
                    guardDecision == null ? "resource guard rejected" : guardDecision.reason()
            );
        }

        ToolRateLimiter.Decision rateDecision = rateLimiter.tryAcquire(context, definition);
        if (!rateDecision.allowed()) {
            return denied(
                    intent.toolName(), context.toolCallId(), "RATE_LIMITED",
                    rateDecision.reason());
        }

        Object rawResult = limiter.execute(
                context.agentRunId(),
                () -> handler.execute(context, intent));
        ResultSanitizer.SanitizedResult sanitized = resultSanitizer.sanitize(rawResult);
        ResultLimiter.LimitedResult limited = resultLimiter.limit(sanitized.value());
        return new Outcome(
                ToolResult.success(intent.toolName(), context.toolCallId(), limited.value()),
                AuditStatus.SUCCESS,
                "NONE",
                summary(limited.value())
        );
    }

    private Outcome denied(
            String toolName, String toolCallId, String violationCode, String reason) {
        return outcome(
                ToolResult.ofStatus(toolName, toolCallId, ToolStatus.FORBIDDEN, null),
                AuditStatus.DENIED,
                violationCode,
                reason
        );
    }

    private Outcome invalid(
            String toolName, String toolCallId, String violationCode, String reason) {
        return outcome(
                ToolResult.ofStatus(toolName, toolCallId, ToolStatus.PARAM_INVALID, null),
                AuditStatus.INVALID,
                violationCode,
                reason
        );
    }

    private Outcome safetyViolation(
            String toolName, String toolCallId, String violationCode, String reason) {
        return outcome(
                ToolResult.ofStatus(toolName, toolCallId, ToolStatus.FORBIDDEN, null),
                AuditStatus.SAFETY_VIOLATION,
                violationCode,
                reason
        );
    }

    private Outcome timeout(
            String toolName, String toolCallId, String violationCode, String reason) {
        return outcome(
                ToolResult.ofStatus(toolName, toolCallId, ToolStatus.TIMEOUT, null),
                AuditStatus.TIMEOUT,
                violationCode,
                reason
        );
    }

    private Outcome failed(
            String toolName, String toolCallId, String violationCode, String reason) {
        return outcome(
                ToolResult.ofStatus(toolName, toolCallId, ToolStatus.FAILED, null),
                AuditStatus.FAILED,
                violationCode,
                reason
        );
    }

    private Outcome outcome(
            ToolResult<Object> result,
            AuditStatus status,
            String violationCode,
            String reason
    ) {
        return new Outcome(result, status, violationCode, summary(reason));
    }

    private String summary(Object value) {
        try {
            ResultSanitizer.SanitizedResult sanitized = resultSanitizer.sanitize(value);
            ResultLimiter.LimitedResult limited = resultLimiter.limit(sanitized.value());
            return Objects.toString(limited.value(), "null");
        } catch (RuntimeException exception) {
            return "[SUMMARY_UNAVAILABLE]";
        }
    }

    private static String safeExceptionMessage(Exception exception) {
        String message = exception.getMessage();
        return message == null || message.isBlank() ? "tool execution failed" : message;
    }

    private void safeAudit(Audit.AuditEvent event) {
        try {
            audit.record(event);
        } catch (RuntimeException ignored) {
            // Audit failure is isolated and must never cause a tool retry.
        }
    }

    private void safeMetrics(
            String toolName,
            AuditStatus status,
            String violationCode,
            long elapsedNanos) {
        try {
            metrics.record(toolName, status, violationCode, elapsedNanos);
        } catch (RuntimeException ignored) {
            // Metrics are observational and must not affect the tool result.
        }
    }

    @Override
    public void close() {
        limiter.close();
    }

    @FunctionalInterface
    public interface ToolHandler {
        Object execute(ToolExecutionContext context, ToolCallIntent intent) throws Exception;
    }

    private record Outcome(
            ToolResult<Object> result,
            AuditStatus auditStatus,
            String violationCode,
            String sanitizedSummary
    ) {
    }
}
