package com.apiops.openapi.controller;

import com.apiops.openapi.application.OpenApiImportApplicationService;
import com.apiops.openapi.application.OpenApiImportResult;
import com.apiops.openapi.parser.OpenApiDocumentParser;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.nio.charset.StandardCharsets;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class OpenApiDocumentControllerTest {

    @Test
    void shouldExposeProjectScopedMultipartUploadEndpoint() throws Exception {
        OpenApiImportApplicationService service = mock(OpenApiImportApplicationService.class);
        byte[] raw = minimalDocument().getBytes(StandardCharsets.UTF_8);
        when(service.importDocument(eq(41L), eq("orders"), any()))
                .thenReturn(new OpenApiImportResult(
                        41L,
                        "orders",
                        "contract.anything",
                        raw.length,
                        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                        new OpenApiDocumentParser().parse(minimalDocument())
                ));
        MockMvc mvc = MockMvcBuilders.standaloneSetup(
                new OpenApiDocumentController(service)
        ).build();

        mvc.perform(multipart("/api/v1/projects/{projectId}/openapi/documents", 41L)
                        .file(new MockMultipartFile("file", "contract.anything", null, raw))
                        .param("sourceKey", "orders"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.code").value("00000"))
                .andExpect(jsonPath("$.data.projectId").value(41))
                .andExpect(jsonPath("$.data.sourceKey").value("orders"))
                .andExpect(jsonPath("$.data.openapiVersion").value("3.0.3"));
    }

    private String minimalDocument() {
        return """
                {"openapi":"3.0.3","info":{"title":"Minimal","version":"1"},"paths":{}}
                """;
    }
}
