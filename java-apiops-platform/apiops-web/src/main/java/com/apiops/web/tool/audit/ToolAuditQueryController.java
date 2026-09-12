package com.apiops.web.tool.audit;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Objects;

@RestController
@ConditionalOnProperty(prefix = "apiops.datasource.tool-gateway", name = "url")
@RequestMapping("/api/v1/projects/{projectId}/tool-calls/{toolCallId}/audit")
public final class ToolAuditQueryController {

    private final ToolAuditQueryApplicationService service;

    public ToolAuditQueryController(ToolAuditQueryApplicationService service) {
        this.service = Objects.requireNonNull(service, "service must not be null");
    }

    @GetMapping
    public ResponseEntity<ToolAuditResponse> find(
            @PathVariable long projectId,
            @PathVariable String toolCallId
    ) {
        return ResponseEntity.of(service.find(projectId, toolCallId));
    }
}
