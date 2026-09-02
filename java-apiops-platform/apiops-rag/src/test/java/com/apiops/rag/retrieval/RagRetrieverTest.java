package com.apiops.rag.retrieval;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.rag.domain.Document;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;
import com.apiops.rag.embedding.EmbeddingException;
import com.apiops.rag.embedding.EmbeddingModel;
import com.apiops.rag.embedding.EmbeddingService;
import com.apiops.rag.embedding.EmbeddingVector;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.repository.RagQueryRecordRepository;
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.VectorSearchMatch;
import com.apiops.rag.vector.VectorStoreException;
import com.apiops.rag.vector.VectorStoreService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.context.SecurityContextHolder;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RagRetrieverTest {

    private static final long PROJECT_ID = 41L;
    private static final long USER_ID = 7L;
    private static final EmbeddingModel MODEL =
            new EmbeddingModel("fake", "retrieval-test", 2);
    private static final EmbeddingVector QUERY_VECTOR =
            new EmbeddingVector(MODEL, List.of(1.0F, 0.0F));
    private static final Clock CLOCK = Clock.fixed(
            Instant.parse("2026-08-13T00:00:00Z"), ZoneOffset.UTC);

    private final KnowledgeRepository knowledge = new KnowledgeRepository();
    private final QueryRecords records = new QueryRecords();
    private final CapturingEmbedding embedding = new CapturingEmbedding();
    private final CapturingVectorStore vectorStore = new CapturingVectorStore();

    @BeforeEach
    void setUp() {
        authenticate();
        knowledge.add(document("doc-a", "runbook/a", "Orders runbook"), List.of(
                chunk("doc-a", "chunk-a", 0, "Check idempotency before retry."),
                chunk("doc-a", "chunk-b", 1, "Inspect the downstream timeout.")));
        knowledge.add(document("doc-b", "runbook/b", "Payments runbook"), List.of(
                chunk("doc-b", "chunk-c", 0, "Check the payment reference.")));
    }

    @AfterEach
    void clearSecurity() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void embedsQuerySearchesRequestedProjectAndMapsStableCitation() {
        vectorStore.matches = List.of(new VectorSearchMatch(
                PROJECT_ID, "doc-a", "chunk-a", 0.91));

        RagRetrieval retrieval = retriever().retrieve(
                PROJECT_ID, "Why did the retry fail?", 3);

        assertEquals("Why did the retry fail?", embedding.text);
        assertSame(QUERY_VECTOR, vectorStore.queryVector);
        assertEquals(PROJECT_ID, vectorStore.projectId);
        assertEquals(3, vectorStore.topK);
        RagSearchResult result = retrieval.results().getFirst();
        assertEquals(PROJECT_ID, result.projectId());
        assertEquals("doc-a", result.documentId());
        assertEquals("chunk-a", result.chunkId());
        assertEquals(0.91, result.relevanceScore());
        assertEquals(result.relevanceScore(), result.citation().score());
        assertEquals("runbook/a", result.citation().sourceId());
        assertEquals("chunk:0", result.citation().location());
        assertEquals(result.content(), result.citation().excerpt());
        RagQueryRecord fact = records.saved.getFirst();
        assertEquals(RagQueryStatus.SUCCESS_WITH_RESULTS, fact.status());
        assertEquals(List.of(new RagResultReference("doc-a", "chunk-a")),
                fact.resultReferences());
    }

    @Test
    void sortsHigherScoresFirstDeduplicatesAndEnforcesTopK() {
        vectorStore.matches = List.of(
                new VectorSearchMatch(PROJECT_ID, "doc-a", "chunk-b", 0.70),
                new VectorSearchMatch(PROJECT_ID, "doc-a", "chunk-a", 0.80),
                new VectorSearchMatch(PROJECT_ID, "doc-a", "chunk-a", 0.95),
                new VectorSearchMatch(PROJECT_ID, "doc-b", "chunk-c", 0.60));

        List<RagSearchResult> results = retriever().retrieve(
                PROJECT_ID, "retry evidence", 2).results();

        assertEquals(List.of("chunk-a", "chunk-b"), results.stream()
                .map(RagSearchResult::chunkId).toList());
        assertEquals(List.of(0.95, 0.70), results.stream()
                .map(RagSearchResult::relevanceScore).toList());
        assertEquals(2, results.size());
    }

    @Test
    void equalScoresHaveStableIdentityTieBreakOrdering() {
        vectorStore.matches = List.of(
                new VectorSearchMatch(PROJECT_ID, "doc-b", "chunk-c", 0.80),
                new VectorSearchMatch(PROJECT_ID, "doc-a", "chunk-b", 0.80),
                new VectorSearchMatch(PROJECT_ID, "doc-a", "chunk-a", 0.80));

        assertEquals(List.of("chunk-a", "chunk-b", "chunk-c"),
                retriever().retrieve(PROJECT_ID, "stable order", 3).results().stream()
                        .map(RagSearchResult::chunkId).toList());
    }

    @Test
    void zeroHitReturnsEmptyAndRecordsDistinctFact() {
        vectorStore.matches = List.of();

        RagRetrieval retrieval = retriever().retrieve(PROJECT_ID, "no evidence", 3);

        assertTrue(retrieval.results().isEmpty());
        RagQueryRecord fact = records.saved.getFirst();
        assertEquals(RagQueryStatus.ZERO_HIT, fact.status());
        assertEquals(0, fact.retrievedCount());
        assertTrue(fact.resultReferences().isEmpty());
    }

    @Test
    void highScoreSurvivesRelevanceFilter() {
        vectorStore.matches = List.of(
                new VectorSearchMatch(PROJECT_ID, "doc-a", "chunk-a", 0.91),
                new VectorSearchMatch(PROJECT_ID, "doc-a", "chunk-b", 0.19));

        List<RagSearchResult> results = retriever(0.80)
                .retrieve(PROJECT_ID, "relevant evidence", 3).results();

        assertEquals(List.of("chunk-a"), results.stream()
                .map(RagSearchResult::chunkId).toList());
        assertEquals(RagQueryStatus.SUCCESS_WITH_RESULTS, records.saved.getFirst().status());
    }

    @Test
    void lowScoreOnlyBecomesZeroHitAfterRelevanceFilter() {
        vectorStore.matches = List.of(
                new VectorSearchMatch(PROJECT_ID, "doc-a", "chunk-a", 0.19));

        RagRetrieval retrieval = retriever(0.80)
                .retrieve(PROJECT_ID, "irrelevant evidence", 3);

        assertTrue(retrieval.results().isEmpty());
        assertEquals(RagQueryStatus.ZERO_HIT, records.saved.getFirst().status());
        assertEquals(0, records.saved.getFirst().retrievedCount());
    }

    @Test
    void highAndLowScoresReturnOnlyHighScoreMatches() {
        vectorStore.matches = List.of(
                new VectorSearchMatch(PROJECT_ID, "doc-a", "chunk-b", 0.21),
                new VectorSearchMatch(PROJECT_ID, "doc-a", "chunk-a", 0.80),
                new VectorSearchMatch(PROJECT_ID, "doc-b", "chunk-c", 0.79));

        List<RagSearchResult> results = retriever(0.80)
                .retrieve(PROJECT_ID, "threshold boundary", 3).results();

        assertEquals(List.of("chunk-a"), results.stream()
                .map(RagSearchResult::chunkId).toList());
    }

    @Test
    void defaultRelevanceFilterPreservesProviderResults() {
        vectorStore.matches = List.of(
                new VectorSearchMatch(PROJECT_ID, "doc-a", "chunk-a", 0.19));

        assertEquals(List.of("chunk-a"), retriever()
                .retrieve(PROJECT_ID, "legacy behavior", 3).results().stream()
                .map(RagSearchResult::chunkId).toList());
    }

    @Test
    void rejectsInvalidRelevanceFilter() {
        assertThrows(IllegalArgumentException.class, () -> retriever(-0.01));
        assertThrows(IllegalArgumentException.class, () -> retriever(1.01));
        assertThrows(IllegalArgumentException.class, () -> retriever(Double.NaN));
    }

    @Test
    void vectorFailureIsNotConvertedToZeroHitAndRecordsFailure() {
        VectorStoreException providerFailure = new VectorStoreException("unavailable");
        vectorStore.failure = providerFailure;

        RagRetrievalException failure = assertThrows(RagRetrievalException.class,
                () -> retriever().retrieve(PROJECT_ID, "evidence", 3));

        assertSame(providerFailure, failure.getCause());
        assertEquals(RagQueryStatus.FAILURE, records.saved.getFirst().status());
    }

    @Test
    void embeddingFailureIsNotConvertedToZeroHitAndSkipsVectorSearch() {
        EmbeddingException providerFailure = new EmbeddingException("unavailable");
        embedding.failure = providerFailure;

        RagRetrievalException failure = assertThrows(RagRetrievalException.class,
                () -> retriever().retrieve(PROJECT_ID, "evidence", 3));

        assertSame(providerFailure, failure.getCause());
        assertEquals(0, vectorStore.calls);
        assertEquals(RagQueryStatus.FAILURE, records.saved.getFirst().status());
    }

    @Test
    void rejectsCrossProjectProviderResultAsDefenseInDepth() {
        vectorStore.matches = List.of(new VectorSearchMatch(
                PROJECT_ID + 1, "doc-a", "chunk-a", 0.91));

        RagRetrievalException failure = assertThrows(RagRetrievalException.class,
                () -> retriever().retrieve(PROJECT_ID, "evidence", 3));

        assertEquals("Vector result violates the requested project scope",
                failure.getMessage());
        assertEquals(RagQueryStatus.FAILURE, records.saved.getFirst().status());
    }

    @Test
    void deniedProjectAccessStopsBeforeEmbeddingAndVectorSearch() {
        ProjectAuthorizationService denied = new ProjectAuthorizationService(
                (userId, projectId) -> Optional.empty());
        RagRetriever retriever = new RagRetriever(
                denied, embedding, vectorStore, knowledge, records, CLOCK);

        assertThrows(AccessDeniedException.class,
                () -> retriever.retrieve(PROJECT_ID, "evidence", 3));

        assertEquals(null, embedding.text);
        assertEquals(0, vectorStore.calls);
        assertTrue(records.saved.isEmpty());
    }

    private RagRetriever retriever() {
        return retriever(null);
    }

    private RagRetriever retriever(Double minRelevanceScore) {
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> userId == USER_ID && projectId == PROJECT_ID
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
        return new RagRetriever(
                authorization, embedding, vectorStore, knowledge, records, CLOCK,
                minRelevanceScore);
    }

    private void authenticate() {
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                USER_ID, "retrieval-user", "not-used", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
    }

    private Document document(String documentId, String sourceKey, String title) {
        return new Document(
                documentId, PROJECT_ID, sourceKey, "RUNBOOK", title, sourceKey + ".md",
                "text/markdown", "a".repeat(64), DocumentStatus.INDEXED, USER_ID,
                Instant.parse("2026-08-12T00:00:00Z"));
    }

    private DocumentChunk chunk(
            String documentId, String chunkId, int ordinal, String content) {
        return new DocumentChunk(
                chunkId, documentId, PROJECT_ID, ordinal, content, "b".repeat(64), Map.of());
    }

    private static final class CapturingEmbedding implements EmbeddingService {
        private String text;
        private RuntimeException failure;

        @Override
        public EmbeddingModel model() {
            return MODEL;
        }

        @Override
        public List<EmbeddingVector> embed(List<String> texts) {
            if (failure != null) {
                throw failure;
            }
            text = texts.getFirst();
            return List.of(QUERY_VECTOR);
        }
    }

    private static final class CapturingVectorStore implements VectorStoreService {
        private List<VectorSearchMatch> matches = List.of();
        private RuntimeException failure;
        private long projectId;
        private EmbeddingVector queryVector;
        private int topK;
        private int calls;

        @Override
        public void upsert(long projectId, String documentId, List<VectorEntry> entries) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<VectorSearchMatch> search(
                long projectId, EmbeddingVector queryVector, int topK) {
            calls++;
            this.projectId = projectId;
            this.queryVector = queryVector;
            this.topK = topK;
            if (failure != null) {
                throw failure;
            }
            return matches;
        }

        @Override
        public void deleteByDocument(long projectId, String documentId) {
            throw new UnsupportedOperationException();
        }
    }

    private static final class KnowledgeRepository implements DocumentRepository {
        private final Map<Key, Document> documents = new LinkedHashMap<>();
        private final Map<Key, List<DocumentChunk>> chunks = new LinkedHashMap<>();

        private void add(Document document, List<DocumentChunk> values) {
            Key key = new Key(document.projectId(), document.documentId());
            documents.put(key, document);
            chunks.put(key, List.copyOf(values));
        }

        @Override
        public Optional<Document> findBySourceKey(long projectId, String sourceKey) {
            return documents.values().stream()
                    .filter(value -> value.projectId() == projectId)
                    .filter(value -> value.sourceKey().equals(sourceKey))
                    .findFirst();
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

    private static final class QueryRecords implements RagQueryRecordRepository {
        private final List<RagQueryRecord> saved = new ArrayList<>();

        @Override
        public void save(RagQueryRecord record) {
            saved.add(record);
        }

        @Override
        public Optional<RagQueryRecord> findById(long projectId, String ragQueryId) {
            return saved.stream()
                    .filter(value -> value.projectId() == projectId)
                    .filter(value -> value.ragQueryId().equals(ragQueryId))
                    .findFirst();
        }
    }
}
