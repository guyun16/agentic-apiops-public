package com.apiops.web.tool;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.repository.AuthUserRepository;
import com.apiops.auth.repository.GlobalRbacRepository;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.security.ApiOpsUserDetailsService;
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
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.AuditStatus;
import com.apiops.web.ApiOpsWebApplication;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;

import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.blankOrNullString;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Public Stage 17 boundary evidence through the production Spring application wiring.
 *
 * <p>The Spring MVC controller, JWT filter, project authorization service, ToolGateway,
 * RagSearchTool, method-security proxy, and RagRetriever are real application components.
 * Only the RAG provider and persistence boundaries use deterministic test backends.</p>
 */
@SpringBootTest(
        classes = ApiOpsWebApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Import(Stage17RagToolGatewayIntegrationTest.Stage17TestConfiguration.class)
class Stage17RagToolGatewayIntegrationTest {

    private static final long USER_A = 7L;
    private static final long PROJECT_A = 42L;
    private static final long PROJECT_B = 43L;
    private static final long STAGE21_GENERATION_PROJECT = 41L;
    private static final long STAGE20_FINAL_PROJECT = 20_205_001L;
    private static final String USERNAME_A = "stage17-project-a";
    private static final String TRACE_ID = "stage18-contract-trace";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private JwtTokenService jwtTokenService;

    @Autowired
    private Stage17RagFixture fixture;

    @Autowired
    private RagRetriever ragRetriever;

    @Autowired
    private Audit audit;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private TestRestTemplate restTemplate;

    @AfterEach
    void resetFixtureAndSecurityContext() {
        fixture.reset();
        org.springframework.security.core.context.SecurityContextHolder.clearContext();
    }

    @Test
    void projectAIdentityCanReadProjectAEvidenceThroughPublicBoundary() throws Exception {
        fixture.returnHit = true;

        mockMvc.perform(post("/api/v1/projects/{projectId}/tool-calls", PROJECT_A)
                        .header("Authorization", bearerToken())
                        .header("X-Trace-Id", TRACE_ID)
                        .contentType(APPLICATION_JSON)
                        .content(ragSearchRequest(PROJECT_A, "check order timeout", 1)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.schemaVersion").value("0.1.0"))
                .andExpect(jsonPath("$.status").value("SUCCESS"))
                .andExpect(jsonPath("$.toolCallId").value(not(blankOrNullString())))
                .andExpect(jsonPath("$.error").doesNotExist())
                .andExpect(jsonPath("$.sanitized").value(true))
                .andExpect(jsonPath("$.traceId").value(TRACE_ID))
                .andExpect(jsonPath("$.data.results", hasSize(1)))
                .andExpect(jsonPath("$.data.results[0].projectId").value(PROJECT_A))
                .andExpect(jsonPath("$.data.results[0].documentId").value("doc-project-a"))
                .andExpect(jsonPath("$.data.results[0].chunkId").value("chunk-project-a"))
                .andExpect(jsonPath("$.data.results[0].relevanceScore").value(0.91))
                .andExpect(jsonPath("$.data.results[0].citation.sourceType").value("RUNBOOK"))
                .andExpect(jsonPath("$.data.results[0].citation.sourceId")
                        .value("runbook/project-a"))
                .andExpect(jsonPath("$.data.results[0].citation.projectId").value(PROJECT_A))
                .andExpect(jsonPath("$.data.results[0].citation.documentId")
                        .value("doc-project-a"))
                .andExpect(jsonPath("$.data.results[0].citation.chunkId")
                        .value("chunk-project-a"))
                .andExpect(jsonPath("$.data.results[0].citation.score").value(0.91))
                .andExpect(jsonPath("$.data.results[0].citation.location").value("chunk:0"))
                .andExpect(jsonPath("$.data.results[0].citation.excerpt")
                        .value("The order timeout is bounded before retry."));

        assertEquals(1, fixture.embeddingCalls.get());
        assertEquals(1, fixture.vectorSearchCalls.get());
        assertEquals(RagQueryStatus.SUCCESS_WITH_RESULTS, fixture.lastRecord().status());
    }

    @Test
    void projectAIdentityCannotReadProjectBThroughPublicBoundary() throws Exception {
        fixture.returnHit = true;

        mockMvc.perform(post("/api/v1/projects/{projectId}/tool-calls", PROJECT_B)
                        .header("Authorization", bearerToken())
                        .header("X-Trace-Id", TRACE_ID)
                        .contentType(APPLICATION_JSON)
                        .content(ragSearchRequest(PROJECT_B, "check order timeout", 1)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.schemaVersion").value("0.1.0"))
                .andExpect(jsonPath("$.status").value("FORBIDDEN"))
                .andExpect(jsonPath("$.toolCallId").value(not(blankOrNullString())))
                .andExpect(jsonPath("$.data").doesNotExist())
                .andExpect(jsonPath("$.error.code").value("FORBIDDEN"))
                .andExpect(jsonPath("$.sanitized").value(true))
                .andExpect(jsonPath("$.traceId").value(TRACE_ID));

        assertEquals(0, fixture.embeddingCalls.get());
        assertEquals(0, fixture.vectorSearchCalls.get());
        assertTrue(fixture.records.isEmpty());
    }

    @Test
    void unauthorizedStructuredTargetIsForbiddenBeforeRagRetrieval() throws Exception {
        fixture.returnHit = true;

        mockMvc.perform(post("/api/v1/projects/{projectId}/tool-calls", PROJECT_A)
                        .header("Authorization", bearerToken())
                        .header("X-Trace-Id", TRACE_ID)
                        .contentType(APPLICATION_JSON)
                        .content(ragSearchRequest(
                                PROJECT_A, "check order timeout", 1, PROJECT_B)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("FORBIDDEN"))
                .andExpect(jsonPath("$.data").doesNotExist())
                .andExpect(jsonPath("$.error.code").value("FORBIDDEN"));

        assertEquals(0, fixture.embeddingCalls.get());
        assertEquals(0, fixture.vectorSearchCalls.get());
        assertTrue(fixture.records.isEmpty());
    }

    @Test
    void authorizedStructuredCrossProjectTargetUsesTargetRagScope() throws Exception {
        fixture.returnHit = true;

        var response = mockMvc.perform(post("/api/v1/projects/{projectId}/tool-calls", PROJECT_A)
                        .header("Authorization", bearerToken())
                        .header("X-Trace-Id", TRACE_ID)
                        .contentType(APPLICATION_JSON)
                        .content(ragSearchRequest(
                                PROJECT_A, "check order failure", 1, STAGE21_GENERATION_PROJECT)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("SUCCESS"))
                .andExpect(jsonPath("$.data.results", hasSize(1)))
                .andExpect(jsonPath("$.data.results[0].projectId")
                        .value(STAGE21_GENERATION_PROJECT))
                .andExpect(jsonPath("$.data.results[0].documentId")
                        .value("doc-stage21-orders"))
                .andReturn();

        String toolCallId = objectMapper.readTree(
                response.getResponse().getContentAsString()).path("toolCallId").asText();
        Audit.AuditEvent event = audit.events().stream()
                .filter(candidate -> candidate.toolCallId().equals(toolCallId))
                .findFirst()
                .orElseThrow();

        assertEquals(PROJECT_A, event.projectId());
        assertEquals(STAGE21_GENERATION_PROJECT, event.requestedTargetProjectId());
        assertEquals(1, fixture.embeddingCalls.get());
        assertEquals(1, fixture.vectorSearchCalls.get());
        assertEquals(STAGE21_GENERATION_PROJECT, fixture.lastRecord().projectId());
    }

    @Test
    void authorizedProjectZeroHitIsSuccessfulEmptyAndNotDenied() throws Exception {
        fixture.returnHit = false;

        mockMvc.perform(post("/api/v1/projects/{projectId}/tool-calls", PROJECT_A)
                        .header("Authorization", bearerToken())
                        .header("X-Trace-Id", TRACE_ID)
                        .contentType(APPLICATION_JSON)
                        .content(ragSearchRequest(PROJECT_A, "query with no indexed match", 1)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("SUCCESS"))
                .andExpect(jsonPath("$.data.results", hasSize(0)))
                .andExpect(jsonPath("$.data.ragQueryId").isNotEmpty());

        assertEquals(1, fixture.embeddingCalls.get());
        assertEquals(1, fixture.vectorSearchCalls.get());
        assertEquals(RagQueryStatus.ZERO_HIT, fixture.lastRecord().status());
    }

    @Test
    void callerToolCallIdIsRejectedAndReplacedByJavaGeneratedIdentity() throws Exception {
        mockMvc.perform(post("/api/v1/projects/{projectId}/tool-calls", PROJECT_A)
                        .header("Authorization", bearerToken())
                        .header("X-Trace-Id", TRACE_ID)
                        .contentType(APPLICATION_JSON)
                        .content(ragSearchRequestWithCallerId()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("PARAM_INVALID"))
                .andExpect(jsonPath("$.toolCallId").value(not("attacker-controlled")))
                .andExpect(jsonPath("$.toolCallId").value(not(blankOrNullString())))
                .andExpect(jsonPath("$.error.code").value("PARAM_INVALID"));

        assertEquals(0, fixture.embeddingCalls.get());
        assertEquals(0, fixture.vectorSearchCalls.get());
    }

    @Test
    void publicGatewayResultCorrelatesWithSharedAuditSink() throws Exception {
        fixture.returnHit = true;

        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", bearerToken());
        headers.set("X-Trace-Id", TRACE_ID);
        headers.setContentType(APPLICATION_JSON);
        var result = restTemplate.exchange(
                "/api/v1/projects/{projectId}/tool-calls",
                HttpMethod.POST,
                new HttpEntity<>(
                        ragSearchRequest(PROJECT_A, "audit the order timeout", 1), headers),
                String.class,
                PROJECT_A);

        assertEquals(HttpStatus.OK, result.getStatusCode());
        var response = objectMapper.readTree(result.getBody());
        assertEquals("SUCCESS", response.path("status").asText());
        String toolCallId = response.path("toolCallId").asText();
        assertTrue(!toolCallId.isBlank());
        Audit.AuditEvent event = audit.events().stream()
                .filter(candidate -> candidate.toolCallId().equals(toolCallId))
                .findFirst()
                .orElseThrow();

        assertEquals(PROJECT_A, event.projectId());
        assertEquals("rag.search", event.toolName());
        assertEquals(AuditStatus.SUCCESS, event.status());
        System.out.println("STAGE20_AUDIT_CORRELATION toolCallId=" + toolCallId);
    }

    @Test
    void productionRagRetrieverUsesMethodSecurityProxy() {
        assertTrue(AopUtils.isAopProxy(ragRetriever));
        assertTrue(AopUtils.isCglibProxy(ragRetriever));
        assertEquals(RagRetriever.class, AopUtils.getTargetClass(ragRetriever));
    }

    private String bearerToken() {
        return "Bearer " + jwtTokenService.generateAccessToken(new ApiOpsPrincipal(
                USER_A,
                USERNAME_A,
                "test-password-hash",
                true,
                List.of(new SimpleGrantedAuthority("TOOL_READ"))));
    }

    private String ragSearchRequest(long projectId, String query, int topK) {
        return ragSearchRequest(projectId, query, topK, null);
    }

    private String ragSearchRequest(
            long projectId, String query, int topK, Long targetProjectId) {
        String target = targetProjectId == null
                ? ""
                : ",\"targetProjectId\":" + targetProjectId;
        return "{\"schemaVersion\":\"0.2.0\","
                + "\"agentRunId\":\"stage18-run\","
                + "\"projectId\":\"" + projectId + "\","
                + "\"toolName\":\"rag.search\",\"params\":{"
                + "\"query\":\"" + query + "\",\"topK\":" + topK + target + "},"
                + "\"traceId\":\"" + TRACE_ID + "\"}";
    }

    private String ragSearchRequestWithCallerId() {
        String request = ragSearchRequest(PROJECT_A, "check order timeout", 1);
        return request.substring(0, request.length() - 1)
                + ",\"toolCallId\":\"attacker-controlled\"}";
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class Stage17TestConfiguration {

        @Bean
        Stage17RagFixture stage17RagFixture() {
            return new Stage17RagFixture();
        }

        @Bean
        @Primary
        AuthUserRepository stage17AuthUserRepository() {
            ApiOpsPrincipal principal = new ApiOpsPrincipal(
                    USER_A, USERNAME_A, "test-password-hash", true, List.of());
            return username -> USERNAME_A.equals(username)
                    ? Optional.of(principal)
                    : Optional.empty();
        }

        @Bean
        @Primary
        UserDetailsService stage17UserDetailsService(AuthUserRepository repository) {
            return new ApiOpsUserDetailsService(repository);
        }

        @Bean
        @Primary
        GlobalRbacRepository stage17GlobalRbacRepository() {
            return new GlobalRbacRepository() {
                @Override
                public Set<String> findRoleCodesByUserId(long userId) {
                    return Set.of();
                }

                @Override
                public Set<String> findPermissionCodesByUserId(long userId) {
                    return userId == USER_A ? Set.of("TOOL_READ") : Set.of();
                }
            };
        }

        @Bean
        @Primary
        ProjectMembershipRepository stage17ProjectMembershipRepository() {
            return (userId, projectId) -> {
                if (userId != USER_A) return Optional.empty();
                if (projectId == PROJECT_A || projectId == STAGE21_GENERATION_PROJECT) {
                    return Optional.of(ProjectRole.VIEWER);
                }
                if (projectId == STAGE20_FINAL_PROJECT) return Optional.of(ProjectRole.EDITOR);
                return Optional.empty();
            };
        }

        @Bean
        @Primary
        EmbeddingService stage17Embedding(Stage17RagFixture fixture) {
            return fixture.embedding;
        }

        @Bean
        VectorStoreService stage17VectorStore(Stage17RagFixture fixture) {
            return fixture.vectorStore;
        }

        @Bean
        DocumentRepository stage17DocumentRepository(Stage17RagFixture fixture) {
            return fixture.documents;
        }
    }

    static final class Stage17RagFixture implements RagQueryRecordRepository {

        private static final EmbeddingModel MODEL =
                new EmbeddingModel("fake", "stage17-web-test", 2);
        private static final EmbeddingVector QUERY_VECTOR =
                new EmbeddingVector(MODEL, List.of(1.0F, 0.0F));

        private final AtomicInteger embeddingCalls = new AtomicInteger();
        private final AtomicInteger vectorSearchCalls = new AtomicInteger();
        private final CopyOnWriteArrayList<RagQueryRecord> records = new CopyOnWriteArrayList<>();
        private final TestEmbedding embedding = new TestEmbedding();
        private final TestVectorStore vectorStore = new TestVectorStore();
        private final TestDocuments documents = new TestDocuments();
        private volatile boolean returnHit;
        private volatile String lastQuery = "";

        private Stage17RagFixture() {
            documents.add(
                    new Document(
                            "doc-project-a", PROJECT_A, "runbook/project-a", "RUNBOOK",
                            "Project A Orders Runbook", "orders.md", "text/markdown",
                            "a".repeat(64), DocumentStatus.INDEXED, USER_A,
                            Instant.parse("2026-08-20T00:00:00Z")),
                    new DocumentChunk(
                            "chunk-project-a", "doc-project-a", PROJECT_A, 0,
                            "The order timeout is bounded before retry.", "b".repeat(64),
                            Map.of()));
            documents.add(
                    new Document(
                            "doc-orders-unique", PROJECT_A, "rag:orders-unique-index", "RUNBOOK",
                            "Orders uniqueness runbook", "orders-unique.md", "text/markdown",
                            "c".repeat(64), DocumentStatus.INDEXED, USER_A,
                            Instant.parse("2026-08-20T00:00:00Z")),
                    new DocumentChunk(
                            "chunk-orders-unique", "doc-orders-unique", PROJECT_A, 0,
                            "The create-order endpoint rejects duplicate order keys because of the unique orders index.",
                            "d".repeat(64), Map.of()));
            documents.add(
                    new Document(
                            "doc-stage21-orders", STAGE21_GENERATION_PROJECT,
                            "rag:orders-constraint-001", "RUNBOOK",
                            "Stage 21 Orders Constraints", "stage21-orders.md", "text/markdown",
                            "e".repeat(64), DocumentStatus.INDEXED, USER_A,
                            Instant.parse("2026-08-20T00:00:00Z")),
                    new DocumentChunk(
                            "chunk-stage21-orders", "doc-stage21-orders", STAGE21_GENERATION_PROJECT, 0,
                            "The create-order endpoint rejects duplicate order keys because of the unique orders index.",
                            "f".repeat(64), Map.of()));
        }

        private void reset() {
            returnHit = false;
            embeddingCalls.set(0);
            vectorSearchCalls.set(0);
            records.clear();
            lastQuery = "";
        }

        private RagQueryRecord lastRecord() {
            return records.getLast();
        }

        void enableHits() {
            returnHit = true;
        }

        List<RagQueryRecord> recordsSnapshot() {
            return List.copyOf(records);
        }

        @Override
        public void save(RagQueryRecord record) {
            records.add(record);
        }

        @Override
        public Optional<RagQueryRecord> findById(long projectId, String ragQueryId) {
            return records.stream()
                    .filter(record -> record.projectId() == projectId)
                    .filter(record -> record.ragQueryId().equals(ragQueryId))
                    .findFirst();
        }

        private final class TestEmbedding implements EmbeddingService {
            @Override
            public EmbeddingModel model() {
                return MODEL;
            }

            @Override
            public List<EmbeddingVector> embed(List<String> texts) {
                embeddingCalls.incrementAndGet();
                lastQuery = texts.isEmpty() ? "" : texts.get(0);
                return List.of(QUERY_VECTOR);
            }
        }

        private final class TestVectorStore implements VectorStoreService {
            @Override
            public void upsert(long projectId, String documentId, List<VectorEntry> entries) {
                throw new UnsupportedOperationException();
            }

            @Override
            public List<VectorSearchMatch> search(
                long projectId, EmbeddingVector queryVector, int topK) {
                vectorSearchCalls.incrementAndGet();
                if (!returnHit) return List.of();
                String query = lastQuery.toLowerCase();
                if (projectId == STAGE21_GENERATION_PROJECT
                        && query.contains("order") && query.contains("failure")) {
                    return List.of(new VectorSearchMatch(
                            STAGE21_GENERATION_PROJECT,
                            "doc-stage21-orders",
                            "chunk-stage21-orders",
                            0.92));
                }
                if (projectId == PROJECT_A
                        && (query.contains("duplicate")
                                || (query.contains("order") && query.contains("failure")))) {
                    return List.of(new VectorSearchMatch(
                            PROJECT_A, "doc-orders-unique", "chunk-orders-unique", 0.93));
                }
                return projectId == PROJECT_A
                        ? List.of(new VectorSearchMatch(
                                PROJECT_A, "doc-project-a", "chunk-project-a", 0.91))
                        : List.of();
            }

            @Override
            public void deleteByDocument(long projectId, String documentId) {
                throw new UnsupportedOperationException();
            }
        }
    }

    private static final class TestDocuments implements DocumentRepository {
        private final List<Document> documents = new ArrayList<>();
        private final List<DocumentChunk> chunks = new ArrayList<>();

        private void add(Document document, DocumentChunk chunk) {
            documents.add(document);
            chunks.add(chunk);
        }

        @Override
        public Optional<Document> findBySourceKey(long projectId, String sourceKey) {
            return documents.stream()
                    .filter(document -> document.projectId() == projectId)
                    .filter(document -> document.sourceKey().equals(sourceKey))
                    .findFirst();
        }

        @Override
        public Optional<Document> findById(long projectId, String documentId) {
            return documents.stream()
                    .filter(document -> document.projectId() == projectId)
                    .filter(document -> document.documentId().equals(documentId))
                    .findFirst();
        }

        @Override
        public List<DocumentChunk> findChunks(long projectId, String documentId) {
            return chunks.stream()
                    .filter(chunk -> chunk.projectId() == projectId)
                    .filter(chunk -> chunk.documentId().equals(documentId))
                    .toList();
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
}
