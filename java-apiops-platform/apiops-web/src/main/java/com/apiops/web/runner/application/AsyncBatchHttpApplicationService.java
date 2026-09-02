package com.apiops.web.runner.application;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.common.enums.ErrorCode;
import com.apiops.common.exception.BusinessException;
import com.apiops.runner.application.BatchCancelResult;
import com.apiops.runner.application.BatchExecutionCoordinator;
import com.apiops.runner.dsl.TestCase;
import com.apiops.runner.messaging.BatchExecutionMessage;
import com.apiops.runner.messaging.BatchExecutionProducer;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.ExecutionFactRepository.BatchExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.PreparedRun;
import com.apiops.runner.state.RunStatus;
import com.apiops.web.runner.dto.AsyncBatchSubmitRequest;
import com.apiops.web.runner.vo.AsyncBatchSubmission;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.context.SecurityContextHolder;

import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/** Project-authorized HTTP boundary for durable asynchronous batches. */
public class AsyncBatchHttpApplicationService {

    private static final Logger LOGGER = LoggerFactory.getLogger(
            AsyncBatchHttpApplicationService.class);

    private final ProjectAuthorizationService authorization;
    private final ExecutionFactRepository repository;
    private final BatchExecutionProducer producer;
    private final BatchExecutionCoordinator coordinator;
    private final ObjectMapper objectMapper;

    public AsyncBatchHttpApplicationService(
            ProjectAuthorizationService authorization,
            ExecutionFactRepository repository,
            BatchExecutionProducer producer,
            BatchExecutionCoordinator coordinator,
            ObjectMapper objectMapper) {
        this.authorization = Objects.requireNonNull(authorization);
        this.repository = Objects.requireNonNull(repository);
        this.producer = Objects.requireNonNull(producer);
        this.coordinator = Objects.requireNonNull(coordinator);
        this.objectMapper = Objects.requireNonNull(objectMapper);
    }

    @PreAuthorize("isAuthenticated()")
    public AsyncBatchSubmission submit(long projectId, AsyncBatchSubmitRequest request) {
        ApiOpsPrincipal principal = principal();
        authorization.requireProjectEditable(principal.getUserId(), projectId);
        List<TestCase> cases = request == null || request.testCases() == null
                ? List.of() : List.copyOf(request.testCases());
        if (cases.isEmpty()) throw invalid("testCases must not be empty");
        List<PreparedRun> prepared = cases.stream().map(testCase -> {
            if (testCase == null || testCase.projectId() != projectId) {
                throw invalid("every TestCase projectId must match the request path");
            }
            if (testCase.steps().isEmpty()) throw invalid("TestCase steps must not be empty");
            return new PreparedRun(testCase.caseId(), testCase.apiId(), testCase.name(),
                    snapshot(testCase));
        }).toList();
        UUID batchId = UUID.randomUUID();
        String traceId = traceId();
        ExecutionFactRepository.PreparedBatch batch = repository.prepareBatch(
                batchId, projectId, principal.getUserId(), prepared);
        try {
            producer.publish(new BatchExecutionMessage(
                    BatchExecutionMessage.CURRENT_VERSION,
                    UUID.randomUUID(),
                    projectId,
                    batchId,
                    principal.getUserId(),
                    traceId,
                    Instant.now()));
        } catch (RuntimeException publishFailure) {
            IllegalStateException failure = new IllegalStateException(
                    "Unable to dispatch execution batch", publishFailure);
            try {
                if (!repository.completeBatch(
                        projectId, batchId, RunStatus.EXECUTION_FAILED, Instant.now())) {
                    failure.addSuppressed(new IllegalStateException(
                            "Prepared batch could not be marked as dispatch failed"));
                }
            } catch (RuntimeException persistenceFailure) {
                failure.addSuppressed(persistenceFailure);
            }
            throw failure;
        }
        LOGGER.info(
                "Accepted execution batch batchId={} runIds={} traceId={} requestId={}",
                batchId,
                batch.members().stream()
                        .map(ExecutionFactRepository.BatchMember::runId)
                        .toList(),
                traceId,
                requestId());
        return new AsyncBatchSubmission(
                batchId,
                batch.members().stream().map(ExecutionFactRepository.BatchMember::taskId).toList(),
                batch.members().stream().map(ExecutionFactRepository.BatchMember::runId).toList());
    }

    @PreAuthorize("isAuthenticated()")
    public BatchCancelResult cancel(long projectId, UUID batchId) {
        ApiOpsPrincipal principal = principal();
        authorization.requireProjectEditable(principal.getUserId(), projectId);
        BatchExecutionFacts batch = repository.findBatch(projectId, batchId)
                .orElseThrow(() -> invalid("execution batch not found"));
        if (batch.status().isTerminal()) return BatchCancelResult.TERMINAL;
        boolean first = repository.requestBatchCancel(projectId, batchId);
        if (!first && repository.findBatch(projectId, batchId)
                .map(BatchExecutionFacts::status)
                .filter(status -> status.isTerminal())
                .isPresent()) {
            return BatchCancelResult.TERMINAL;
        }
        coordinator.requestCancel(batchId);
        return first ? BatchCancelResult.REQUESTED : BatchCancelResult.ALREADY_REQUESTED;
    }

    private ApiOpsPrincipal principal() {
        Object value = SecurityContextHolder.getContext().getAuthentication().getPrincipal();
        if (!(value instanceof ApiOpsPrincipal principal)) {
            throw new AccessDeniedException("Authenticated ApiOpsPrincipal required");
        }
        return principal;
    }

    private String snapshot(TestCase testCase) {
        try {
            return objectMapper.writeValueAsString(testCase);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Unable to serialize TestCase snapshot", exception);
        }
    }

    private String traceId() {
        String value = MDC.get("traceId");
        return value == null || value.isBlank() ? UUID.randomUUID().toString() : value;
    }

    private String requestId() {
        String value = MDC.get("requestId");
        return value == null || value.isBlank() ? "-" : value;
    }

    private BusinessException invalid(String message) {
        return new BusinessException(ErrorCode.PARAM_INVALID, message);
    }
}
