package com.apiops.web.runner.application;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.runner.application.BatchCancelResult;
import com.apiops.runner.application.BatchExecutionCoordinator;
import com.apiops.runner.application.RunExecutionService;
import com.apiops.runner.dsl.EnvironmentSpec;
import com.apiops.runner.dsl.RequestSpec;
import com.apiops.runner.dsl.TestCase;
import com.apiops.runner.dsl.TestStep;
import com.apiops.runner.messaging.BatchExecutionMessage;
import com.apiops.runner.messaging.BatchExecutionProducer;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.ExecutionFactRepository.BatchExecutionFacts;
import com.apiops.runner.persistence.ExecutionFactRepository.BatchMember;
import com.apiops.runner.persistence.ExecutionFactRepository.PreparedBatch;
import com.apiops.runner.state.RunStatus;
import com.apiops.web.runner.dto.AsyncBatchSubmitRequest;
import com.fasterxml.jackson.databind.json.JsonMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class AsyncBatchHttpApplicationServiceTest {

    @Test
    void cancelResolvesBatchOnServerAndControlsReportBatchScope() throws Exception {
        var repository = mock(ExecutionFactRepository.class);
        var producer = mock(BatchExecutionProducer.class);
        var coordinator = mock(BatchExecutionCoordinator.class);
        var batchId = UUID.randomUUID();
        String snapshot = JsonMapper.builder().build().writeValueAsString(testCase(101L, "one"));
        when(repository.findExecutionInput(301L)).thenReturn(Optional.of(
                new ExecutionFactRepository.RunExecutionInput(101L, 201L, 301L, "one", "api", snapshot)));
        when(repository.findRun(101L, 301L)).thenReturn(Optional.of(
                new ExecutionFactRepository.RunExecutionFacts(101L, 201L, 301L, "one", "api", "one",
                        RunStatus.RUNNING, com.apiops.common.enums.FailureType.NONE, null, null, List.of())));
        when(repository.findBatchIdForRun(101L, 301L)).thenReturn(Optional.of(batchId));
        when(repository.findBatch(101L, batchId)).thenReturn(Optional.of(new BatchExecutionFacts(
                batchId, 101L, 7L, RunStatus.RUNNING, false, null, null,
                List.of(new BatchMember(201L, 301L), new BatchMember(202L, 302L)))));
        when(repository.requestBatchCancel(101L, batchId)).thenReturn(true);
        var service = service(ProjectRole.EDITOR, repository, producer, coordinator);
        assertEquals(2, service.controls(101L, 301L).batchSize());
        assertEquals(true, service.controls(101L, 301L).canCancel());
        assertEquals(BatchCancelResult.REQUESTED, service.cancelRun(101L, 301L));
        verify(coordinator).requestCancel(batchId);
    }

    @Test
    void rerunCopiesSnapshotWithOnlyDirectSourceAndDoesNotUpdateHistory() throws Exception {
        var repository = mock(ExecutionFactRepository.class);
        var producer = mock(BatchExecutionProducer.class);
        var mapper = JsonMapper.builder().build();
        var base = testCase(101L, "original");
        var original = new TestCase(base.schemaVersion(), base.caseId(), base.projectId(), base.apiId(),
                base.name(), base.environment(), base.description(), List.of("smoke", "apiops:rerun-of:99"), base.steps());
        String snapshot = mapper.writeValueAsString(original);
        when(repository.findExecutionInput(301L)).thenReturn(Optional.of(
                new ExecutionFactRepository.RunExecutionInput(101L, 201L, 301L, "original", "api", snapshot)));
        when(repository.findRun(101L, 301L)).thenReturn(Optional.of(
                new ExecutionFactRepository.RunExecutionFacts(101L, 201L, 301L, "original", "api", "original",
                        RunStatus.SUCCESS, com.apiops.common.enums.FailureType.NONE, null, null, List.of())));
        when(repository.prepareBatch(any(), eq(101L), eq(7L), anyList())).thenAnswer(call -> {
            List<ExecutionFactRepository.PreparedRun> copies = call.getArgument(3);
            TestCase copy = mapper.readValue(copies.getFirst().testCaseDslJson(), TestCase.class);
            assertEquals(original.steps(), copy.steps());
            assertEquals(original.environment(), copy.environment());
            assertEquals(List.of("smoke", "apiops:rerun-of:301"), copy.tags());
            return new PreparedBatch(call.getArgument(0), 101L, List.of(new BatchMember(202L, 302L)));
        });
        var result = service(ProjectRole.EDITOR, repository, producer).rerun(101L, 301L);
        assertEquals(List.of(302L), result.runIds());
        assertEquals(snapshot, repository.findExecutionInput(301L).orElseThrow().testCaseDslJson());
        verify(repository, never()).completeRun(any(Long.class), any(), any(), any());
        verify(producer).publish(any());
    }

    @Test
    void runControlsRejectCrossProjectInputsAndRunsWithoutBatch() throws Exception {
        var repository = mock(ExecutionFactRepository.class);
        var producer = mock(BatchExecutionProducer.class);
        var service = service(ProjectRole.EDITOR, repository, producer);
        String snapshot = JsonMapper.builder().build().writeValueAsString(testCase(102L, "other"));
        when(repository.findExecutionInput(301L)).thenReturn(Optional.of(
                new ExecutionFactRepository.RunExecutionInput(102L, 201L, 301L, "other", "api", snapshot)));
        assertThrows(com.apiops.common.exception.BusinessException.class, () -> service.rerun(101L, 301L));
        assertThrows(com.apiops.common.exception.BusinessException.class, () -> service.cancelRun(101L, 301L));
        assertThrows(com.apiops.common.exception.BusinessException.class, () -> service.controls(101L, 301L));
        when(repository.findExecutionInput(301L)).thenReturn(Optional.of(
                new ExecutionFactRepository.RunExecutionInput(101L, 201L, 301L, "local", "api", snapshot)));
        assertThrows(com.apiops.common.exception.BusinessException.class, () -> service.cancelRun(101L, 301L));
        verifyNoInteractions(producer);
        verify(repository, never()).requestBatchCancel(any(Long.class), any());
    }

    @Test
    void viewersCannotUseRunMutations() {
        var repository = mock(ExecutionFactRepository.class);
        var producer = mock(BatchExecutionProducer.class);
        var service = service(ProjectRole.VIEWER, repository, producer);
        assertThrows(AccessDeniedException.class, () -> service.rerun(101L, 301L));
        assertThrows(AccessDeniedException.class, () -> service.cancelRun(101L, 301L));
        verifyNoInteractions(repository, producer);
    }

    @AfterEach
    void clearSecurity() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void editorSubmitPersistsDurableMembersThenPublishesOnlyBatchIdentity() {
        ExecutionFactRepository repository = mock(ExecutionFactRepository.class);
        BatchExecutionProducer producer = mock(BatchExecutionProducer.class);
        UUID batchId = UUID.randomUUID();
        when(repository.prepareBatch(any(), eq(101L), eq(7L), anyList()))
                .thenAnswer(call -> new PreparedBatch(
                        call.getArgument(0), 101L,
                        List.of(new BatchMember(201L, 301L), new BatchMember(202L, 302L))));
        AsyncBatchHttpApplicationService service = service(
                ProjectRole.EDITOR, repository, producer);

        var result = service.submit(101L, new AsyncBatchSubmitRequest(List.of(
                testCase(101L, "one"), testCase(101L, "two"))));

        assertEquals(List.of(201L, 202L), result.taskIds());
        assertEquals(List.of(301L, 302L), result.runIds());
        verify(repository).prepareBatch(eq(result.batchId()), eq(101L), eq(7L), anyList());
        verify(producer).publish(org.mockito.ArgumentMatchers.argThat(message ->
                message.projectId() == 101L
                        && message.batchId().equals(result.batchId())
                        && message.requestedBy() == 7L));
    }

    @Test
    void publishFailureClosesPreparedBatchAndNeverStartsExecution() {
        ExecutionFactRepository repository = mock(ExecutionFactRepository.class);
        BatchExecutionProducer producer = mock(BatchExecutionProducer.class);
        BatchExecutionCoordinator coordinator = mock(BatchExecutionCoordinator.class);
        when(repository.prepareBatch(any(), eq(101L), eq(7L), anyList()))
                .thenAnswer(call -> new PreparedBatch(
                        call.getArgument(0), 101L, List.of(new BatchMember(201L, 301L))));
        when(repository.completeBatch(eq(101L), any(), eq(RunStatus.EXECUTION_FAILED), any()))
                .thenReturn(true);
        org.mockito.Mockito.doThrow(new IllegalStateException("rabbit unavailable"))
                .when(producer).publish(any(BatchExecutionMessage.class));
        AsyncBatchHttpApplicationService service = service(
                ProjectRole.EDITOR, repository, producer, coordinator);

        IllegalStateException failure = assertThrows(IllegalStateException.class,
                () -> service.submit(101L,
                        new AsyncBatchSubmitRequest(List.of(testCase(101L, "one")))));

        assertEquals("Unable to dispatch execution batch", failure.getMessage());
        verify(repository).completeBatch(
                eq(101L), any(), eq(RunStatus.EXECUTION_FAILED), any());
        verifyNoInteractions(coordinator);
    }

    @Test
    void viewerCannotSubmitOrCancelAnotherProjectsBatch() {
        ExecutionFactRepository repository = mock(ExecutionFactRepository.class);
        BatchExecutionProducer producer = mock(BatchExecutionProducer.class);
        AsyncBatchHttpApplicationService service = service(
                ProjectRole.VIEWER, repository, producer);

        assertThrows(AccessDeniedException.class,
                () -> service.submit(101L, new AsyncBatchSubmitRequest(
                        List.of(testCase(101L, "denied")))));
        assertThrows(AccessDeniedException.class,
                () -> service.cancel(101L, UUID.randomUUID()));
        verify(repository, never()).prepareBatch(any(), eq(101L), eq(7L), anyList());
        verify(producer, never()).publish(any(BatchExecutionMessage.class));
    }

    @Test
    void cancelReturnsRequestedAlreadyRequestedAndTerminalWithoutReopening() {
        ExecutionFactRepository repository = mock(ExecutionFactRepository.class);
        BatchExecutionProducer producer = mock(BatchExecutionProducer.class);
        UUID batchId = UUID.randomUUID();
        BatchExecutionFacts running = new BatchExecutionFacts(
                batchId, 101L, 7L, RunStatus.RUNNING, false, null, null,
                List.of(new BatchMember(201L, 301L)));
        BatchExecutionFacts terminal = new BatchExecutionFacts(
                batchId, 101L, 7L, RunStatus.SUCCESS, true, null, null,
                List.of(new BatchMember(201L, 301L)));
        when(repository.findBatch(101L, batchId))
                .thenReturn(Optional.of(running), Optional.of(running),
                        Optional.of(running), Optional.of(terminal));
        when(repository.requestBatchCancel(101L, batchId)).thenReturn(true, false);
        AsyncBatchHttpApplicationService service = service(
                ProjectRole.EDITOR, repository, producer);

        assertEquals(BatchCancelResult.REQUESTED, service.cancel(101L, batchId));
        assertEquals(BatchCancelResult.ALREADY_REQUESTED, service.cancel(101L, batchId));
        assertEquals(BatchCancelResult.TERMINAL, service.cancel(101L, batchId));
        verify(repository, org.mockito.Mockito.times(2)).requestBatchCancel(101L, batchId);
    }

    private AsyncBatchHttpApplicationService service(
            ProjectRole role,
            ExecutionFactRepository repository,
            BatchExecutionProducer producer) {
        return service(role, repository, producer, mock(BatchExecutionCoordinator.class));
    }

    private AsyncBatchHttpApplicationService service(
            ProjectRole role,
            ExecutionFactRepository repository,
            BatchExecutionProducer producer,
            BatchExecutionCoordinator coordinator) {
        authenticate();
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> Optional.ofNullable(role));
        return new AsyncBatchHttpApplicationService(
                authorization, repository, producer, coordinator, JsonMapper.builder().build());
    }

    private void authenticate() {
        ApiOpsPrincipal principal = new ApiOpsPrincipal(7L, "editor", "hash", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(principal, null, List.of()));
    }

    private TestCase testCase(long projectId, String caseId) {
        return new TestCase("1.0.0", caseId, projectId, "api", caseId,
                new EnvironmentSpec("http://localhost", java.util.Map.of()), null, null,
                List.of(new TestStep(caseId + "-step", caseId,
                        new RequestSpec("GET", "/", null, null, null, null),
                        List.of(), List.of())));
    }
}
