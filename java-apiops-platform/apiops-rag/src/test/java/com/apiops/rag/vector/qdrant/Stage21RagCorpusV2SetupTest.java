package com.apiops.rag.vector.qdrant;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.repository.JdbcProjectMembershipRepository;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.rag.application.DocumentIngestionApplicationService;
import com.apiops.rag.application.DocumentIngestionInput;
import com.apiops.rag.application.DocumentIngestionResult;
import com.apiops.rag.domain.Document;
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
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import javax.sql.DataSource;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.time.Clock;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Test-scoped, repeatable loader for the real Stage 21 RAG Corpus V2.
 *
 * <p>All writes use the production ingestion application service. The temporary
 * Project 42 editor grant is restored in {@code @AfterEach}; retrieval still
 * uses the production JDBC project-membership repository and authorization
 * service. No vector point is inserted directly.</p>
 */
class Stage21RagCorpusV2SetupTest {

    private static final long PROJECT_41 = 41L;
    private static final long PROJECT_42 = 42L;
    private static final String NORMAL_USERNAME = "stage21-normal";
    private static final String LEGACY_STAGE21_SOURCE_KEY = "stage21/runtime/controlled-rag";
    private static final String COLLECTION = "apiops_rag_chunks_v1";
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final Path CORPUS_ROOT = Path.of(
            "java-apiops-platform", "apiops-web", "src", "test", "resources",
            "stage21", "rag-corpus-v2");

    private static DataSource ragDataSource;
    private static DataSource authDataSource;
    private static String zhipuApiKey;
    private static String qdrantBaseUrl;

    private DocumentRepository repository;
    private QdrantVectorStoreService vectorStore;
    private long normalUserId;
    private String originalProject42Role;

    @BeforeAll
    static void loadRealInfrastructureConfiguration() {
        String ragUrl = System.getenv("APIOPS_RAG_DB_URL");
        String ragUsername = System.getenv("APIOPS_RAG_DB_USERNAME");
        String ragPassword = System.getenv("APIOPS_RAG_DB_PASSWORD");
        zhipuApiKey = System.getenv("ZHIPU_API_KEY");
        qdrantBaseUrl = System.getenv("APIOPS_RAG_QDRANT_BASE_URL");
        if (blank(ragUrl) || blank(ragUsername) || blank(ragPassword)
                || blank(zhipuApiKey) || blank(qdrantBaseUrl)) {
            return;
        }

        ragDataSource = new DriverManagerDataSource(ragUrl, ragUsername, ragPassword);
        authDataSource = new DriverManagerDataSource(
                valueOrDefault(
                        System.getenv("APIOPS_AUTH_DB_URL"),
                        "jdbc:mysql://127.0.0.1:3306/apiops_auth"),
                valueOrDefault(System.getenv("APIOPS_AUTH_DB_USERNAME"), ragUsername),
                valueOrDefault(System.getenv("APIOPS_AUTH_DB_PASSWORD"), ragPassword));
    }

    @BeforeEach
    void prepareProductionServices() throws Exception {
        assumeTrue(ragDataSource != null,
                "Set APIOPS_RAG_DB_*, ZHIPU_API_KEY, and APIOPS_RAG_QDRANT_BASE_URL "
                        + "to run the real Corpus V2 setup");
        repository = new JdbcDocumentRepository(ragDataSource, OBJECT_MAPPER);
        vectorStore = new QdrantVectorStoreService(
                qdrantBaseUrl,
                COLLECTION,
                Duration.ofSeconds(10),
                valueOrDefault(System.getenv("APIOPS_RAG_QDRANT_API_KEY"), ""),
                OBJECT_MAPPER);
        vectorStore.initialize();

        normalUserId = findUserId(authDataSource, NORMAL_USERNAME);
        originalProject42Role = findProjectRole(authDataSource, normalUserId, PROJECT_42);
        assertNotNull(originalProject42Role, "stage21-normal must have Project 42 membership");
        updateProjectRole(authDataSource, normalUserId, PROJECT_42, "EDITOR");
        authenticate(normalUserId);
    }

    @AfterEach
    void restoreProjectAuthorization() {
        SecurityContextHolder.clearContext();
        if (authDataSource != null && originalProject42Role != null) {
            updateProjectRole(authDataSource, normalUserId, PROJECT_42, originalProject42Role);
        }
    }

    @Test
    void ingestsCorpusV2ThroughProductionJavaPipelineAndIsIdempotentBySourceKey()
            throws Exception {
        Path repositoryRoot = findRepositoryRoot();
        Path manifestPath = repositoryRoot.resolve(CORPUS_ROOT).resolve("corpus-manifest.json");
        JsonNode manifest = OBJECT_MAPPER.readTree(Files.readString(manifestPath));
        DocumentIngestionApplicationService service = applicationService();

        boolean legacyDocumentRemoved = removeLegacyStage21SmokeDocument(service);

        List<Map<String, Object>> ingested = new ArrayList<>();
        for (JsonNode document : manifest.path("documents")) {
            long projectId = document.path("projectId").asLong();
            String relativeFile = document.path("file").asText();
            DocumentIngestionResult result = service.ingest(
                    projectId,
                    input(manifestPath.getParent(), document, relativeFile));
            assertEquals(DocumentStatus.INDEXED, result.status());
            assertEquals("zhipu", result.embeddingModel().provider());
            assertEquals("embedding-3", result.embeddingModel().model());
            assertEquals(1_024, result.embeddingModel().dimension());

            List<DocumentChunk> chunks = repository.findChunks(projectId, result.documentId());
            assertEquals(result.chunkCount(), chunks.size());
            assertTrue(chunks.size() > 0);
            assertEquals(chunks.size(), vectorStoreCount(projectId, result.documentId()));

            ingested.add(Map.of(
                    "projectId", projectId,
                    "sourceKey", document.path("sourceKey").asText(),
                    "documentId", result.documentId(),
                    "chunks", chunks.size(),
                    "qdrantPoints", vectorStoreCount(projectId, result.documentId())));
        }

        JsonNode first = manifest.path("documents").get(0);
        DocumentIngestionResult reindexed = service.ingest(
                PROJECT_41,
                input(manifestPath.getParent(), first, first.path("file").asText()));
        assertEquals(
                ingested.getFirst().get("documentId"),
                reindexed.documentId(),
                "same sourceKey must reuse the document identity");

        long project41Documents = ingested.stream()
                .filter(value -> ((Number) value.get("projectId")).longValue() == PROJECT_41)
                .count();
        long project42Documents = ingested.stream()
                .filter(value -> ((Number) value.get("projectId")).longValue() == PROJECT_42)
                .count();
        long project41Chunks = ingested.stream()
                .filter(value -> ((Number) value.get("projectId")).longValue() == PROJECT_41)
                .mapToLong(value -> ((Number) value.get("chunks")).longValue())
                .sum();
        long project42Chunks = ingested.stream()
                .filter(value -> ((Number) value.get("projectId")).longValue() == PROJECT_42)
                .mapToLong(value -> ((Number) value.get("chunks")).longValue())
                .sum();
        long qdrantPoints = ingested.stream()
                .mapToLong(value -> ((Number) value.get("qdrantPoints")).longValue())
                .sum();
        assertTrue(project41Documents > 0);
        assertTrue(project42Documents > 0);
        assertTrue(project41Chunks > 0);
        assertTrue(project42Chunks > 0);

        Map<String, Object> report = new HashMap<>();
        report.put("corpusVersion", manifest.path("corpusVersion").asText());
        report.put("embeddingModel", manifest.path("embeddingModel").asText());
        report.put("embeddingDimension", manifest.path("embeddingDimension").asInt());
        report.put("chunkSize", manifest.path("chunking").path("chunkSize").asInt());
        report.put("chunkOverlap", manifest.path("chunking").path("chunkOverlap").asInt());
        report.put("documents", ingested.size());
        report.put("chunks", project41Chunks + project42Chunks);
        report.put("qdrantPoints", qdrantPoints);
        report.put("project41Documents", project41Documents);
        report.put("project42Documents", project42Documents);
        report.put("legacyStage21SmokeDocumentRemoved", legacyDocumentRemoved);
        report.put("ingestedDocuments", ingested);
        Path reportPath = repositoryRoot.resolve(
                Path.of("artifacts", "stage21", "rag-v2-corpus-setup", "setup-report.json"));
        Files.createDirectories(reportPath.getParent());
        Files.writeString(
                reportPath,
                OBJECT_MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(report) + "\n");
        System.out.println("STAGE21_RAG_CORPUS_V2_SETUP "
                + OBJECT_MAPPER.writeValueAsString(report));
    }

    private DocumentIngestionApplicationService applicationService() {
        ProjectMembershipRepository membership =
                new JdbcProjectMembershipRepository(authDataSource);
        return new DocumentIngestionApplicationService(
                new ProjectAuthorizationService(membership),
                new PlainTextDocumentParser(),
                new FixedSizeTextSplitter(new TextSplitterConfig(1_000, 100)),
                repository,
                new ZhipuEmbeddingService(zhipuApiKey, Duration.ofSeconds(30), OBJECT_MAPPER),
                vectorStore,
                Clock.systemUTC());
    }

    /** Remove only the known pre-V2 Stage 21 smoke fixture through the formal delete boundary. */
    private boolean removeLegacyStage21SmokeDocument(
            DocumentIngestionApplicationService service) {
        Document legacy = repository.findBySourceKey(
                PROJECT_41, LEGACY_STAGE21_SOURCE_KEY).orElse(null);
        if (legacy == null || legacy.status() == DocumentStatus.DELETED) {
            return false;
        }
        service.delete(PROJECT_41, legacy.documentId());
        return true;
    }

    private DocumentIngestionInput input(
            Path manifestDirectory, JsonNode document, String relativeFile)
            throws IOException {
        Path file = manifestDirectory.resolve(relativeFile).normalize();
        if (!file.startsWith(manifestDirectory)) {
            throw new IOException("Corpus file escapes the manifest directory: " + relativeFile);
        }
        return new DocumentIngestionInput(
                document.path("sourceKey").asText(),
                document.path("sourceType").asText(),
                document.path("title").asText(),
                file.getFileName().toString(),
                document.path("mediaType").asText(),
                Files.readAllBytes(file));
    }

    private long vectorStoreCount(long projectId, String documentId) {
        return new QdrantTestClient(qdrantBaseUrl, OBJECT_MAPPER)
                .count(COLLECTION, projectId, documentId);
    }

    private static long findUserId(DataSource dataSource, String username) throws Exception {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "SELECT id FROM auth_user WHERE username = ?")) {
            statement.setString(1, username);
            try (ResultSet resultSet = statement.executeQuery()) {
                assertTrue(resultSet.next(), "configured Stage 21 user must exist");
                return resultSet.getLong(1);
            }
        }
    }

    private static String findProjectRole(
            DataSource dataSource, long userId, long projectId) throws Exception {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "SELECT project_role FROM apiops_project_member "
                             + "WHERE project_id = ? AND user_id = ?")) {
            statement.setLong(1, projectId);
            statement.setLong(2, userId);
            try (ResultSet resultSet = statement.executeQuery()) {
                return resultSet.next() ? resultSet.getString(1) : null;
            }
        }
    }

    private static void updateProjectRole(
            DataSource dataSource, long userId, long projectId, String role) {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "UPDATE apiops_project_member SET project_role = ? "
                             + "WHERE project_id = ? AND user_id = ?")) {
            statement.setString(1, role);
            statement.setLong(2, projectId);
            statement.setLong(3, userId);
            if (statement.executeUpdate() != 1) {
                throw new IllegalStateException("Stage 21 project membership was not updated");
            }
        } catch (Exception failure) {
            throw new IllegalStateException("Unable to update temporary Stage 21 role", failure);
        }
    }

    private void authenticate(long userId) {
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                userId, NORMAL_USERNAME, "database-backed-test", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
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

    private static boolean blank(String value) {
        return value == null || value.isBlank();
    }

    private static String valueOrDefault(String value, String fallback) {
        return blank(value) ? fallback : value;
    }
}
