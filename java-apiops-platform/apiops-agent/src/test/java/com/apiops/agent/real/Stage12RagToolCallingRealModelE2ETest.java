package com.apiops.agent.real;

import com.apiops.agent.model.AgentModelRequest;
import com.apiops.agent.model.springai.SpringAiAgentModelClient;
import com.apiops.agent.tool.RagSearchToolCallbackFactory;
import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.rag.domain.Document;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;
import com.apiops.rag.embedding.EmbeddingVector;
import com.apiops.rag.embedding.zhipu.ZhipuEmbeddingService;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.repository.RagQueryRecordRepository;
import com.apiops.rag.retrieval.RagQueryRecord;
import com.apiops.rag.retrieval.RagQueryStatus;
import com.apiops.rag.retrieval.RagRetriever;
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.qdrant.QdrantVectorStoreService;
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.AuditStatus;
import com.apiops.tool.gateway.Metrics;
import com.apiops.tool.gateway.ParamValidator;
import com.apiops.tool.gateway.RagSearchTool;
import com.apiops.tool.gateway.ResourceGuard;
import com.apiops.tool.gateway.ResultLimiter;
import com.apiops.tool.gateway.ResultSanitizer;
import com.apiops.tool.gateway.ToolAuth;
import com.apiops.tool.gateway.ToolExecutionContext;
import com.apiops.tool.gateway.ToolExecutionLimiter;
import com.apiops.tool.gateway.ToolGateway;
import com.apiops.tool.gateway.ToolRegistry;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/** Real DeepSeek -> Gateway -> Stage 10 RAG -> Qdrant acceptance evidence. */
class Stage12RagToolCallingRealModelE2ETest {

    private static final long USER_ID = 7L;
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final String QUERY = "Check the order timeout before retrying.";

    private String qdrantBaseUrl;
    private String collection;
    private long projectId;
    private String documentId;
    private QdrantVectorStoreService vectorStore;

    @BeforeEach
    void setUp() {
        String embeddingKey = System.getenv("ZHIPU_API_KEY");
        qdrantBaseUrl = System.getenv("APIOPS_RAG_QDRANT_BASE_URL");
        assumeTrue(embeddingKey != null && !embeddingKey.isBlank()
                        && qdrantBaseUrl != null && !qdrantBaseUrl.isBlank(),
                "Set ZHIPU_API_KEY and APIOPS_RAG_QDRANT_BASE_URL");
        collection = "apiops_stage12_agent_rag_"
                + UUID.randomUUID().toString().replace("-", "");
        projectId = 9_700_000L + (UUID.randomUUID().hashCode() & 0x000f_ffffL);
        documentId = "stage12-real-rag-doc-" + UUID.randomUUID();
        vectorStore = new QdrantVectorStoreService(
                qdrantBaseUrl, collection, Duration.ofSeconds(10), "", OBJECT_MAPPER);
        vectorStore.initialize();
    }

    @AfterEach
    void cleanup() {
        if (qdrantBaseUrl == null || collection == null) {
            return;
        }
        try {
            HttpClient.newHttpClient().send(
                    HttpRequest.newBuilder(URI.create(
                                    qdrantBaseUrl + "/collections/" + collection))
                            .DELETE().timeout(Duration.ofSeconds(10)).build(),
                    HttpResponse.BodyHandlers.discarding());
        } catch (Exception ignored) {
            // Best-effort cleanup after the real infrastructure assertion.
        }
    }

    @Test
    void realDeepSeekUsesGatewayBackedRagAndContinuesWithCitation() {
        String embeddingKey = System.getenv("ZHIPU_API_KEY");
        ZhipuEmbeddingService embeddings = new ZhipuEmbeddingService(
                embeddingKey, Duration.ofSeconds(30), OBJECT_MAPPER);
        EmbeddingVector vector = embeddings.embed(QUERY);

        Knowledge knowledge = new Knowledge();
        knowledge.add(new Document(
                documentId, projectId, "runbook/stage12-orders", "RUNBOOK",
                "Stage 12 order runbook", "orders.md", "text/markdown",
                "a".repeat(64), DocumentStatus.INDEXED, USER_ID, Instant.now()),
                List.of(new DocumentChunk(
                        "chunk-stage12-real-rag", documentId, projectId, 0,
                        "The order timeout is bounded before a retry is considered.",
                        "b".repeat(64), Map.of())));
        vectorStore.upsert(projectId, documentId, List.of(new VectorEntry(
                projectId, documentId, "chunk-stage12-real-rag", "b".repeat(64),
                vector, Map.of())));

        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, requestedProjectId) -> userId == USER_ID
                        && requestedProjectId == projectId
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
        Records records = new Records();
        RagRetriever retriever = new RagRetriever(
                authorization, embeddings, vectorStore, knowledge, records,
                Clock.systemUTC());
        ToolRegistry registry = new ToolRegistry(authorization);
        RagSearchTool.register(registry);
        Audit audit = new Audit();
        Metrics metrics = new Metrics();
        ToolGateway gateway = new ToolGateway(
                new ToolAuth(registry, authorization),
                new ParamValidator(),
                ResourceGuard.allowAll(),
                new ToolExecutionLimiter(Duration.ofSeconds(30), 4, 2),
                new ResultSanitizer(),
                new ResultLimiter(100_000),
                audit,
                metrics);
        ToolExecutionContext trustedContext = new ToolExecutionContext(
                USER_ID, projectId, Set.of("TOOL_READ"),
                "caller-supplied-value", "stage12-real-agent-run", "stage12-real-model-call");

        try (gateway) {
            SpringAiAgentModelClient modelClient =
                    (SpringAiAgentModelClient) DeepSeekRealTestSupport.client();
            var response = modelClient.callWithRagTool(
                    new AgentModelRequest(
                            "stage12-real-rag", "v1",
                            "You are a Gateway security acceptance test. You must call "
                                    + "rag.search exactly once with the supplied query and topK=1. "
                                    + "After the tool result, return a JSON object with "
                                    + "toolResultUsed=true, citationPreserved=true, and chunkId "
                                    + "copied exactly from the tool result. Do not invent evidence.",
                            "Call rag.search exactly once with query " + QUERY
                                    + " and topK=1, then continue using the returned citation.",
                            "{}"),
                    trustedContext,
                    new RagSearchToolCallbackFactory(gateway, registry, retriever, OBJECT_MAPPER));

            String finalContent = response.content().toLowerCase(java.util.Locale.ROOT);
            assertTrue(finalContent.contains("toolresultused"));
            assertTrue(finalContent.contains("true"));
            assertTrue(finalContent.contains("chunk-stage12-real-rag"));
            assertTrue(finalContent.contains("citationpreserved"));
            assertNotNull(records.saved);
            assertEquals(RagQueryStatus.SUCCESS_WITH_RESULTS, records.saved.status());
            assertEquals(1, records.saved.retrievedCount());
            assertEquals(1, audit.events().size());
            Audit.AuditEvent event = audit.events().getFirst();
            assertEquals(RagSearchTool.TOOL_NAME, event.toolName());
            assertEquals(projectId, event.projectId());
            assertEquals(AuditStatus.SUCCESS, event.status());
            assertFalse(event.toolCallId().equals(trustedContext.toolCallId()));
            assertTrue(event.sanitizedSummary().contains("citation"));
            assertTrue(metrics.snapshot().calls() == 1);
            assertEquals(1, metrics.snapshot().success());

            System.out.println("REAL_STAGE12_RAG_TOOL_E2E provider=DeepSeek"
                    + " toolName=" + RagSearchTool.TOOL_NAME
                    + " projectId=" + projectId
                    + " status=SUCCESS citationPreserved=true"
                    + " auditFacts=1 metricsCalls=" + metrics.snapshot().calls()
                    + " finalResponseObserved=true");
        }
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
