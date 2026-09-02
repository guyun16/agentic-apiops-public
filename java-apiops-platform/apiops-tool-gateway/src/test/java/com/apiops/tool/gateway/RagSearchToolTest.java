package com.apiops.tool.gateway;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.common.tool.ToolResult;
import com.apiops.rag.domain.Document;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;
import com.apiops.rag.embedding.EmbeddingModel;
import com.apiops.rag.embedding.EmbeddingService;
import com.apiops.rag.embedding.EmbeddingVector;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.repository.RagQueryRecordRepository;
import com.apiops.rag.retrieval.RagQueryRecord;
import com.apiops.rag.retrieval.RagQueryStatus;
import com.apiops.rag.retrieval.RagRetriever;
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.VectorSearchMatch;
import com.apiops.rag.vector.VectorStoreService;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RagSearchToolTest {

    private static final long USER_ID = 7L;
    private static final long PROJECT_ID = 42L;
    private static final EmbeddingModel MODEL =
            new EmbeddingModel("fake", "gateway-rag-test", 2);
    private static final EmbeddingVector QUERY_VECTOR =
            new EmbeddingVector(MODEL, List.of(1.0F, 0.0F));
    private static final Clock CLOCK = Clock.fixed(
            Instant.parse("2026-08-15T00:00:00Z"), ZoneOffset.UTC);

    @Test
    void allowedRagSearchRunsThroughGatewayAndPreservesCitation() {
        Fixture fixture = fixture();
        try (ToolSecurityTestSupport.Bundle bundle =
                     ToolSecurityTestSupport.gateway(
                             RagSearchTool.definition(),
                             ResourceGuard.projectReadable(fixture.authorization))) {
            ToolResult<Object> result = RagSearchTool.execute(
                    bundle.gateway(),
                    fixture.retriever,
                    ToolSecurityTestSupport.context("rag-run"),
                    new ToolCallIntent(RagSearchTool.TOOL_NAME,
                            Map.of("query", "why did the order fail", "topK", 2)));

            assertEquals("SUCCESS", result.getStatus().name());
            assertEquals(1, fixture.embedding.calls);
            assertEquals(1, fixture.vectorStore.calls);
            assertEquals(PROJECT_ID, fixture.vectorStore.projectId);
            assertEquals(2, fixture.vectorStore.topK);
            assertEquals(RagQueryStatus.SUCCESS_WITH_RESULTS,
                    fixture.queryRecords.saved.getFirst().status());
            assertNotNull(result.getData());
            Map<?, ?> data = (Map<?, ?>) result.getData();
            assertNotNull(data.get("ragQueryId"));
            List<?> results = (List<?>) data.get("results");
            assertEquals(1, results.size());
            Map<?, ?> modelResult = (Map<?, ?>) results.getFirst();
            assertEquals("chunk-rag", modelResult.get("chunkId"));
            Map<?, ?> citation = (Map<?, ?>) modelResult.get("citation");
            assertEquals("RUNBOOK", citation.get("sourceType"));
            assertEquals("chunk:0", citation.get("location"));
            assertEquals("Check the order timeout.", citation.get("excerpt"));
        }
    }

    @Test
    void omittedTargetFallsBackToTrustedCurrentProject() {
        Fixture fixture = fixture();
        try (ToolSecurityTestSupport.Bundle bundle =
                     ToolSecurityTestSupport.gateway(
                             RagSearchTool.definition(),
                             ResourceGuard.projectReadable(fixture.authorization))) {
            ToolResult<Object> result = RagSearchTool.execute(
                    bundle.gateway(),
                    fixture.retriever,
                    ToolSecurityTestSupport.context("rag-current-scope"),
                    validIntent());

            assertEquals("SUCCESS", result.getStatus().name());
            assertEquals(PROJECT_ID, fixture.vectorStore.projectId);
        }
    }

    @Test
    void authorizedCrossProjectTargetUsesTargetMembershipAndRetrieverScope() {
        Fixture fixture = fixture((userId, projectId) ->
                userId == USER_ID && (projectId == 41L || projectId == PROJECT_ID)
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
        ToolExecutionContext context = new ToolExecutionContext(
                USER_ID, 41L, Set.of("TOOL_READ"), "caller", "rag-cross-project");
        try (ToolSecurityTestSupport.Bundle bundle =
                     ToolSecurityTestSupport.gateway(
                             RagSearchTool.definition(),
                             ResourceGuard.projectReadable(fixture.authorization),
                             (userId, projectId) ->
                                     userId == USER_ID && (projectId == 41L || projectId == PROJECT_ID)
                                             ? Optional.of(ProjectRole.VIEWER) : Optional.empty())) {
            ToolResult<Object> result = RagSearchTool.execute(
                    bundle.gateway(),
                    fixture.retriever,
                    context,
                    new ToolCallIntent(RagSearchTool.TOOL_NAME,
                            Map.of("query", "why did the order fail", "topK", 2,
                                    RagSearchTool.TARGET_PROJECT_ARGUMENT, (int) PROJECT_ID)));

            assertEquals("SUCCESS", result.getStatus().name());
            assertEquals(PROJECT_ID, fixture.vectorStore.projectId);
            assertEquals(1, fixture.embedding.calls);
            assertEquals(1, fixture.vectorStore.calls);
            assertEquals(PROJECT_ID, bundle.audit().events().getFirst().requestedTargetProjectId());
        }
    }

    @Test
    void unauthorizedCrossProjectTargetIsForbiddenBeforeRetriever() {
        Fixture fixture = fixture((userId, projectId) ->
                userId == USER_ID && projectId == 41L
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
        ToolExecutionContext context = new ToolExecutionContext(
                USER_ID, 41L, Set.of("TOOL_READ"), "caller", "rag-denied-target");
        try (ToolSecurityTestSupport.Bundle bundle =
                     ToolSecurityTestSupport.gateway(
                             RagSearchTool.definition(),
                             ResourceGuard.projectReadable(fixture.authorization),
                             (userId, projectId) -> userId == USER_ID && projectId == 41L
                                     ? Optional.of(ProjectRole.VIEWER) : Optional.empty())) {
            ToolResult<Object> result = RagSearchTool.execute(
                    bundle.gateway(),
                    fixture.retriever,
                    context,
                    new ToolCallIntent(RagSearchTool.TOOL_NAME,
                            Map.of("query", "why did the order fail", "topK", 2,
                                    RagSearchTool.TARGET_PROJECT_ARGUMENT, (int) PROJECT_ID)));

            assertEquals("FORBIDDEN", result.getStatus().name());
            assertEquals(0, fixture.embedding.calls);
            assertEquals(0, fixture.vectorStore.calls);
            assertEquals(41L, bundle.audit().events().getFirst().projectId());
            assertEquals(PROJECT_ID,
                    bundle.audit().events().getFirst().requestedTargetProjectId());
        }
    }

    @Test
    void missingToolAuthorityStopsBeforeTargetAuthorizationAndRetriever() {
        Fixture fixture = fixture();
        ToolExecutionContext context = new ToolExecutionContext(
                USER_ID, PROJECT_ID, Set.of(), "caller", "rag-no-tool-authority");
        try (ToolSecurityTestSupport.Bundle bundle =
                     ToolSecurityTestSupport.gateway(
                             RagSearchTool.definition(),
                             ResourceGuard.projectReadable(fixture.authorization))) {
            ToolResult<Object> result = RagSearchTool.execute(
                    bundle.gateway(),
                    fixture.retriever,
                    context,
                    new ToolCallIntent(RagSearchTool.TOOL_NAME,
                            Map.of("query", "why did the order fail", "topK", 2,
                                    RagSearchTool.TARGET_PROJECT_ARGUMENT, (int) PROJECT_ID)));

            assertEquals("FORBIDDEN", result.getStatus().name());
            assertEquals(0, fixture.embedding.calls);
            assertEquals(0, fixture.vectorStore.calls);
        }
    }

    @Test
    void zeroHitRagSearchIsSuccessfulEmptyResult() {
        Fixture fixture = fixture();
        fixture.vectorStore.matches = List.of();
        try (ToolSecurityTestSupport.Bundle bundle =
                     ToolSecurityTestSupport.gateway(RagSearchTool.definition(), ResourceGuard.allowAll())) {
            ToolResult<Object> result = RagSearchTool.execute(
                    bundle.gateway(),
                    fixture.retriever,
                    ToolSecurityTestSupport.context("rag-zero-hit"),
                    validIntent());

            assertEquals("SUCCESS", result.getStatus().name());
            Map<?, ?> data = (Map<?, ?>) result.getData();
            assertTrue(((List<?>) data.get("results")).isEmpty());
            assertEquals(RagQueryStatus.ZERO_HIT, fixture.queryRecords.saved.getFirst().status());
        }
    }

    @Test
    void deniedContextStopsBeforeRagRetrieverAndUnderlyingResources() {
        Fixture fixture = fixture();
        ToolExecutionContext crossProject = new ToolExecutionContext(
                USER_ID, PROJECT_ID + 1, Set.of("TOOL_READ"), "caller", "rag-run");
        try (ToolSecurityTestSupport.Bundle bundle =
                     ToolSecurityTestSupport.gateway(RagSearchTool.definition(), ResourceGuard.allowAll())) {
            ToolResult<Object> result = RagSearchTool.execute(
                    bundle.gateway(),
                    fixture.retriever,
                    crossProject,
                    validIntent());

            assertEquals("FORBIDDEN", result.getStatus().name());
            assertEquals(0, fixture.embedding.calls);
            assertEquals(0, fixture.vectorStore.calls);
            assertTrue(fixture.queryRecords.saved.isEmpty());
        }
    }

    @Test
    void invalidModelArgumentsStopBeforeRagRetriever() {
        Fixture fixture = fixture();
        try (ToolSecurityTestSupport.Bundle bundle =
                     ToolSecurityTestSupport.gateway(RagSearchTool.definition(), ResourceGuard.allowAll())) {
            ToolResult<Object> result = RagSearchTool.execute(
                    bundle.gateway(),
                    fixture.retriever,
                    ToolSecurityTestSupport.context("rag-run"),
                    new ToolCallIntent(RagSearchTool.TOOL_NAME,
                            Map.of("query", "evidence", "topK", 2, "projectId", 999)));

            assertEquals("PARAM_INVALID", result.getStatus().name());
            assertEquals(0, fixture.embedding.calls);
            assertEquals(0, fixture.vectorStore.calls);
            assertTrue(fixture.queryRecords.saved.isEmpty());
        }
    }

    @Test
    void modelCannotSupplyProjectIdentityToRagHandler() {
        Fixture fixture = fixture();
        try (ToolSecurityTestSupport.Bundle bundle =
                     ToolSecurityTestSupport.gateway(RagSearchTool.definition(), ResourceGuard.allowAll())) {
            ToolResult<Object> result = RagSearchTool.execute(
                    bundle.gateway(),
                    fixture.retriever,
                    ToolSecurityTestSupport.context("rag-run"),
                    new ToolCallIntent(RagSearchTool.TOOL_NAME,
                            Map.of("query", "evidence", "topK", 2, "userId", USER_ID,
                                    "projectId", PROJECT_ID)));

            assertEquals("PARAM_INVALID", result.getStatus().name());
            assertFalse(fixture.embedding.calls > 0);
            assertFalse(fixture.vectorStore.calls > 0);
        }
    }

    private static ToolCallIntent validIntent() {
        return new ToolCallIntent(RagSearchTool.TOOL_NAME,
                Map.of("query", "why did the order fail", "topK", 2));
    }

    private static Fixture fixture() {
        return fixture((userId, projectId) -> userId == USER_ID && projectId == PROJECT_ID
                ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
    }

    private static Fixture fixture(ProjectMembershipRepository membershipRepository) {
        CapturingEmbedding embedding = new CapturingEmbedding();
        CapturingVectorStore vectorStore = new CapturingVectorStore();
        KnowledgeRepository knowledge = new KnowledgeRepository();
        QueryRecords queryRecords = new QueryRecords();
        Document document = new Document(
                "doc-rag", PROJECT_ID, "runbook/orders", "RUNBOOK", "Orders runbook",
                "orders.md", "text/markdown", "a".repeat(64), DocumentStatus.INDEXED,
                USER_ID, Instant.parse("2026-08-14T00:00:00Z"));
        DocumentChunk chunk = new DocumentChunk(
                "chunk-rag", "doc-rag", PROJECT_ID, 0,
                "Check the order timeout.", "b".repeat(64), Map.of());
        knowledge.add(document, List.of(chunk));
        vectorStore.matches = List.of(new VectorSearchMatch(
                PROJECT_ID, "doc-rag", "chunk-rag", 0.91));
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                membershipRepository);
        return new Fixture(
                embedding,
                vectorStore,
                queryRecords,
                new RagRetriever(authorization, embedding, vectorStore, knowledge,
                        queryRecords, CLOCK),
                authorization);
    }

    private record Fixture(
            CapturingEmbedding embedding,
            CapturingVectorStore vectorStore,
            QueryRecords queryRecords,
            RagRetriever retriever,
            ProjectAuthorizationService authorization
    ) {
    }

    private static final class CapturingEmbedding implements EmbeddingService {
        private int calls;

        @Override
        public EmbeddingModel model() {
            return MODEL;
        }

        @Override
        public List<EmbeddingVector> embed(List<String> texts) {
            calls++;
            return List.of(QUERY_VECTOR);
        }
    }

    private static final class CapturingVectorStore implements VectorStoreService {
        private List<VectorSearchMatch> matches = List.of();
        private int calls;
        private long projectId;
        private int topK;

        @Override
        public void upsert(long projectId, String documentId, List<VectorEntry> entries) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<VectorSearchMatch> search(
                long projectId, EmbeddingVector queryVector, int topK) {
            calls++;
            this.projectId = projectId;
            this.topK = topK;
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
