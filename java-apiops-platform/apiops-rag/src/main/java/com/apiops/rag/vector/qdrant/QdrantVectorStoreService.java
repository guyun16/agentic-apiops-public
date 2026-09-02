package com.apiops.rag.vector.qdrant;

import com.apiops.rag.embedding.EmbeddingModel;
import com.apiops.rag.embedding.EmbeddingVector;
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.VectorSearchMatch;
import com.apiops.rag.vector.VectorStoreException;
import com.apiops.rag.vector.VectorStoreService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.regex.Pattern;

/** Qdrant REST adapter for the fixed Stage 10 embedding compatibility space. */
public final class QdrantVectorStoreService implements VectorStoreService {

    public static final EmbeddingModel INDEX_MODEL =
            new EmbeddingModel("zhipu", "embedding-3", 1_024);
    public static final String INDEX_DISTANCE = "Cosine";

    private static final UUID POINT_NAMESPACE =
            UUID.fromString("d0203df5-6a5b-5a35-9239-2133e0f5f80b");
    private static final Pattern COLLECTION_NAME = Pattern.compile("[A-Za-z0-9_-]+");

    private final URI baseUrl;
    private final String collection;
    private final Duration timeout;
    private final String apiKey;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public QdrantVectorStoreService(
            String baseUrl,
            String collection,
            Duration timeout,
            String apiKey,
            ObjectMapper objectMapper
    ) {
        this(baseUrl, collection, timeout, apiKey, objectMapper,
                HttpClient.newBuilder().connectTimeout(timeout).build());
    }

    QdrantVectorStoreService(
            String baseUrl,
            String collection,
            Duration timeout,
            String apiKey,
            ObjectMapper objectMapper,
            HttpClient httpClient
    ) {
        String normalizedBaseUrl = requireText(baseUrl, "baseUrl");
        this.baseUrl = URI.create(normalizedBaseUrl.endsWith("/")
                ? normalizedBaseUrl.substring(0, normalizedBaseUrl.length() - 1)
                : normalizedBaseUrl);
        this.collection = requireText(collection, "collection");
        if (!COLLECTION_NAME.matcher(this.collection).matches()) {
            throw new IllegalArgumentException("collection contains unsupported characters");
        }
        this.timeout = Objects.requireNonNull(timeout, "timeout must not be null");
        if (timeout.isZero() || timeout.isNegative()) {
            throw new IllegalArgumentException("timeout must be positive");
        }
        this.apiKey = apiKey == null ? "" : apiKey;
        this.objectMapper = Objects.requireNonNull(
                objectMapper, "objectMapper must not be null");
        this.httpClient = Objects.requireNonNull(
                httpClient, "httpClient must not be null");
    }

    /** Creates the fixed collection when absent and rejects incompatible existing state. */
    public void initialize() {
        Response existing = exchange("GET", collectionPath(), null);
        if (existing.statusCode() == 404) {
            ObjectNode create = objectMapper.createObjectNode();
            ObjectNode vectors = create.putObject("vectors");
            vectors.put("size", INDEX_MODEL.dimension());
            vectors.put("distance", INDEX_DISTANCE);
            requireOk(exchange("PUT", collectionPath(), create),
                    "Qdrant collection bootstrap failed");
            existing = exchange("GET", collectionPath(), null);
        }
        requireOk(existing, "Qdrant collection lookup failed");
        validateCollection(existing.body());
        ensurePayloadIndex(existing.body(), "projectId", "integer");
        ensurePayloadIndex(existing.body(), "documentId", "keyword");
    }

    @Override
    public void upsert(long projectId, String documentId, List<VectorEntry> entries) {
        validateScope(projectId, documentId);
        List<VectorEntry> values = List.copyOf(
                Objects.requireNonNull(entries, "entries must not be null"));
        if (values.isEmpty()) {
            throw new VectorStoreException("Qdrant upsert entries must not be empty");
        }

        ArrayNode points = objectMapper.createArrayNode();
        for (VectorEntry entry : values) {
            validateEntry(projectId, documentId, entry);
            ObjectNode point = points.addObject();
            point.put("id", pointId(projectId, documentId, entry.chunkId()).toString());
            ArrayNode vector = point.putArray("vector");
            entry.embedding().values().forEach(vector::add);
            ObjectNode payload = point.putObject("payload");
            payload.put("projectId", projectId);
            payload.put("documentId", documentId);
            payload.put("chunkId", entry.chunkId());
            payload.put("contentHash", entry.contentHash());
            payload.put("embeddingProvider", INDEX_MODEL.provider());
            payload.put("embeddingModel", INDEX_MODEL.model());
            payload.put("embeddingDimension", INDEX_MODEL.dimension());
        }
        ObjectNode request = objectMapper.createObjectNode();
        request.set("points", points);
        requireCompleted(exchange("PUT", pointsPath() + "?wait=true", request),
                "Qdrant point upsert failed");
    }

    @Override
    public List<VectorSearchMatch> search(
            long projectId, EmbeddingVector queryVector, int topK) {
        if (projectId <= 0) {
            throw new VectorStoreException("projectId must be positive");
        }
        validateEmbedding(Objects.requireNonNull(
                queryVector, "queryVector must not be null"));
        if (topK <= 0) {
            throw new VectorStoreException("topK must be positive");
        }

        ObjectNode request = objectMapper.createObjectNode();
        ArrayNode query = request.putArray("query");
        queryVector.values().forEach(query::add);
        request.set("filter", projectFilter(projectId));
        request.put("limit", topK);
        request.put("with_payload", true);
        request.put("with_vector", false);
        Response response = exchange("POST", pointsPath() + "/query", request);
        requireOk(response, "Qdrant point query failed");

        JsonNode result = response.body().path("result");
        JsonNode points = result.has("points") ? result.path("points") : result;
        if (!points.isArray()) {
            throw new VectorStoreException("Qdrant point query response is malformed");
        }
        List<VectorSearchMatch> matches = new ArrayList<>();
        for (JsonNode point : points) {
            JsonNode payload = point.path("payload");
            if (!payload.isObject()
                    || payload.path("projectId").asLong(Long.MIN_VALUE) != projectId
                    || payload.path("documentId").asText().isBlank()
                    || payload.path("chunkId").asText().isBlank()) {
                throw new VectorStoreException("Qdrant point query payload is malformed");
            }
            JsonNode score = point.path("score");
            if (!score.isNumber() || !Double.isFinite(score.asDouble())) {
                throw new VectorStoreException("Qdrant point query score is malformed");
            }
            matches.add(new VectorSearchMatch(
                    projectId,
                    payload.path("documentId").asText(),
                    payload.path("chunkId").asText(),
                    cosineRelevanceScore(score.asDouble())));
            if (matches.size() == topK) {
                break;
            }
        }
        return List.copyOf(matches);
    }

    @Override
    public void deleteByDocument(long projectId, String documentId) {
        validateScope(projectId, documentId);
        ObjectNode request = objectMapper.createObjectNode();
        request.set("filter", documentFilter(projectId, documentId));
        requireCompleted(exchange("POST", pointsPath() + "/delete?wait=true", request),
                "Qdrant document vector delete failed");
    }

    static UUID pointId(long projectId, String documentId, String chunkId) {
        if (projectId <= 0) {
            throw new IllegalArgumentException("projectId must be positive");
        }
        String document = requireText(documentId, "documentId");
        String chunk = requireText(chunkId, "chunkId");
        String name = projectId + ":" + document.length() + ":" + document
                + ":" + chunk.length() + ":" + chunk;
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-1");
            digest.update(uuidBytes(POINT_NAMESPACE));
            byte[] hash = digest.digest(name.getBytes(StandardCharsets.UTF_8));
            hash[6] = (byte) ((hash[6] & 0x0f) | 0x50);
            hash[8] = (byte) ((hash[8] & 0x3f) | 0x80);
            ByteBuffer bytes = ByteBuffer.wrap(hash);
            return new UUID(bytes.getLong(), bytes.getLong());
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-1 is unavailable", exception);
        }
    }

    private void validateCollection(JsonNode response) {
        JsonNode vectors = response.path("result").path("config")
                .path("params").path("vectors");
        int dimension = vectors.path("size").asInt(-1);
        String distance = vectors.path("distance").asText();
        if (dimension != INDEX_MODEL.dimension()
                || !INDEX_DISTANCE.equalsIgnoreCase(distance)) {
            throw new VectorStoreException(
                    "Qdrant collection is incompatible with zhipu embedding-3/1024 Cosine");
        }
    }

    private void ensurePayloadIndex(JsonNode response, String field, String type) {
        JsonNode definition = response.path("result").path("payload_schema").path(field);
        if (!definition.isMissingNode()) {
            if (!type.equalsIgnoreCase(definition.path("data_type").asText())) {
                throw new VectorStoreException(
                        "Qdrant payload index " + field + " has an incompatible type");
            }
            return;
        }
        ObjectNode request = objectMapper.createObjectNode();
        request.put("field_name", field);
        request.put("field_schema", type);
        requireOk(exchange("PUT", collectionPath() + "/index?wait=true", request),
                "Qdrant payload index bootstrap failed for " + field);
    }

    private void validateEntry(long projectId, String documentId, VectorEntry entry) {
        if (entry == null) {
            throw new VectorStoreException("Qdrant upsert entry must not be null");
        }
        if (entry.projectId() != projectId || !entry.documentId().equals(documentId)) {
            throw new VectorStoreException(
                    "Qdrant upsert entry does not match project document scope");
        }
        requireVectorText(entry.chunkId(), "chunkId");
        requireVectorText(entry.contentHash(), "contentHash");
        validateEmbedding(entry.embedding());
    }

    private void validateEmbedding(EmbeddingVector vector) {
        if (!INDEX_MODEL.equals(vector.model())) {
            throw new VectorStoreException(
                    "Qdrant vector is incompatible with zhipu embedding-3/1024");
        }
        if (vector.values().stream().anyMatch(value -> !Float.isFinite(value))) {
            throw new VectorStoreException("Qdrant vector contains a non-finite value");
        }
    }

    private void validateScope(long projectId, String documentId) {
        if (projectId <= 0) {
            throw new VectorStoreException("projectId must be positive");
        }
        requireVectorText(documentId, "documentId");
    }

    private ObjectNode projectFilter(long projectId) {
        ObjectNode filter = objectMapper.createObjectNode();
        ArrayNode must = filter.putArray("must");
        match(must, "projectId", projectId);
        return filter;
    }

    /** Qdrant Cosine query scores already use the business higher-is-better direction. */
    private double cosineRelevanceScore(double score) {
        return score;
    }

    private ObjectNode documentFilter(long projectId, String documentId) {
        ObjectNode filter = projectFilter(projectId);
        ArrayNode must = (ArrayNode) filter.path("must");
        match(must, "documentId", documentId);
        return filter;
    }

    private void match(ArrayNode must, String key, long value) {
        ObjectNode condition = must.addObject();
        condition.put("key", key);
        condition.putObject("match").put("value", value);
    }

    private void match(ArrayNode must, String key, String value) {
        ObjectNode condition = must.addObject();
        condition.put("key", key);
        condition.putObject("match").put("value", value);
    }

    private Response exchange(String method, String path, JsonNode body) {
        try {
            HttpRequest.Builder request = HttpRequest.newBuilder(baseUrl.resolve(path))
                    .timeout(timeout)
                    .header("Accept", "application/json");
            if (!apiKey.isBlank()) {
                request.header("api-key", apiKey);
            }
            if (body == null) {
                request.method(method, HttpRequest.BodyPublishers.noBody());
            } else {
                request.header("Content-Type", "application/json");
                request.method(method, HttpRequest.BodyPublishers.ofString(
                        objectMapper.writeValueAsString(body), StandardCharsets.UTF_8));
            }
            HttpResponse<String> response = httpClient.send(
                    request.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            JsonNode json = parseBody(response.statusCode(), response.body());
            return new Response(response.statusCode(), json);
        } catch (HttpTimeoutException exception) {
            throw new VectorStoreException("Qdrant request timed out", exception);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new VectorStoreException("Qdrant request was interrupted", exception);
        } catch (IOException exception) {
            throw new VectorStoreException("Qdrant request failed", exception);
        }
    }

    private JsonNode parseBody(int statusCode, String body) {
        try {
            return objectMapper.readTree(body);
        } catch (JsonProcessingException exception) {
            throw new VectorStoreException(
                    "Qdrant response is malformed for HTTP status " + statusCode, exception);
        }
    }

    private void requireOk(Response response, String message) {
        if (response.statusCode() < 200 || response.statusCode() >= 300
                || !"ok".equalsIgnoreCase(response.body().path("status").asText())) {
            throw new VectorStoreException(message
                    + " with HTTP status " + response.statusCode());
        }
    }

    private void requireCompleted(Response response, String message) {
        requireOk(response, message);
        String status = response.body().path("result").path("status").asText();
        if (!"completed".equalsIgnoreCase(status)) {
            throw new VectorStoreException(message + " was not confirmed complete");
        }
    }

    private String collectionPath() {
        return "/collections/" + collection;
    }

    private String pointsPath() {
        return collectionPath() + "/points";
    }

    private static byte[] uuidBytes(UUID value) {
        return ByteBuffer.allocate(16)
                .putLong(value.getMostSignificantBits())
                .putLong(value.getLeastSignificantBits())
                .array();
    }

    private static String requireText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }

    private static void requireVectorText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw new VectorStoreException(name + " must not be blank");
        }
    }

    private record Response(int statusCode, JsonNode body) {
    }
}
