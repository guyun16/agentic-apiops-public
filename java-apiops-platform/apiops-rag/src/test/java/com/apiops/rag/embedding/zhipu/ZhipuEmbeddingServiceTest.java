package com.apiops.rag.embedding.zhipu;

import com.apiops.rag.embedding.EmbeddingException;
import com.apiops.rag.embedding.EmbeddingModel;
import com.apiops.rag.embedding.EmbeddingVector;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ZhipuEmbeddingServiceTest {

    private static final String TEST_KEY = "test-key-never-log";

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final AtomicInteger requests = new AtomicInteger();
    private HttpServer server;
    private volatile int responseStatus;
    private volatile String responseBody;
    private volatile String requestBody;
    private volatile String authorization;
    private volatile Duration responseDelay;

    @BeforeEach
    void startServer() throws IOException {
        responseStatus = 200;
        responseBody = response(List.of(0), 1_024);
        responseDelay = Duration.ZERO;
        server = HttpServer.create(new InetSocketAddress(
                InetAddress.getLoopbackAddress(), 0), 0);
        server.createContext("/embeddings", this::handle);
        server.start();
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }

    @Test
    void sendsFixedModelAndDimensionAndEmbedsSingleText() throws Exception {
        EmbeddingVector vector = service(TEST_KEY).embed("orders");

        JsonNode request = objectMapper.readTree(requestBody);
        assertEquals("embedding-3", request.path("model").asText());
        assertEquals(1_024, request.path("dimensions").asInt());
        assertTrue(request.path("input").isArray());
        assertEquals(List.of("orders"), objectMapper.convertValue(
                request.path("input"), objectMapper.getTypeFactory()
                        .constructCollectionType(List.class, String.class)));
        assertEquals("Bearer " + TEST_KEY, authorization);
        assertEquals(new EmbeddingModel("zhipu", "embedding-3", 1_024), vector.model());
        assertEquals(1_024, vector.values().size());
        assertEquals(1, requests.get());
    }

    @Test
    void sendsOneBatchRequestAndRestoresInputOrderByResponseIndex() {
        responseBody = response(List.of(2, 0, 1), 1_024);

        List<EmbeddingVector> vectors = service(TEST_KEY).embed(
                List.of("first", "second", "third"));

        assertEquals(3, vectors.size());
        assertEquals(0.25F, vectors.get(0).values().getFirst());
        assertEquals(1.25F, vectors.get(1).values().getFirst());
        assertEquals(2.25F, vectors.get(2).values().getFirst());
        assertEquals(1, requests.get());
    }

    @Test
    void rejectsResponseCountMismatch() {
        responseBody = response(List.of(0), 1_024);

        EmbeddingException failure = assertThrows(EmbeddingException.class,
                () -> service(TEST_KEY).embed(List.of("first", "second")));

        assertEquals("Zhipu embedding response count does not match input",
                failure.getMessage());
    }

    @Test
    void rejectsInvalidResponseIndex() {
        responseBody = response(List.of(1), 1_024);

        EmbeddingException failure = assertThrows(EmbeddingException.class,
                () -> service(TEST_KEY).embed("first"));

        assertEquals("Zhipu embedding response index is invalid", failure.getMessage());
    }

    @Test
    void rejectsWrongVectorDimension() {
        responseBody = response(List.of(0), 1_023);

        EmbeddingException failure = assertThrows(EmbeddingException.class,
                () -> service(TEST_KEY).embed("first"));

        assertEquals("Zhipu embedding vector dimension is invalid", failure.getMessage());
    }

    @Test
    void mapsHttp4xxWithoutLeakingProviderBodyOrKey() {
        responseStatus = 401;
        responseBody = "{\"error\":{\"message\":\"sensitive provider detail\"}}";

        EmbeddingException failure = assertThrows(EmbeddingException.class,
                () -> service(TEST_KEY).embed("first"));

        assertEquals("Zhipu embedding request failed with HTTP status 401",
                failure.getMessage());
        assertFalse(failure.getMessage().contains(TEST_KEY));
        assertFalse(failure.getMessage().contains("sensitive provider detail"));
    }

    @Test
    void mapsHttp5xxToStableFailure() {
        responseStatus = 503;
        responseBody = "unavailable";

        EmbeddingException failure = assertThrows(EmbeddingException.class,
                () -> service(TEST_KEY).embed("first"));

        assertEquals("Zhipu embedding request failed with HTTP status 503",
                failure.getMessage());
    }

    @Test
    void mapsMalformedJsonToStableFailure() {
        responseBody = "not-json";

        EmbeddingException failure = assertThrows(EmbeddingException.class,
                () -> service(TEST_KEY).embed("first"));

        assertEquals("Zhipu embedding response is malformed", failure.getMessage());
    }

    @Test
    void mapsApiErrorPayloadWithoutLeakingProviderDetail() {
        responseBody = "{\"error\":{\"code\":\"bad\","
                + "\"message\":\"sensitive provider detail\"}}";

        EmbeddingException failure = assertThrows(EmbeddingException.class,
                () -> service(TEST_KEY).embed("first"));

        assertEquals("Zhipu embedding API returned an error", failure.getMessage());
        assertFalse(failure.getMessage().contains("sensitive provider detail"));
    }

    @Test
    void mapsTimeoutToStableFailure() {
        responseDelay = Duration.ofMillis(300);

        EmbeddingException failure = assertThrows(EmbeddingException.class,
                () -> service(TEST_KEY, Duration.ofMillis(50)).embed("first"));

        assertEquals("Zhipu embedding request timed out", failure.getMessage());
    }

    @Test
    void missingApiKeyFailsBeforeHttpWithoutLeakingSecrets() {
        EmbeddingException failure = assertThrows(EmbeddingException.class,
                () -> service(" ").embed("first"));

        assertEquals(
                "Zhipu API key is not configured; set ZHIPU_API_KEY externally",
                failure.getMessage());
        assertEquals(0, requests.get());
        assertFalse(failure.getMessage().contains(TEST_KEY));
    }

    @Test
    void rejectsBatchLargerThan64WithoutHttp() {
        List<String> input = new ArrayList<>();
        for (int index = 0; index < 65; index++) {
            input.add("text-" + index);
        }

        EmbeddingException failure = assertThrows(EmbeddingException.class,
                () -> service(TEST_KEY).embed(input));

        assertEquals("Zhipu embedding batch must not exceed 64 texts",
                failure.getMessage());
        assertEquals(0, requests.get());
    }

    private ZhipuEmbeddingService service(String apiKey) {
        return service(apiKey, Duration.ofSeconds(2));
    }

    private ZhipuEmbeddingService service(String apiKey, Duration timeout) {
        URI endpoint = URI.create("http://" + server.getAddress().getHostString()
                + ":" + server.getAddress().getPort() + "/embeddings");
        return new ZhipuEmbeddingService(
                apiKey, timeout, objectMapper,
                HttpClient.newHttpClient(), endpoint);
    }

    private String response(List<Integer> indexes, int dimension) {
        ObjectNode root = objectMapper.createObjectNode();
        root.put("model", "embedding-3");
        root.put("object", "list");
        ArrayNode data = root.putArray("data");
        for (int index : indexes) {
            ObjectNode item = data.addObject();
            item.put("index", index);
            item.put("object", "embedding");
            ArrayNode values = item.putArray("embedding");
            values.add(index + 0.25F);
            for (int value = 1; value < dimension; value++) {
                values.add(0.0F);
            }
        }
        return root.toString();
    }

    private void handle(HttpExchange exchange) throws IOException {
        requests.incrementAndGet();
        requestBody = new String(
                exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        authorization = exchange.getRequestHeaders().getFirst("Authorization");
        try {
            Thread.sleep(responseDelay);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            exchange.close();
            return;
        }
        byte[] body = responseBody.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(responseStatus, body.length);
        exchange.getResponseBody().write(body);
        exchange.close();
    }
}
