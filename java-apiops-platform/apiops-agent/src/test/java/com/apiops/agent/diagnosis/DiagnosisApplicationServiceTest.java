package com.apiops.agent.diagnosis;

import com.apiops.agent.model.AgentModelException;
import com.apiops.rag.application.DiagnosticContextApplicationService;
import com.apiops.rag.context.ContextPack;
import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.vo.TestReportVO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;
import java.util.Optional;

import static com.apiops.agent.diagnosis.DiagnosisTestSupport.API_ID;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.PROJECT_ID;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.RUN_ID;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.agent;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.insufficientJson;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.packWithRag;
import static com.apiops.agent.diagnosis.DiagnosisTestSupport.validJson;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class DiagnosisApplicationServiceTest {

    private final ProjectAuthorizationService authorization =
            new ProjectAuthorizationService((userId, projectId) ->
                    userId == 77L && projectId == PROJECT_ID
                            ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
    private final TestReportQueryService reports = mock(TestReportQueryService.class);

    @BeforeEach
    void authenticate() {
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                77L, "diagnosis-user", "unused", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
        when(reports.getReport(PROJECT_ID, RUN_ID)).thenReturn(testReport());
    }

    @AfterEach
    void clearAuthentication() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void projectAndRunIdentityMatchProducesAcceptedReport() {
        ContextPack pack = packWithRag();
        DiagnosticContextApplicationService context = context(pack);
        var client = new DiagnosisTestSupport.SequenceClient(validJson(
                true, Long.toString(PROJECT_ID), Long.toString(RUN_ID),
                "{\"itemId\":\"run:" + RUN_ID + "\"},{\"itemId\":\"chunk:chunk-1\"}"));
        DiagnosisExecutionResult result = service(context, agent(client)).diagnose(
                PROJECT_ID, RUN_ID, API_ID, "Explain the failed run", 3);

        assertEquals(PROJECT_ID, result.report().projectId());
        assertEquals(RUN_ID, result.report().runId());
        assertEquals("report:" + RUN_ID, result.report().reportId());
        assertEquals(pack, result.contextPack());
        assertEquals(1, result.modelCallCount());
        verify(reports).getReport(PROJECT_ID, RUN_ID);
        verify(context).buildContext(PROJECT_ID, RUN_ID, API_ID, "Explain the failed run", 3);
    }

    @Test
    void modelProjectOrRunSwapIsRejectedBeforeAcceptance() {
        ContextPack pack = packWithRag();
        DiagnosticContextApplicationService context = context(pack);
        String projectSwap = validJson(true, "9999", Long.toString(RUN_ID),
                "{\"itemId\":\"run:" + RUN_ID + "\"}");
        assertThrows(DiagnosisIdentityValidationException.class,
                () -> service(context, agent(new DiagnosisTestSupport.SequenceClient(projectSwap)))
                        .diagnose(PROJECT_ID, RUN_ID, API_ID, "Explain", 1));

        String runSwap = validJson(true, Long.toString(PROJECT_ID), "9999",
                "{\"itemId\":\"run:" + RUN_ID + "\"}");
        assertThrows(DiagnosisIdentityValidationException.class,
                () -> service(context, agent(new DiagnosisTestSupport.SequenceClient(runSwap)))
                        .diagnose(PROJECT_ID, RUN_ID, API_ID, "Explain", 1));
    }

    @Test
    void modelReportIdSwapIsRejectedBeforeAcceptance() {
        ContextPack pack = packWithRag();
        DiagnosticContextApplicationService context = context(pack);
        String reportSwap = validJson(true, Long.toString(PROJECT_ID), Long.toString(RUN_ID),
                "report:wrong", "{\"itemId\":\"run:" + RUN_ID + "\"}");

        assertThrows(DiagnosisIdentityValidationException.class,
                () -> service(context, agent(new DiagnosisTestSupport.SequenceClient(reportSwap)))
                        .diagnose(PROJECT_ID, RUN_ID, API_ID, "Explain", 1));
    }

    @Test
    void citationInvalidIsRejectedAfterBoundedRepair() {
        ContextPack pack = packWithRag();
        DiagnosticContextApplicationService context = context(pack);
        String invalid = validJson(true, Long.toString(PROJECT_ID), Long.toString(RUN_ID),
                "{\"itemId\":\"chunk:not-in-pack\"}");
        var client = new DiagnosisTestSupport.SequenceClient(invalid, invalid);

        assertThrows(com.apiops.agent.structured.StructuredOutputException.class,
                () -> service(context, agent(client)).diagnose(
                        PROJECT_ID, RUN_ID, API_ID, "Explain", 1));
        assertEquals(2, client.requests.size());
    }

    @Test
    void zeroRagAndInsufficientEvidenceAreAcceptedAsLimitedDiagnosis() {
        ContextPack pack = DiagnosisTestSupport.zeroRagPack();
        DiagnosticContextApplicationService context = context(pack);
        DiagnosisExecutionResult result = service(context,
                agent(new DiagnosisTestSupport.SequenceClient(insufficientJson()))).diagnose(
                PROJECT_ID, RUN_ID, API_ID, "Explain with available facts", 0);

        assertFalse(result.report().sufficientEvidence());
        assertTrue(result.report().rootCauseHypotheses().isEmpty());
    }

    @Test
    void providerFailurePropagatesSeparatelyAndDoesNotBecomeValidationFailure() {
        ContextPack pack = packWithRag();
        DiagnosticContextApplicationService context = context(pack);
        assertThrows(AgentModelException.class,
                () -> service(context, agent(new DiagnosisTestSupport.SequenceClient(
                        new AgentModelException("Model provider call failed"))))
                        .diagnose(PROJECT_ID, RUN_ID, API_ID, "Explain", 1));
    }

    private DiagnosticContextApplicationService context(ContextPack pack) {
        DiagnosticContextApplicationService context = mock(
                DiagnosticContextApplicationService.class);
        when(context.buildContext(PROJECT_ID, RUN_ID, API_ID, "Explain", 1))
                .thenReturn(pack);
        when(context.buildContext(PROJECT_ID, RUN_ID, API_ID, "Explain the failed run", 3))
                .thenReturn(pack);
        when(context.buildContext(PROJECT_ID, RUN_ID, API_ID,
                "Explain with available facts", 0)).thenReturn(pack);
        return context;
    }

    private DiagnosisApplicationService service(
            DiagnosticContextApplicationService context, DiagnosisAgent agent) {
        return new DiagnosisApplicationService(
                context, reports, agent, authorization, new DiagnosisCitationValidator());
    }

    private TestReportVO testReport() {
        return new TestReportVO(
                PROJECT_ID, 1L, RUN_ID, com.apiops.runner.state.RunStatus.ASSERTION_FAILED,
                java.time.Instant.parse("2026-08-13T00:00:00Z"),
                java.time.Instant.parse("2026-08-13T00:00:01Z"),
                new TestReportVO.Summary(1, 1, 1, 0, 1,
                        com.apiops.common.enums.FailureType.ASSERTION_MISMATCH), List.of());
    }
}
