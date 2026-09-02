package com.apiops.agent.tool;

import com.apiops.agent.model.AgentModelRequest;
import com.apiops.agent.model.springai.SpringAiAgentModelClient;
import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.rag.domain.Document;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;
import com.apiops.rag.embedding.EmbeddingModel;
import com.apiops.rag.embedding.EmbeddingService;
import com.apiops.rag.embedding.EmbeddingVector;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.repository.RagQueryRecordRepository;
import com.apiops.rag.retrieval.RagQueryRecord;
import com.apiops.rag.retrieval.RagRetriever;
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.VectorSearchMatch;
import com.apiops.rag.vector.VectorStoreService;
import com.apiops.tool.gateway.Audit;
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
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.model.tool.ToolCallingChatOptions;
import org.springframework.ai.tool.ToolCallback;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RagSearchToolCallbackFactoryTest {

    private static final long USER_ID = 7L;
    private static final long PROJECT_ID = 42L;
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final EmbeddingModel MODEL =
            new EmbeddingModel("fake", "agent-rag-test", 2);
    private static final EmbeddingVector VECTOR =
            new EmbeddingVector(MODEL, List.of(1.0F, 0.0F));

    @Test
    void modelContinuationUsesGatewayBoundRagCallbackAndKeepsCitation() throws Exception {
        Fixture fixture = fixture();
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                membershipFor(PROJECT_ID));
        ToolRegistry registry = new ToolRegistry(authorization);
        RagSearchTool.register(registry);
        ToolGateway gateway = new ToolGateway(
                new ToolAuth(registry, authorization),
                new ParamValidator(),
                ResourceGuard.allowAll(),
                new ToolExecutionLimiter(Duration.ofSeconds(3), 50, 2),
                new ResultSanitizer(),
                new ResultLimiter(100_000),
                new Audit(),
                new com.apiops.tool.gateway.Metrics());
        RagSearchToolCallbackFactory factory = new RagSearchToolCallbackFactory(
                gateway, registry, fixture.retriever, MAPPER);
        ToolExecutionContext trustedContext = new ToolExecutionContext(
                USER_ID, PROJECT_ID, Set.of("TOOL_READ"),
                "model-tool-call", "agent-run-rag");
        assertThrows(IllegalArgumentException.class,
                () -> factory.create(trustedContext, ToolRegistry.GENERATE_TEST_CASE));
        AtomicReference<String> callbackResult = new AtomicReference<>();
        ChatModel model = prompt -> {
            ToolCallingChatOptions options = (ToolCallingChatOptions) prompt.getOptions();
            assertEquals(1, options.getToolCallbacks().size());
            ToolCallback callback = options.getToolCallbacks().getFirst();
            assertEquals("rag_search",
                    callback.getToolDefinition().name());
            String toolResult = callback.call(
                    "{\"query\":\"order timeout\",\"topK\":1}");
            callbackResult.set(toolResult);
            return new ChatResponse(
                    List.of(new Generation(new AssistantMessage(
                            "continuation:" + toolResult))),
                    ChatResponseMetadata.builder().id("model-call-rag").build());
        };

        try (gateway) {
            var response = new SpringAiAgentModelClient(model)
                    .callWithRagTool(
                            new AgentModelRequest(
                                    "diagnosis", "v1", "system", "search", "{}"),
                            trustedContext,
                            factory);

            JsonNode toolResult = MAPPER.readTree(callbackResult.get());
            assertEquals("SUCCESS", toolResult.get("status").asText());
            assertTrue(callbackResult.get().contains("citation"));
            assertTrue(response.content().contains("chunk-rag"));
            assertEquals(1, fixture.embedding.calls);
            assertEquals(1, fixture.vectorStore.calls);
            assertEquals(PROJECT_ID, fixture.vectorStore.projectId);
        }
    }

    @Test
    void deniedOrInvalidRagCallbackDoesNotInvokeRetriever() throws Exception {
        Fixture fixture = fixture();
        AtomicBoolean projectAllowed = new AtomicBoolean(true);
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> projectAllowed.get()
                        && userId == USER_ID && projectId == PROJECT_ID
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
        ToolRegistry registry = new ToolRegistry(authorization);
        RagSearchTool.register(registry);
        ToolGateway gateway = new ToolGateway(
                new ToolAuth(registry, authorization),
                new ParamValidator(),
                ResourceGuard.allowAll(),
                new ToolExecutionLimiter(Duration.ofSeconds(3), 50, 2),
                new ResultSanitizer(),
                new ResultLimiter(100_000),
                new Audit(),
                new com.apiops.tool.gateway.Metrics());
        RagSearchToolCallbackFactory factory = new RagSearchToolCallbackFactory(
                gateway, registry, fixture.retriever, MAPPER);
        ToolExecutionContext trustedContext = new ToolExecutionContext(
                USER_ID, PROJECT_ID, Set.of("TOOL_READ"),
                "model-tool-call", "agent-run-rag");

        try (gateway) {
            GatewayToolCallbackAdapter callback = factory.create(trustedContext);
            JsonNode invalid = MAPPER.readTree(callback.call(
                    "{\"query\":\"order timeout\",\"topK\":1,\"projectId\":999}"));
            assertEquals("PARAM_INVALID", invalid.get("status").asText());
            assertEquals(0, fixture.embedding.calls);

            projectAllowed.set(false);
            JsonNode denied = MAPPER.readTree(callback.call(
                    "{\"query\":\"order timeout\",\"topK\":1}"));
            assertEquals("FORBIDDEN", denied.get("status").asText());
            assertEquals(0, fixture.embedding.calls);
            assertEquals(0, fixture.vectorStore.calls);
        }
    }

    private static ProjectMembershipRepository membershipFor(long projectId) {
        return (userId, requestedProjectId) -> userId == USER_ID
                && requestedProjectId == projectId
                ? Optional.of(ProjectRole.VIEWER) : Optional.empty();
    }

    private static Fixture fixture() {
        CapturingEmbedding embedding = new CapturingEmbedding();
        CapturingVectorStore vectorStore = new CapturingVectorStore();
        KnowledgeRepository knowledge = new KnowledgeRepository();
        QueryRecords records = new QueryRecords();
        Document document = new Document(
                "doc-rag", PROJECT_ID, "runbook/orders", "RUNBOOK", "Orders runbook",
                "orders.md", "text/markdown", "a".repeat(64), DocumentStatus.INDEXED,
                USER_ID, Instant.parse("2026-08-14T00:00:00Z"));
        knowledge.add(document, List.of(new DocumentChunk(
                "chunk-rag", "doc-rag", PROJECT_ID, 0,
                "Check the order timeout.", "b".repeat(64), Map.of())));
        vectorStore.matches = List.of(new VectorSearchMatch(
                PROJECT_ID, "doc-rag", "chunk-rag", 0.91));
        RagRetriever retriever = new RagRetriever(
                new ProjectAuthorizationService(membershipFor(PROJECT_ID)),
                embedding, vectorStore, knowledge, records,
                Clock.fixed(Instant.parse("2026-08-15T00:00:00Z"), ZoneOffset.UTC));
        return new Fixture(embedding, vectorStore, retriever);
    }

    private record Fixture(
            CapturingEmbedding embedding,
            CapturingVectorStore vectorStore,
            RagRetriever retriever
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
            return List.of(VECTOR);
        }
    }

    private static final class CapturingVectorStore implements VectorStoreService {
        private List<VectorSearchMatch> matches = List.of();
        private int calls;
        private long projectId;

        @Override
        public void upsert(long projectId, String documentId, List<VectorEntry> entries) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<VectorSearchMatch> search(
                long projectId, EmbeddingVector queryVector, int topK) {
            calls++;
            this.projectId = projectId;
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
