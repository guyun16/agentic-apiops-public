package com.apiops.rag.vector.qdrant;

import com.apiops.rag.embedding.EmbeddingModel;
import com.apiops.rag.embedding.EmbeddingVector;
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.VectorStoreException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.Function;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class QdrantVectorStoreServiceTest {

    private static final long PROJECT_ID = 41L;
    private static final String DOCUMENT_ID = "doc-orders";
    private static final String API_KEY = "test-qdrant-key-never-log";

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final List<CapturedRequest> requests = new CopyOnWriteArrayList<>();
    private HttpServer server;
    private Function<CapturedRequest, StubResponse> responder;
    private Duration responseDelay;

    @BeforeEach
    void startServer() throws IOException {
        responder = ignored -> okCompleted();
        responseDelay = Duration.ZERO;
        server = HttpServer.create(new InetSocketAddress(
                InetAddress.getLoopbackAddress(), 0), 0);
        server.createContext("/", this::handle);
        server.start();
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }

    @Test
    void deterministicPointIdIsStableAndIncludesEveryScopeIdentity() {
        UUID first = QdrantVectorStoreService.pointId(
                PROJECT_ID, DOCUMENT_ID, "chunk-1");

        assertEquals(first, QdrantVectorStoreService.pointId(
                PROJECT_ID, DOCUMENT_ID, "chunk-1"));
        assertEquals(5, first.version());
        assertNotEquals(first, QdrantVectorStoreService.pointId(
                PROJECT_ID + 1, DOCUMENT_ID, "chunk-1"));
        assertNotEquals(first, QdrantVectorStoreService.pointId(
                PROJECT_ID, DOCUMENT_ID + "-other", "chunk-1"));
        assertNotEquals(first, QdrantVectorStoreService.pointId(
                PROJECT_ID, DOCUMENT_ID, "chunk-2"));
        assertNotEquals(
                QdrantVectorStoreService.pointId(PROJECT_ID, "a\u001fb", "c"),
                QdrantVectorStoreService.pointId(PROJECT_ID, "a", "b\u001fc"));
    }

    @Test
    void upsertUsesOneWaitedBatchAndPreservesCompatibilityPayload() throws Exception {
        service().upsert(PROJECT_ID, DOCUMENT_ID, List.of(
                entry("chunk-1"), entry("chunk-2")));

        assertEquals(1, requests.size());
        CapturedRequest request = requests.getFirst();
        assertEquals("PUT", request.method());
        assertEquals("/collections/apiops_rag_chunks_v1/points", request.path());
        assertEquals("wait=true", request.query());
        assertEquals(API_KEY, request.apiKey());
        JsonNode points = objectMapper.readTree(request.body()).path("points");
        assertEquals(2, points.size());
        JsonNode first = points.get(0);
        assertEquals(1_024, first.path("vector").size());
        assertEquals(PROJECT_ID, first.path("payload").path("projectId").asLong());
        assertEquals(DOCUMENT_ID,
                first.path("payload").path("documentId").asText());
        assertEquals("chunk-1", first.path("payload").path("chunkId").asText());
        assertEquals("zhipu",
                first.path("payload").path("embeddingProvider").asText());
        assertEquals("embedding-3",
                first.path("payload").path("embeddingModel").asText());
        assertEquals(1_024,
                first.path("payload").path("embeddingDimension").asInt());
        assertFalse(first.path("payload").has("content"));
    }

    @Test
    void rejectsEmptyScopeMismatchAndEmbeddingMismatchBeforeHttp() {
        assertThrows(VectorStoreException.class,
                () -> service().upsert(PROJECT_ID, DOCUMENT_ID, List.of()));
        assertThrows(VectorStoreException.class,
                () -> service().upsert(PROJECT_ID, DOCUMENT_ID,
                        List.of(entry(PROJECT_ID + 1, DOCUMENT_ID, "chunk-1",
                                QdrantVectorStoreService.INDEX_MODEL))));
        assertThrows(VectorStoreException.class,
                () -> service().upsert(PROJECT_ID, DOCUMENT_ID,
                        List.of(entry(PROJECT_ID, DOCUMENT_ID, "chunk-1",
                                new EmbeddingModel("other", "model", 3)))));

        assertTrue(requests.isEmpty());
    }

    @Test
    void deleteUsesProjectAndDocumentFilterAndWaitsForCompletion() throws Exception {
        service().deleteByDocument(PROJECT_ID, DOCUMENT_ID);

        CapturedRequest request = requests.getFirst();
        assertEquals("POST", request.method());
        assertEquals("/collections/apiops_rag_chunks_v1/points/delete", request.path());
        assertEquals("wait=true", request.query());
        JsonNode must = objectMapper.readTree(request.body()).path("filter").path("must");
        assertEquals(2, must.size());
        assertEquals("projectId", must.get(0).path("key").asText());
        assertEquals(PROJECT_ID,
                must.get(0).path("match").path("value").asLong());
        assertEquals("documentId", must.get(1).path("key").asText());
        assertEquals(DOCUMENT_ID,
                must.get(1).path("match").path("value").asText());
    }

    @Test
    void searchFiltersInsideQdrantAndExposesHigherIsBetterCosineScore() throws Exception {
        responder = ignored -> new StubResponse(200, """
                {"status":"ok","result":{"points":[
                  {"id":"1","score":0.9,"payload":{
                    "projectId":41,"documentId":"doc-orders","chunkId":"chunk-1"}}
                ]}}
                """);

        var matches = service().search(PROJECT_ID, vector(
                QdrantVectorStoreService.INDEX_MODEL), 3);

        assertEquals(1, matches.size());
        assertEquals("chunk-1", matches.getFirst().chunkId());
        assertEquals(0.9, matches.getFirst().relevanceScore());
        JsonNode body = objectMapper.readTree(requests.getFirst().body());
        assertEquals(PROJECT_ID, body.path("filter").path("must").get(0)
                .path("match").path("value").asLong());
        assertEquals(3, body.path("limit").asInt());
        assertFalse(body.has("score_threshold"));
    }

    @Test
    void searchRejectsMissingScoreAndDefensivelyLimitsProviderResponse() {
        responder = ignored -> new StubResponse(200, """
                {"status":"ok","result":{"points":[
                  {"id":"1","score":0.9,"payload":{
                    "projectId":41,"documentId":"doc-orders","chunkId":"chunk-1"}},
                  {"id":"2","score":0.8,"payload":{
                    "projectId":41,"documentId":"doc-orders","chunkId":"chunk-2"}}
                ]}}
                """);
        assertEquals(1, service().search(PROJECT_ID, vector(
                QdrantVectorStoreService.INDEX_MODEL), 1).size());

        responder = ignored -> new StubResponse(200, """
                {"status":"ok","result":{"points":[
                  {"id":"1","payload":{
                    "projectId":41,"documentId":"doc-orders","chunkId":"chunk-1"}}
                ]}}
                """);
        VectorStoreException failure = assertThrows(VectorStoreException.class,
                () -> service().search(PROJECT_ID, vector(
                        QdrantVectorStoreService.INDEX_MODEL), 1));
        assertEquals("Qdrant point query score is malformed", failure.getMessage());
    }

    @Test
    void bootstrapCreatesMissingCollectionAndPayloadIndexesThenIsReusable()
            throws Exception {
        responder = request -> {
            int call = requests.size();
            if (call == 1) {
                return new StubResponse(404, "{\"status\":\"error\"}");
            }
            if (call == 2 || call == 4 || call == 5) {
                return ok();
            }
            return collectionResponse(false);
        };

        service().initialize();

        assertEquals(5, requests.size());
        JsonNode create = objectMapper.readTree(requests.get(1).body());
        assertEquals(1_024, create.path("vectors").path("size").asInt());
        assertEquals("Cosine", create.path("vectors").path("distance").asText());
        JsonNode projectIndex = objectMapper.readTree(requests.get(3).body());
        JsonNode documentIndex = objectMapper.readTree(requests.get(4).body());
        assertEquals("projectId", projectIndex.path("field_name").asText());
        assertEquals("integer", projectIndex.path("field_schema").asText());
        assertEquals("documentId", documentIndex.path("field_name").asText());
        assertEquals("keyword", documentIndex.path("field_schema").asText());

        requests.clear();
        responder = ignored -> collectionResponse(true);
        service().initialize();
        assertEquals(1, requests.size());
    }

    @Test
    void incompatibleCollectionFailsWithoutMutation() {
        responder = ignored -> new StubResponse(200, """
                {"status":"ok","result":{"config":{"params":{"vectors":{
                  "size":3,"distance":"Dot"}}},"payload_schema":{}}}
                """);

        VectorStoreException failure = assertThrows(
                VectorStoreException.class, () -> service().initialize());

        assertEquals(
                "Qdrant collection is incompatible with zhipu embedding-3/1024 Cosine",
                failure.getMessage());
        assertEquals(1, requests.size());
        assertEquals("GET", requests.getFirst().method());
    }

    @Test
    void mapsHttpMalformedAndUnconfirmedResponsesWithoutLeakingSecrets() {
        responder = ignored -> new StubResponse(503,
                "{\"status\":\"error\",\"detail\":\"sensitive\"}");
        VectorStoreException http = assertThrows(VectorStoreException.class,
                () -> service().deleteByDocument(PROJECT_ID, DOCUMENT_ID));
        assertEquals("Qdrant document vector delete failed with HTTP status 503",
                http.getMessage());
        assertFalse(http.getMessage().contains(API_KEY));
        assertFalse(http.getMessage().contains("sensitive"));

        responder = ignored -> new StubResponse(200, "not-json");
        VectorStoreException malformed = assertThrows(VectorStoreException.class,
                () -> service().deleteByDocument(PROJECT_ID, DOCUMENT_ID));
        assertEquals("Qdrant response is malformed for HTTP status 200",
                malformed.getMessage());

        responder = ignored -> new StubResponse(200,
                "{\"status\":\"ok\",\"result\":{\"status\":\"acknowledged\"}}");
        VectorStoreException incomplete = assertThrows(VectorStoreException.class,
                () -> service().deleteByDocument(PROJECT_ID, DOCUMENT_ID));
        assertEquals("Qdrant document vector delete failed was not confirmed complete",
                incomplete.getMessage());
    }

    @Test
    void mapsTimeoutToStableFailure() {
        responseDelay = Duration.ofMillis(250);

        VectorStoreException failure = assertThrows(VectorStoreException.class,
                () -> service(Duration.ofMillis(50))
                        .deleteByDocument(PROJECT_ID, DOCUMENT_ID));

        assertEquals("Qdrant request timed out", failure.getMessage());
        assertFalse(failure.getMessage().contains(API_KEY));
    }

    private QdrantVectorStoreService service() {
        return service(Duration.ofSeconds(2));
    }

    private QdrantVectorStoreService service(Duration timeout) {
        String baseUrl = "http://" + server.getAddress().getHostString()
                + ":" + server.getAddress().getPort();
        return new QdrantVectorStoreService(
                baseUrl, "apiops_rag_chunks_v1", timeout,
                API_KEY, objectMapper);
    }

    private VectorEntry entry(String chunkId) {
        return entry(PROJECT_ID, DOCUMENT_ID, chunkId,
                QdrantVectorStoreService.INDEX_MODEL);
    }

    private VectorEntry entry(
            long projectId, String documentId, String chunkId, EmbeddingModel model) {
        return new VectorEntry(projectId, documentId, chunkId, "a".repeat(64),
                vector(model), java.util.Map.of());
    }

    private EmbeddingVector vector(EmbeddingModel model) {
        return new EmbeddingVector(model,
                new ArrayList<>(java.util.Collections.nCopies(model.dimension(), 0.25F)));
    }

    private StubResponse collectionResponse(boolean indexes) {
        String schema = indexes
                ? "\"projectId\":{\"data_type\":\"integer\"},"
                    + "\"documentId\":{\"data_type\":\"keyword\"}"
                : "";
        return new StubResponse(200, "{\"status\":\"ok\",\"result\":{"
                + "\"config\":{\"params\":{\"vectors\":{"
                + "\"size\":1024,\"distance\":\"Cosine\"}}},"
                + "\"payload_schema\":{" + schema + "}}}");
    }

    private StubResponse ok() {
        return new StubResponse(200, "{\"status\":\"ok\",\"result\":true}");
    }

    private StubResponse okCompleted() {
        return new StubResponse(200,
                "{\"status\":\"ok\",\"result\":{\"status\":\"completed\"}}");
    }

    private void handle(HttpExchange exchange) throws IOException {
        String body = new String(
                exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        CapturedRequest captured = new CapturedRequest(
                exchange.getRequestMethod(), exchange.getRequestURI().getPath(),
                exchange.getRequestURI().getQuery(), body,
                exchange.getRequestHeaders().getFirst("api-key"));
        requests.add(captured);
        try {
            Thread.sleep(responseDelay);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            exchange.close();
            return;
        }
        StubResponse response = responder.apply(captured);
        byte[] bytes = response.body().getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(response.status(), bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    private record CapturedRequest(
            String method, String path, String query, String body, String apiKey) {
    }

    private record StubResponse(int status, String body) {
    }
}
