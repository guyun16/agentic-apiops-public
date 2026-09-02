package com.apiops.rag.vector.qdrant;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.rag.application.DocumentIngestionApplicationService;
import com.apiops.rag.application.DocumentIngestionInput;
import com.apiops.rag.application.DocumentIngestionResult;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;
import com.apiops.rag.embedding.zhipu.ZhipuEmbeddingService;
import com.apiops.rag.parser.PlainTextDocumentParser;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.repository.JdbcDocumentRepository;
import com.apiops.rag.splitter.FixedSizeTextSplitter;
import com.apiops.rag.splitter.TextSplitterConfig;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import javax.sql.DataSource;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.time.Clock;
import java.time.Duration;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class DocumentZhipuQdrantE2EIntegrationTest {

    private static final String COLLECTION = "apiops_rag_chunks_v1";
    private static final long USER_ID = 7L;
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private static DataSource dataSource;
    private static String zhipuApiKey;
    private static String qdrantBaseUrl;

    private long projectId;
    private String documentId;
    private DocumentRepository repository;
    private QdrantVectorStoreService vectorStore;
    private QdrantTestClient qdrant;

    @BeforeAll
    static void requireRealInfrastructure() {
        String databaseUrl = System.getenv("APIOPS_RAG_DB_URL");
        String databaseUsername = System.getenv("APIOPS_RAG_DB_USERNAME");
        String databasePassword = System.getenv("APIOPS_RAG_DB_PASSWORD");
        zhipuApiKey = System.getenv("ZHIPU_API_KEY");
        qdrantBaseUrl = System.getenv("APIOPS_RAG_QDRANT_BASE_URL");
        if (databaseUrl == null || databaseUsername == null || databasePassword == null
                || zhipuApiKey == null || zhipuApiKey.isBlank()
                || qdrantBaseUrl == null || qdrantBaseUrl.isBlank()) {
            return;
        }

        dataSource = new DriverManagerDataSource(
                databaseUrl, databaseUsername, databasePassword);
        new ResourceDatabasePopulator(
                new org.springframework.core.io.ClassPathResource("db/rag-schema.sql"))
                .execute(dataSource);
    }

    @BeforeEach
    void setUp() {
        assumeTrue(dataSource != null,
                "Set APIOPS_RAG_DB_*, ZHIPU_API_KEY, and APIOPS_RAG_QDRANT_BASE_URL "
                        + "to run the real Stage 10 E2E");
        projectId = 9_000_000L
                + (UUID.randomUUID().getLeastSignificantBits() & 0x000f_ffffL);
        repository = new JdbcDocumentRepository(dataSource, OBJECT_MAPPER);
        vectorStore = new QdrantVectorStoreService(
                qdrantBaseUrl, COLLECTION, Duration.ofSeconds(10), "", OBJECT_MAPPER);
        vectorStore.initialize();
        qdrant = new QdrantTestClient(qdrantBaseUrl, OBJECT_MAPPER);

        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                USER_ID, "stage10-e2e", "not-used", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
    }

    @AfterEach
    void cleanup() throws Exception {
        SecurityContextHolder.clearContext();
        if (documentId != null) {
            try {
                vectorStore.deleteByDocument(projectId, documentId);
            } catch (RuntimeException ignored) {
                // Best-effort cleanup; the test has already surfaced infrastructure failure.
            }
        }
        if (dataSource != null) {
            try (Connection connection = dataSource.getConnection();
                 PreparedStatement chunks = connection.prepareStatement(
                         "DELETE FROM rag_document_chunk WHERE project_id = ?");
                 PreparedStatement documents = connection.prepareStatement(
                         "DELETE FROM rag_document WHERE project_id = ?")) {
                chunks.setLong(1, projectId);
                chunks.executeUpdate();
                documents.setLong(1, projectId);
                documents.executeUpdate();
            }
        }
    }

    @Test
    void ingestsReindexesAndDeletesAcrossRealMySqlZhipuAndQdrant() throws Exception {
        DocumentIngestionApplicationService service = applicationService();

        DocumentIngestionResult initial = service.ingest(
                projectId, input("stage10-qdrant-e2e.md"));
        documentId = initial.documentId();
        List<DocumentChunk> initialChunks = repository.findChunks(projectId, documentId);
        Set<String> oldChunkIds = chunkIds(initialChunks);

        assertEquals(DocumentStatus.INDEXED, initial.status());
        assertEquals(DocumentStatus.INDEXED,
                repository.findById(projectId, documentId).orElseThrow().status());
        assertEquals("zhipu", initial.embeddingModel().provider());
        assertEquals("embedding-3", initial.embeddingModel().model());
        assertEquals(1_024, initial.embeddingModel().dimension());
        assertEquals(initialChunks.size(), qdrant.count(COLLECTION, projectId, documentId));

        DocumentIngestionResult reindexed = service.ingest(
                projectId, input("stage10-qdrant-e2e-reindexed.md"));
        List<DocumentChunk> currentChunks = repository.findChunks(projectId, documentId);
        List<JsonNode> currentPayloads = qdrant.payloads(COLLECTION, projectId, documentId);

        assertEquals(documentId, reindexed.documentId());
        assertEquals(DocumentStatus.INDEXED, reindexed.status());
        assertEquals(currentChunks.size(), currentPayloads.size());
        assertEquals(chunkIds(currentChunks), payloadChunkIds(currentPayloads));
        assertTrue(payloadChunkIds(currentPayloads).stream()
                .noneMatch(oldChunkIds::contains));

        service.delete(projectId, documentId);

        assertEquals(0, qdrant.count(COLLECTION, projectId, documentId));
        assertEquals(DocumentStatus.DELETED,
                repository.findById(projectId, documentId).orElseThrow().status());
        assertTrue(repository.findChunks(projectId, documentId).isEmpty());
    }

    private DocumentIngestionApplicationService applicationService() {
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, requestedProjectId) -> userId == USER_ID
                        && requestedProjectId == projectId
                        ? java.util.Optional.of(ProjectRole.OWNER)
                        : java.util.Optional.empty());
        return new DocumentIngestionApplicationService(
                authorization,
                new PlainTextDocumentParser(),
                new FixedSizeTextSplitter(new TextSplitterConfig(1_000, 100)),
                repository,
                new ZhipuEmbeddingService(
                        zhipuApiKey, Duration.ofSeconds(30), OBJECT_MAPPER),
                vectorStore,
                Clock.systemUTC());
    }

    private DocumentIngestionInput input(String fixture) throws IOException {
        byte[] content;
        try (InputStream input = getClass().getResourceAsStream("/fixtures/" + fixture)) {
            if (input == null) {
                throw new IOException("Missing E2E fixture");
            }
            content = input.readAllBytes();
        }
        return new DocumentIngestionInput(
                "runbook/orders", "RUNBOOK", "Orders diagnostic runbook",
                fixture, "text/markdown", content);
    }

    private Set<String> chunkIds(List<DocumentChunk> chunks) {
        Set<String> values = new HashSet<>();
        chunks.forEach(chunk -> values.add(chunk.chunkId()));
        return Set.copyOf(values);
    }

    private Set<String> payloadChunkIds(List<JsonNode> payloads) {
        Set<String> values = new HashSet<>();
        payloads.forEach(payload -> values.add(payload.path("chunkId").asText()));
        return Set.copyOf(values);
    }
}
