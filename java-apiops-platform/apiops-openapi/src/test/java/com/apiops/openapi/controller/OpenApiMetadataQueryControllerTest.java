package com.apiops.openapi.controller;

import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.exception.OpenApiMetadataNotFoundException;
import com.apiops.openapi.exception.OpenApiQueryExceptionHandler;
import com.apiops.openapi.vo.ApiDocumentVO;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.openapi.vo.ApiMetadataSummaryVO;
import io.swagger.v3.core.util.Json;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class OpenApiMetadataQueryControllerTest {

    private static final long PROJECT_ID = 41L;

    @Test
    void shouldExposeDocumentQueryWithoutPersistenceFields() throws Exception {
        OpenApiQueryApplicationService service = mock(OpenApiQueryApplicationService.class);
        when(service.getDocument(PROJECT_ID, "doc-1")).thenReturn(new ApiDocumentVO(
                "doc-1", PROJECT_ID, "orders", "orders.yaml", "3.0.3",
                "Orders", "1.0.0", "YAML", "a".repeat(64), 1,
                "ACTIVE", null, null));

        mvc(service).perform(get(
                        "/api/v1/projects/{projectId}/openapi/documents/{apiDocId}",
                        PROJECT_ID, "doc-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.apiDocId").value("doc-1"))
                .andExpect(jsonPath("$.data.versionNo").value(1))
                .andExpect(jsonPath("$.data.id").doesNotExist())
                .andExpect(jsonPath("$.data.rawContent").doesNotExist())
                .andExpect(jsonPath("$.data.createdBy").doesNotExist());
    }

    @Test
    void shouldExposeLightweightApiListWithStructuredTags() throws Exception {
        OpenApiQueryApplicationService service = mock(OpenApiQueryApplicationService.class);
        when(service.listApis(PROJECT_ID)).thenReturn(List.of(new ApiMetadataSummaryVO(
                "api-1", "doc-1", "getOrders", "GET", "/orders", "List orders",
                Json.mapper().readTree("[\"orders\"]"), false)));

        mvc(service).perform(get("/api/v1/projects/{projectId}/openapi/apis", PROJECT_ID))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].apiId").value("api-1"))
                .andExpect(jsonPath("$.data[0].tags[0]").value("orders"))
                .andExpect(jsonPath("$.data[0].description").doesNotExist())
                .andExpect(jsonPath("$.data[0].parameters").doesNotExist())
                .andExpect(jsonPath("$.data[0].id").doesNotExist());
    }

    @Test
    void shouldExposeStructuredApiDetailWithoutDatabaseIds() throws Exception {
        OpenApiQueryApplicationService service = mock(OpenApiQueryApplicationService.class);
        when(service.getApi(PROJECT_ID, "api-1")).thenReturn(detail());

        mvc(service).perform(get(
                        "/api/v1/projects/{projectId}/openapi/apis/{apiId}",
                        PROJECT_ID, "api-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.tags[0]").value("orders"))
                .andExpect(jsonPath("$.data.servers[0].url").value("https://api.example"))
                .andExpect(jsonPath("$.data.security[0].apiKeyAuth").isArray())
                .andExpect(jsonPath("$.data.parameters[0].schema.type").value("integer"))
                .andExpect(jsonPath("$.data.requestSchemas[0].schema.type").value("object"))
                .andExpect(jsonPath("$.data.responseSchemas[0].schema.type").value("object"))
                .andExpect(jsonPath("$.data.examples[0].value.id").value(1))
                .andExpect(jsonPath("$.data.id").doesNotExist())
                .andExpect(jsonPath("$.data.examples[0].ownerRefId").doesNotExist());
    }

    @Test
    void shouldReturnUnifiedNotFoundResponse() throws Exception {
        OpenApiQueryApplicationService service = mock(OpenApiQueryApplicationService.class);
        when(service.getApi(PROJECT_ID, "missing"))
                .thenThrow(new OpenApiMetadataNotFoundException("OpenAPI API", "missing"));

        mvc(service).perform(get(
                        "/api/v1/projects/{projectId}/openapi/apis/{apiId}",
                        PROJECT_ID, "missing"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("A0002"))
                .andExpect(jsonPath("$.data").doesNotExist());
    }

    private MockMvc mvc(OpenApiQueryApplicationService service) {
        return MockMvcBuilders.standaloneSetup(new OpenApiMetadataQueryController(service))
                .setControllerAdvice(new OpenApiQueryExceptionHandler())
                .build();
    }

    private ApiMetadataDetailVO detail() throws Exception {
        return new ApiMetadataDetailVO(
                "api-1", "doc-1", "getOrders", "GET", "/orders",
                "List orders", "Returns orders",
                Json.mapper().readTree("[\"orders\"]"),
                Json.mapper().readTree("[{\"url\":\"https://api.example\"}]"),
                Json.mapper().readTree("[{\"apiKeyAuth\":[]}]"), false,
                List.of(new ApiMetadataDetailVO.ParameterVO(
                        "limit", "query", false, null,
                        Json.mapper().readTree("{\"type\":\"integer\"}"),
                        Json.mapper().readTree("10"))),
                List.of(new ApiMetadataDetailVO.RequestSchemaVO(
                        true, "application/json",
                        Json.mapper().readTree("{\"type\":\"object\"}"))),
                List.of(new ApiMetadataDetailVO.ResponseSchemaVO(
                        "200", "ok", "application/json",
                        Json.mapper().readTree("{\"type\":\"object\"}"))),
                List.of(new ApiMetadataDetailVO.ExampleVO(
                        new ApiMetadataDetailVO.ExampleOwnerVO(
                                "RESPONSE_SCHEMA", null, null, "application/json", "200"),
                        "success", null, null,
                        Json.mapper().readTree("{\"id\":1}")))
        );
    }
}
