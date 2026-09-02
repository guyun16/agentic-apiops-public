package com.apiops.web.runner.application;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.web.runner.vo.RunSummaryVO;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;
import java.util.Objects;

/** Project-authorized read boundary for the Runs explorer. */
public class RunQueryApplicationService {

    private final ProjectAuthorizationService authorization;
    private final ExecutionFactRepository repository;

    public RunQueryApplicationService(
            ProjectAuthorizationService authorization,
            ExecutionFactRepository repository
    ) {
        this.authorization = Objects.requireNonNull(authorization);
        this.repository = Objects.requireNonNull(repository);
    }

    @PreAuthorize("isAuthenticated()")
    public List<RunSummaryVO> list(long projectId) {
        ApiOpsPrincipal principal = currentPrincipal();
        authorization.requireProjectReadable(principal.getUserId(), projectId);
        return repository.findRecentRunSummaries(projectId).stream()
                .map(RunSummaryVO::from)
                .toList();
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
