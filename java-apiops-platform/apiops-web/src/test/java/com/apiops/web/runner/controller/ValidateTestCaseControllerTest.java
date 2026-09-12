package com.apiops.web.runner.controller;

import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ValidateTestCaseControllerTest {
    private final ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();
    private final OpenApiQueryApplicationService queries = mock(OpenApiQueryApplicationService.class);
    private ValidateTestCaseController controller;
    private ObjectNode candidate;

    @Test
    void optionalOpenApiModuleDoesNotPreventApplicationStartup() {
        new ApplicationContextRunner()
                .withUserConfiguration(ValidateTestCaseController.class)
                .run(context -> {
                    assertNull(context.getStartupFailure());
                    assertFalse(context.containsBean("validateTestCaseController"));
                });
        new ApplicationContextRunner()
                .withPropertyValues("apiops.datasource.openapi.url=jdbc:mysql://localhost/openapi")
                .withBean(OpenApiQueryApplicationService.class, () -> queries)
                .withBean(ObjectMapper.class, () -> mapper)
                .withUserConfiguration(ValidateTestCaseController.class)
                .run(context -> {
                    assertNull(context.getStartupFailure());
                    assertNotNull(context.getBean(ValidateTestCaseController.class));
                });
    }

    @BeforeEach
    void setup() throws Exception {
        var metadata = mock(ApiMetadataDetailVO.class);
        when(metadata.servers()).thenReturn(mapper.readTree("[{\"url\":\"http://localhost:8080\"}]"));
        when(queries.getApi(1001L, "api_create_order")).thenReturn(metadata);
        candidate = (ObjectNode) mapper.readTree(Files.readString(Path.of(
                "../apiops-runner/src/test/resources/testcase-dsl/valid-basic.json")));
        controller = new ValidateTestCaseController(queries, mapper);
    }

    @Test
    void acceptsEditedRequestWithoutSubmittingIt() {
        ((ObjectNode) candidate.path("steps").get(0).path("request").path("query")).put("dryRun", true);
        assertTrue(controller.validate(1001L, "api_create_order", candidate).getData().valid());
        verify(queries).getApi(1001L, "api_create_order");
    }

    @Test
    void rejectsSchemaErrors() {
        candidate.remove("steps");
        var result = controller.validate(1001L, "api_create_order", candidate).getData();
        assertFalse(result.valid());
        assertFalse(result.errors().isEmpty());
    }

    @Test
    void rejectsChangedProjectEndpointAndBaseUrl() {
        for (String field : new String[] { "projectId", "apiId", "baseUrl" }) {
            ObjectNode edited = candidate.deepCopy();
            if (field.equals("projectId")) edited.put(field, 999);
            else if (field.equals("apiId")) edited.put(field, "other-api");
            else ((ObjectNode) edited.path("environment")).put(field, "https://example.com");
            var result = controller.validate(1001L, "api_create_order", edited).getData();
            assertFalse(result.valid(), field);
            assertEquals("TARGET_MISMATCH", result.errors().getFirst().code());
        }
    }

    @Test
    void enforcesMetadataAuthorizationBeforeInspectingCandidate() {
        when(queries.getApi(1001L, "api_create_order")).thenThrow(new AccessDeniedException("denied"));
        assertThrows(AccessDeniedException.class,
                () -> controller.validate(1001L, "api_create_order", mapper.createObjectNode()));
    }
}
