package com.apiops.agent.real;

import com.apiops.agent.diagnosis.DiagnosisAgent;
import com.apiops.agent.diagnosis.DiagnosisApplicationService;
import com.apiops.agent.diagnosis.DiagnosisCitationValidator;
import com.apiops.agent.diagnosis.DiagnosisReportCandidateMapper;
import com.apiops.agent.prompt.PromptTemplateService;
import com.apiops.agent.structured.BoundedStructuredOutputRepair;
import com.apiops.agent.structured.StructuredOutputException;
import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.common.enums.FailureType;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.rag.application.DiagnosticContextApplicationService;
import com.apiops.rag.context.ContextCompressor;
import com.apiops.rag.context.ContextDeduplicator;
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
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.VectorSearchMatch;
import com.apiops.rag.vector.VectorStoreService;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.vo.TestReportVO;
import com.apiops.runner.state.RunStatus;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** Explicit real-provider acceptance; excluded from default Surefire execution. */
class Stage11DiagnosisRealModelE2ETest {

    private static final long PROJECT_ID = 11004L;
    private static final long RUN_ID = 110401L;
    private static final long USER_ID = 1104L;
    private static final String API_ID = "api_stage11_diagnosis";
    private static final String OPERATION_ID = "createOrder";

    @BeforeEach
    void authenticate() {
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                USER_ID, "stage11-diagnosis-real", "unused", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
    }

    @AfterEach
    void clearAuthentication() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void realFailedReportMetadataContextPackToDeepSeekDiagnosisAndCitationValidation() {
        String apiKey = System.getenv(DeepSeekRealTestSupport.API_KEY_ENV);
        Assumptions.assumeTrue(apiKey != null && !apiKey.isBlank(),
                () -> "Set " + DeepSeekRealTestSupport.API_KEY_ENV
                        + " for the explicit real diagnosis acceptance");

        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> userId == USER_ID && projectId == PROJECT_ID
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
        TestReportVO report = failedReport();
        ApiMetadataDetailVO metadata = metadata();
        TestReportQueryService reports = mock(TestReportQueryService.class);
        OpenApiQueryApplicationService apis = mock(OpenApiQueryApplicationService.class);
        when(reports.getReport(PROJECT_ID, RUN_ID)).thenReturn(report);
        when(apis.getApi(PROJECT_ID, API_ID)).thenReturn(metadata);

        RagRetriever rag = new RagRetriever(
                authorization,
                new FixedEmbeddingService(),
                new FixedVectorStore(),
                new FixedDocumentRepository(),
                new RecordingRagQueryRecordRepository(),
                Clock.fixed(Instant.parse("2026-08-13T00:00:00Z"), ZoneOffset.UTC));
        JsonMapper objectMapper = JsonMapper.builder()
                .addModule(new JavaTimeModule())
                .build();
        ContextPackBuilder contextBuilder = new ContextPackBuilder(
                objectMapper, new SensitiveDataMasker(),
                new ContextDeduplicator(), new ContextRanker(),
                new ContextCompressor(new ContextPackProperties()));
        DiagnosticContextApplicationService contextService =
                new DiagnosticContextApplicationService(reports, apis, rag, contextBuilder);

        var modelClient = DeepSeekRealTestSupport.client();
        DiagnosisAgent agent = new DiagnosisAgent(
                new PromptTemplateService(),
                new BoundedStructuredOutputRepair<>(modelClient,
                        DiagnosisReportCandidateMapper.fromClasspath(objectMapper)),
                objectMapper);
        var application = new DiagnosisApplicationService(
                contextService, reports, agent, authorization, new DiagnosisCitationValidator());
        final var result = diagnoseAndRethrowWithSafeErrors(application);

        assertEquals(PROJECT_ID, result.report().projectId());
        assertEquals(RUN_ID, result.report().runId());
        assertEquals("diagnosis", result.promptName());
        assertEquals("v1", result.promptVersion());
        assertFalse(result.contextPack().items().isEmpty());
        assertTrue(result.contextPack().items().stream()
                .anyMatch(item -> item.itemId().equals("run:" + RUN_ID)));
        assertTrue(result.contextPack().items().stream()
                .anyMatch(item -> item.itemId().equals("chunk:stage11-diagnosis")));
        assertNotNull(result.report());
        assertTrue(result.report().summary().length() > 0);
        assertFalse(result.report().rootCauseHypotheses().isEmpty());
        assertTrue(result.report().rootCauseHypotheses().stream()
                .allMatch(hypothesis -> !hypothesis.evidenceRefs().isEmpty()));

        System.out.println("REAL_STAGE11_DIAGNOSIS_E2E provider=DeepSeek"
                + " adapter=SpringAiAgentModelClient model=" + DeepSeekRealTestSupport.MODEL
                + " projectId=" + PROJECT_ID
                + " runId=" + RUN_ID
                + " contextItemIds=" + result.contextPack().items().stream()
                        .map(item -> item.itemId()).toList()
                + " modelCallCount=" + result.modelCallCount()
                + " modelCallIds=" + result.modelCalls().stream()
                        .map(call -> call.modelCallId()).toList()
                + " repairOf=" + result.modelCalls().stream()
                        .map(call -> call.repairOfModelCallId()).toList()
                + " promptVersion=" + result.promptVersion()
                + " sufficientEvidence=" + result.report().sufficientEvidence()
                + " hypothesisCount=" + result.report().rootCauseHypotheses().size()
                + " evidenceRefs=" + result.report().rootCauseHypotheses().stream()
                        .flatMap(hypothesis -> hypothesis.evidenceRefs().stream())
                        .map(evidenceRef -> evidenceRef.itemId()).toList()
                + " citationValidation=true");
    }

    private com.apiops.agent.diagnosis.DiagnosisExecutionResult diagnoseAndRethrowWithSafeErrors(
            DiagnosisApplicationService application) {
        try {
            return application.diagnose(PROJECT_ID, RUN_ID, API_ID,
                    "Diagnose the supplied failed POST /orders assertion using only the supplied evidence. "
                            + "The retrieved runbook chunk contains a concrete matching scenario: the contract "
                            + "expects HTTP 201 with an orderId, the failed response is HTTP 500 with "
                            + "errorCode INVENTORY_RESERVATION_MISSING, and the documented cause is that the "
                            + "inventory reservation was not created before order creation. If that evidence "
                            + "supports the diagnosis, return at least one root-cause hypothesis and cite the "
                            + "exact supporting ContextPack itemId; do not invent identities or execution facts.", 1);
        } catch (StructuredOutputException exception) {
            System.out.println("REAL_STAGE11_DIAGNOSIS_STRUCTURED_ERRORS=" + exception.errors());
            throw exception;
        }
    }

    private TestReportVO failedReport() {
        return new TestReportVO(
                PROJECT_ID, 110400L, RUN_ID, RunStatus.ASSERTION_FAILED,
                Instant.parse("2026-08-13T00:00:00Z"),
                Instant.parse("2026-08-13T00:00:02Z"),
                new TestReportVO.Summary(
                        1, 1, 1, 0, 1, FailureType.ASSERTION_MISMATCH),
                List.of());
    }

    private ApiMetadataDetailVO metadata() {
        return new ApiMetadataDetailVO(
                API_ID, "doc-stage11", OPERATION_ID, "POST", "/orders",
                "Create order", "Create one order",
                JsonMapper.builder().build().createArrayNode(),
                JsonMapper.builder().build().createArrayNode(),
                JsonMapper.builder().build().createArrayNode(), false,
                List.of(), List.of(), List.of(), List.of());
    }

    private static final class FixedEmbeddingService implements EmbeddingService {
        private static final EmbeddingModel MODEL = new EmbeddingModel("test", "diagnosis", 1);

        @Override
        public EmbeddingModel model() {
            return MODEL;
        }

        @Override
        public List<EmbeddingVector> embed(List<String> texts) {
            return texts.stream().map(text -> new EmbeddingVector(MODEL, List.of(1.0F))).toList();
        }
    }

    private static final class FixedVectorStore implements VectorStoreService {
        @Override
        public void upsert(long projectId, String documentId, List<VectorEntry> entries) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<VectorSearchMatch> search(
                long projectId, EmbeddingVector queryVector, int topK) {
            return List.of(new VectorSearchMatch(
                    projectId, "doc-stage11-diagnosis", "stage11-diagnosis", 0.88));
        }

        @Override
        public void deleteByDocument(long projectId, String documentId) {
            throw new UnsupportedOperationException();
        }
    }

    private static final class FixedDocumentRepository implements DocumentRepository {
        @Override
        public Optional<Document> findBySourceKey(long projectId, String sourceKey) {
            return Optional.empty();
        }

        @Override
        public Optional<Document> findById(long projectId, String documentId) {
            return Optional.of(new Document(
                    documentId, PROJECT_ID, "stage11/diagnosis", "RUNBOOK",
                    "Diagnosis runbook", "diagnosis.md", "text/markdown", "hash",
                    DocumentStatus.INDEXED, USER_ID,
                    Instant.parse("2026-08-13T00:00:00Z")));
        }

        @Override
        public List<DocumentChunk> findChunks(long projectId, String documentId) {
            return List.of(new DocumentChunk(
                    "stage11-diagnosis", documentId, PROJECT_ID, 0,
                    "Runbook for the create-order assertion: when the contract expects HTTP 201 with an "
                            + "orderId but the failed response is HTTP 500 with "
                            + "errorCode INVENTORY_RESERVATION_MISSING, the supported root cause is that "
                            + "the inventory reservation was not created before order creation. This is the "
                            + "concrete scenario represented by the supplied failed TestReport; cite this "
                            + "chunk as evidence for that hypothesis.",
                    "chunk-hash", Map.of()));
        }

        @Override public void saveKnowledge(Document document, List<DocumentChunk> chunks) { throw new UnsupportedOperationException(); }
        @Override public void updateStatus(long projectId, String documentId, DocumentStatus status) { throw new UnsupportedOperationException(); }
        @Override public void markDeleted(long projectId, String documentId) { throw new UnsupportedOperationException(); }
    }

    private static final class RecordingRagQueryRecordRepository
            implements RagQueryRecordRepository {
        @Override public void save(RagQueryRecord record) { }
        @Override public Optional<RagQueryRecord> findById(long projectId, String ragQueryId) {
            return Optional.empty();
        }
    }

}
