package com.apiops.report.application;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.report.assembler.TestReportAssembler;
import com.apiops.report.exception.TestReportNotFoundException;
import com.apiops.report.vo.TestReportVO;
import com.apiops.runner.persistence.ExecutionFactRepository;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Objects;

public class TestReportQueryService {

    private final ProjectAuthorizationService projectAuthorizationService;
    private final ExecutionFactRepository repository;
    private final TestReportAssembler assembler;

    public TestReportQueryService(
            ProjectAuthorizationService projectAuthorizationService,
            ExecutionFactRepository repository,
            TestReportAssembler assembler
    ) {
        this.projectAuthorizationService = Objects.requireNonNull(
                projectAuthorizationService, "projectAuthorizationService must not be null");
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.assembler = Objects.requireNonNull(assembler, "assembler must not be null");
    }

    @PreAuthorize("isAuthenticated()")
    public TestReportVO getReport(long projectId, long runId) {
        projectAuthorizationService.requireProjectReadable(currentPrincipal().getUserId(), projectId);
        return repository.findRun(projectId, runId)
                .map(assembler::assemble)
                .orElseThrow(() -> new TestReportNotFoundException(projectId, runId));
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
