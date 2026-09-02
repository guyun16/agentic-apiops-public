package com.apiops.report;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.common.enums.FailureType;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.assembler.TestReportAssembler;
import com.apiops.report.exception.TestReportNotFoundException;
import com.apiops.report.vo.TestReportVO;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.state.RunStatus;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class TestReportQueryServiceTest {

    private ExecutionFactRepository repository;
    private TestReportQueryService service;

    @BeforeEach
    void setUp() {
        repository = mock(ExecutionFactRepository.class);
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> Optional.of(ProjectRole.VIEWER));
        service = new TestReportQueryService(
                authorization,
                repository,
                new TestReportAssembler(new ObjectMapper()));
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                7L, "report-reader", "not-used", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
    }

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void readsSuccessfulReportWithAllAssertionsPassed() {
        when(repository.findRun(TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID))
                .thenReturn(Optional.of(TestReportFacts.success()));

        TestReportVO report = service.getReport(
                TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID);

        assertEquals(TestReportFacts.PROJECT_ID, report.projectId());
        assertEquals(TestReportFacts.RUN_ID, report.runId());
        assertEquals("report:" + TestReportFacts.RUN_ID, report.reportId());
        assertEquals(RunStatus.SUCCESS, report.status());
        assertEquals(2, report.summary().totalAssertions());
        assertEquals(2, report.summary().passedAssertions());
        assertEquals(0, report.summary().failedAssertions());
    }

    @Test
    void repeatedReadbackKeepsTheSameReportIdentity() {
        when(repository.findRun(TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID))
                .thenReturn(Optional.of(TestReportFacts.success()));

        TestReportVO first = service.getReport(TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID);
        TestReportVO second = service.getReport(TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID);

        assertEquals(first.reportId(), second.reportId());
    }

    @Test
    void readsAssertionFailedReportWithFailedAssertion() {
        when(repository.findRun(TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID))
                .thenReturn(Optional.of(TestReportFacts.assertionFailed()));

        TestReportVO report = service.getReport(
                TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID);

        assertEquals(RunStatus.ASSERTION_FAILED, report.status());
        assertEquals(FailureType.ASSERTION_MISMATCH, report.summary().failureType());
        assertEquals(1, report.summary().failedAssertions());
        assertFalse(report.cases().getFirst().steps().getFirst()
                .assertionResults().getFirst().passed());
    }

    @Test
    void readsExecutionFailedReportWithoutInventingResponseOrAssertionFailure() {
        when(repository.findRun(TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID))
                .thenReturn(Optional.of(TestReportFacts.executionFailed()));

        TestReportVO report = service.getReport(
                TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID);

        TestReportVO.StepReport step = report.cases().getFirst().steps().getFirst();
        assertEquals(RunStatus.EXECUTION_FAILED, report.status());
        assertEquals(FailureType.CONNECT_ERROR, report.summary().failureType());
        assertEquals(0, report.summary().totalAssertions());
        assertEquals(0, report.summary().failedAssertions());
        assertNull(step.responseStatusCode());
        assertNull(step.durationMs());
        assertEquals(List.of(), step.assertionResults());
    }

    @Test
    void wrongProjectWithSameRunIsNotFound() {
        long wrongProjectId = TestReportFacts.PROJECT_ID + 1;
        when(repository.findRun(wrongProjectId, TestReportFacts.RUN_ID))
                .thenReturn(Optional.empty());

        assertThrows(TestReportNotFoundException.class,
                () -> service.getReport(wrongProjectId, TestReportFacts.RUN_ID));

        verify(repository).findRun(wrongProjectId, TestReportFacts.RUN_ID);
    }

    @Test
    void nonMemberCannotReachExecutionFacts() {
        TestReportQueryService deniedService = new TestReportQueryService(
                new ProjectAuthorizationService((userId, projectId) -> Optional.empty()),
                repository,
                new TestReportAssembler(new ObjectMapper()));

        assertThrows(AccessDeniedException.class,
                () -> deniedService.getReport(
                        TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID));

        verify(repository, never()).findRun(TestReportFacts.PROJECT_ID, TestReportFacts.RUN_ID);
    }
}
