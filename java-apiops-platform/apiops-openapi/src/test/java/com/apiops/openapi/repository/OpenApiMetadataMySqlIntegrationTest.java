package com.apiops.openapi.repository;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.openapi.application.OpenApiImportApplicationService;
import com.apiops.openapi.application.OpenApiImportResult;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.config.OpenApiImportProperties;
import com.apiops.openapi.converter.OpenApiMetadataAssembler;
import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;
import com.apiops.openapi.exception.OpenApiImportErrorCode;
import com.apiops.openapi.exception.OpenApiImportException;
import com.apiops.openapi.exception.OpenApiMetadataNotFoundException;
import com.apiops.openapi.normalizer.OpenApiMetadataNormalizer;
import com.apiops.openapi.parser.OpenApiDocumentParser;
import com.apiops.openapi.vo.ApiDocumentVO;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.openapi.vo.ApiMetadataSummaryVO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.unit.DataSize;

import javax.sql.DataSource;
import java.io.InputStream;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Logger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.spy;

class OpenApiMetadataMySqlIntegrationTest {

    private static final List<Long> PROJECTS_TO_CLEAN = new CopyOnWriteArrayList<>();
    private static DataSource dataSource;

    @BeforeAll
    static void initializeSchema() throws Exception {
        String url = System.getenv("APIOPS_OPENAPI_DB_URL");
        Assumptions.assumeTrue(url != null,
                "Set APIOPS_OPENAPI_DB_URL to run MySQL integration");
        String username = System.getenv("APIOPS_OPENAPI_DB_USERNAME");
        String password = System.getenv("APIOPS_OPENAPI_DB_PASSWORD");
        Assumptions.assumeTrue(username != null && password != null,
                "Set matching MySQL username and password environment variables");
        Class.forName("com.mysql.cj.jdbc.Driver");
        dataSource = new DriverManagerDataSource(url, username, password);
        try (Connection connection = dataSource.getConnection()) {
            assertEquals("apiops_openapi", connection.getCatalog());
            executeSchema(connection);
            executeSchema(connection);
        }
    }

    @AfterEach
    void cleanRows() throws SQLException {
        SecurityContextHolder.clearContext();
        if (dataSource == null) {
            return;
        }
        try (Connection connection = dataSource.getConnection()) {
            for (long projectId : PROJECTS_TO_CLEAN) {
                for (String table : List.of(
                        "api_example", "api_response_schema", "api_request_schema",
                        "api_parameter", "api_endpoint", "api_document")) {
                    try (PreparedStatement statement = connection.prepareStatement(
                            "DELETE FROM " + table + " WHERE project_id = ?")) {
                        statement.setLong(1, projectId);
                        statement.executeUpdate();
                    }
                }
            }
            PROJECTS_TO_CLEAN.clear();
        }
    }

    @Test
    void shouldInitializeAllSixTablesWithProjectIsolationColumn() throws Exception {
        try (Connection connection = dataSource.getConnection()) {
            for (String table : List.of(
                    "api_document", "api_endpoint", "api_parameter",
                    "api_request_schema", "api_response_schema", "api_example")) {
                assertTrue(tableExists(connection, table), table + " should exist");
                assertTrue(columnExists(connection, table, "project_id"),
                        table + ".project_id should exist");
            }
        }
    }

    @Test
    void shouldEnforceApiDocumentProjectSourceVersionUniqueness() throws Exception {
        long projectId = projectId();
        String suffix = suffix();
        try (Connection connection = dataSource.getConnection()) {
            insertDocument(connection, projectId, "doc-" + suffix, "orders-" + suffix, 1);
            assertThrows(SQLException.class, () -> insertDocument(
                    connection, projectId, "doc-copy-" + suffix, "orders-" + suffix, 1));
        }
    }

    @Test
    void shouldEnforcePlatformWideApiDocumentBusinessIdUniqueness() throws Exception {
        long firstProjectId = projectId();
        long secondProjectId = projectId();
        String suffix = suffix();
        String apiDocId = "doc-global-" + suffix;
        try (Connection connection = dataSource.getConnection()) {
            insertDocument(connection, firstProjectId, apiDocId, "orders-a-" + suffix, 1);
            assertThrows(SQLException.class, () -> insertDocument(
                    connection, secondProjectId, apiDocId, "orders-b-" + suffix, 1));
        }
    }

    @Test
    void shouldEnforcePlatformWideApiEndpointBusinessIdUniqueness() throws Exception {
        long firstProjectId = projectId();
        long secondProjectId = projectId();
        String suffix = suffix();
        String apiId = "api-global-" + suffix;
        try (Connection connection = dataSource.getConnection()) {
            insertEndpoint(connection, firstProjectId, apiId,
                    "doc-a-" + suffix, "firstOperation", "GET", "/orders");
            assertThrows(SQLException.class, () -> insertEndpoint(
                    connection, secondProjectId, apiId,
                    "doc-b-" + suffix, "secondOperation", "POST", "/customers"));
        }
    }

    @Test
    void shouldAllowOperationIdToRepeatAcrossDocuments() throws Exception {
        long projectId = projectId();
        String suffix = suffix();
        try (Connection connection = dataSource.getConnection()) {
            insertEndpoint(connection, projectId, "api-a-" + suffix,
                    "doc-a-" + suffix, "sharedOperation", "GET", "/orders");
            insertEndpoint(connection, projectId, "api-b-" + suffix,
                    "doc-b-" + suffix, "sharedOperation", "GET", "/orders");
            assertEquals(2, countEndpoints(connection, projectId));
        }
    }

    @Test
    void shouldScopeEndpointMethodPathUniquenessToDocument() throws Exception {
        long projectId = projectId();
        String suffix = suffix();
        try (Connection connection = dataSource.getConnection()) {
            insertEndpoint(connection, projectId, "api-get-" + suffix,
                    "doc-a-" + suffix, null, "GET", "/orders");
            assertThrows(SQLException.class, () -> insertEndpoint(
                    connection, projectId, "api-get-copy-" + suffix,
                    "doc-a-" + suffix, null, "GET", "/orders"));

            insertEndpoint(connection, projectId, "api-post-" + suffix,
                    "doc-a-" + suffix, null, "POST", "/orders");
            insertEndpoint(connection, projectId, "api-other-doc-" + suffix,
                    "doc-b-" + suffix, null, "GET", "/orders");
            assertEquals(3, countEndpoints(connection, projectId));
        }
    }

    @Test
    void shouldSaveAndQueryAllMetadataByBusinessIds() {
        long projectId = projectId();
        String suffix = suffix();
        String apiDocId = "doc-repo-" + suffix;
        String apiId = "api-repo-" + suffix;
        OpenApiMetadataRepository repository = new JdbcOpenApiMetadataRepository(dataSource);

        ApiDocument document = repository.save(new ApiDocument(
                0, apiDocId, projectId, "orders-" + suffix, "orders.yaml", "3.0.3",
                "Orders", "1.0.0", "YAML", "a".repeat(64), "openapi: 3.0.3",
                1, "ACTIVE", 1, null, null));
        ApiEndpoint endpoint = repository.save(new ApiEndpoint(
                0, apiId, apiDocId, projectId, "listOrders", "GET", "/orders",
                "List orders", null, "[]", "[]", "[]", false, null, null));
        ApiParameter parameter = repository.save(new ApiParameter(
                0, apiId, projectId, "limit", "query", false, null,
                "{\"type\":\"integer\"}", "10", null));
        ApiRequestSchema request = repository.save(new ApiRequestSchema(
                0, apiId, projectId, false, "application/json",
                "{\"type\":\"object\"}", null));
        ApiResponseSchema response = repository.save(new ApiResponseSchema(
                0, apiId, projectId, "default", "fallback", "application/json",
                "{\"type\":\"object\"}", null));
        ApiExample example = repository.save(new ApiExample(
                0, apiId, projectId, "RESPONSE_SCHEMA", response.id(), "fallback",
                null, null, "{\"message\":\"failed\"}", null));

        assertTrue(document.id() > 0);
        assertNotNull(document.createdAt());
        assertEquals(document, repository.findDocument(projectId, apiDocId).orElseThrow());
        assertEquals(endpoint, repository.findEndpoint(projectId, apiId).orElseThrow());
        assertEquals(List.of(endpoint), repository.findEndpoints(projectId));
        assertTrue(repository.findEndpoints(projectId + 1).isEmpty());
        assertEquals(List.of(parameter), repository.findParameters(projectId, apiId));
        assertEquals(List.of(request), repository.findRequestSchemas(projectId, apiId));
        assertEquals("default", repository.findResponseSchemas(projectId, apiId)
                .getFirst().statusCode());
        assertEquals(List.of(example), repository.findExamples(projectId, apiId));
        assertFalse(repository.findEndpoint(projectId + 1, apiId).isPresent());
    }

    @Test
    void shouldImportFirstCompleteSnapshotAsVersionOne() throws Exception {
        long projectId = projectId();
        OpenApiImportResult result = importDocument(
                service(new JdbcOpenApiMetadataRepository(dataSource)),
                projectId, "demo", fixture("metadata-normalization.yaml"));

        assertEquals(1, result.versionNo());
        assertFalse(result.existing());
        assertFalse(result.apiDocId().isBlank());
        assertCompleteSnapshot(projectId, 1);
    }

    @Test
    void shouldReturnExistingSnapshotWithoutDuplicatingAnyMetadata() throws Exception {
        long projectId = projectId();
        OpenApiImportApplicationService service = service(
                new JdbcOpenApiMetadataRepository(dataSource));
        byte[] content = fixture("metadata-normalization.yaml");

        OpenApiImportResult first = importDocument(service, projectId, "demo", content);
        Map<String, Integer> before = counts(projectId);
        OpenApiImportResult repeated = importDocument(service, projectId, "demo", content);

        assertEquals(first.apiDocId(), repeated.apiDocId());
        assertEquals(1, repeated.versionNo());
        assertTrue(repeated.existing());
        assertEquals(before, counts(projectId));
    }

    @Test
    void shouldCreateNextVersionWithoutOverwritingPreviousSnapshot() throws Exception {
        long projectId = projectId();
        OpenApiMetadataRepository repository = new JdbcOpenApiMetadataRepository(dataSource);
        OpenApiImportApplicationService service = service(repository);
        byte[] firstContent = fixture("metadata-normalization.yaml");
        byte[] secondContent = (new String(firstContent, StandardCharsets.UTF_8)
                + "\n# version two\n").getBytes(StandardCharsets.UTF_8);

        OpenApiImportResult first = importDocument(service, projectId, "demo", firstContent);
        OpenApiImportResult second = importDocument(service, projectId, "demo", secondContent);

        assertEquals(1, first.versionNo());
        assertEquals(2, second.versionNo());
        assertFalse(second.existing());
        assertFalse(first.apiDocId().equals(second.apiDocId()));
        assertEquals(List.of(second.apiDocId(), first.apiDocId()),
                repository.findDocuments(projectId).stream().map(ApiDocument::apiDocId).toList());
        assertTrue(repository.findDocuments(projectId + 1).isEmpty());
        assertCompleteSnapshot(projectId, 2);
    }

    @Test
    void shouldScopeIdempotencyBySourceKey() throws Exception {
        long projectId = projectId();
        OpenApiImportApplicationService service = service(
                new JdbcOpenApiMetadataRepository(dataSource));
        byte[] content = fixture("metadata-normalization.yaml");

        OpenApiImportResult first = importDocument(service, projectId, "source-a", content);
        OpenApiImportResult second = importDocument(service, projectId, "source-b", content);

        assertFalse(first.apiDocId().equals(second.apiDocId()));
        assertEquals(1, first.versionNo());
        assertEquals(1, second.versionNo());
        assertEquals(2, count("api_document", projectId));
    }

    @Test
    void shouldScopeIdempotencyByProject() throws Exception {
        long firstProject = projectId();
        long secondProject = projectId();
        OpenApiImportApplicationService service = service(
                new JdbcOpenApiMetadataRepository(dataSource));
        byte[] content = fixture("metadata-normalization.yaml");

        OpenApiImportResult first = importDocument(service, firstProject, "demo", content);
        OpenApiImportResult second = importDocument(service, secondProject, "demo", content);

        assertFalse(first.apiDocId().equals(second.apiDocId()));
        assertEquals(1, count("api_document", firstProject));
        assertEquals(1, count("api_document", secondProject));
    }

    @Test
    void shouldWriteNothingWhenParseOrNormalizeFails() throws Exception {
        long projectId = projectId();
        OpenApiImportApplicationService service = service(
                new JdbcOpenApiMetadataRepository(dataSource));

        assertThrows(RuntimeException.class, () -> importDocument(
                service, projectId, "parse-failure", "not openapi".getBytes(StandardCharsets.UTF_8)));
        assertThrows(RuntimeException.class, () -> importDocument(
                service, projectId, "normalize-failure", duplicateOperationDocument()));

        counts(projectId).values().forEach(value -> assertEquals(0, value));
    }

    @Test
    void shouldRejectUnsupportedOpenApi31WithoutWritingMetadata() throws Exception {
        long projectId = projectId();

        OpenApiImportException exception = assertThrows(OpenApiImportException.class,
                () -> importDocument(
                        service(new JdbcOpenApiMetadataRepository(dataSource)),
                        projectId,
                        "unsupported-openapi-31",
                        fixture("unsupported-openapi-31.json")));

        assertEquals(OpenApiImportErrorCode.UNSUPPORTED_OPENAPI_VERSION,
                exception.errorCode());
        counts(projectId).values().forEach(value -> assertEquals(0, value));
    }

    @Test
    void shouldImportPersistAndQueryRealStage5OpenApiEndToEnd() throws Exception {
        long projectId = projectId();
        long wrongProjectId = projectId();
        byte[] content = stage5Document();
        OpenApiMetadataRepository repository = new JdbcOpenApiMetadataRepository(dataSource);
        OpenApiImportApplicationService importService = service(repository);

        OpenApiImportResult imported = importDocument(
                importService, projectId, "demo-order-service-stage5", content);
        Map<String, Integer> importedCounts = counts(projectId);
        OpenApiImportResult repeated = importDocument(
                importService, projectId, "demo-order-service-stage5", content);

        System.out.printf(
                "Stage5 E2E apiDocId=%s versionNo=%d firstExisting=%s repeatedExisting=%s counts=%s%n",
                imported.apiDocId(), imported.versionNo(), imported.existing(),
                repeated.existing(), importedCounts);

        assertFalse(imported.existing());
        assertEquals(1, imported.versionNo());
        assertFalse(imported.apiDocId().isBlank());
        assertEquals(64, imported.contentHash().length());
        assertTrue(repeated.existing());
        assertEquals(imported.apiDocId(), repeated.apiDocId());
        assertEquals(imported.versionNo(), repeated.versionNo());
        assertEquals(importedCounts, counts(projectId));
        assertEquals(Map.of(
                "api_document", 1,
                "api_endpoint", 16,
                "api_parameter", 17,
                "api_request_schema", 4,
                "api_response_schema", 62,
                "api_example", 66
        ), importedCounts);

        OpenApiQueryApplicationService queryService = queryService(repository);
        ApiDocumentVO document = queryService.getDocument(projectId, imported.apiDocId());
        assertEquals("Agentic APIOps Demo Order Service API", document.title());
        assertEquals("3.0.1", document.openapiVersion());
        assertEquals("0.1.0", document.apiVersion());
        assertEquals(imported.versionNo(), document.versionNo());
        assertEquals("ACTIVE", document.status());
        assertEquals(imported.contentHash(), document.contentHash());

        List<ApiMetadataSummaryVO> apis = queryService.listApis(projectId);
        assertEquals(16, apis.size());
        ApiMetadataSummaryVO createOrder = api(apis, "createOrder");
        ApiMetadataSummaryVO listProducts = api(apis, "listProducts");
        ApiMetadataSummaryVO paymentCallback = api(apis, "receivePaymentCallback");
        assertApi(createOrder, "POST", "/orders");
        assertApi(listProducts, "GET", "/products");
        assertApi(paymentCallback, "POST", "/payments/callback");

        ApiMetadataDetailVO createOrderDetail = queryService.getApi(
                projectId, createOrder.apiId());
        assertApiDetail(createOrderDetail, "createOrder", "POST", "/orders", "Orders");
        assertJsonRequest(createOrderDetail);
        assertEquals(Set.of("200", "400", "404", "409", "500"),
                responseStatuses(createOrderDetail));
        assertEquals(Set.of("createOrderRequest", "createdOrder", "invalidParameter",
                        "missingUser", "insufficientInventory", "systemError"),
                exampleNames(createOrderDetail));
        assertStructuredResponseSchemas(createOrderDetail);

        ApiMetadataDetailVO productDetail = queryService.getApi(
                projectId, listProducts.apiId());
        assertApiDetail(productDetail, "listProducts", "GET", "/products", "Products");
        assertEquals(Set.of("pageNo", "pageSize", "productNo", "productName", "status"),
                productDetail.parameters().stream()
                        .map(ApiMetadataDetailVO.ParameterVO::name).collect(java.util.stream.Collectors.toSet()));
        productDetail.parameters().forEach(parameter -> {
            assertEquals("query", parameter.location());
            assertFalse(parameter.required());
            assertTrue(parameter.schema().isObject());
        });
        assertEquals("1", parameter(productDetail, "pageNo").schema().path("minimum").asText());
        assertEquals("1", parameter(productDetail, "pageSize").schema().path("minimum").asText());
        assertEquals("100", parameter(productDetail, "pageSize").schema().path("maximum").asText());
        assertEquals(64, parameter(productDetail, "productNo").schema().path("maxLength").asInt());
        assertTrue(parameter(productDetail, "productNo").schema().path("nullable").asBoolean());
        assertEquals(128, parameter(productDetail, "productName").schema().path("maxLength").asInt());
        assertTrue(parameter(productDetail, "productName").schema().path("nullable").asBoolean());
        assertEquals("string", parameter(productDetail, "status").schema().path("type").asText());
        assertEquals(32, parameter(productDetail, "status").schema().path("maxLength").asInt());
        assertTrue(parameter(productDetail, "status").schema().path("nullable").asBoolean());

        ApiMetadataDetailVO callbackDetail = queryService.getApi(
                projectId, paymentCallback.apiId());
        assertApiDetail(callbackDetail, "receivePaymentCallback", "POST",
                "/payments/callback", "Payments");
        assertJsonRequest(callbackDetail);
        assertEquals(Set.of("200", "400", "404", "409", "500"),
                responseStatuses(callbackDetail));
        assertEquals(Set.of("paymentCallbackRequest", "firstSuccess", "invalidCallback",
                        "missingPayment", "callbackConflict", "systemError"),
                exampleNames(callbackDetail));
        assertStructuredResponseSchemas(callbackDetail);

        assertThrows(OpenApiMetadataNotFoundException.class,
                () -> queryService.getDocument(wrongProjectId, imported.apiDocId()));
        assertThrows(OpenApiMetadataNotFoundException.class,
                () -> queryService.getApi(wrongProjectId, createOrder.apiId()));
    }

    @Test
    void shouldRollbackDocumentAndChildrenWhenPersistenceFailsMidSnapshot() throws Exception {
        long projectId = projectId();
        JdbcOpenApiMetadataRepository real = new JdbcOpenApiMetadataRepository(dataSource);
        JdbcOpenApiMetadataRepository failing = spy(real);
        AtomicInteger endpointSaves = new AtomicInteger();
        doAnswer(invocation -> {
            if (endpointSaves.incrementAndGet() == 2) {
                throw new IllegalStateException("deliberate endpoint persistence failure");
            }
            return invocation.callRealMethod();
        }).when(failing).save(any(ApiEndpoint.class));

        assertThrows(IllegalStateException.class, () -> importDocument(
                service(failing), projectId, "rollback", fixture("metadata-normalization.yaml")));

        assertEquals(2, endpointSaves.get());
        counts(projectId).values().forEach(value -> assertEquals(0, value));
    }

    @Test
    void shouldConvergeConcurrentSameImportToOneSnapshot() throws Exception {
        long projectId = projectId();
        byte[] content = fixture("metadata-normalization.yaml");
        OpenApiMetadataRepository repository = new JdbcOpenApiMetadataRepository(dataSource);
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        try (ExecutorService executor = Executors.newFixedThreadPool(2)) {
            List<Future<OpenApiImportResult>> futures = List.of(
                    executor.submit(() -> concurrentImport(
                            service(repository), projectId, content, ready, start)),
                    executor.submit(() -> concurrentImport(
                            service(repository), projectId, content, ready, start))
            );
            ready.await();
            start.countDown();

            OpenApiImportResult first = futures.get(0).get();
            OpenApiImportResult second = futures.get(1).get();
            assertEquals(first.apiDocId(), second.apiDocId());
            assertEquals(1, first.versionNo());
            assertEquals(1, second.versionNo());
            assertEquals(1, (first.existing() ? 1 : 0) + (second.existing() ? 1 : 0));
        }
        assertCompleteSnapshot(projectId, 1);
    }

    private OpenApiQueryApplicationService queryService(OpenApiMetadataRepository repository) {
        authenticate();
        ProjectMembershipRepository membership = (userId, projectId) ->
                Optional.of(ProjectRole.OWNER);
        return new OpenApiQueryApplicationService(
                new ProjectAuthorizationService(membership),
                repository,
                new OpenApiMetadataAssembler());
    }

    private ApiMetadataSummaryVO api(
            List<ApiMetadataSummaryVO> apis, String operationId) {
        return apis.stream()
                .filter(api -> operationId.equals(api.operationId()))
                .findFirst()
                .orElseThrow();
    }

    private void assertApi(ApiMetadataSummaryVO api, String method, String path) {
        assertEquals(method, api.method());
        assertEquals(path, api.path());
        assertTrue(api.tags().isArray());
    }

    private void assertApiDetail(
            ApiMetadataDetailVO detail,
            String operationId,
            String method,
            String path,
            String tag
    ) {
        assertEquals(operationId, detail.operationId());
        assertEquals(method, detail.method());
        assertEquals(path, detail.path());
        assertTrue(detail.tags().isArray());
        assertEquals(tag, detail.tags().get(0).asText());
        assertTrue(detail.servers().isArray());
        assertNull(detail.security());
    }

    private void assertJsonRequest(ApiMetadataDetailVO detail) {
        ApiMetadataDetailVO.RequestSchemaVO request = detail.requestSchemas().stream()
                .filter(schema -> "application/json".equals(schema.mediaType()))
                .findFirst()
                .orElseThrow();
        assertTrue(request.required());
        assertTrue(request.schema().isObject());
        assertFalse(request.schema().isTextual());
    }

    private void assertStructuredResponseSchemas(ApiMetadataDetailVO detail) {
        detail.responseSchemas().forEach(response -> {
            assertEquals("application/json", response.mediaType());
            assertTrue(response.schema().isObject());
            assertFalse(response.schema().isTextual());
        });
        detail.examples().forEach(example -> {
            assertNotNull(example.owner());
            assertTrue(example.value().isObject());
            assertFalse(example.value().isTextual());
        });
    }

    private Set<String> responseStatuses(ApiMetadataDetailVO detail) {
        return detail.responseSchemas().stream()
                .map(ApiMetadataDetailVO.ResponseSchemaVO::statusCode)
                .collect(java.util.stream.Collectors.toSet());
    }

    private Set<String> exampleNames(ApiMetadataDetailVO detail) {
        return detail.examples().stream()
                .map(ApiMetadataDetailVO.ExampleVO::exampleName)
                .collect(java.util.stream.Collectors.toSet());
    }

    private ApiMetadataDetailVO.ParameterVO parameter(
            ApiMetadataDetailVO detail, String name) {
        return detail.parameters().stream()
                .filter(parameter -> name.equals(parameter.name()))
                .findFirst()
                .orElseThrow();
    }

    private OpenApiImportApplicationService service(OpenApiMetadataRepository repository) {
        authenticate();
        ProjectMembershipRepository membership = (userId, projectId) ->
                Optional.of(ProjectRole.OWNER);
        OpenApiImportProperties properties = new OpenApiImportProperties();
        properties.setMaxFileSize(DataSize.ofMegabytes(1));
        return new OpenApiImportApplicationService(
                new ProjectAuthorizationService(membership),
                new OpenApiDocumentParser(),
                properties,
                new OpenApiMetadataNormalizer(),
                repository,
                new DataSourceTransactionManager(dataSource)
        );
    }

    private OpenApiImportResult importDocument(
            OpenApiImportApplicationService service,
            long projectId,
            String sourceKey,
            byte[] content
    ) {
        return service.importDocument(projectId, sourceKey,
                new MockMultipartFile("file", "contract.yaml", null, content));
    }

    private OpenApiImportResult concurrentImport(
            OpenApiImportApplicationService service,
            long projectId,
            byte[] content,
            CountDownLatch ready,
            CountDownLatch start
    ) throws Exception {
        ready.countDown();
        start.await();
        return importDocument(service, projectId, "concurrent", content);
    }

    private void authenticate() {
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                7L, "import-user", "not-used", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
    }

    private byte[] fixture(String name) throws Exception {
        try (InputStream input = Objects.requireNonNull(
                getClass().getResourceAsStream("/openapi/" + name))) {
            return input.readAllBytes();
        }
    }

    private byte[] stage5Document() throws Exception {
        Path path = Path.of("..", "..", "docs", "openapi",
                "demo-order-service-openapi.json").toAbsolutePath().normalize();
        return Files.readAllBytes(path);
    }

    private byte[] duplicateOperationDocument() {
        return """
                openapi: 3.0.3
                info:
                  title: Duplicate Operations
                  version: 1.0.0
                paths:
                  /first:
                    get:
                      operationId: duplicate
                      responses:
                        '200':
                          description: ok
                  /second:
                    post:
                      operationId: duplicate
                      responses:
                        '200':
                          description: ok
                """.getBytes(StandardCharsets.UTF_8);
    }

    private void assertCompleteSnapshot(long projectId, int versions) throws SQLException {
        Map<String, Integer> values = counts(projectId);
        assertEquals(versions, values.get("api_document"));
        values.forEach((table, count) -> {
            assertTrue(count > 0, table + " should contain imported metadata");
            assertEquals(0, count % versions,
                    table + " should contain one complete set per version");
        });
    }

    private Map<String, Integer> counts(long projectId) throws SQLException {
        Map<String, Integer> values = new LinkedHashMap<>();
        for (String table : List.of(
                "api_document", "api_endpoint", "api_parameter",
                "api_request_schema", "api_response_schema", "api_example")) {
            values.put(table, count(table, projectId));
        }
        return values;
    }

    private int count(String table, long projectId) throws SQLException {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "SELECT COUNT(*) FROM " + table + " WHERE project_id = ?")) {
            statement.setLong(1, projectId);
            try (ResultSet rows = statement.executeQuery()) {
                assertTrue(rows.next());
                return rows.getInt(1);
            }
        }
    }

    private static void executeSchema(Connection connection) throws Exception {
        String script;
        try (InputStream input = Objects.requireNonNull(
                OpenApiMetadataMySqlIntegrationTest.class.getResourceAsStream(
                        "/db/openapi-schema.sql"))) {
            script = new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
        for (String statementText : script.split(";")) {
            String sql = statementText.trim();
            if (!sql.isEmpty()) {
                try (Statement statement = connection.createStatement()) {
                    statement.execute(sql);
                }
            }
        }
    }

    private static void insertDocument(
            Connection connection, long projectId, String apiDocId,
            String sourceKey, int versionNo) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement("""
                INSERT INTO api_document
                    (api_doc_id, project_id, source_key, document_name, openapi_version,
                     title, api_version, document_format, content_hash, raw_content,
                     version_no, status, created_by, created_at, updated_at)
                VALUES (?, ?, ?, 'contract.yaml', '3.0.3', 'Contract', '1.0.0', 'YAML',
                        ?, 'openapi: 3.0.3', ?, 'ACTIVE', 1,
                        CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))
                """)) {
            statement.setString(1, apiDocId);
            statement.setLong(2, projectId);
            statement.setString(3, sourceKey);
            statement.setString(4, "b".repeat(64));
            statement.setInt(5, versionNo);
            statement.executeUpdate();
        }
    }

    private static void insertEndpoint(
            Connection connection, long projectId, String apiId,
            String apiDocId, String operationId, String method, String path) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement("""
                INSERT INTO api_endpoint
                    (api_id, api_doc_id, project_id, operation_id, http_method, path, deprecated,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, FALSE, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))
                """)) {
            statement.setString(1, apiId);
            statement.setString(2, apiDocId);
            statement.setLong(3, projectId);
            statement.setString(4, operationId);
            statement.setString(5, method);
            statement.setString(6, path);
            statement.executeUpdate();
        }
    }

    private static int countEndpoints(Connection connection, long projectId) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT COUNT(*) FROM api_endpoint WHERE project_id = ?")) {
            statement.setLong(1, projectId);
            try (ResultSet resultSet = statement.executeQuery()) {
                assertTrue(resultSet.next());
                return resultSet.getInt(1);
            }
        }
    }

    private static boolean tableExists(Connection connection, String table) throws SQLException {
        try (ResultSet tables = connection.getMetaData().getTables(
                connection.getCatalog(), null, table, new String[]{"TABLE"})) {
            return tables.next();
        }
    }

    private static boolean columnExists(
            Connection connection, String table, String column) throws SQLException {
        try (ResultSet columns = connection.getMetaData().getColumns(
                connection.getCatalog(), null, table, column)) {
            return columns.next();
        }
    }

    private static long projectId() {
        long value = UUID.randomUUID().getMostSignificantBits() & Long.MAX_VALUE;
        PROJECTS_TO_CLEAN.add(value);
        return value;
    }

    private static String suffix() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    private static final class DriverManagerDataSource implements DataSource {
        private final String url;
        private final String username;
        private final String password;

        private DriverManagerDataSource(String url, String username, String password) {
            this.url = url;
            this.username = username;
            this.password = password;
        }

        @Override
        public Connection getConnection() throws SQLException {
            return DriverManager.getConnection(url, username, password);
        }

        @Override
        public Connection getConnection(String username, String password) throws SQLException {
            return DriverManager.getConnection(url, username, password);
        }

        @Override
        public <T> T unwrap(Class<T> iface) throws SQLException {
            throw new SQLException("Not a wrapper");
        }

        @Override
        public boolean isWrapperFor(Class<?> iface) {
            return false;
        }

        @Override
        public PrintWriter getLogWriter() {
            return null;
        }

        @Override
        public void setLogWriter(PrintWriter out) {
        }

        @Override
        public void setLoginTimeout(int seconds) {
        }

        @Override
        public int getLoginTimeout() {
            return 0;
        }

        @Override
        public Logger getParentLogger() {
            return Logger.getLogger(Logger.GLOBAL_LOGGER_NAME);
        }
    }
}
