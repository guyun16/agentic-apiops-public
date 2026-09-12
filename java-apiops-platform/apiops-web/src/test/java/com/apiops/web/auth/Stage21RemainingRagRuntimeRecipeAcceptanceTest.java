package com.apiops.web.auth;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
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
import com.apiops.rag.retrieval.RagRetrieval;
import com.apiops.rag.retrieval.RagRetriever;
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.VectorSearchMatch;
import com.apiops.rag.vector.VectorStoreService;
import com.apiops.web.ApiOpsWebApplication;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.regex.Pattern;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Live acceptance for sidecar RAG-only recipes through the production Java boundary.
 *
 * <p>The retriever/provider is the existing Stage 21 test-owned deterministic bean. The
 * Tool Gateway, JWT filter, ToolAuth, ResourceGuard, and project authorization are still
 * the application components under test. No Runner is involved in this path.</p>
 */
@SpringBootTest(
        classes = ApiOpsWebApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "server.port=0",
                "apiops.datasource.auth.url=${APIOPS_AUTH_DB_URL:jdbc:mysql://127.0.0.1:3306/apiops_auth}",
                "apiops.datasource.auth.username=${APIOPS_AUTH_DB_USERNAME:root}",
                "apiops.datasource.auth.password=${APIOPS_AUTH_DB_PASSWORD}",
                "apiops.datasource.openapi.url=${APIOPS_OPENAPI_DB_URL:jdbc:mysql://127.0.0.1:3306/apiops_openapi}",
                "apiops.datasource.openapi.username=${APIOPS_OPENAPI_DB_USERNAME:root}",
                "apiops.datasource.openapi.password=${APIOPS_OPENAPI_DB_PASSWORD}",
                "apiops.datasource.runner.url=${APIOPS_RUNNER_DB_URL:jdbc:mysql://127.0.0.1:3306/apiops_runner}",
                "apiops.datasource.runner.username=${APIOPS_RUNNER_DB_USERNAME:root}",
                "apiops.datasource.runner.password=${APIOPS_RUNNER_DB_PASSWORD}",
                "apiops.datasource.rag.url=${APIOPS_RAG_DB_URL:jdbc:mysql://127.0.0.1:3306/apiops_rag}",
                "apiops.datasource.rag.username=${APIOPS_RAG_DB_USERNAME:root}",
                "apiops.datasource.rag.password=${APIOPS_RAG_DB_PASSWORD}",
                "apiops.auth.jwt.secret=${APIOPS_JWT_SECRET}",
                "apiops.auth.jwt.issuer=stage21-remaining-rag",
                "apiops.auth.jwt.access-token-ttl=15m",
                "spring.ai.model.chat=none",
                "spring.ai.model.embedding=none",
                "spring.ai.model.image=none",
                "spring.ai.model.moderation=none",
                "spring.ai.model.audio.speech=none",
                "spring.ai.model.audio.transcription=none",
                "apiops.rag.vector-store.qdrant.enabled=false",
                "apiops.rabbitmq.execution.enabled=false",
                "apiops.runner.progress.enabled=false",
                "management.health.redis.enabled=false"
        })
@Import(Stage21RemainingRagRuntimeRecipeAcceptanceTest.Stage21EvidenceRagConfiguration.class)
class Stage21RemainingRagRuntimeRecipeAcceptanceTest {

    private static final String NORMAL = "NORMAL";
    private static final String SAFETY_41 = "SAFETY_41_ISOLATED";
    private static final String SAFETY_42 = "SAFETY_42_ISOLATED";

    @LocalServerPort
    private int serverPort;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private RecordingRagRetriever ragRetriever;

    @Test
    void allSidecarRagOnlyRecipesUseJavaToolGatewayWithoutRunner() throws Exception {
        Path root = findRepositoryRoot();
        JsonNode sidecar = objectMapper.readTree(
                root.resolve("python-apiops-agentlab/tests/benchmark/fixtures/"
                        + "stage21-execution-prerequisites.json").toFile());
        JsonNode catalog = objectMapper.readTree(
                root.resolve("python-apiops-agentlab/tests/benchmark/fixtures/support/"
                        + "stage21-remaining-rag-recipes.json").toFile());
        Map<String, JsonNode> recipes = indexRecipes(catalog);
        List<JsonNode> ragRows = new ArrayList<>();
        for (JsonNode row : sidecar.path("tasks")) {
            if (!"RUNTIME_RECIPE".equals(row.path("resourceSetupType").asText())) {
                continue;
            }
            boolean rag = false;
            for (JsonNode operation : row.path("requiredOperations")) {
                rag |= "RAG_SEARCH".equals(operation.asText());
            }
            boolean runner = false;
            for (JsonNode operation : row.path("requiredOperations")) {
                runner |= "RUNNER_SUBMIT".equals(operation.asText());
            }
            if (rag && !runner) {
                ragRows.add(row);
            }
        }
        assertEquals(11, ragRows.size());
        assertEquals(11, recipes.size());
        int positiveCount = 0;
        int zeroHitCount = 0;
        int forbiddenCount = 0;

        Map<String, Session> sessions = new HashMap<>();
        for (JsonNode row : ragRows) {
            String profile = row.path("authProfile").asText();
            sessions.computeIfAbsent(profile, this::loginProfile);
        }

        for (JsonNode row : ragRows) {
            String taskId = row.path("benchmarkTaskId").asText();
            JsonNode recipe = recipes.get(taskId);
            assertNotNull(recipe, taskId);
            String profile = row.path("authProfile").asText();
            long currentProjectId = row.path("currentProjectId").asLong();
            JsonNode targetNode = row.get("targetProjectId");
            Long targetProjectId = targetNode == null || targetNode.isNull()
                    ? null
                    : targetNode.asLong();
            String scenarioType = scenarioType(recipe, targetProjectId);
            assertEquals(recipe.path("sourceReference").asText(), authorityReference(sidecar, taskId));

            int retrieverCallsBefore = ragRetriever.projects().size();
            Map<String, Object> params = new LinkedHashMap<>();
            params.put("query", recipe.path("query").asText());
            params.put("topK", recipe.path("topK").asInt());
            if (targetProjectId != null) {
                params.put("targetProjectId", targetProjectId);
            }
            Map<String, Object> request = new LinkedHashMap<>();
            request.put("schemaVersion", "0.2.0");
            request.put("agentRunId", "stage21-rag-runtime-" + taskId);
            request.put("projectId", Long.toString(currentProjectId));
            request.put("toolName", "rag.search");
            request.put("params", params);
            request.put("traceId", "stage21-rag-runtime-trace-" + taskId);

            HttpResponse<String> response = HttpClient.newHttpClient().send(
                    HttpRequest.newBuilder(URI.create(
                                    "http://127.0.0.1:" + serverPort
                                            + "/api/v1/projects/" + currentProjectId + "/tool-calls"))
                            .header("Authorization", "Bearer " + sessions.get(profile).token())
                            .header("Content-Type", "application/json")
                            .header("X-Trace-Id", "stage21-rag-runtime-trace-" + taskId)
                            .timeout(Duration.ofSeconds(10))
                            .POST(HttpRequest.BodyPublishers.ofString(
                                    objectMapper.writeValueAsString(request)))
                            .build(),
                    HttpResponse.BodyHandlers.ofString());
            assertEquals(200, response.statusCode(), taskId);
            JsonNode result = objectMapper.readTree(response.body());
            String toolCallId = result.path("toolCallId").asText();
            assertFalse(toolCallId.isBlank(), taskId);
            String status = result.path("status").asText();
            int retrieverCallsAfter = ragRetriever.projects().size();
            Map<String, Object> evidence = new LinkedHashMap<>();
            evidence.put("taskId", taskId);
            evidence.put("profile", profile);
            evidence.put("currentProjectId", currentProjectId);
            evidence.put("targetProjectId", targetProjectId);
            evidence.put("toolName", "rag.search");
            evidence.put("toolCallId", toolCallId);
            evidence.put("status", status);
            evidence.put("scenarioType", scenarioType);
            if (targetProjectId == null) {
                assertEquals("NORMAL", profile, taskId);
                assertEquals("SUCCESS", status, taskId);
                JsonNode data = result.path("data");
                String ragQueryId = data.path("ragQueryId").asText();
                assertFalse(ragQueryId.isBlank(), taskId);
                JsonNode resultRows = data.path("results");
                assertTrue(resultRows.isArray(), taskId);
                int resultCount = resultRows.size();
                boolean expectedZeroHit = isZeroHitQuery(recipe.path("query").asText());
                if (expectedZeroHit) {
                    assertEquals(0, resultCount, taskId);
                } else {
                    assertTrue(resultCount > 0,
                            () -> taskId + " must return Java-owned evidence: " + result);
                }
                assertTrue(resultCount <= recipe.path("topK").asInt(), taskId);
                assertEvidenceRows(resultRows, currentProjectId, taskId);
                RagQueryRecord queryRecord = ragRetriever.queryRecord(ragQueryId);
                assertNotNull(queryRecord, taskId);
                assertEquals(resultCount, queryRecord.retrievedCount(), taskId);
                assertEquals(expectedZeroHit
                                ? RagQueryStatus.ZERO_HIT
                                : RagQueryStatus.SUCCESS_WITH_RESULTS,
                        queryRecord.status(), taskId);
                assertEquals(retrieverCallsBefore + 1, retrieverCallsAfter, taskId);
                assertEquals(currentProjectId,
                        ragRetriever.projects().get(retrieverCallsAfter - 1), taskId);
                List<String> sourceIds = sourceIds(resultRows);
                boolean scenarioMatch = semanticScenarioMatches(
                        scenarioType, sourceIds, resultCount);
                assertTrue(scenarioMatch,
                        () -> taskId + " semantic scenario mismatch: " + sourceIds);
                evidence.put("ragQueryId", ragQueryId);
                evidence.put("resultCount", resultCount);
                evidence.put("citation", citations(resultRows));
                evidence.put("source", sourceIds);
                evidence.put("evidenceSourceIds", sourceIds);
                evidence.put("retrieverInvoked", true);
                evidence.put("scenarioMatch", scenarioMatch);
                if (expectedZeroHit) {
                    zeroHitCount++;
                } else {
                    positiveCount++;
                }
            } else {
                assertTrue(profile.equals(SAFETY_41) || profile.equals(SAFETY_42), taskId);
                assertEquals("FORBIDDEN", status, taskId);
                assertTrue(result.path("data").isMissingNode() || result.path("data").isNull());
                assertEquals(retrieverCallsBefore, retrieverCallsAfter, taskId);
                evidence.put("ragQueryId", null);
                evidence.put("resultCount", null);
                evidence.put("citation", List.of());
                evidence.put("source", List.of());
                evidence.put("evidenceSourceIds", List.of());
                evidence.put("retrieverInvoked", false);
                evidence.put("scenarioMatch", true);
                forbiddenCount++;
            }
            System.out.println("STAGE21_RAG_RUNTIME_RESULT "
                    + objectMapper.writeValueAsString(evidence));
        }
        assertEquals(7, positiveCount);
        assertEquals(2, zeroHitCount);
        assertEquals(2, forbiddenCount);
        System.out.println("RAG_EVIDENCE_READINESS_PASS tasks=11 positive=7 zeroHit=2 isolationForbidden=2");
    }

    private void assertEvidenceRows(JsonNode rows, long projectId, String taskId) {
        double previousScore = Double.POSITIVE_INFINITY;
        for (JsonNode row : rows) {
            assertEquals(projectId, row.path("projectId").asLong(), taskId);
            assertFalse(row.path("documentId").asText().isBlank(), taskId);
            assertFalse(row.path("chunkId").asText().isBlank(), taskId);
            assertFalse(row.path("content").asText().isBlank(), taskId);
            double score = row.path("relevanceScore").asDouble(Double.NaN);
            assertTrue(Double.isFinite(score) && score > 0.0, taskId);
            assertTrue(score <= previousScore, taskId);
            previousScore = score;
            JsonNode citation = row.path("citation");
            assertFalse(citation.path("sourceType").asText().isBlank(), taskId);
            assertFalse(citation.path("sourceId").asText().isBlank(), taskId);
            assertEquals(projectId, citation.path("projectId").asLong(), taskId);
            assertFalse(citation.path("documentId").asText().isBlank(), taskId);
            assertFalse(citation.path("chunkId").asText().isBlank(), taskId);
            assertFalse(citation.path("excerpt").asText().isBlank(), taskId);
        }
    }

    private List<String> sourceIds(JsonNode rows) {
        List<String> values = new ArrayList<>();
        for (JsonNode row : rows) {
            values.add(row.path("citation").path("sourceId").asText());
        }
        return List.copyOf(values);
    }

    private List<Map<String, Object>> citations(JsonNode rows) {
        List<Map<String, Object>> values = new ArrayList<>();
        for (JsonNode row : rows) {
            JsonNode citation = row.path("citation");
            Map<String, Object> value = new LinkedHashMap<>();
            value.put("sourceType", citation.path("sourceType").asText());
            value.put("sourceId", citation.path("sourceId").asText());
            value.put("documentId", citation.path("documentId").asText());
            value.put("chunkId", citation.path("chunkId").asText());
            value.put("excerpt", citation.path("excerpt").asText());
            values.add(value);
        }
        return List.copyOf(values);
    }

    /** Classifies the public recipe scenario; it is not used to route retrieval. */
    private String scenarioType(JsonNode recipe, Long targetProjectId) {
        if (targetProjectId != null) {
            return "CROSS_PROJECT_ISOLATION";
        }
        String query = recipe.path("query").asText().toLowerCase(java.util.Locale.ROOT);
        if (isZeroHitQuery(query)) {
            return "AUTHORIZED_ZERO_HIT";
        }
        if (query.contains("relevant") && query.contains("distractor")) {
            return "RELEVANT_OVER_DISTRACTOR";
        }
        if (query.contains("report and unique index")) {
            return "MULTI_REPORT_INDEX";
        }
        if (query.contains("citation identity")) {
            return "REPORT_CITATION";
        }
        if (query.contains("independent") && query.contains("constraints")) {
            return "MULTI_CONSTRAINT";
        }
        if (query.contains("near match") || query.contains("unique index exact")) {
            return "EXACT_OVER_NEAR_MATCH";
        }
        if (query.contains("single constraint")) {
            return "SINGLE_EXACT_CONSTRAINT";
        }
        return "AUTHORIZED_EVIDENCE";
    }

    /**
     * Checks only the independently defined scenario shape, not an expected evidence set.
     * Retrieval itself remains query/content based and has no task-specific branch.
     */
    private boolean semanticScenarioMatches(
            String scenarioType, List<String> sourceIds, int resultCount) {
        return switch (scenarioType) {
            case "AUTHORIZED_ZERO_HIT" -> resultCount == 0 && sourceIds.isEmpty();
            case "REPORT_CITATION" -> firstIs(sourceIds, "report:701");
            case "RELEVANT_OVER_DISTRACTOR" -> firstIs(
                    sourceIds, "rag:orders-constraint-001")
                    && !sourceIds.contains("rag:product-catalog-999");
            case "MULTI_CONSTRAINT" -> sourceIds.contains("rag:orders-constraint-001")
                    && sourceIds.contains("rag:orders-unique-index");
            case "MULTI_REPORT_INDEX" -> sourceIds.contains("report:701")
                    && sourceIds.contains("rag:orders-unique-index");
            case "EXACT_OVER_NEAR_MATCH" -> firstIs(
                    sourceIds, "rag:orders-unique-index")
                    && !sourceIds.contains("rag:orders-unique-index-summary");
            case "SINGLE_EXACT_CONSTRAINT" -> firstIs(
                    sourceIds, "rag:orders-constraint-001")
                    && !sourceIds.contains("rag:product-catalog-999");
            default -> resultCount > 0 && !sourceIds.isEmpty();
        };
    }

    private boolean firstIs(List<String> sourceIds, String expected) {
        return !sourceIds.isEmpty() && expected.equals(sourceIds.get(0));
    }

    /** The two explicit no-hit recipes are identified from their public query input only. */
    private boolean isZeroHitQuery(String query) {
        String normalized = query.toLowerCase(java.util.Locale.ROOT);
        return normalized.contains("no hit") || normalized.contains("no indexed match");
    }

    private Map<String, JsonNode> indexRecipes(JsonNode catalog) {
        Map<String, JsonNode> recipes = new LinkedHashMap<>();
        for (JsonNode recipe : catalog.path("recipes")) {
            assertTrue(recipes.put(recipe.path("benchmarkTaskId").asText(), recipe) == null);
        }
        return recipes;
    }

    private String authorityReference(JsonNode sidecar, String taskId) {
        for (JsonNode row : sidecar.path("tasks")) {
            if (!taskId.equals(row.path("benchmarkTaskId").asText())) {
                continue;
            }
            return row.path("resourceProjectId").isMissingNode()
                    ? ""
                    : taskAuthorityReference(taskId);
        }
        throw new IllegalArgumentException("sidecar task not found: " + taskId);
    }

    private String taskAuthorityReference(String taskId) {
        try {
            Path root = findRepositoryRoot();
            JsonNode manifest = objectMapper.readTree(
                    root.resolve("python-apiops-agentlab/tests/benchmark/fixtures/dataset-manifest.json")
                            .toFile());
            for (JsonNode entry : manifest.path("tasks")) {
                if (!taskId.equals(entry.path("benchmarkTaskId").asText())) {
                    continue;
                }
                JsonNode task = objectMapper.readTree(
                        root.resolve("python-apiops-agentlab/tests/benchmark/fixtures")
                                .resolve(entry.path("taskFile").asText()).toFile());
                for (JsonNode input : task.path("initialState").path("entries")) {
                    if ("JAVA_RESOURCE".equals(input.path("kind").asText())
                            && ("authorityFixture".equals(input.path("key").asText())
                                    || "testReport".equals(input.path("key").asText()))) {
                        return input.path("ref").asText();
                    }
                }
            }
        } catch (IOException exception) {
            throw new IllegalStateException("cannot read Stage 21 task input", exception);
        }
        throw new IllegalArgumentException("task input reference not found: " + taskId);
    }

    private Session loginProfile(String profile) {
        String username;
        String passwordEnvironment;
        if (NORMAL.equals(profile)) {
            username = "stage21-normal";
            passwordEnvironment = "STAGE21_NORMAL_PASSWORD";
        } else if (SAFETY_41.equals(profile)) {
            username = "stage21-safety41";
            passwordEnvironment = "STAGE21_SAFETY41_PASSWORD";
        } else if (SAFETY_42.equals(profile)) {
            username = "stage21-safety42";
            passwordEnvironment = "STAGE21_SAFETY42_PASSWORD";
        } else {
            throw new IllegalArgumentException("unknown Stage 21 profile: " + profile);
        }
        try {
            HttpResponse<String> response = HttpClient.newHttpClient().send(
                    HttpRequest.newBuilder(URI.create(
                                    "http://127.0.0.1:" + serverPort + "/api/v1/auth/login"))
                            .header("Content-Type", "application/json")
                            .timeout(Duration.ofSeconds(5))
                            .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(
                                    Map.of("username", username,
                                            "password", requiredEnvironment(passwordEnvironment)))))
                            .build(),
                    HttpResponse.BodyHandlers.ofString());
            assertEquals(200, response.statusCode(), profile);
            JsonNode body = objectMapper.readTree(response.body());
            assertTrue(body.path("success").asBoolean(), profile);
            assertEquals(username, body.path("data").path("username").asText());
            String token = body.path("data").path("accessToken").asText();
            assertFalse(token.isBlank(), profile);
            return new Session(username, body.path("data").path("userId").asLong(), token);
        } catch (IOException | InterruptedException exception) {
            throw new IllegalStateException("Stage 21 profile login failed: " + profile, exception);
        }
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        assertTrue(value != null && !value.isBlank(), name + " must be supplied");
        return value;
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

    private record Session(String username, long userId, String token) {
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class Stage21EvidenceRagConfiguration {

        @Bean
        Stage21EvidenceHarness stage21EvidenceHarness() {
            return new Stage21EvidenceHarness();
        }

        @Bean
        @Primary
        EmbeddingService stage21EvidenceEmbedding(
                @Qualifier("stage21EvidenceHarness") Stage21EvidenceHarness harness) {
            return harness.embedding();
        }

        @Bean
        @Primary
        VectorStoreService stage21EvidenceVectorStore(
                @Qualifier("stage21EvidenceHarness") Stage21EvidenceHarness harness) {
            return harness.vectorStore();
        }

        @Bean
        @Primary
        DocumentRepository stage21EvidenceDocuments(
                @Qualifier("stage21EvidenceHarness") Stage21EvidenceHarness harness) {
            return harness.world().documentRepository();
        }

        @Bean
        @Primary
        RagQueryRecordRepository stage21EvidenceQueryRecords(
                @Qualifier("stage21EvidenceHarness") Stage21EvidenceHarness harness) {
            return harness.world().queryRecordRepository();
        }

        @Bean
        @Primary
        RecordingRagRetriever stage21EvidenceRetriever(
                @Qualifier("stage21EvidenceHarness") Stage21EvidenceHarness harness) {
            return new RecordingRagRetriever(
                    harness.world(), harness.embedding(), harness.vectorStore(),
                    harness.world().documentRepository(), harness.world().queryRecordRepository());
        }
    }

    static final class Stage21EvidenceHarness {

        private final Stage21EvidenceWorld world = new Stage21EvidenceWorld();
        private final EmbeddingService embedding = new Stage21Embedding(world);
        private final VectorStoreService vectorStore = new Stage21VectorStore(world);

        Stage21EvidenceWorld world() {
            return world;
        }

        EmbeddingService embedding() {
            return embedding;
        }

        VectorStoreService vectorStore() {
            return vectorStore;
        }
    }

    /**
     * Java-owned formal evidence world for the runtime recipe gate.
     *
     * <p>The corpus is seeded as Document/Chunk records and indexed through the same
     * provider-neutral EmbeddingService and VectorStoreService boundaries consumed by
     * RagRetriever. Query text is embedded and matched by content tokens; no task ID,
     * GroundTruth, or expected-evidence routing enters this path.</p>
     */
    static final class Stage21EvidenceWorld implements EmbeddingService, VectorStoreService {

        private static final int DIMENSION = 4_096;
        private static final double MIN_RELEVANCE_SCORE = 0.28;
        private static final EmbeddingModel MODEL = new EmbeddingModel(
                "stage21-java-test", "content-token-v1", DIMENSION);
        private static final Pattern TOKEN = Pattern.compile("[a-z0-9]+");
        private static final Comparator<VectorSearchMatch> MATCH_ORDER = Comparator
                .comparingDouble(VectorSearchMatch::relevanceScore).reversed()
                .thenComparing(VectorSearchMatch::documentId)
                .thenComparing(VectorSearchMatch::chunkId);

        private final Map<Key, Document> documents = new LinkedHashMap<>();
        private final Map<Key, List<DocumentChunk>> chunks = new LinkedHashMap<>();
        private final Map<ChunkKey, VectorEntry> vectors = new LinkedHashMap<>();
        private final CopyOnWriteArrayList<RagQueryRecord> records =
                new CopyOnWriteArrayList<>();
        private final DocumentRepository documentRepository = new FormalDocuments();
        private final RagQueryRecordRepository queryRecordRepository = new QueryRecords();

        Stage21EvidenceWorld() {
            for (CorpusDocument value : corpus()) {
                Document document = new Document(
                        value.documentId(), value.projectId(), value.sourceKey(),
                        value.sourceType(), value.title(), value.documentId() + ".md",
                        "text/markdown", value.documentHash(), DocumentStatus.INDEXED,
                        value.createdBy(), Instant.parse("2026-08-28T00:00:00Z"));
                DocumentChunk chunk = new DocumentChunk(
                        value.chunkId(), value.documentId(), value.projectId(), 0,
                        value.content(), value.chunkHash(), Map.of());
                documentRepository.saveKnowledge(document, List.of(chunk));
            }
            for (CorpusDocument value : corpus()) {
                upsert(value.projectId(), value.documentId(), List.of(
                        new VectorEntry(value.projectId(), value.documentId(),
                                value.chunkId(), value.chunkHash(), embedOne(value.content()), Map.of())));
            }
        }

        @Override
        public EmbeddingModel model() {
            return MODEL;
        }

        @Override
        public List<EmbeddingVector> embed(List<String> texts) {
            Objects.requireNonNull(texts, "texts must not be null");
            if (texts.isEmpty()) {
                throw new IllegalArgumentException("texts must not be empty");
            }
            return texts.stream().map(this::embedOne).toList();
        }

        private EmbeddingVector embedOne(String text) {
            if (text == null || text.isBlank()) {
                throw new IllegalArgumentException("text must not be blank");
            }
            float[] values = new float[DIMENSION];
            Map<String, Integer> documentFrequency = documentFrequency();
            TOKEN.matcher(text.toLowerCase(java.util.Locale.ROOT)).results().forEach(match -> {
                String token = match.group();
                int frequency = documentFrequency.getOrDefault(token, 0);
                if (frequency == 0) {
                    return;
                }
                double inverseDocumentFrequency = 1.0 + Math.log(
                        (documents.size() + 1.0) / (frequency + 1.0));
                values[Math.floorMod(token.hashCode(), DIMENSION)] +=
                        (float) inverseDocumentFrequency;
            });
            List<Float> boxed = new ArrayList<>(DIMENSION);
            for (float value : values) {
                boxed.add(value);
            }
            return new EmbeddingVector(MODEL, boxed);
        }

        @Override
        public synchronized void upsert(
                long projectId, String documentId, List<VectorEntry> entries) {
            List<VectorEntry> values = List.copyOf(entries);
            if (values.isEmpty()) {
                throw new IllegalArgumentException("entries must not be empty");
            }
            values.forEach(entry -> {
                if (entry.projectId() != projectId || !entry.documentId().equals(documentId)) {
                    throw new IllegalArgumentException("vector entry scope mismatch");
                }
                if (!MODEL.equals(entry.embedding().model())) {
                    throw new IllegalArgumentException("vector model mismatch");
                }
            });
            vectors.keySet().removeIf(key -> key.projectId() == projectId
                    && key.documentId().equals(documentId));
            for (VectorEntry entry : values) {
                vectors.put(new ChunkKey(projectId, documentId, entry.chunkId()), entry);
            }
        }

        @Override
        public synchronized List<VectorSearchMatch> search(
                long projectId, EmbeddingVector queryVector, int topK) {
            Objects.requireNonNull(queryVector, "queryVector must not be null");
            if (!MODEL.equals(queryVector.model())) {
                throw new IllegalArgumentException("query vector model mismatch");
            }
            if (topK <= 0) {
                throw new IllegalArgumentException("topK must be positive");
            }
            List<VectorSearchMatch> matches = vectors.values().stream()
                    .filter(value -> value.projectId() == projectId)
                    .map(value -> new VectorSearchMatch(
                            projectId, value.documentId(), value.chunkId(),
                            cosine(queryVector, value.embedding())))
                    .filter(value -> value.relevanceScore() >= MIN_RELEVANCE_SCORE)
                    .sorted(MATCH_ORDER)
                    .limit(topK)
                    .toList();
            return List.copyOf(matches);
        }

        private Map<String, Integer> documentFrequency() {
            Map<String, Integer> values = new HashMap<>();
            for (List<DocumentChunk> documentChunks : chunks.values()) {
                java.util.Set<String> tokens = new java.util.HashSet<>();
                for (DocumentChunk chunk : documentChunks) {
                    TOKEN.matcher(chunk.content().toLowerCase(java.util.Locale.ROOT)).results()
                            .map(java.util.regex.MatchResult::group)
                            .forEach(tokens::add);
                }
                tokens.forEach(token -> values.merge(token, 1, Integer::sum));
            }
            return values;
        }

        private double cosine(EmbeddingVector left, EmbeddingVector right) {
            double dot = 0.0;
            double leftNorm = 0.0;
            double rightNorm = 0.0;
            for (int index = 0; index < DIMENSION; index++) {
                double leftValue = left.values().get(index);
                double rightValue = right.values().get(index);
                dot += leftValue * rightValue;
                leftNorm += leftValue * leftValue;
                rightNorm += rightValue * rightValue;
            }
            if (leftNorm == 0.0 || rightNorm == 0.0) {
                return 0.0;
            }
            return dot / Math.sqrt(leftNorm * rightNorm);
        }

        @Override
        public synchronized void deleteByDocument(long projectId, String documentId) {
            vectors.keySet().removeIf(key -> key.projectId() == projectId
                    && key.documentId().equals(documentId));
            documentRepository.markDeleted(projectId, documentId);
        }

        DocumentRepository documentRepository() {
            return documentRepository;
        }

        RagQueryRecordRepository queryRecordRepository() {
            return queryRecordRepository;
        }

        private final class FormalDocuments implements DocumentRepository {

            @Override
            public synchronized Optional<Document> findBySourceKey(
                    long projectId, String sourceKey) {
                return documents.values().stream()
                        .filter(value -> value.projectId() == projectId)
                        .filter(value -> value.sourceKey().equals(sourceKey))
                        .findFirst();
            }

            @Override
            public synchronized Optional<Document> findById(
                    long projectId, String documentId) {
                return Optional.ofNullable(documents.get(new Key(projectId, documentId)));
            }

            @Override
            public synchronized List<DocumentChunk> findChunks(
                    long projectId, String documentId) {
                return chunks.getOrDefault(new Key(projectId, documentId), List.of());
            }

            @Override
            public synchronized void saveKnowledge(
                    Document document, List<DocumentChunk> values) {
                Key key = new Key(document.projectId(), document.documentId());
                documents.put(key, document);
                chunks.put(key, List.copyOf(values));
            }

            @Override
            public synchronized void updateStatus(
                    long projectId, String documentId, DocumentStatus status) {
                Key key = new Key(projectId, documentId);
                Document document = documents.get(key);
                if (document == null) {
                    throw new IllegalArgumentException("document not found");
                }
                documents.put(key, document.withStatus(status));
            }

            @Override
            public synchronized void markDeleted(long projectId, String documentId) {
                Key key = new Key(projectId, documentId);
                documents.remove(key);
                chunks.remove(key);
            }
        }

        private final class QueryRecords implements RagQueryRecordRepository {

            @Override
            public void save(RagQueryRecord record) {
                records.add(record);
            }

            @Override
            public Optional<RagQueryRecord> findById(
                    long projectId, String ragQueryId) {
                return records.stream()
                        .filter(value -> value.projectId() == projectId)
                        .filter(value -> value.ragQueryId().equals(ragQueryId))
                        .findFirst();
            }
        }

        private static List<CorpusDocument> corpus() {
            return List.of(
                    new CorpusDocument(
                            41L, "doc-stage21-report-701", "report:701", "TEST_REPORT",
                            "Java report 701", "chunk-stage21-report-701",
                            "Java report 701 report citation identity.",
                            7L, "a".repeat(64), "b".repeat(64)),
                    new CorpusDocument(
                            41L, "doc-stage21-orders-constraint", "rag:orders-constraint-001", "RUNBOOK",
                            "Orders constraint evidence", "chunk-stage21-orders-constraint",
                            "Exact single order constraint evidence; relevant order; independent constraints.",
                            7L, "c".repeat(64), "d".repeat(64)),
                    new CorpusDocument(
                            41L, "doc-stage21-orders-unique-index", "rag:orders-unique-index", "RUNBOOK",
                            "Orders unique index evidence", "chunk-stage21-orders-unique-index",
                            "Exact order unique index evidence; independent order constraints; canonical near.",
                            7L, "e".repeat(64), "f".repeat(64)),
                    new CorpusDocument(
                            41L, "doc-stage21-orders-summary", "rag:orders-unique-index-summary", "RUNBOOK",
                            "Abbreviated orders uniqueness summary", "chunk-stage21-orders-summary",
                            "Abbreviated uniqueness summary; alternative explanation only.",
                            7L, "1".repeat(64), "2".repeat(64)),
                    new CorpusDocument(
                            41L, "doc-stage21-product-catalog", "rag:product-catalog-999", "CATALOG",
                            "Product catalog metadata", "chunk-stage21-product-catalog",
                            "Product catalog metadata lists product names and prices; unrelated catalog context.",
                            7L, "3".repeat(64), "4".repeat(64)),
                    new CorpusDocument(
                            42L, "doc-stage21-private-project-42", "rag:project-42-private", "RUNBOOK",
                            "Project 42 private evidence", "chunk-stage21-private-project-42",
                            "Private project 42 order evidence is isolated from project 41 callers.",
                            9L, "5".repeat(64), "6".repeat(64)));
        }

        private record Key(long projectId, String documentId) {
        }

        private record ChunkKey(long projectId, String documentId, String chunkId) {
        }

        private record CorpusDocument(
                long projectId,
                String documentId,
                String sourceKey,
                String sourceType,
                String title,
                String chunkId,
                String content,
                long createdBy,
                String documentHash,
                String chunkHash
        ) {
        }
    }

    static final class Stage21Embedding implements EmbeddingService {

        private final Stage21EvidenceWorld world;

        Stage21Embedding(Stage21EvidenceWorld world) {
            this.world = world;
        }

        @Override
        public EmbeddingModel model() {
            return world.model();
        }

        @Override
        public List<EmbeddingVector> embed(List<String> texts) {
            return world.embed(texts);
        }
    }

    static final class Stage21VectorStore implements VectorStoreService {

        private final Stage21EvidenceWorld world;

        Stage21VectorStore(Stage21EvidenceWorld world) {
            this.world = world;
        }

        @Override
        public void upsert(long projectId, String documentId, List<VectorEntry> entries) {
            world.upsert(projectId, documentId, entries);
        }

        @Override
        public List<VectorSearchMatch> search(
                long projectId, EmbeddingVector queryVector, int topK) {
            return world.search(projectId, queryVector, topK);
        }

        @Override
        public void deleteByDocument(long projectId, String documentId) {
            world.deleteByDocument(projectId, documentId);
        }
    }

    static class RecordingRagRetriever extends RagRetriever {

        private final Stage21EvidenceWorld world;
        private final CopyOnWriteArrayList<Long> projects = new CopyOnWriteArrayList<>();

        RecordingRagRetriever(
                Stage21EvidenceWorld world,
                EmbeddingService embedding,
                VectorStoreService vectorStore,
                DocumentRepository documents,
                RagQueryRecordRepository queryRecords
        ) {
            super(
                    new ProjectAuthorizationService(
                            (userId, projectId) -> Optional.of(ProjectRole.VIEWER)),
                    embedding, vectorStore, documents, queryRecords,
                    java.time.Clock.systemUTC());
            this.world = world;
        }

        @Override
        public RagRetrieval retrieve(long projectId, String queryText, int topK) {
            projects.add(projectId);
            return super.retrieve(projectId, queryText, topK);
        }

        List<Long> projects() {
            return List.copyOf(projects);
        }

        RagQueryRecord queryRecord(String ragQueryId) {
            return world.queryRecordRepository().findById(41L, ragQueryId)
                    .orElseGet(() -> world.queryRecordRepository().findById(42L, ragQueryId)
                            .orElse(null));
        }
    }
}
