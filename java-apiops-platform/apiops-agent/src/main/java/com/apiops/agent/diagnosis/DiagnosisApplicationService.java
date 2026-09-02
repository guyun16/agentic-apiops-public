package com.apiops.agent.diagnosis;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.rag.application.DiagnosticContextApplicationService;
import com.apiops.rag.context.ContextPack;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.vo.TestReportVO;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Objects;

/** Deterministic boundary from authoritative Stage 10 evidence to accepted diagnosis. */
public final class DiagnosisApplicationService {

    private final DiagnosticContextApplicationService contextService;
    private final TestReportQueryService reportQueryService;
    private final DiagnosisAgent agent;
    private final ProjectAuthorizationService authorization;
    private final DiagnosisCitationValidator citationValidator;

    public DiagnosisApplicationService(
            DiagnosticContextApplicationService contextService,
            TestReportQueryService reportQueryService,
            DiagnosisAgent agent,
            ProjectAuthorizationService authorization,
            DiagnosisCitationValidator citationValidator) {
        this.contextService = Objects.requireNonNull(contextService, "contextService");
        this.reportQueryService = Objects.requireNonNull(reportQueryService, "reportQueryService");
        this.agent = Objects.requireNonNull(agent, "agent");
        this.authorization = Objects.requireNonNull(authorization, "authorization");
        this.citationValidator = Objects.requireNonNull(citationValidator, "citationValidator");
    }

    public DiagnosisExecutionResult diagnose(
            long projectId,
            long runId,
            String apiId,
            String task,
            int topK) {
        if (projectId <= 0 || runId <= 0) {
            throw new IllegalArgumentException("projectId and runId must be positive");
        }
        authorization.requireProjectReadable(currentPrincipal().getUserId(), projectId);
        TestReportVO testReport = reportQueryService.getReport(projectId, runId);
        ContextPack contextPack = contextService.buildContext(
                projectId, runId, apiId, task, topK);
        var generated = agent.generate(projectId, runId, testReport.reportId(), contextPack, task,
                candidate -> validateCandidate(
                        candidate, contextPack, projectId, runId, testReport.reportId()));
        validateCandidate(generated.candidate(), contextPack, projectId, runId,
                testReport.reportId());
        return new DiagnosisExecutionResult(
                generated.agentRunId(), generated.promptName(), generated.promptVersion(),
                generated.modelCalls(), contextPack, generated.candidate());
    }

    private DiagnosisReport validateCandidate(
            DiagnosisReport candidate,
            ContextPack contextPack,
            long projectId,
            long runId,
            String reportId) {
        if (candidate.projectId() != projectId) {
            throw new DiagnosisIdentityValidationException(
                    "DiagnosisReport projectId does not match requested projectId");
        }
        if (candidate.runId() != runId) {
            throw new DiagnosisIdentityValidationException(
                    "DiagnosisReport runId does not match requested runId");
        }
        if (!candidate.reportId().equals(reportId)) {
            throw new DiagnosisIdentityValidationException(
                    "DiagnosisReport reportId does not match authoritative TestReport");
        }
        citationValidator.validate(candidate, contextPack);
        return candidate;
    }

    private ApiOpsPrincipal currentPrincipal() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null
                || !authentication.isAuthenticated()
                || !(authentication.getPrincipal() instanceof ApiOpsPrincipal principal)) {
            throw new AccessDeniedException("Authenticated ApiOpsPrincipal required");
        }
        return principal;
    }
}
