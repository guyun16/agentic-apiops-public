package com.apiops.rag.application;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.common.enums.FailureType;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.converter.OpenApiMetadataAssembler;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.rag.context.ContextCompressor;
import com.apiops.rag.context.ContextDeduplicator;
import com.apiops.rag.context.ContextPack;
import com.apiops.rag.context.ContextPackBuilder;
import com.apiops.rag.context.ContextPackProperties;
import com.apiops.rag.context.ContextRanker;
import com.apiops.rag.context.SensitiveDataMasker;
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
import com.apiops.rag.retrieval.RagSearchResult;
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.VectorSearchMatch;
import com.apiops.rag.vector.VectorStoreService;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.assembler.TestReportAssembler;
import com.apiops.report.vo.TestReportVO;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.state.RunStatus;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.lang.reflect.Proxy;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;

class DiagnosticContextApplicationServiceTest {

    private static final long PROJECT_ID = 41L;
    private static final long USER_ID = 7L;

    @AfterEach
    void clearSecurity() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void usesAllFormalBoundariesPropagatesProjectAndReturnsBuilderPack() {
        authenticate();
        TestReportVO report = report();
        ApiMetadataDetailVO metadata = metadata();
        RecordingTestReportQueryService reports =
                new RecordingTestReportQueryService(report);
        RecordingOpenApiQueryService apis = new RecordingOpenApiQueryService(metadata);
        CapturingEmbeddingService embedding = new CapturingEmbeddingService();
        CapturingVectorStore vectorStore = new CapturingVectorStore();
        CapturingQueryRecordRepository queryRecords = new CapturingQueryRecordRepository();
        RagRetriever retriever = new RagRetriever(
                authorization(), embedding, vectorStore,
                new EmptyDocumentRepository(), queryRecords,
                Clock.fixed(Instant.parse("2026-08-13T02:00:00Z"), ZoneOffset.UTC));
        RecordingContextPackBuilder builder = new RecordingContextPackBuilder();
        DiagnosticContextApplicationService service =
                new DiagnosticContextApplicationService(reports, apis, retriever, builder);

        ContextPack pack = service.buildContext(
                PROJECT_ID, 34L, "api-1", "why did it fail?", 3);

        assertEquals(1, reports.calls);
        assertEquals(PROJECT_ID, reports.projectId);
        assertEquals(34L, reports.runId);
        assertEquals(1, apis.calls);
        assertEquals(PROJECT_ID, apis.projectId);
        assertEquals("api-1", apis.apiId);
        assertEquals("why did it fail?", embedding.text);
        assertEquals(PROJECT_ID, vectorStore.projectId);
        assertEquals(3, vectorStore.topK);
        assertEquals(PROJECT_ID, queryRecords.saved.projectId());
        assertEquals(PROJECT_ID, builder.projectId);
        assertSame(report, builder.report);
        assertSame(metadata, builder.metadata);
        assertEquals(List.of(), builder.ragResults);
        assertSame(builder.returned, pack);
        assertEquals(PROJECT_ID, pack.projectId());
    }

    private static ProjectAuthorizationService authorization() {
        return new ProjectAuthorizationService((userId, projectId) ->
                userId == USER_ID && projectId == PROJECT_ID
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
    }

    private static void authenticate() {
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                USER_ID, "context-user", "unused", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
    }

    private static TestReportVO report() {
        return new TestReportVO(
                PROJECT_ID, 12L, 34L, RunStatus.ASSERTION_FAILED,
                Instant.parse("2026-08-13T01:00:00Z"),
                Instant.parse("2026-08-13T01:00:02Z"),
                new TestReportVO.Summary(
                        1, 1, 1, 0, 1, FailureType.ASSERTION_MISMATCH),
                List.of());
    }

    private static ApiMetadataDetailVO metadata() {
        return new ApiMetadataDetailVO(
                "api-1", "doc-1", "getOrder", "GET", "/orders/{id}",
                "Get order", "Returns one order",
                JsonNodeFactory.instance.arrayNode().add("orders"),
                JsonNodeFactory.instance.arrayNode(),
                JsonNodeFactory.instance.arrayNode(), false,
                List.of(), List.of(), List.of(), List.of());
    }

    @SuppressWarnings("unchecked")
    private static <T> T unusedProxy(Class<T> type) {
        return (T) Proxy.newProxyInstance(
                type.getClassLoader(), new Class<?>[]{type},
                (proxy, method, arguments) -> {
                    throw new UnsupportedOperationException(method.getName());
                });
    }

    private static final class RecordingTestReportQueryService
            extends TestReportQueryService {
        private final TestReportVO value;
        private int calls;
        private long projectId;
        private long runId;

        private RecordingTestReportQueryService(TestReportVO value) {
            super(authorization(), unusedProxy(ExecutionFactRepository.class),
                    new TestReportAssembler(new ObjectMapper().findAndRegisterModules()));
            this.value = value;
        }

        @Override
        public TestReportVO getReport(long projectId, long runId) {
            calls++;
            this.projectId = projectId;
            this.runId = runId;
            return value;
        }
    }

    private static final class RecordingOpenApiQueryService
            extends OpenApiQueryApplicationService {
        private final ApiMetadataDetailVO value;
        private int calls;
        private long projectId;
        private String apiId;

        private RecordingOpenApiQueryService(ApiMetadataDetailVO value) {
            super(authorization(), unusedProxy(OpenApiMetadataRepository.class),
                    new OpenApiMetadataAssembler());
            this.value = value;
        }

        @Override
        public ApiMetadataDetailVO getApi(long projectId, String apiId) {
            calls++;
            this.projectId = projectId;
            this.apiId = apiId;
            return value;
        }
    }

    private static final class CapturingEmbeddingService implements EmbeddingService {
        private static final EmbeddingModel MODEL = new EmbeddingModel("fake", "context", 2);
        private String text;

        @Override
        public EmbeddingModel model() {
            return MODEL;
        }

        @Override
        public List<EmbeddingVector> embed(List<String> texts) {
            text = texts.getFirst();
            return List.of(new EmbeddingVector(MODEL, List.of(1.0F, 0.0F)));
        }
    }

    private static final class CapturingVectorStore implements VectorStoreService {
        private long projectId;
        private int topK;

        @Override
        public void upsert(long projectId, String documentId, List<VectorEntry> entries) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<VectorSearchMatch> search(
                long projectId, EmbeddingVector queryVector, int topK) {
            this.projectId = projectId;
            this.topK = topK;
            return List.of();
        }

        @Override
        public void deleteByDocument(long projectId, String documentId) {
            throw new UnsupportedOperationException();
        }
    }

    private static final class EmptyDocumentRepository implements DocumentRepository {
        @Override
        public Optional<Document> findBySourceKey(long projectId, String sourceKey) {
            return Optional.empty();
        }

        @Override
        public Optional<Document> findById(long projectId, String documentId) {
            return Optional.empty();
        }

        @Override
        public List<DocumentChunk> findChunks(long projectId, String documentId) {
            return List.of();
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
    }

    private static final class CapturingQueryRecordRepository
            implements RagQueryRecordRepository {
        private RagQueryRecord saved;

        @Override
        public void save(RagQueryRecord record) {
            saved = record;
        }

        @Override
        public Optional<RagQueryRecord> findById(long projectId, String ragQueryId) {
            return Optional.ofNullable(saved);
        }
    }

    private static final class RecordingContextPackBuilder extends ContextPackBuilder {
        private long projectId;
        private TestReportVO report;
        private ApiMetadataDetailVO metadata;
        private List<RagSearchResult> ragResults;
        private ContextPack returned;

        private RecordingContextPackBuilder() {
            super(new ObjectMapper().findAndRegisterModules(),
                    new SensitiveDataMasker(), new ContextDeduplicator(),
                    new ContextRanker(), new ContextCompressor(new ContextPackProperties()));
        }

        @Override
        public ContextPack build(
                long projectId,
                TestReportVO report,
                ApiMetadataDetailVO metadata,
                List<RagSearchResult> ragResults
        ) {
            this.projectId = projectId;
            this.report = report;
            this.metadata = metadata;
            this.ragResults = ragResults;
            returned = super.build(projectId, report, metadata, ragResults);
            return returned;
        }
    }
}
