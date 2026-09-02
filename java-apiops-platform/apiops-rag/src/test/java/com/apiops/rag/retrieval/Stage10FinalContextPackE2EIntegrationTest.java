package com.apiops.rag.vector.qdrant;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.common.enums.FailureType;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.converter.OpenApiMetadataAssembler;
import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.repository.JdbcOpenApiMetadataRepository;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.rag.application.DiagnosticContextApplicationService;
import com.apiops.rag.application.DocumentIngestionApplicationService;
import com.apiops.rag.application.DocumentIngestionInput;
import com.apiops.rag.application.DocumentIngestionResult;
import com.apiops.rag.context.ContextCompressor;
import com.apiops.rag.context.ContextDeduplicator;
import com.apiops.rag.context.ContextItem;
import com.apiops.rag.context.ContextPack;
import com.apiops.rag.context.ContextPackBuilder;
import com.apiops.rag.context.ContextPackProperties;
import com.apiops.rag.context.ContextRanker;
import com.apiops.rag.context.ContextSource;
import com.apiops.rag.context.SensitiveDataMasker;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;
import com.apiops.rag.embedding.zhipu.ZhipuEmbeddingService;
import com.apiops.rag.parser.PlainTextDocumentParser;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.repository.JdbcDocumentRepository;
import com.apiops.rag.repository.JdbcRagQueryRecordRepository;
import com.apiops.rag.repository.RagQueryRecordRepository;
import com.apiops.rag.retrieval.RagQueryRecord;
import com.apiops.rag.retrieval.RagQueryStatus;
import com.apiops.rag.retrieval.RagRetrieval;
import com.apiops.rag.retrieval.RagRetriever;
import com.apiops.rag.retrieval.RagSearchResult;
import com.apiops.rag.splitter.FixedSizeTextSplitter;
import com.apiops.rag.splitter.TextSplitterConfig;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.assembler.TestReportAssembler;
import com.apiops.report.vo.TestReportVO;
import com.apiops.runner.assertion.AssertionResult;
import com.apiops.runner.dsl.AssertionType;
import com.apiops.runner.execution.StepResult;
import com.apiops.runner.http.HttpResponseSnapshot;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.JdbcExecutionFactRepository;
import com.apiops.runner.state.RunStatus;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import javax.sql.DataSource;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class Stage10FinalContextPackE2EIntegrationTest {

    private static final long USER_ID = 7L;
    private static final String API_ID = "api_stage10_inventory_reservation";
    private static final String QUERY = "Why did inventory reservation fail with insufficient stock?";
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper().findAndRegisterModules();
    private static final List<String> TEST_SECRETS = List.of(
            "TEST_ONLY_BEARER_TOKEN", "TEST_ONLY_SESSION_COOKIE", "TEST_ONLY_REFRESH_COOKIE",
            "TEST_ONLY_PASSWORD", "TEST_ONLY_API_KEY", "TEST_ONLY_SECRET");

    private static DataSource ragDataSource;
    private static DataSource runnerDataSource;
    private static DataSource openApiDataSource;
    private static String zhipuApiKey;
    private static String qdrantBaseUrl;

    private long projectA;
    private long projectB;
    private String collection;
    private String documentA;
    private String documentB;
    private long runId;
    private QdrantVectorStoreService vectorStore;
    private QdrantTestClient qdrant;

    @BeforeAll
    static void requireInfrastructure() {
        String ragUrl = System.getenv("APIOPS_RAG_DB_URL");
        String ragUser = System.getenv("APIOPS_RAG_DB_USERNAME");
        String ragPassword = System.getenv("APIOPS_RAG_DB_PASSWORD");
        String runnerUrl = System.getenv("APIOPS_RUNNER_DB_URL");
        String runnerUser = System.getenv("APIOPS_RUNNER_DB_USERNAME");
        String runnerPassword = System.getenv("APIOPS_RUNNER_DB_PASSWORD");
        String openApiUrl = System.getenv("APIOPS_OPENAPI_DB_URL");
        String openApiUser = System.getenv("APIOPS_OPENAPI_DB_USERNAME");
        String openApiPassword = System.getenv("APIOPS_OPENAPI_DB_PASSWORD");
        zhipuApiKey = System.getenv("ZHIPU_API_KEY");
        qdrantBaseUrl = System.getenv("APIOPS_RAG_QDRANT_BASE_URL");
        if (blank(ragUrl, ragUser, ragPassword, runnerUrl, runnerUser, runnerPassword,
                openApiUrl, openApiUser, openApiPassword, zhipuApiKey, qdrantBaseUrl)) {
            return;
        }
        ragDataSource = dataSource(ragUrl, ragUser, ragPassword);
        runnerDataSource = dataSource(runnerUrl, runnerUser, runnerPassword);
        openApiDataSource = dataSource(openApiUrl, openApiUser, openApiPassword);
        initialize(ragDataSource, "db/rag-schema.sql");
        initialize(runnerDataSource, "db/runner-schema.sql");
        initialize(openApiDataSource, "db/openapi-schema.sql");
    }

    @BeforeEach
    void setUp() {
        assumeTrue(ragDataSource != null,
                "Set RAG/Runner/OpenAPI DB variables, ZHIPU_API_KEY, and Qdrant URL");
        long suffix = UUID.randomUUID().getLeastSignificantBits() & 0x000f_ffffL;
        projectA = 9_500_000L + suffix;
        projectB = projectA + 2_000_000L;
        collection = "apiops_stage10_final_" + UUID.randomUUID().toString().replace("-", "");
        vectorStore = new QdrantVectorStoreService(
                qdrantBaseUrl, collection, Duration.ofSeconds(10), "", OBJECT_MAPPER);
        vectorStore.initialize();
        qdrant = new QdrantTestClient(qdrantBaseUrl, OBJECT_MAPPER);
        authenticate();
    }

    @AfterEach
    void cleanup() throws Exception {
        SecurityContextHolder.clearContext();
        if (qdrant != null && collection != null) {
            try {
                qdrant.deleteCollection(collection);
            } catch (RuntimeException ignored) {
                // Best effort after the real infrastructure assertions have completed.
            }
        }
        if (ragDataSource != null) {
            deleteProject(ragDataSource, projectA,
                    "rag_document_chunk", "rag_query_record", "rag_document");
            deleteProject(ragDataSource, projectB,
                    "rag_document_chunk", "rag_query_record", "rag_document");
            deleteProject(runnerDataSource, projectA,
                    "step_result", "case_result", "test_batch_run", "test_batch",
                    "test_run", "test_task");
            deleteProject(openApiDataSource, projectA,
                    "api_example", "api_parameter", "api_request_schema",
                    "api_response_schema", "api_endpoint", "api_document");
        }
    }

    @Test
    void buildsContextFromRealReportMetadataAndProjectScopedRetrieval() throws Exception {
        ProjectAuthorizationService authorization = authorization();
        OpenApiMetadataRepository openApiRepository =
                new JdbcOpenApiMetadataRepository(openApiDataSource);
        persistMetadata(openApiRepository);
        OpenApiQueryApplicationService metadataQueries = new OpenApiQueryApplicationService(
                authorization, openApiRepository, new OpenApiMetadataAssembler());
        ApiMetadataDetailVO metadata = metadataQueries.getApi(projectA, API_ID);

        ExecutionFactRepository executionFacts = new JdbcExecutionFactRepository(
                runnerDataSource, OBJECT_MAPPER);
        runId = persistFailure(executionFacts);
        TestReportQueryService reportQueries = new TestReportQueryService(
                authorization, executionFacts, new TestReportAssembler(OBJECT_MAPPER));
        TestReportVO report = reportQueries.getReport(projectA, runId);

        DocumentRepository documents = new JdbcDocumentRepository(
                ragDataSource, OBJECT_MAPPER);
        RagQueryRecordRepository queryRecords = new JdbcRagQueryRecordRepository(
                ragDataSource, OBJECT_MAPPER);
        ZhipuEmbeddingService embeddings = new ZhipuEmbeddingService(
                zhipuApiKey, Duration.ofSeconds(30), OBJECT_MAPPER);
        DocumentIngestionApplicationService ingestion = new DocumentIngestionApplicationService(
                authorization, new PlainTextDocumentParser(),
                new FixedSizeTextSplitter(new TextSplitterConfig(1_000, 100)),
                documents, embeddings, vectorStore, Clock.systemUTC());
        DocumentIngestionResult ingestedA = ingestion.ingest(projectA,
                input("runbook/inventory-a", "stage10-final-inventory-runbook.md"));
        documentA = ingestedA.documentId();
        DocumentIngestionResult ingestedB = ingestion.ingest(projectB,
                input("runbook/inventory-b", "stage10-final-inventory-runbook.md"));
        documentB = ingestedB.documentId();

        List<DocumentChunk> chunks = documents.findChunks(projectA, documentA);
        assertEquals(DocumentStatus.INDEXED, ingestedA.status());
        assertEquals("zhipu", ingestedA.embeddingModel().provider());
        assertEquals("embedding-3", ingestedA.embeddingModel().model());
        assertEquals(1_024, ingestedA.embeddingModel().dimension());
        assertFalse(chunks.isEmpty());
        assertEquals(java.util.stream.IntStream.range(0, chunks.size()).boxed().toList(),
                chunks.stream().map(DocumentChunk::ordinal).toList());
        assertTrue(chunks.stream().allMatch(chunk -> chunk.projectId() == projectA
                && chunk.documentId().equals(documentA)
                && !chunk.chunkId().isBlank()));
        assertEquals(chunks.size(), qdrant.count(collection, projectA, documentA));
        assertTrue(qdrant.count(collection, projectB, documentB) > 0);

        RagRetriever retriever = new RagRetriever(
                authorization, embeddings, vectorStore, documents, queryRecords,
                Clock.systemUTC());
        RagRetrieval retrieval = retriever.retrieve(projectA, QUERY, 2);
        assertFalse(retrieval.results().isEmpty());
        assertTrue(retrieval.results().size() <= 2);
        assertTrue(retrieval.results().stream().allMatch(result ->
                result.projectId() == projectA && result.documentId().equals(documentA)));
        assertTrue(retrieval.results().stream().noneMatch(result ->
                result.documentId().equals(documentB)));
        assertTrue(retrieval.results().getFirst().content().contains("INSUFFICIENT_STOCK"));
        assertTrue(retrieval.results().getFirst().relevanceScore()
                >= retrieval.results().getLast().relevanceScore());
        assertEquals(retrieval.results().stream().map(RagSearchResult::chunkId).distinct().count(),
                retrieval.results().size());
        retrieval.results().forEach(result -> {
            assertEquals(result.projectId(), result.citation().projectId());
            assertEquals(result.documentId(), result.citation().documentId());
            assertEquals(result.chunkId(), result.citation().chunkId());
            assertEquals(result.relevanceScore(), result.citation().score());
            assertEquals(result.content(), result.citation().excerpt());
            assertEquals("RUNBOOK", result.citation().sourceType());
            assertEquals("runbook/inventory-a", result.citation().sourceId());
        });

        ContextPackBuilder builder = contextBuilder();
        DiagnosticContextApplicationService contexts = new DiagnosticContextApplicationService(
                reportQueries, metadataQueries, retriever, builder);
        ContextPack first = contexts.buildContext(
                projectA, runId, API_ID, QUERY, 2);
        ContextPack second = contexts.buildContext(
                projectA, runId, API_ID, QUERY, 2);

        assertEquals(first, second);
        assertEquals(projectA, first.projectId());
        assertTrue(first.totalChars() <= first.maxTotalChars());
        assertEquals(List.of(ContextSource.TEST_REPORT, ContextSource.OPENAPI_METADATA),
                first.items().subList(0, 2).stream().map(ContextItem::source).toList());
        assertTrue(first.items().get(0).content().contains("ASSERTION_FAILED"));
        assertTrue(first.items().get(0).content().contains("INSUFFICIENT_STOCK"));
        assertTrue(first.items().get(1).content().contains(API_ID));
        assertTrue(first.items().get(1).content().contains("/orders"));
        assertTrue(first.items().get(1).content().contains("POST"));
        List<ContextItem> ragItems = first.items().stream()
                .filter(item -> item.source() == ContextSource.RAG_DOCUMENT).toList();
        assertFalse(ragItems.isEmpty());
        ragItems.forEach(item -> {
            assertEquals(projectA, item.projectId());
            assertEquals(item.content(), item.citation().excerpt());
            assertEquals(item.relevanceScore(), item.citation().score());
        });
        String contextText = first.items().stream()
                .map(ContextItem::content).reduce("", String::concat);
        for (int index = 0; index < TEST_SECRETS.size(); index++) {
            String secret = TEST_SECRETS.get(index);
            for (ContextItem item : first.items()) {
                assertFalse(item.content().contains(secret),
                        "sensitive category leaked at test index " + index
                                + " from " + item.source() + "/" + item.itemId());
            }
        }
        assertTrue(report.cases().getFirst().steps().getFirst().assertionResults()
                .getFirst().message().contains("TEST_ONLY_BEARER_TOKEN"));

        RagQueryRecord queryFact = queryRecords.findById(
                projectA, retrieval.ragQueryId()).orElseThrow();
        assertEquals(RagQueryStatus.SUCCESS_WITH_RESULTS, queryFact.status());
        assertEquals(retrieval.results().size(), queryFact.retrievedCount());

        System.out.printf(
                "STAGE10_FINAL_E2E projectId=%d runId=%d apiId=%s documentId=%s "
                        + "chunkId=%s relevanceScore=%.6f topK=2 contextChars=%d%n",
                projectA, runId, API_ID, documentA,
                retrieval.results().getFirst().chunkId(),
                retrieval.results().getFirst().relevanceScore(), first.totalChars());

        ingestion.delete(projectA, documentA);
        assertEquals(0, qdrant.count(collection, projectA, documentA));
        assertTrue(retriever.retrieve(projectA, QUERY, 2).results().isEmpty());
    }

    private long persistFailure(ExecutionFactRepository repository) {
        long taskId = repository.saveTask(
                projectA, "case-stage10-inventory", API_ID,
                "Inventory reservation failure", "{\"stage\":10}");
        Instant started = Instant.parse("2026-08-13T03:00:00Z");
        Instant finished = Instant.parse("2026-08-13T03:00:01Z");
        long persistedRunId = repository.saveRun(
                projectA, taskId, RunStatus.ASSERTION_FAILED,
                FailureType.ASSERTION_MISMATCH, started, finished);
        long caseResultId = repository.saveCaseResult(
                projectA, persistedRunId, "case-stage10-inventory",
                RunStatus.ASSERTION_FAILED, FailureType.ASSERTION_MISMATCH,
                started, finished);
        repository.saveStepResult(projectA, persistedRunId, caseResultId,
                "reserve-inventory", new StepResult(
                        RunStatus.ASSERTION_FAILED,
                        FailureType.ASSERTION_MISMATCH,
                        List.of(new AssertionResult(
                                AssertionType.STATUS_CODE, false, 201, 409,
                                "INSUFFICIENT_STOCK Authorization: Bearer TEST_ONLY_BEARER_TOKEN "
                                        + "Cookie: SESSION=TEST_ONLY_SESSION_COOKIE")),
                        new HttpResponseSnapshot(409, Map.of(), "", 125)));
        return persistedRunId;
    }

    private void persistMetadata(OpenApiMetadataRepository repository) {
        String apiDocId = "api_doc_stage10_" + projectA;
        repository.save(new ApiDocument(
                0, apiDocId, projectA, "openapi/demo-order", "demo-order.yaml",
                "3.0.3", "Demo Order API", "1.0.0", "YAML",
                "a".repeat(64), "openapi: 3.0.3", 1, "ACTIVE", USER_ID,
                null, null));
        repository.save(new ApiEndpoint(
                0, API_ID, apiDocId, projectA, "createOrder", "POST", "/orders",
                "Create order", "Reserves inventory and creates an order. "
                        + "api_key=TEST_ONLY_API_KEY secret=TEST_ONLY_SECRET",
                "[\"orders\"]", "[]", "[]", false, null, null));
    }

    private ContextPackBuilder contextBuilder() {
        return new ContextPackBuilder(
                OBJECT_MAPPER, new SensitiveDataMasker(), new ContextDeduplicator(),
                new ContextRanker(), new ContextCompressor(new ContextPackProperties()));
    }

    private DocumentIngestionInput input(String sourceKey, String fixture) throws Exception {
        byte[] content;
        try (InputStream input = getClass().getResourceAsStream("/fixtures/" + fixture)) {
            content = java.util.Objects.requireNonNull(input, "fixture").readAllBytes();
        }
        return new DocumentIngestionInput(
                sourceKey, "RUNBOOK", "Inventory reservation failure runbook",
                fixture, "text/markdown", content);
    }

    private ProjectAuthorizationService authorization() {
        return new ProjectAuthorizationService((userId, projectId) ->
                userId == USER_ID && (projectId == projectA || projectId == projectB)
                        ? Optional.of(ProjectRole.OWNER) : Optional.empty());
    }

    private void authenticate() {
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                USER_ID, "stage10-final-e2e", "unused", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
    }

    private static DataSource dataSource(String url, String username, String password) {
        return new DriverManagerDataSource(url, username, password);
    }

    private static void initialize(DataSource dataSource, String schema) {
        new ResourceDatabasePopulator(new ClassPathResource(schema)).execute(dataSource);
    }

    private static boolean blank(String... values) {
        return java.util.Arrays.stream(values).anyMatch(
                value -> value == null || value.isBlank());
    }

    private static void deleteProject(
            DataSource dataSource, long projectId, String... tables) throws Exception {
        if (dataSource == null || projectId <= 0) {
            return;
        }
        try (Connection connection = dataSource.getConnection()) {
            for (String table : tables) {
                try (PreparedStatement statement = connection.prepareStatement(
                        "DELETE FROM " + table + " WHERE project_id = ?")) {
                    statement.setLong(1, projectId);
                    statement.executeUpdate();
                }
            }
        }
    }
}
