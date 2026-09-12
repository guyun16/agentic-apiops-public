package com.apiops.web.tool;

import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.apiops.web.ApiOpsWebApplication;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.ActiveProfiles;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

/** Cross-process generation evidence through the existing Java metadata boundary. */
@SpringBootTest(
        classes = ApiOpsWebApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
@DirtiesContext
@Import({
        Stage17RagToolGatewayIntegrationTest.Stage17TestConfiguration.class,
        Stage21GenerationCrossProcessE2ETest.MetadataConfiguration.class
})
class Stage21GenerationCrossProcessE2ETest {

    private static final long USER_ID = 7L;
    private static final long PROJECT_ID = 41L;
    private static final String API_ID = "api-api-1";
    private static final String USERNAME = "stage17-project-a";

    @Autowired
    private JwtTokenService jwtTokenService;

    @Autowired
    private ObjectMapper objectMapper;

    @LocalServerPort
    private int serverPort;

    @Test
    void pythonGenerationUsesRealJavaMetadataAndExistingStage16Graph() throws Exception {
        String token = jwtTokenService.generateAccessToken(new ApiOpsPrincipal(
                USER_ID,
                USERNAME,
                "test-password-hash",
                true,
                List.of(new SimpleGrantedAuthority("TOOL_READ"))));
        String traceId = "stage21-generation-" + UUID.randomUUID();
        Path pythonProject = findPythonProject();
        ProcessBuilder builder = new ProcessBuilder(
                "uv", "run", "python", "scripts/stage20_real_e2e.py", "--generation-e2e");
        builder.directory(pythonProject.toFile());
        builder.environment().put("JAVA_APIOPS_BASE_URL", "http://127.0.0.1:" + serverPort);
        builder.environment().put("JAVA_APIOPS_TOKEN", token);
        builder.environment().put("STAGE20_PROJECT_ID", Long.toString(PROJECT_ID));
        builder.environment().put("STAGE20_API_ID", API_ID);
        builder.environment().put("STAGE20_TRACE_ID", traceId);
        copyOptionalEnvironment(builder, "STAGE21_CANDIDATE_FIXTURE");
        builder.environment().put("PYTHONUTF8", "1");

        Process process = builder.start();
        CompletableFuture<String> stdout = readAsync(process.getInputStream());
        CompletableFuture<String> stderr = readAsync(process.getErrorStream());
        if (!process.waitFor(60, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            fail("Python Stage 21 generation subprocess exceeded the 60 second deadline");
        }
        String output = stdout.join().trim();
        String errors = stderr.join().trim();
        assertFalse(output.contains(token), "Python stdout must not expose credential");
        assertFalse(errors.contains(token), "Python stderr must not expose credential");
        assertEquals(0, process.exitValue(), () -> "Python generation E2E failed: " + errors);

        JsonNode result = objectMapper.readTree(output);
        assertEquals(PROJECT_ID, result.path("projectId").asLong());
        assertEquals(API_ID, result.path("apiId").asText());
        assertEquals("OpenApiMetadataDetail", result.path("metadata").path("typed").asText());
        assertEquals("listProducts", result.path("metadata").path("operationId").asText());
        assertEquals("TestCaseDSL", result.path("generation").path("validatedDsl").asText());
        assertEquals(traceId, result.path("identity").path("traceId").asText());
        assertTrue(result.path("identity").path("agentRunId").asText().startsWith(
                "stage21-generation-agent:"));
        assertTrue(result.path("generation").path("traceRecordCount").asInt() > 0);
        assertTrue(result.path("httpRequests").size() >= 1);
        assertEquals(
                "/api/v1/projects/41/openapi/apis/api-api-1",
                result.path("httpRequests").get(0).path("path").asText());
        assertTrue(result.path("httpRequests").findValuesAsText("path").stream()
                .noneMatch(path -> path.endsWith("/test-batches")));

        System.out.println("STAGE21_GENERATION_CORRELATION " + result);
    }

    private static void copyOptionalEnvironment(ProcessBuilder builder, String name) {
        String value = System.getenv(name);
        if (value != null && !value.isBlank()) {
            builder.environment().put(name, value);
        }
    }

    private static CompletableFuture<String> readAsync(java.io.InputStream stream) {
        return CompletableFuture.supplyAsync(() -> {
            try (stream) {
                return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
            } catch (IOException exception) {
                throw new UncheckedIOException(exception);
            }
        });
    }

    private static Path findPythonProject() {
        Path current = Path.of("").toAbsolutePath();
        while (current != null) {
            Path candidate = current.resolve("python-apiops-agentlab");
            if (Files.isRegularFile(candidate.resolve("pyproject.toml"))) {
                return candidate;
            }
            current = current.getParent();
        }
        throw new IllegalStateException("python-apiops-agentlab project was not found");
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class MetadataConfiguration {

        @Bean
        @Primary
        OpenApiMetadataRepository stage21GenerationMetadataRepository() {
            Instant now = Instant.parse("2026-08-26T00:00:00Z");
            ApiEndpoint endpoint = new ApiEndpoint(
                    1L,
                    API_ID,
                    "stage21-generation-api",
                    PROJECT_ID,
                    "listProducts",
                    "GET",
                    "/products",
                    "List products",
                    "Stage 21 live generation endpoint",
                    "[\"products\"]",
                    "[{\"url\":\"http://127.0.0.1:18080\"}]",
                    "[]",
                    false,
                    now,
                    now);
            ApiResponseSchema response = new ApiResponseSchema(
                    1L,
                    API_ID,
                    PROJECT_ID,
                    "200",
                    "Product page returned",
                    "application/json",
                    "{\"type\":\"object\"}",
                    now);
            return new OpenApiMetadataRepository() {
                @Override
                public com.apiops.openapi.domain.ApiDocument save(
                        com.apiops.openapi.domain.ApiDocument document) {
                    return document;
                }

                @Override
                public Optional<com.apiops.openapi.domain.ApiDocument> findDocument(
                        long projectId, String apiDocId) {
                    return Optional.empty();
                }

                @Override
                public Optional<com.apiops.openapi.domain.ApiDocument> findDocument(
                        long projectId, String sourceKey, String contentHash) {
                    return Optional.empty();
                }

                @Override
                public Optional<com.apiops.openapi.domain.ApiDocument> findLatestDocument(
                        long projectId, String sourceKey) {
                    return Optional.empty();
                }

                @Override
                public List<com.apiops.openapi.domain.ApiDocument> findDocuments(long projectId) {
                    return List.of();
                }

                @Override
                public ApiEndpoint save(ApiEndpoint value) {
                    return value;
                }

                @Override
                public Optional<ApiEndpoint> findEndpoint(long projectId, String apiId) {
                    return projectId == PROJECT_ID && API_ID.equals(apiId)
                            ? Optional.of(endpoint) : Optional.empty();
                }

                @Override
                public List<ApiEndpoint> findEndpoints(long projectId) {
                    return projectId == PROJECT_ID ? List.of(endpoint) : List.of();
                }

                @Override
                public ApiParameter save(ApiParameter value) {
                    return value;
                }

                @Override
                public List<ApiParameter> findParameters(long projectId, String apiId) {
                    return List.of();
                }

                @Override
                public ApiRequestSchema save(ApiRequestSchema value) {
                    return value;
                }

                @Override
                public List<ApiRequestSchema> findRequestSchemas(long projectId, String apiId) {
                    return List.of();
                }

                @Override
                public ApiResponseSchema save(ApiResponseSchema value) {
                    return value;
                }

                @Override
                public List<ApiResponseSchema> findResponseSchemas(long projectId, String apiId) {
                    return projectId == PROJECT_ID && API_ID.equals(apiId)
                            ? List.of(response) : List.of();
                }

                @Override
                public ApiExample save(ApiExample value) {
                    return value;
                }

                @Override
                public List<ApiExample> findExamples(long projectId, String apiId) {
                    return List.of();
                }
            };
        }
    }
}
