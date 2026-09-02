package com.apiops.openapi.application;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.openapi.converter.OpenApiMetadataAssembler;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.exception.OpenApiMetadataNotFoundException;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.apiops.openapi.vo.ApiDocumentVO;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.openapi.vo.ApiMetadataSummaryVO;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;

public class OpenApiQueryApplicationService {

    private final ProjectAuthorizationService projectAuthorizationService;
    private final OpenApiMetadataRepository repository;
    private final OpenApiMetadataAssembler assembler;

    public OpenApiQueryApplicationService(
            ProjectAuthorizationService projectAuthorizationService,
            OpenApiMetadataRepository repository,
            OpenApiMetadataAssembler assembler
    ) {
        this.projectAuthorizationService = projectAuthorizationService;
        this.repository = repository;
        this.assembler = assembler;
    }

    @PreAuthorize("isAuthenticated()")
    public ApiDocumentVO getDocument(long projectId, String apiDocId) {
        requireProjectReadable(projectId);
        return repository.findDocument(projectId, apiDocId)
                .map(assembler::document)
                .orElseThrow(() -> new OpenApiMetadataNotFoundException(
                        "OpenAPI document", apiDocId));
    }

    @PreAuthorize("isAuthenticated()")
    public List<ApiDocumentVO> listDocuments(long projectId) {
        requireProjectReadable(projectId);
        return repository.findDocuments(projectId).stream()
                .map(assembler::document)
                .toList();
    }

    @PreAuthorize("isAuthenticated()")
    public List<ApiMetadataSummaryVO> listApis(long projectId) {
        requireProjectReadable(projectId);
        return repository.findEndpoints(projectId).stream()
                .map(assembler::summary)
                .toList();
    }

    @PreAuthorize("isAuthenticated()")
    public ApiMetadataDetailVO getApi(long projectId, String apiId) {
        requireProjectReadable(projectId);
        ApiEndpoint endpoint = repository.findEndpoint(projectId, apiId)
                .orElseThrow(() -> new OpenApiMetadataNotFoundException(
                        "OpenAPI API", apiId));
        return assembler.detail(
                endpoint,
                repository.findParameters(projectId, apiId),
                repository.findRequestSchemas(projectId, apiId),
                repository.findResponseSchemas(projectId, apiId),
                repository.findExamples(projectId, apiId)
        );
    }

    private void requireProjectReadable(long projectId) {
        projectAuthorizationService.requireProjectReadable(
                currentPrincipal().getUserId(), projectId);
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
