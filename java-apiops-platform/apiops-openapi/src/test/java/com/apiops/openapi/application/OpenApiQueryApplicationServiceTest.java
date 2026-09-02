package com.apiops.openapi.application;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.openapi.converter.OpenApiMetadataAssembler;
import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;
import com.apiops.openapi.exception.OpenApiMetadataNotFoundException;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.apiops.openapi.vo.ApiDocumentVO;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.openapi.vo.ApiMetadataSummaryVO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OpenApiQueryApplicationServiceTest {

    private static final long PROJECT_ID = 41L;
    private static final String API_DOC_ID = "api_doc_orders";
    private static final String API_ID = "api_get_orders";

    private OpenApiMetadataRepository repository;
    private OpenApiQueryApplicationService service;

    @BeforeEach
    void setUp() {
        repository = mock(OpenApiMetadataRepository.class);
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> Optional.of(ProjectRole.VIEWER));
        service = new OpenApiQueryApplicationService(
                authorization, repository, new OpenApiMetadataAssembler());
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                7L, "query-user", "not-used", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
    }

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void shouldQueryDocumentAsPublicView() {
        when(repository.findDocument(PROJECT_ID, API_DOC_ID)).thenReturn(Optional.of(
                new ApiDocument(
                        99, API_DOC_ID, PROJECT_ID, "orders", "orders.yaml", "3.0.3",
                        "Orders", "1.0.0", "YAML", "a".repeat(64), "raw", 2,
                        "ACTIVE", 7, null, null)));

        ApiDocumentVO result = service.getDocument(PROJECT_ID, API_DOC_ID);

        assertEquals(API_DOC_ID, result.apiDocId());
        assertEquals(2, result.versionNo());
        assertEquals("Orders", result.title());
    }

    @Test
    void shouldListLightweightApiSummaries() {
        when(repository.findEndpoints(PROJECT_ID)).thenReturn(List.of(endpoint()));

        List<ApiMetadataSummaryVO> result = service.listApis(PROJECT_ID);

        assertEquals(1, result.size());
        assertEquals("GET", result.getFirst().method());
        assertEquals("orders", result.getFirst().tags().get(0).asText());
        assertFalse(result.getFirst().deprecated());
    }

    @Test
    void shouldQueryProjectScopedApiDetailWithStructuredMetadata() {
        stubDetail(PROJECT_ID);

        ApiMetadataDetailVO result = service.getApi(PROJECT_ID, API_ID);

        assertEquals(API_ID, result.apiId());
        assertTrue(result.tags().isArray());
        assertTrue(result.servers().isArray());
        assertTrue(result.security().isArray());
        assertTrue(result.parameters().getFirst().schema().isObject());
        assertTrue(result.requestSchemas().getFirst().schema().isObject());
        assertTrue(result.responseSchemas().getFirst().schema().isObject());
        assertTrue(result.examples().getFirst().value().isObject());
        assertEquals("200", result.examples().getFirst().owner().statusCode());
    }

    @Test
    void shouldNotReturnExistingApiFromAnotherProject() {
        long wrongProject = 42L;
        when(repository.findEndpoint(PROJECT_ID, API_ID))
                .thenReturn(Optional.of(endpoint()));
        when(repository.findEndpoint(wrongProject, API_ID)).thenReturn(Optional.empty());

        assertThrows(OpenApiMetadataNotFoundException.class,
                () -> service.getApi(wrongProject, API_ID));

        verify(repository).findEndpoint(wrongProject, API_ID);
        verify(repository, never()).findParameters(wrongProject, API_ID);
    }

    @Test
    void shouldUseUnifiedNotFoundForMissingApi() {
        when(repository.findEndpoint(PROJECT_ID, "missing")).thenReturn(Optional.empty());

        assertThrows(OpenApiMetadataNotFoundException.class,
                () -> service.getApi(PROJECT_ID, "missing"));
    }

    private void stubDetail(long projectId) {
        when(repository.findEndpoint(projectId, API_ID)).thenReturn(Optional.of(endpoint()));
        when(repository.findParameters(projectId, API_ID)).thenReturn(List.of(
                new ApiParameter(11, API_ID, projectId, "limit", "query", false,
                        "Limit", "{\"type\":\"integer\"}", "10", null)));
        when(repository.findRequestSchemas(projectId, API_ID)).thenReturn(List.of(
                new ApiRequestSchema(12, API_ID, projectId, true, "application/json",
                        "{\"type\":\"object\"}", null)));
        when(repository.findResponseSchemas(projectId, API_ID)).thenReturn(List.of(
                new ApiResponseSchema(13, API_ID, projectId, "200", "ok",
                        "application/json", "{\"type\":\"object\"}", null)));
        when(repository.findExamples(projectId, API_ID)).thenReturn(List.of(
                new ApiExample(14, API_ID, projectId, "RESPONSE_SCHEMA", 13,
                        "success", "Success", null, "{\"id\":1}", null)));
    }

    private ApiEndpoint endpoint() {
        return new ApiEndpoint(
                10, API_ID, API_DOC_ID, PROJECT_ID, "getOrders", "GET", "/orders",
                "List orders", "Returns orders", "[\"orders\"]",
                "[{\"url\":\"https://api.example\"}]",
                "[{\"apiKeyAuth\":[]}]", false, null, null);
    }
}
