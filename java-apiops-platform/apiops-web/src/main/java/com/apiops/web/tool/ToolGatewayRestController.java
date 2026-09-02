package com.apiops.web.tool;

import com.apiops.auth.security.ApiOpsPrincipal;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Stable REST adapter; it never calls a concrete Tool or resource client. */
@RestController
@RequestMapping("/api/v1/projects/{projectId}/tool-calls")
public final class ToolGatewayRestController {

    private final ToolGatewayRestApplicationService service;

    public ToolGatewayRestController(ToolGatewayRestApplicationService service) {
        this.service = service;
    }

    @PostMapping
    public ToolResultResponse call(
            @PathVariable long projectId,
            @RequestBody ToolCallRequest request
    ) {
        Authentication authentication = currentAuthentication();
        return service.execute(
                (ApiOpsPrincipal) authentication.getPrincipal(),
                projectId,
                request,
                authentication.getAuthorities());
    }

    private Authentication currentAuthentication() {
        Authentication current = SecurityContextHolder.getContext().getAuthentication();
        if (current == null || !(current.getPrincipal() instanceof ApiOpsPrincipal)) {
            throw new AccessDeniedException("Authenticated ApiOpsPrincipal required");
        }
        return current;
    }
}
