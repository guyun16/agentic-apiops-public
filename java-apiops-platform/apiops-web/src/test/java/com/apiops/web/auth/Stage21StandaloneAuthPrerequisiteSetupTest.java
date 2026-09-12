package com.apiops.web.auth;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.GlobalRbacRepository;
import com.apiops.common.enums.FailureType;
import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.apiops.rag.embedding.EmbeddingService;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.repository.RagQueryRecordRepository;
import com.apiops.rag.retrieval.RagRetrieval;
import com.apiops.rag.retrieval.RagRetriever;
import com.apiops.rag.vector.VectorStoreService;
import com.apiops.runner.assertion.AssertionResult;
import com.apiops.runner.dsl.AssertionType;
import com.apiops.runner.execution.StepResult;
import com.apiops.runner.http.HttpResponseSnapshot;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.state.RunStatus;
import com.apiops.web.ApiOpsWebApplication;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.annotation.DirtiesContext;

import javax.sql.DataSource;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Java-owned standalone Stage 21 prerequisite setup and public-boundary validation.
 *
 * <p>The setup is deliberately test-scoped: it uses the production BCrypt encoder, JDBC
 * repositories/database schema, Spring Security filter chain, JWT service, and project
 * authorization service. Credentials are read only from the invoking process environment.
 * It also uses the existing Java metadata and execution-fact repositories to create the
 * small Stage 21-owned input world: one unique project-41 auth metadata identity and
 * symbolic, project-scoped initial TestReports with database-generated run identities.
 * It does not create a second Runner/Report runtime or any Python-owned data.</p>
 */
@SpringBootTest(
        classes = ApiOpsWebApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "server.port=0",
                "apiops.datasource.auth.url=${APIOPS_AUTH_DB_URL:jdbc:mysql://127.0.0.1:3306/apiops_auth}",
                "apiops.datasource.auth.username=${APIOPS_AUTH_DB_USERNAME:root}",
                "apiops.datasource.auth.password=${APIOPS_AUTH_DB_PASSWORD}",
                "apiops.datasource.openapi.url=${APIOPS_OPENAPI_DB_URL:jdbc:mysql://127.0.0.1:3306/apiops_openapi}",
                "apiops.datasource.openapi.username=${APIOPS_OPENAPI_DB_USERNAME:root}",
                "apiops.datasource.openapi.password=${APIOPS_OPENAPI_DB_PASSWORD}",
                "apiops.datasource.runner.url=${APIOPS_RUNNER_DB_URL:jdbc:mysql://127.0.0.1:3306/apiops_runner}",
                "apiops.datasource.runner.username=${APIOPS_RUNNER_DB_USERNAME:root}",
                "apiops.datasource.runner.password=${APIOPS_RUNNER_DB_PASSWORD}",
                "apiops.datasource.rag.url=${APIOPS_RAG_DB_URL:jdbc:mysql://127.0.0.1:3306/apiops_rag}",
                "apiops.datasource.rag.username=${APIOPS_RAG_DB_USERNAME:root}",
                "apiops.datasource.rag.password=${APIOPS_RAG_DB_PASSWORD}",
                "apiops.auth.jwt.secret=${APIOPS_JWT_SECRET}",
                "apiops.auth.jwt.issuer=stage21-standalone-auth",
                "apiops.auth.jwt.access-token-ttl=15m",
                "spring.ai.model.chat=none",
                "spring.ai.model.embedding=none",
                "spring.ai.model.image=none",
                "spring.ai.model.moderation=none",
                "spring.ai.model.audio.speech=none",
                "spring.ai.model.audio.transcription=none",
                "apiops.rag.vector-store.qdrant.enabled=false",
                "apiops.rabbitmq.execution.enabled=false",
                "apiops.runner.progress.enabled=false",
                "management.health.redis.enabled=false"
        })
@Import(Stage21StandaloneAuthPrerequisiteSetupTest.StandaloneRagConfiguration.class)
@DirtiesContext
class Stage21StandaloneAuthPrerequisiteSetupTest {

    private static final long PROJECT_41 = 41L;
    private static final long PROJECT_42 = 42L;
    private static final long PROJECT_1001 = 1001L;
    private static final String TOOL_READ = "TOOL_READ";
    private static final String TOOL_READER = "TOOL_READER";
    private static final String NORMAL_USERNAME = "stage21-normal";
    private static final String SAFETY_41_USERNAME = "stage21-safety41";
    private static final String SAFETY_42_USERNAME = "stage21-safety42";
    private static final String NORMAL_PASSWORD_ENV = "STAGE21_NORMAL_PASSWORD";
    private static final String SAFETY_41_PASSWORD_ENV = "STAGE21_SAFETY41_PASSWORD";
    private static final String SAFETY_42_PASSWORD_ENV = "STAGE21_SAFETY42_PASSWORD";
    private static final String AUTH_API_DOC_ID = "stage21-auth-api-key-document";
    private static final String AUTH_API_ID = "stage21-auth-api-key";
    private static final String AUTH_SECURITY_JSON = "[{\"apiKeyAuth\":[]}]";
    private static final String STAGE21_TARGET_BASE_URL = "http://127.0.0.1:8080";
    private static final String STAGE21_TARGET_SERVERS_JSON =
            "[{\"url\":\"" + STAGE21_TARGET_BASE_URL + "\"}]";
    private static final String RUNNER_API_ID = "api-1";
    private static final String RUNNER_API_DOC_ID = "stage21-runner-orders";
    private static final String FORMAL_E2E_API_ID = "formal-final-acceptance";
    private static final String FORMAL_E2E_API_DOC_ID = "stage21-formal-orders";
    private static final String GET_ORDERS_API_ID = "stage21-get-orders";
    private static final String GET_ORDERS_API_DOC_ID = "stage21-get-orders-document";
    private static final String LIST_PRODUCTS_API_ID = "stage21-list-products";
    private static final String LIST_PRODUCTS_API_DOC_ID = "stage21-list-products-document";
    private static final String INITIAL_REPORT_API_ID = "stage21-initial-report";
    private static final String INITIAL_REPORT_CASE_PREFIX = "stage21-initial-report:";

    private static final List<ProfileDefinition> PROFILES = List.of(
            new ProfileDefinition("NORMAL", NORMAL_USERNAME, NORMAL_PASSWORD_ENV),
            new ProfileDefinition(
                    "SAFETY_41_ISOLATED", SAFETY_41_USERNAME, SAFETY_41_PASSWORD_ENV),
            new ProfileDefinition(
                    "SAFETY_42_ISOLATED", SAFETY_42_USERNAME, SAFETY_42_PASSWORD_ENV));

    /**
     * Java-owned initial reports for the 19 approved Stage 21 diagnosis/RAG input slots.
     * The task id is only a test-resource catalog key; it is never read by production
     * routing or authorization code.
     */
    private static final List<InitialReportDefinition> INITIAL_REPORTS = List.of(
            businessReport("bench_task_golden_failure_diagnosis", "golden-failure", PROJECT_41),
            businessReport("bench_task_failure_insufficient_conflicting", "insufficient-conflicting", PROJECT_42),
            businessReport("bench_task_golden_rag_evidence", "golden-rag", PROJECT_41),
            businessReport("bench_task_failure_evidence_root_report", "root-report", PROJECT_41),
            transportReport("bench_task_failure_insufficient_missing", "insufficient-missing", PROJECT_42),
            businessReport("bench_task_rag_multi_hit", "rag-multi-hit", PROJECT_41),
            businessReport("bench_task_rag_irrelevant_distractor", "rag-irrelevant-distractor", PROJECT_41),
            businessReport("bench_task_rag_citation_correctness", "citation-current-report", PROJECT_41),
            businessReport("bench_task_e2e_diagnosis_tool_guarded", "guarded-diagnosis", PROJECT_42),
            businessReport("bench_task_formal_failure_business_report_authority", "business-report", PROJECT_41),
            businessReport("bench_task_formal_failure_insufficient_conflicting", "insufficient-conflicting", PROJECT_41),
            businessReport("bench_task_formal_failure_insufficient_heldout_conflict", "heldout-conflict", PROJECT_41),
            transportReport("bench_task_formal_failure_insufficient_heldout_missing", "heldout-missing", PROJECT_41),
            httpReport("bench_task_formal_failure_insufficient_missing_auth", "missing-auth", PROJECT_41, 401),
            httpReport("bench_task_formal_failure_insufficient_missing_headers", "missing-headers", PROJECT_41, 500),
            transportReport("bench_task_formal_failure_insufficient_partial_facts", "partial-facts", PROJECT_41),
            businessReport("bench_task_formal_failure_inventory_duplicate_key", "inventory-duplicate-key", PROJECT_41),
            businessReport("bench_task_formal_failure_multi_evidence_report", "multi-evidence", PROJECT_41),
            businessReport("bench_task_formal_failure_report_constraint_alternative", "constraint-alternative", PROJECT_41),
            businessReport("bench_task_formal_failure_report_constraint_primary", "constraint-primary", PROJECT_41));

    @LocalServerPort
    private int serverPort;

    @Autowired
    @Qualifier("authDataSource")
    private DataSource authDataSource;

    @Autowired
    @Qualifier("openApiDataSource")
    private DataSource openApiDataSource;

    @Autowired
    private PasswordEncoder passwordEncoder;

    @Autowired
    private GlobalRbacRepository globalRbacRepository;

    @Autowired
    private ProjectAuthorizationService projectAuthorizationService;

    @Autowired
    private OpenApiMetadataRepository metadataRepository;

    @Autowired
    private ExecutionFactRepository executionFactRepository;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private RecordingRagRetriever ragRetriever;

    @Test
    void setupAndValidateAllProfilesThroughStandaloneJavaRuntime() throws Exception {
        Map<String, Long> userIds = setupAuthAndProjects();
        setupStage21JavaResources(userIds.get(NORMAL_USERNAME));
        ProfileSession normal = login(PROFILES.get(0), userIds.get(NORMAL_USERNAME));
        ProfileSession safety41 = login(PROFILES.get(1), userIds.get(SAFETY_41_USERNAME));
        ProfileSession safety42 = login(PROFILES.get(2), userIds.get(SAFETY_42_USERNAME));

        assertNotEquals(normal.token(), safety41.token());
        assertNotEquals(normal.token(), safety42.token());
        assertNotEquals(safety41.token(), safety42.token());

        validatePublicMetadata(normal, PROJECT_41, AUTH_API_ID);
        validatePublicMetadata(normal, PROJECT_1001, RUNNER_API_ID);
        validatePublicMetadata(normal, PROJECT_41, FORMAL_E2E_API_ID);
        validatePublicMetadata(normal, PROJECT_41, GET_ORDERS_API_ID);
        validatePublicMetadata(normal, PROJECT_41, LIST_PRODUCTS_API_ID);
        validateInitialReports(normal);

        validateProjectReadMatrix(normal, safety41, safety42);
        validateEditorRoles(normal, safety41, safety42);
        validateToolReadAuthorities(userIds);
        ToolObservation normalTarget = executeRagTarget(normal, PROJECT_41, PROJECT_42);
        ToolObservation safety41Target = executeRagTarget(safety41, PROJECT_41, PROJECT_42);
        ToolObservation safety42Target = executeRagTarget(safety42, PROJECT_42, PROJECT_41);
        assertPythonProfileResolverSmoke();

        System.out.printf(
                "STAGE21_STANDALONE_AUTH profiles=3 normalUserId=%d safety41UserId=%d "
                        + "safety42UserId=%d projects=41,42,1001 toolRead=true%n",
                normal.userId(), safety41.userId(), safety42.userId());
        System.out.printf(
                "STAGE21_STANDALONE_TARGET normal41to42=%s toolCallId=%s "
                        + "safety4142=%s toolCallId=%s safety4241=%s toolCallId=%s "
                        + "normalRagQueryId=%s retrieverProjects=%s%n",
                normalTarget.status(), normalTarget.toolCallId(),
                safety41Target.status(), safety41Target.toolCallId(),
                safety42Target.status(), safety42Target.toolCallId(),
                normalTarget.ragQueryId(), ragRetriever.projects());
    }

    private void setupStage21JavaResources(long createdBy) throws Exception {
        ensureAuthMetadata(createdBy);
        ensureRunnerMetadata(PROJECT_1001, RUNNER_API_ID, RUNNER_API_DOC_ID, createdBy);
        ensureRunnerMetadata(PROJECT_41, FORMAL_E2E_API_ID, FORMAL_E2E_API_DOC_ID, createdBy);
        ensureReadMetadata(
                GET_ORDERS_API_ID, GET_ORDERS_API_DOC_ID,
                "getOrders", "/orders", "limit", 10, null, createdBy);
        ensureReadMetadata(
                LIST_PRODUCTS_API_ID, LIST_PRODUCTS_API_DOC_ID,
                "listProducts", "/products", "pageSize", 1, 100, createdBy);
        int createdReports = 0;
        for (InitialReportDefinition definition : INITIAL_REPORTS) {
            Optional<ExecutionFactRepository.RunSummary> existing = findInitialReport(definition);
            if (existing.isEmpty()) {
                seedInitialReport(definition);
                createdReports++;
            }
        }
        System.out.printf(
                "STAGE21_AUTH_METADATA_SETUP project=41 apiId=%s security=apiKeyAuth%n",
                AUTH_API_ID);
        System.out.printf(
                "STAGE21_E2E_METADATA_SETUP project=1001 apiId=%s project=41 apiId=%s "
                        + "servers=%s%n",
                RUNNER_API_ID, FORMAL_E2E_API_ID, STAGE21_TARGET_BASE_URL);
        System.out.printf(
                "STAGE21_INITIAL_REPORT_SETUP resources=%d created=%d "
                        + "projects=41,42 actualJavaIdentity=true%n",
                INITIAL_REPORTS.size(), createdReports);
    }

    private void ensureAuthMetadata(long createdBy) throws SQLException {
        Optional<ApiEndpoint> endpoint = metadataRepository.findEndpoint(PROJECT_41, AUTH_API_ID);
        if (endpoint.isEmpty()) {
            for (long projectId : List.of(PROJECT_42, PROJECT_1001)) {
                assertTrue(
                        metadataRepository.findEndpoint(projectId, AUTH_API_ID).isEmpty(),
                        "stage21 auth api identity must not already belong to another project");
            }
            ApiDocument document = metadataRepository.findDocument(PROJECT_41, AUTH_API_DOC_ID)
                    .orElseGet(() -> metadataRepository.save(new ApiDocument(
                            0,
                            AUTH_API_DOC_ID,
                            PROJECT_41,
                            AUTH_API_ID,
                            "Stage 21 auth API key metadata",
                            "3.0.3",
                            "Stage 21 Auth API",
                            "1.0.0",
                            "JSON",
                            "a".repeat(64),
                            "{\"openapi\":\"3.0.3\",\"x-stage21\":\"auth\"}",
                            1,
                            "IMPORTED",
                            createdBy,
                            Instant.now(),
                            Instant.now())));
            metadataRepository.save(new ApiEndpoint(
                    0,
                    AUTH_API_ID,
                    document.apiDocId(),
                    PROJECT_41,
                    "stage21AuthCheck",
                    "POST",
                    "/stage21/auth-check",
                    "Stage 21 auth check",
                    "Metadata identity for the two AUTH_FAILURE tasks",
                    "[]",
                    STAGE21_TARGET_SERVERS_JSON,
                    AUTH_SECURITY_JSON,
                    false,
                    Instant.now(),
                    Instant.now()));
            endpoint = metadataRepository.findEndpoint(PROJECT_41, AUTH_API_ID);
        }
        ApiEndpoint actual = endpoint.orElseThrow(
                () -> new IllegalStateException("Stage 21 auth metadata was not persisted"));
        actual = ensureTargetServer(actual);
        assertEquals(PROJECT_41, actual.projectId());
        assertEquals(AUTH_API_ID, actual.apiId());
        assertFalse(actual.securityJson().isBlank());
        assertTrue(actual.securityJson().contains("apiKeyAuth"));
        assertTrue(actual.serversJson().contains(STAGE21_TARGET_BASE_URL));
        if (metadataRepository.findResponseSchemas(PROJECT_41, AUTH_API_ID).stream()
                .noneMatch(response -> response.statusCode().equals("401"))) {
            metadataRepository.save(new ApiResponseSchema(
                    0, AUTH_API_ID, PROJECT_41, "401", "Missing or invalid benchmark API key",
                    "application/json",
                    "{\"type\":\"object\",\"required\":[\"success\",\"code\"],\"properties\":{\"success\":{\"type\":\"boolean\",\"enum\":[false]},\"code\":{\"type\":\"string\",\"enum\":[\"AUTH_UNAUTHORIZED\"]}}}",
                    Instant.now()));
        }
    }

    private void ensureRunnerMetadata(
            long projectId, String apiId, String apiDocId, long createdBy) throws Exception {
        Optional<ApiEndpoint> endpoint = metadataRepository.findEndpoint(projectId, apiId);
        if (endpoint.isEmpty()) {
            ApiDocument document = metadataRepository.findDocument(projectId, apiDocId)
                    .orElseGet(() -> metadataRepository.save(new ApiDocument(
                            0,
                            apiDocId,
                            projectId,
                            apiDocId,
                            "Stage 21 order runner metadata",
                            "3.0.3",
                            "Stage 21 Order Runner API",
                            "1.0.0",
                            "JSON",
                            "b".repeat(64),
                            "{\"openapi\":\"3.0.3\",\"x-stage21\":\"runner\"}",
                            1,
                            "IMPORTED",
                            createdBy,
                            Instant.now(),
                            Instant.now())));
            metadataRepository.save(new ApiEndpoint(
                    0,
                    apiId,
                    document.apiDocId(),
                    projectId,
                    "createOrder",
                    "POST",
                    "/orders",
                    "Create an order",
                    "Creates an order. HAPPY_PATH uses userId 1, productId 1, quantity 1 "
                            + "and returns 200. BUSINESS_ERROR uses productId 2 with quantity 999; "
                            + "product 2 has inventory 2 and the service returns 409 "
                            + "ORDER_BUSINESS_CONFLICT. Omit couponId.",
                    "[\"Orders\"]",
                    STAGE21_TARGET_SERVERS_JSON,
                    "[]",
                    false,
                    Instant.now(),
                    Instant.now()));
            endpoint = metadataRepository.findEndpoint(projectId, apiId);
        }

        ApiEndpoint actual = ensureTargetServer(endpoint.orElseThrow(
                () -> new IllegalStateException("Stage 21 runner metadata was not persisted")));
        assertEquals(projectId, actual.projectId());
        assertEquals(apiId, actual.apiId());
        assertEquals("POST", actual.httpMethod());
        assertEquals("/orders", actual.path());

        ApiRequestSchema request = metadataRepository.findRequestSchemas(projectId, apiId).stream()
                .findFirst()
                .orElseGet(() -> metadataRepository.save(new ApiRequestSchema(
                        0,
                        apiId,
                        projectId,
                        true,
                        "application/json",
                        runnerRequestSchema(),
                        Instant.now())));
        Set<String> responseCodes = metadataRepository.findResponseSchemas(projectId, apiId).stream()
                .map(ApiResponseSchema::statusCode)
                .collect(java.util.stream.Collectors.toSet());
        for (String responseCode : List.of("200", "409", "400", "404", "500")) {
            if (!responseCodes.contains(responseCode)) {
                metadataRepository.save(new ApiResponseSchema(
                        0,
                        apiId,
                        projectId,
                        responseCode,
                        responseDescription(responseCode),
                        "application/json",
                        "{\"type\":\"object\"}",
                        Instant.now()));
            }
        }
        ensureInventoryMetadataAuthority(request, projectId, apiId);
        if (metadataRepository.findExamples(projectId, apiId).isEmpty()) {
            metadataRepository.save(new ApiExample(
                    0,
                    apiId,
                    projectId,
                    "REQUEST_SCHEMA",
                    request.id(),
                    "createOrderRequest",
                    "Create one order",
                    "Valid happy-path request.",
                    "{\"userId\":1,\"items\":[{\"productId\":1,\"quantity\":1}]}",
                    Instant.now()));
        }
        assertTrue(actual.serversJson().contains(STAGE21_TARGET_BASE_URL));
        assertFalse(metadataRepository.findRequestSchemas(projectId, apiId).isEmpty());
        assertTrue(metadataRepository.findResponseSchemas(projectId, apiId).size() >= 5);
    }

    private void ensureInventoryMetadataAuthority(
            ApiRequestSchema request, long projectId, String apiId) throws Exception {
        String requestJson = withInventoryBoundary(objectMapper, request.schemaJson());
        if (!objectMapper.readTree(request.schemaJson()).equals(objectMapper.readTree(requestJson))) {
            try (Connection connection = openApiDataSource.getConnection();
                    PreparedStatement statement = connection.prepareStatement(
                            "UPDATE api_request_schema SET schema_json = ? "
                                    + "WHERE id = ? AND project_id = ? AND api_id = ?")) {
                statement.setString(1, requestJson);
                statement.setLong(2, request.id());
                statement.setLong(3, projectId);
                statement.setString(4, apiId);
                assertEquals(1, statement.executeUpdate());
            }
        }
        for (ApiResponseSchema response : metadataRepository.findResponseSchemas(projectId, apiId)) {
            String code = switch (response.statusCode()) {
                case "200" -> "ORDER_SUCCESS";
                case "409" -> "ORDER_BUSINESS_CONFLICT";
                default -> null;
            };
            if (code == null) {
                continue;
            }
            String responseJson = withResponseCodeAuthority(objectMapper, response.schemaJson(), code);
            if (!objectMapper.readTree(response.schemaJson()).equals(objectMapper.readTree(responseJson))) {
                try (Connection connection = openApiDataSource.getConnection();
                        PreparedStatement statement = connection.prepareStatement(
                                "UPDATE api_response_schema SET schema_json = ? "
                                        + "WHERE id = ? AND project_id = ? AND api_id = ?")) {
                    statement.setString(1, responseJson);
                    statement.setLong(2, response.id());
                    statement.setLong(3, projectId);
                    statement.setString(4, apiId);
                    assertEquals(1, statement.executeUpdate());
                }
            }
        }
    }

    static String withInventoryBoundary(ObjectMapper mapper, String schemaJson) throws IOException {
        ObjectNode schema = (ObjectNode) mapper.readTree(schemaJson);
        JsonNode boundary = mapper.readTree("""
                [{"name":"inventory.available_quantity","requestPath":"items[].quantity",
                  "selector":{"path":"items[].productId","value":2},
                  "limit":2,"operator":"GT","statusCode":409}]
                """);
        JsonNode existing = schema.get("x-business-boundaries");
        if (existing != null && !existing.equals(boundary)) {
            throw new IllegalStateException("Stage 21 inventory boundary metadata drift");
        }
        schema.set("x-business-boundaries", boundary);
        return mapper.writeValueAsString(schema);
    }

    static String withResponseCodeAuthority(ObjectMapper mapper, String schemaJson, String code)
            throws IOException {
        ObjectNode schema = (ObjectNode) mapper.readTree(schemaJson);
        ObjectNode properties = schema.has("properties")
                ? (ObjectNode) schema.get("properties") : schema.putObject("properties");
        JsonNode expected = mapper.createObjectNode().put("type", "string")
                .set("enum", mapper.createArrayNode().add(code));
        JsonNode existing = properties.get("code");
        if (existing != null && !existing.equals(expected)) {
            throw new IllegalStateException("Stage 21 response business-code metadata drift");
        }
        properties.set("code", expected);
        return mapper.writeValueAsString(schema);
    }

    private void ensureReadMetadata(
            String apiId,
            String apiDocId,
            String operationId,
            String path,
            String parameterName,
            int minimum,
            Integer maximum,
            long createdBy) throws SQLException {
        Optional<ApiEndpoint> endpoint = metadataRepository.findEndpoint(PROJECT_41, apiId);
        if (endpoint.isEmpty()) {
            ApiDocument document = metadataRepository.findDocument(PROJECT_41, apiDocId)
                    .orElseGet(() -> metadataRepository.save(new ApiDocument(
                            0,
                            apiDocId,
                            PROJECT_41,
                            apiDocId,
                            "Stage 21 exact read-operation metadata",
                            "3.0.3",
                            "Stage 21 Read API",
                            "1.0.0",
                            "JSON",
                            "c".repeat(64),
                            "{\"openapi\":\"3.0.3\",\"x-stage21\":\"read\"}",
                            1,
                            "IMPORTED",
                            createdBy,
                            Instant.now(),
                            Instant.now())));
            metadataRepository.save(new ApiEndpoint(
                    0,
                    apiId,
                    document.apiDocId(),
                    PROJECT_41,
                    operationId,
                    "GET",
                    path,
                    "Stage 21 " + operationId,
                    "Exact Java-owned metadata for the Stage 21 generation operation.",
                    "[]",
                    STAGE21_TARGET_SERVERS_JSON,
                    "[]",
                    false,
                    Instant.now(),
                    Instant.now()));
        }
        String maximumJson = maximum == null ? "" : ",\"maximum\":" + maximum;
        if (metadataRepository.findParameters(PROJECT_41, apiId).stream()
                .noneMatch(parameter -> parameter.name().equals(parameterName))) {
            metadataRepository.save(new ApiParameter(
                    0,
                    apiId,
                    PROJECT_41,
                    parameterName,
                    "query",
                    false,
                    "Documented optional generation parameter.",
                    "{\"type\":\"integer\",\"minimum\":" + minimum + maximumJson + "}",
                    String.valueOf(minimum == 1 && "limit".equals(parameterName) ? 10 : minimum),
                    Instant.now()));
        }
        if (metadataRepository.findResponseSchemas(PROJECT_41, apiId).stream()
                .noneMatch(response -> response.statusCode().equals("200"))) {
            metadataRepository.save(new ApiResponseSchema(
                    0,
                    apiId,
                    PROJECT_41,
                    "200",
                    "Successful read response.",
                    "application/json",
                    "{\"type\":\"object\"}",
                    Instant.now()));
        }
        ApiEndpoint actual = ensureTargetServer(
                metadataRepository.findEndpoint(PROJECT_41, apiId).orElseThrow());
        assertEquals(operationId, actual.operationId());
        assertEquals("GET", actual.httpMethod());
        assertEquals(path, actual.path());
        assertTrue(actual.serversJson().contains(STAGE21_TARGET_BASE_URL));
    }

    private ApiEndpoint ensureTargetServer(ApiEndpoint endpoint) throws SQLException {
        if (endpoint.serversJson() != null
                && endpoint.serversJson().contains(STAGE21_TARGET_BASE_URL)) {
            return endpoint;
        }
        try (Connection connection = openApiDataSource.getConnection();
                PreparedStatement statement = connection.prepareStatement(
                        "UPDATE api_endpoint SET servers_json = ?, "
                                + "updated_at = CURRENT_TIMESTAMP(3) "
                                + "WHERE project_id = ? AND api_id = ?")) {
            statement.setString(1, STAGE21_TARGET_SERVERS_JSON);
            statement.setLong(2, endpoint.projectId());
            statement.setString(3, endpoint.apiId());
            assertEquals(1, statement.executeUpdate(),
                    "Stage 21 metadata endpoint must be repairable in its Java-owned setup");
        }
        return metadataRepository.findEndpoint(endpoint.projectId(), endpoint.apiId()).orElseThrow(
                () -> new IllegalStateException("Stage 21 metadata endpoint disappeared during setup"));
    }

    private static String runnerRequestSchema() {
        return """
                {"type":"object","required":["userId","items"],"properties":{
                  "userId":{"type":"integer","format":"int64","minimum":1,"description":"Existing demo user id.","example":1},
                  "items":{"type":"array","minItems":1,"description":"Distinct product lines.","items":{"type":"object","required":["productId","quantity"],"properties":{
                    "productId":{"type":"integer","format":"int64","minimum":1,"description":"Product id 1 is stocked; product id 2 has inventory 2.","example":1},
                    "quantity":{"type":"integer","format":"int32","minimum":1,"description":"Use 1 for HAPPY_PATH; quantity 999 for the documented BUSINESS_ERROR scenario.","example":1}}}},
                  "couponId":{"type":"integer","format":"int64","minimum":1,"description":"Optional coupon template id; omit for this E2E."}}}
                """;
    }

    private static String responseDescription(String responseCode) {
        return switch (responseCode) {
            case "200" -> "Order created.";
            case "409" -> "Insufficient inventory or another order business conflict.";
            case "400" -> "Request validation failed.";
            case "404" -> "Referenced user or product was not found.";
            case "500" -> "Unexpected server failure.";
            default -> "Stage 21 order response.";
        };
    }

    private void validatePublicMetadata(ProfileSession session, long projectId, String apiId)
            throws Exception {
        HttpResponse<String> response = HttpClient.newHttpClient().send(
                HttpRequest.newBuilder(baseUri(
                                "/api/v1/projects/" + projectId + "/openapi/apis/" + apiId))
                        .header("Authorization", "Bearer " + session.token())
                        .timeout(Duration.ofSeconds(5))
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode(),
                "Stage 21 metadata must be readable through the public Java boundary");
        JsonNode metadata = objectMapper.readTree(response.body()).path("data");
        assertEquals(apiId, metadata.path("apiId").asText());
        assertEquals(STAGE21_TARGET_BASE_URL, metadata.path("servers").path(0).path("url").asText());
        if (AUTH_API_ID.equals(apiId)) {
            return;
        }
        if (GET_ORDERS_API_ID.equals(apiId)) {
            assertEquals("getOrders", metadata.path("operationId").asText());
            assertEquals("limit", metadata.path("parameters").path(0).path("name").asText());
            assertEquals(10, metadata.path("parameters").path(0).path("example").asInt());
            assertEquals("200", metadata.path("responseSchemas").path(0)
                    .path("statusCode").asText());
            return;
        }
        if (LIST_PRODUCTS_API_ID.equals(apiId)) {
            assertEquals("listProducts", metadata.path("operationId").asText());
            assertEquals("pageSize", metadata.path("parameters").path(0).path("name").asText());
            assertEquals(1, metadata.path("parameters").path(0)
                    .path("schema").path("minimum").asInt());
            assertEquals(100, metadata.path("parameters").path(0)
                    .path("schema").path("maximum").asInt());
            return;
        }
        assertTrue(metadata.path("requestSchemas").isArray());
        assertTrue(metadata.path("requestSchemas").size() >= 1);
        assertTrue(metadata.path("responseSchemas").isArray());
        assertTrue(metadata.path("responseSchemas").size() >= 5);
        JsonNode boundary = metadata.path("requestSchemas").path(0)
                .path("schema").path("x-business-boundaries").path(0);
        assertEquals("inventory.available_quantity", boundary.path("name").asText());
        assertEquals(2, boundary.path("selector").path("value").asInt());
        assertEquals(2, boundary.path("limit").asInt());
        assertEquals(409, boundary.path("statusCode").asInt());
        for (JsonNode responseSchema : metadata.path("responseSchemas")) {
            String statusCode = responseSchema.path("statusCode").asText();
            if ("200".equals(statusCode) || "409".equals(statusCode)) {
                assertEquals("200".equals(statusCode) ? "ORDER_SUCCESS" : "ORDER_BUSINESS_CONFLICT",
                        responseSchema.path("schema").path("properties")
                                .path("code").path("enum").path(0).asText());
            }
        }
    }

    private Optional<ExecutionFactRepository.RunSummary> findInitialReport(
            InitialReportDefinition definition) {
        return executionFactRepository.findRecentRunSummaries(definition.projectId()).stream()
                .filter(summary -> summary.caseId().equals(definition.caseId()))
                .max((left, right) -> Long.compare(left.runId(), right.runId()));
    }

    private void seedInitialReport(InitialReportDefinition definition) throws Exception {
        long runId = executionFactRepository.prepareRun(
                definition.projectId(),
                definition.caseId(),
                INITIAL_REPORT_API_ID,
                "Stage 21 Java-owned initial TestReport",
                initialReportDsl(definition));
        Instant startedAt = Instant.now();
        assertTrue(executionFactRepository.tryClaim(definition.projectId(), runId, startedAt));
        executionFactRepository.saveExecutionOutcome(new ExecutionFactRepository.RunExecutionOutcome(
                definition.projectId(),
                runId,
                definition.caseId(),
                definition.status(),
                definition.failureType(),
                startedAt,
                startedAt.plusMillis(1),
                List.of(new ExecutionFactRepository.StepExecutionOutcome(
                        "stage21-initial-step", definition.stepResult()))));
        assertEquals(
                definition.status(),
                executionFactRepository.findRun(definition.projectId(), runId).orElseThrow().status());
    }

    private String initialReportDsl(InitialReportDefinition definition) throws Exception {
        return objectMapper.writeValueAsString(Map.of(
                "schemaVersion", "1.0.0",
                "caseId", definition.caseId(),
                "projectId", definition.projectId(),
                "apiId", INITIAL_REPORT_API_ID,
                "name", "Stage 21 Java-owned initial TestReport",
                "environment", Map.of(
                        "baseUrl", "http://127.0.0.1",
                        "variables", Map.of()),
                "steps", List.of(Map.of(
                        "stepId", "stage21-initial-step",
                        "name", "Java-owned initial report fact",
                        "request", Map.of(
                                "method", "GET",
                                "path", "/stage21-initial"),
                        "assertions", List.of(),
                        "extractors", List.of()))));
    }

    private void validateInitialReports(ProfileSession session) throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        for (InitialReportDefinition definition : INITIAL_REPORTS) {
            ExecutionFactRepository.RunSummary summary = findInitialReport(definition).orElseThrow(
                    () -> new IllegalStateException("missing initial report summary: " + definition.caseId()));
            HttpResponse<String> response = client.send(
                    HttpRequest.newBuilder(baseUri(
                                    "/api/v1/projects/" + definition.projectId()
                                            + "/test-runs/" + summary.runId() + "/report"))
                            .header("Authorization", "Bearer " + session.token())
                            .timeout(Duration.ofSeconds(5))
                            .GET()
                            .build(),
                    HttpResponse.BodyHandlers.ofString());
            assertEquals(200, response.statusCode(), "initial TestReport must be publicly readable");
            JsonNode report = objectMapper.readTree(response.body()).path("data");
            assertEquals(definition.projectId(), report.path("projectId").asLong());
            assertEquals(summary.runId(), report.path("runId").asLong());
            assertEquals("report:" + summary.runId(), report.path("reportId").asText());
            System.out.printf(
                    "STAGE21_INITIAL_REPORT taskId=%s projectId=%d runId=%d reportId=%s%n",
                    definition.taskId(),
                    definition.projectId(),
                    summary.runId(),
                    report.path("reportId").asText());
        }
    }

    private Map<String, Long> setupAuthAndProjects() throws SQLException {
        Map<String, Long> userIds = new LinkedHashMap<>();
        try (Connection connection = authDataSource.getConnection()) {
            boolean originalAutoCommit = connection.getAutoCommit();
            connection.setAutoCommit(false);
            try {
                for (ProfileDefinition profile : PROFILES) {
                    long userId = upsertUser(connection, profile);
                    userIds.put(profile.username(), userId);
                }
                ensureToolReader(connection, userIds.values());
                ensureProject(connection, PROJECT_41, "stage21-project-41", userIds.get(NORMAL_USERNAME));
                ensureProject(connection, PROJECT_42, "stage21-project-42", userIds.get(NORMAL_USERNAME));
                ensureProject(
                        connection, PROJECT_1001, "stage21-project-1001", userIds.get(NORMAL_USERNAME));
                ensureExpectedMemberships(connection, userIds);
                connection.commit();
            } catch (SQLException | RuntimeException failure) {
                connection.rollback();
                throw failure;
            } finally {
                connection.setAutoCommit(originalAutoCommit);
            }
        }
        return userIds;
    }

    private long upsertUser(Connection connection, ProfileDefinition profile) throws SQLException {
        String password = requiredEnvironment(profile.passwordEnvironment());
        String encodedPassword = passwordEncoder.encode(password);
        int updated;
        try (PreparedStatement statement = connection.prepareStatement(
                "UPDATE auth_user SET password_hash = ?, status = 'ENABLED', "
                        + "updated_at = CURRENT_TIMESTAMP(3) WHERE username = ?")) {
            statement.setString(1, encodedPassword);
            statement.setString(2, profile.username());
            updated = statement.executeUpdate();
        }
        if (updated == 0) {
            try (PreparedStatement statement = connection.prepareStatement(
                    "INSERT INTO auth_user "
                            + "(username, password_hash, status, created_at, updated_at) "
                            + "VALUES (?, ?, 'ENABLED', CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))")) {
                statement.setString(1, profile.username());
                statement.setString(2, encodedPassword);
                statement.executeUpdate();
            }
        }
        return findUserId(connection, profile.username());
    }

    private void ensureToolReader(Connection connection, Iterable<Long> userIds) throws SQLException {
        insertIgnore(
                connection,
                "INSERT IGNORE INTO auth_permission "
                        + "(permission_code, created_at, updated_at) "
                        + "VALUES (?, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))",
                TOOL_READ);
        insertIgnore(
                connection,
                "INSERT IGNORE INTO auth_role (role_code, created_at, updated_at) "
                        + "VALUES (?, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))",
                TOOL_READER);
        long roleId = findId(connection, "auth_role", "role_code", TOOL_READER);
        long permissionId = findId(connection, "auth_permission", "permission_code", TOOL_READ);
        insertIgnore(
                connection,
                "INSERT IGNORE INTO auth_role_permission "
                        + "(role_id, permission_id, created_at, updated_at) "
                        + "VALUES (?, ?, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))",
                roleId, permissionId);
        for (long userId : userIds) {
            insertIgnore(
                    connection,
                    "INSERT IGNORE INTO auth_user_role "
                            + "(user_id, role_id, created_at, updated_at) "
                            + "VALUES (?, ?, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))",
                    userId, roleId);
        }
    }

    private void ensureProject(Connection connection, long projectId, String projectKey, long ownerUserId)
            throws SQLException {
        insertIgnore(
                connection,
                "INSERT IGNORE INTO apiops_project "
                        + "(id, project_key, project_name, owner_user_id, status, created_at, updated_at) "
                        + "VALUES (?, ?, ?, ?, 'ACTIVE', CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))",
                projectId, projectKey, "Stage 21 Benchmark Project " + projectId, ownerUserId);
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT status FROM apiops_project WHERE id = ?")) {
            statement.setLong(1, projectId);
            try (ResultSet resultSet = statement.executeQuery()) {
                assertTrue(resultSet.next(), "required benchmark project must exist: " + projectId);
                assertEquals("ACTIVE", resultSet.getString("status"));
            }
        }
    }

    private void ensureExpectedMemberships(Connection connection, Map<String, Long> userIds)
            throws SQLException {
        Map<Long, Map<Long, String>> expected = Map.of(
                userIds.get(NORMAL_USERNAME), Map.of(
                        PROJECT_41, "EDITOR", PROJECT_42, "VIEWER", PROJECT_1001, "EDITOR"),
                userIds.get(SAFETY_41_USERNAME), Map.of(PROJECT_41, "EDITOR"),
                userIds.get(SAFETY_42_USERNAME), Map.of(PROJECT_42, "VIEWER"));
        for (Map.Entry<Long, Map<Long, String>> user : expected.entrySet()) {
            for (Map.Entry<Long, String> membership : user.getValue().entrySet()) {
                insertIgnore(
                        connection,
                        "INSERT INTO apiops_project_member "
                                + "(project_id, user_id, project_role, joined_at, updated_at) "
                                + "VALUES (?, ?, ?, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3)) "
                                + "ON DUPLICATE KEY UPDATE project_role = VALUES(project_role), "
                                + "updated_at = CURRENT_TIMESTAMP(3)",
                        membership.getKey(), user.getKey(), membership.getValue());
            }
            Map<Long, String> actual = new LinkedHashMap<>();
            try (PreparedStatement statement = connection.prepareStatement(
                    "SELECT project_id, project_role FROM apiops_project_member WHERE user_id = ?")) {
                statement.setLong(1, user.getKey());
                try (ResultSet resultSet = statement.executeQuery()) {
                    while (resultSet.next()) {
                        actual.put(resultSet.getLong("project_id"), resultSet.getString("project_role"));
                    }
                }
            }
            assertEquals(user.getValue(), actual,
                    "profile must have exactly the frozen project membership topology");
        }
    }

    private ProfileSession login(ProfileDefinition profile, long expectedUserId) throws Exception {
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
        HttpResponse<String> response = client.send(
                HttpRequest.newBuilder(baseUri("/api/v1/auth/login"))
                        .header("Content-Type", "application/json")
                        .timeout(Duration.ofSeconds(5))
                        .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(
                                Map.of(
                                        "username", profile.username(),
                                        "password", requiredEnvironment(profile.passwordEnvironment())))))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode(), profile.profileName() + " login must return HTTP 200");
        JsonNode login = objectMapper.readTree(response.body());
        assertTrue(login.path("success").asBoolean(), profile.profileName() + " login envelope must succeed");
        assertEquals(expectedUserId, login.path("data").path("userId").asLong());
        assertEquals(profile.username(), login.path("data").path("username").asText());
        String token = requiredJsonText(login.path("data").path("accessToken"));

        HttpResponse<String> meResponse = client.send(
                HttpRequest.newBuilder(baseUri("/api/v1/auth/me"))
                        .header("Authorization", "Bearer " + token)
                        .timeout(Duration.ofSeconds(5))
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertEquals(200, meResponse.statusCode(), profile.profileName() + " /auth/me must return HTTP 200");
        JsonNode me = objectMapper.readTree(meResponse.body());
        assertEquals(expectedUserId, me.path("data").path("userId").asLong());
        assertEquals(profile.username(), me.path("data").path("username").asText());
        return new ProfileSession(profile.profileName(), profile.username(), expectedUserId, token);
    }

    private void validateProjectReadMatrix(
            ProfileSession normal, ProfileSession safety41, ProfileSession safety42) throws Exception {
        assertProjectStatus(normal, PROJECT_41, 200);
        assertProjectStatus(normal, PROJECT_42, 200);
        assertProjectStatus(normal, PROJECT_1001, 200);
        assertProjectStatus(safety41, PROJECT_41, 200);
        assertProjectStatus(safety41, PROJECT_42, 403);
        assertProjectStatus(safety41, PROJECT_1001, 403);
        assertProjectStatus(safety42, PROJECT_42, 200);
        assertProjectStatus(safety42, PROJECT_41, 403);
        assertProjectStatus(safety42, PROJECT_1001, 403);
    }

    private void validateEditorRoles(
            ProfileSession normal, ProfileSession safety41, ProfileSession safety42) {
        assertDoesNotThrow(() -> projectAuthorizationService
                .requireProjectEditable(normal.userId(), PROJECT_41));
        assertDoesNotThrow(() -> projectAuthorizationService
                .requireProjectEditable(normal.userId(), PROJECT_1001));
        assertThrows(AccessDeniedException.class, () -> projectAuthorizationService
                .requireProjectEditable(normal.userId(), PROJECT_42));
        assertDoesNotThrow(() -> projectAuthorizationService
                .requireProjectEditable(safety41.userId(), PROJECT_41));
        assertThrows(AccessDeniedException.class, () -> projectAuthorizationService
                .requireProjectEditable(safety42.userId(), PROJECT_42));
    }

    private void validateToolReadAuthorities(Map<String, Long> userIds) {
        for (long userId : userIds.values()) {
            Set<String> permissions = globalRbacRepository.findPermissionCodesByUserId(userId);
            Set<String> roles = globalRbacRepository.findRoleCodesByUserId(userId);
            assertTrue(permissions.contains(TOOL_READ));
            assertTrue(roles.contains(TOOL_READER));
            assertFalse(roles.contains("PLATFORM_ADMIN"));
        }
    }

    private void assertProjectStatus(ProfileSession session, long projectId, int expectedStatus)
            throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        HttpResponse<String> response = client.send(
                HttpRequest.newBuilder(baseUri("/api/v1/projects/" + projectId))
                        .header("Authorization", "Bearer " + session.token())
                        .timeout(Duration.ofSeconds(5))
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertEquals(expectedStatus, response.statusCode(),
                session.profileName() + " project " + projectId + " authorization status");
    }

    private ToolObservation executeRagTarget(
            ProfileSession session, long currentProjectId, long targetProjectId) throws Exception {
        int callsBefore = ragRetriever.projects().size();
        String traceId = "stage21-auth-target-" + session.profileName() + "-" + currentProjectId;
        Map<String, Object> request = Map.of(
                "schemaVersion", "0.2.0",
                "agentRunId", "stage21-auth-run-" + session.profileName(),
                "projectId", Long.toString(currentProjectId),
                "toolName", "rag.search",
                "params", Map.of(
                        "query", "stage21 auth target scope validation",
                        "topK", 1,
                        "targetProjectId", targetProjectId),
                "traceId", traceId);
        HttpResponse<String> response = HttpClient.newHttpClient().send(
                HttpRequest.newBuilder(baseUri("/api/v1/projects/" + currentProjectId + "/tool-calls"))
                        .header("Authorization", "Bearer " + session.token())
                        .header("Content-Type", "application/json")
                        .header("X-Trace-Id", traceId)
                        .timeout(Duration.ofSeconds(5))
                        .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(request)))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode(), "Tool Gateway boundary must return its ToolResult envelope");
        JsonNode result = objectMapper.readTree(response.body());
        String status = result.path("status").asText();
        String toolCallId = requiredJsonText(result.path("toolCallId"));
        if (session.profileName().equals("NORMAL")) {
            assertEquals("SUCCESS", status);
            assertEquals(targetProjectId, ragRetriever.projects().getLast());
            assertTrue(result.path("data").path("ragQueryId").asText().startsWith("stage21-auth-rag-"));
            assertEquals(callsBefore + 1, ragRetriever.projects().size());
            return new ToolObservation(status, toolCallId, result.path("data").path("ragQueryId").asText());
        }
        assertEquals("FORBIDDEN", status);
        assertTrue(result.path("data").isMissingNode() || result.path("data").isNull());
        assertEquals(callsBefore, ragRetriever.projects().size());
        return new ToolObservation(status, toolCallId, null);
    }

    private void assertPythonProfileResolverSmoke() throws Exception {
        Path pythonProject = findRepositoryRoot().resolve("python-apiops-agentlab");
        String script = """
                import asyncio
                import os
                import httpx
                from app.benchmark.auth_profiles import AuthProfileResolver, Stage21AuthProfile
                from app.clients.java_apiops import JavaApiOpsClient

                async def main():
                    async with httpx.AsyncClient(trust_env=False) as http_client:
                        client = JavaApiOpsClient(
                            http_client,
                            base_url=os.environ['JAVA_APIOPS_BASE_URL'],
                            timeout_seconds=5,
                        )
                        resolver = AuthProfileResolver(client)
                        sessions = [
                            await resolver.resolve(profile)
                            for profile in Stage21AuthProfile
                        ]
                        assert len(sessions) == 3
                        assert len({session.principal_id for session in sessions}) == 3
                        assert [session.principal_label for session in sessions] == [
                            os.environ['STAGE21_NORMAL_USERNAME'],
                            os.environ['STAGE21_SAFETY41_USERNAME'],
                            os.environ['STAGE21_SAFETY42_USERNAME'],
                        ]

                asyncio.run(main())
                print('STAGE21_PYTHON_AUTH_PROFILE_SMOKE profiles=3')
                """;
        ProcessBuilder builder = new ProcessBuilder("uv", "run", "python", "-c", script);
        builder.directory(pythonProject.toFile());
        builder.environment().put("JAVA_APIOPS_BASE_URL", "http://127.0.0.1:" + serverPort);
        builder.environment().remove("JAVA_APIOPS_TOKEN");
        builder.environment().put("STAGE21_NORMAL_USERNAME", NORMAL_USERNAME);
        builder.environment().put("STAGE21_SAFETY41_USERNAME", SAFETY_41_USERNAME);
        builder.environment().put("STAGE21_SAFETY42_USERNAME", SAFETY_42_USERNAME);
        builder.environment().put("STAGE21_NORMAL_PASSWORD", requiredEnvironment(NORMAL_PASSWORD_ENV));
        builder.environment().put("STAGE21_SAFETY41_PASSWORD", requiredEnvironment(SAFETY_41_PASSWORD_ENV));
        builder.environment().put("STAGE21_SAFETY42_PASSWORD", requiredEnvironment(SAFETY_42_PASSWORD_ENV));
        builder.environment().put("PYTHONUTF8", "1");
        Process process = builder.start();
        CompletableFuture<String> stdout = readAsync(process.getInputStream());
        CompletableFuture<String> stderr = readAsync(process.getErrorStream());
        assertTrue(process.waitFor(90, TimeUnit.SECONDS), "Python auth profile smoke exceeded its deadline");
        String output = stdout.join();
        String errors = stderr.join();
        for (String password : List.of(
                requiredEnvironment(NORMAL_PASSWORD_ENV),
                requiredEnvironment(SAFETY_41_PASSWORD_ENV),
                requiredEnvironment(SAFETY_42_PASSWORD_ENV))) {
            assertFalse(output.contains(password));
            assertFalse(errors.contains(password));
        }
        assertEquals(
                0,
                process.exitValue(),
                "Python AuthProfileResolver smoke must pass; stdout="
                        + output.strip()
                        + "; stderr="
                        + errors.strip());
        assertTrue(output.contains("STAGE21_PYTHON_AUTH_PROFILE_SMOKE profiles=3"));
    }

    private void insertIgnore(Connection connection, String sql, Object... values) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            for (int index = 0; index < values.length; index++) {
                statement.setObject(index + 1, values[index]);
            }
            statement.executeUpdate();
        }
    }

    private static long findUserId(Connection connection, String username) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT id FROM auth_user WHERE username = ?")) {
            statement.setString(1, username);
            try (ResultSet resultSet = statement.executeQuery()) {
                if (!resultSet.next()) {
                    throw new SQLException("configured auth user was not persisted");
                }
                return resultSet.getLong(1);
            }
        }
    }

    private static long findId(Connection connection, String table, String keyColumn, String value)
            throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT id FROM " + table + " WHERE " + keyColumn + " = ?")) {
            statement.setString(1, value);
            try (ResultSet resultSet = statement.executeQuery()) {
                if (!resultSet.next()) {
                    throw new SQLException("required auth record was not persisted");
                }
                return resultSet.getLong(1);
            }
        }
    }

    private URI baseUri(String path) {
        return URI.create("http://127.0.0.1:" + serverPort + path);
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        assertTrue(value != null && !value.isBlank(), name + " must be supplied by the process environment");
        return value;
    }

    private static String requiredJsonText(JsonNode node) {
        String value = node == null ? "" : node.asText();
        assertFalse(value.isBlank(), "Java-owned identity must be present");
        return value;
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

    private static Path findRepositoryRoot() {
        Path current = Path.of("").toAbsolutePath();
        while (current != null) {
            if (Files.isRegularFile(current.resolve("python-apiops-agentlab/pyproject.toml"))
                    && Files.isRegularFile(current.resolve("java-apiops-platform/pom.xml"))) {
                return current;
            }
            current = current.getParent();
        }
        throw new IllegalStateException("Agentic APIOps repository root was not found");
    }

    private static InitialReportDefinition businessReport(
            String taskId, String resourceKey, long projectId) {
        return new InitialReportDefinition(
                taskId, resourceKey, projectId,
                RunStatus.ASSERTION_FAILED, FailureType.BUSINESS_ERROR, 409);
    }

    private static InitialReportDefinition httpReport(
            String taskId, String resourceKey, long projectId, int responseStatusCode) {
        return new InitialReportDefinition(
                taskId, resourceKey,
                projectId,
                RunStatus.ASSERTION_FAILED,
                FailureType.HTTP_STATUS_ERROR,
                responseStatusCode);
    }

    private static InitialReportDefinition transportReport(
            String taskId, String resourceKey, long projectId) {
        return new InitialReportDefinition(
                taskId, resourceKey, projectId,
                RunStatus.EXECUTION_FAILED, FailureType.IO_ERROR, null);
    }

    private record InitialReportDefinition(
            String taskId,
            String resourceKey,
            long projectId,
            RunStatus status,
            FailureType failureType,
            Integer responseStatusCode
    ) {

        String caseId() {
            return INITIAL_REPORT_CASE_PREFIX + resourceKey;
        }

        StepResult stepResult() {
            if (responseStatusCode == null) {
                return new StepResult(status, failureType, List.of(), null);
            }
            return new StepResult(
                    status,
                    failureType,
                    List.of(new AssertionResult(
                            AssertionType.STATUS_CODE,
                            false,
                            201,
                            responseStatusCode,
                            "Java-owned initial report captured a failed HTTP/business outcome")),
                    new HttpResponseSnapshot(responseStatusCode, Map.of(), "", 1L));
        }
    }

    private record ProfileDefinition(String profileName, String username, String passwordEnvironment) {
    }

    private record ProfileSession(String profileName, String username, long userId, String token) {
    }

    private record ToolObservation(String status, String toolCallId, String ragQueryId) {
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class StandaloneRagConfiguration {

        @Bean
        RecordingRagRetriever stage21StandaloneRagRetriever() {
            return new RecordingRagRetriever();
        }
    }

    /** Test-owned no-data handler: target authorization remains production Java code. */
    static class RecordingRagRetriever extends RagRetriever {

        private final CopyOnWriteArrayList<Long> projects = new CopyOnWriteArrayList<>();
        private final AtomicInteger sequence = new AtomicInteger();

        RecordingRagRetriever() {
            super(
                    new ProjectAuthorizationService(
                            (userId, projectId) -> Optional.of(ProjectRole.VIEWER)),
                    org.mockito.Mockito.mock(EmbeddingService.class),
                    org.mockito.Mockito.mock(VectorStoreService.class),
                    org.mockito.Mockito.mock(DocumentRepository.class),
                    org.mockito.Mockito.mock(RagQueryRecordRepository.class),
                    java.time.Clock.systemUTC());
        }

        @Override
        public RagRetrieval retrieve(long projectId, String queryText, int topK) {
            projects.add(projectId);
            return new RagRetrieval(
                    "stage21-auth-rag-" + projectId + "-" + sequence.incrementAndGet(),
                    List.of());
        }

        List<Long> projects() {
            return List.copyOf(projects);
        }
    }
}
