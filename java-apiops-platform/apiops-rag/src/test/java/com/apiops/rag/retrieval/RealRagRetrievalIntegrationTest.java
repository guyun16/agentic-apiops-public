package com.apiops.rag.retrieval;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.rag.domain.Document;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;
import com.apiops.rag.embedding.EmbeddingVector;
import com.apiops.rag.embedding.zhipu.ZhipuEmbeddingService;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.repository.RagQueryRecordRepository;
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.qdrant.QdrantVectorStoreService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class RealRagRetrievalIntegrationTest {

    private static final long USER_ID = 7L;
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private String qdrantBaseUrl;
    private String collection;
    private long projectA;
    private long projectB;
    private long projectC;
    private QdrantVectorStoreService vectorStore;

    @BeforeEach
    void setUp() {
        String apiKey = System.getenv("ZHIPU_API_KEY");
        qdrantBaseUrl = System.getenv("APIOPS_RAG_QDRANT_BASE_URL");
        assumeTrue(apiKey != null && !apiKey.isBlank()
                        && qdrantBaseUrl != null && !qdrantBaseUrl.isBlank(),
                "Set ZHIPU_API_KEY and APIOPS_RAG_QDRANT_BASE_URL "
                        + "to run real retrieval integration");
        collection = "apiops_rag_retrieval_it_"
                + UUID.randomUUID().toString().replace("-", "");
        vectorStore = new QdrantVectorStoreService(
                qdrantBaseUrl, collection, Duration.ofSeconds(10), "", OBJECT_MAPPER);
        vectorStore.initialize();
        projectA = 9_100_000L + (UUID.randomUUID().hashCode() & 0x000f_ffffL);
        projectB = projectA + 2_000_000L;
        projectC = projectA + 4_000_000L;
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                USER_ID, "real-retrieval", "not-used", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
    }

    @AfterEach
    void cleanup() {
        SecurityContextHolder.clearContext();
        if (qdrantBaseUrl == null || collection == null) {
            return;
        }
        try {
            java.net.http.HttpClient.newHttpClient().send(
                    java.net.http.HttpRequest.newBuilder(java.net.URI.create(
                                    qdrantBaseUrl + "/collections/" + collection))
                            .DELETE().timeout(Duration.ofSeconds(10)).build(),
                    java.net.http.HttpResponse.BodyHandlers.discarding());
        } catch (Exception ignored) {
            // Best-effort cleanup after a real infrastructure test.
        }
    }

    @Test
    void retrievesRealZhipuEmbeddingFromProjectScopedQdrantWithCitation() {
        String apiKey = System.getenv("ZHIPU_API_KEY");
        ZhipuEmbeddingService embeddings = new ZhipuEmbeddingService(
                apiKey, Duration.ofSeconds(30), OBJECT_MAPPER);
        String query = "Check the idempotency key before retrying order creation.";
        String other = "Database backups are retained for thirty days.";
        List<EmbeddingVector> vectors = embeddings.embed(List.of(query, other));

        Knowledge knowledge = new Knowledge();
        knowledge.add(document(projectA, "doc-a", "runbook/a"), List.of(
                chunk(projectA, "doc-a", "chunk-a", 0, query),
                chunk(projectA, "doc-a", "chunk-b", 1, other)));
        knowledge.add(document(projectB, "doc-b", "runbook/b"), List.of(
                chunk(projectB, "doc-b", "chunk-project-b", 0, query)));
        vectorStore.upsert(projectA, "doc-a", List.of(
                entry(projectA, "doc-a", "chunk-a", vectors.get(0)),
                entry(projectA, "doc-a", "chunk-b", vectors.get(1))));
        vectorStore.upsert(projectB, "doc-b", List.of(
                entry(projectB, "doc-b", "chunk-project-b", vectors.get(0))));

        Records records = new Records();
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> userId == USER_ID && projectId == projectA
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
        RagRetrieval retrieval = new RagRetriever(
                authorization, embeddings, vectorStore, knowledge, records,
                Clock.systemUTC()).retrieve(projectA, query, 2);

        assertEquals(2, retrieval.results().size());
        assertEquals("chunk-a", retrieval.results().getFirst().chunkId());
        assertTrue(retrieval.results().stream().allMatch(
                result -> result.projectId() == projectA));
        assertTrue(retrieval.results().stream().noneMatch(
                result -> result.chunkId().equals("chunk-project-b")));
        assertTrue(retrieval.results().get(0).relevanceScore()
                >= retrieval.results().get(1).relevanceScore());
        assertEquals(retrieval.results().getFirst().relevanceScore(),
                retrieval.results().getFirst().citation().score());
        assertEquals("doc-a", retrieval.results().getFirst().citation().documentId());
        assertEquals("chunk-a", retrieval.results().getFirst().citation().chunkId());
        assertEquals(RagQueryStatus.SUCCESS_WITH_RESULTS, records.saved.status());
    }

    @Test
    void realZeroHitIsSuccessfulEmptyAndPersistsZeroHitFact() {
        String apiKey = System.getenv("ZHIPU_API_KEY");
        ZhipuEmbeddingService embeddings = new ZhipuEmbeddingService(
                apiKey, Duration.ofSeconds(30), OBJECT_MAPPER);
        Records records = new Records();
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, requestedProjectId) -> userId == USER_ID
                        && (requestedProjectId == projectA || requestedProjectId == projectC)
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());

        RagRetrieval retrieval = new RagRetriever(
                authorization, embeddings, vectorStore, new Knowledge(), records,
                Clock.systemUTC()).retrieve(
                        projectC, "no indexed evidence exists for this project", 2);

        assertTrue(retrieval.results().isEmpty());
        assertEquals(projectC, records.saved.projectId());
        assertEquals(RagQueryStatus.ZERO_HIT, records.saved.status());
        assertEquals(0, records.saved.retrievedCount());
    }

    private Document document(long projectId, String documentId, String sourceKey) {
        return new Document(
                documentId, projectId, sourceKey, "RUNBOOK", "Orders runbook",
                sourceKey + ".md", "text/markdown", "a".repeat(64),
                DocumentStatus.INDEXED, USER_ID, Instant.now());
    }

    private DocumentChunk chunk(
            long projectId, String documentId, String chunkId, int ordinal, String content) {
        return new DocumentChunk(
                chunkId, documentId, projectId, ordinal, content,
                "b".repeat(64), Map.of());
    }

    private VectorEntry entry(
            long projectId, String documentId, String chunkId, EmbeddingVector vector) {
        return new VectorEntry(
                projectId, documentId, chunkId, "b".repeat(64), vector, Map.of());
    }

    private static final class Knowledge implements DocumentRepository {
        private final Map<Key, Document> documents = new LinkedHashMap<>();
        private final Map<Key, List<DocumentChunk>> chunks = new LinkedHashMap<>();

        private void add(Document document, List<DocumentChunk> values) {
            Key key = new Key(document.projectId(), document.documentId());
            documents.put(key, document);
            chunks.put(key, List.copyOf(values));
        }

        @Override
        public Optional<Document> findBySourceKey(long projectId, String sourceKey) {
            return Optional.empty();
        }

        @Override
        public Optional<Document> findById(long projectId, String documentId) {
            return Optional.ofNullable(documents.get(new Key(projectId, documentId)));
        }

        @Override
        public List<DocumentChunk> findChunks(long projectId, String documentId) {
            return chunks.getOrDefault(new Key(projectId, documentId), List.of());
        }

        @Override
        public void saveKnowledge(Document document, List<DocumentChunk> chunks) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void updateStatus(long projectId, String documentId, DocumentStatus status) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void markDeleted(long projectId, String documentId) {
            throw new UnsupportedOperationException();
        }

        private record Key(long projectId, String documentId) {
        }
    }

    private static final class Records implements RagQueryRecordRepository {
        private RagQueryRecord saved;

        @Override
        public void save(RagQueryRecord record) {
            saved = record;
        }

        @Override
        public Optional<RagQueryRecord> findById(long projectId, String ragQueryId) {
            return Optional.ofNullable(saved).filter(record ->
                    record.projectId() == projectId && record.ragQueryId().equals(ragQueryId));
        }
    }
}
