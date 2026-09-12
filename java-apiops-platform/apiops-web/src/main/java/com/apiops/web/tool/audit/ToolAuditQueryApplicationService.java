package com.apiops.web.tool.audit;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.tool.gateway.audit.ToolAuditRepository;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Objects;
import java.util.Optional;

/** Authenticated, project-authorized read boundary for durable Tool Audit facts. */
public class ToolAuditQueryApplicationService {

    private final ProjectAuthorizationService authorization;
    private final ToolAuditRepository repository;

    public ToolAuditQueryApplicationService(
            ProjectAuthorizationService authorization,
            ToolAuditRepository repository
    ) {
        this.authorization = Objects.requireNonNull(authorization);
        this.repository = Objects.requireNonNull(repository);
    }

    @PreAuthorize("isAuthenticated()")
    public Optional<ToolAuditResponse> find(long projectId, String toolCallId) {
        ApiOpsPrincipal principal = currentPrincipal();
        authorization.requireProjectReadable(principal.getUserId(), projectId);
        return repository.findByToolCallId(projectId, toolCallId).map(ToolAuditResponse::from);
    }

    private static ApiOpsPrincipal currentPrincipal() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null
                || !authentication.isAuthenticated()
                || !(authentication.getPrincipal() instanceof ApiOpsPrincipal principal)) {
            throw new AccessDeniedException("Authenticated ApiOpsPrincipal required");
        }
        return principal;
    }
}
