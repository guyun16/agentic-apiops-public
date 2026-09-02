package com.apiops.rag.embedding.zhipu;

import com.apiops.rag.embedding.EmbeddingException;
import com.apiops.rag.embedding.EmbeddingModel;
import com.apiops.rag.embedding.EmbeddingService;
import com.apiops.rag.embedding.EmbeddingVector;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Objects;

/** JDK HTTP adapter for the fixed Zhipu Embedding-3 compatibility profile. */
public final class ZhipuEmbeddingService implements EmbeddingService {

    static final URI DEFAULT_ENDPOINT = URI.create(
            "https://open.bigmodel.cn/api/paas/v4/embeddings");
    static final int MAX_BATCH_SIZE = 64;
    private static final EmbeddingModel MODEL =
            new EmbeddingModel("zhipu", "embedding-3", 1_024);

    private final String apiKey;
    private final Duration timeout;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;
    private final URI endpoint;

    public ZhipuEmbeddingService(
            String apiKey, Duration timeout, ObjectMapper objectMapper) {
        this(apiKey, timeout, objectMapper, client(timeout), DEFAULT_ENDPOINT);
    }

    ZhipuEmbeddingService(
            String apiKey,
            Duration timeout,
            ObjectMapper objectMapper,
            HttpClient httpClient,
            URI endpoint
    ) {
        this.apiKey = apiKey == null ? "" : apiKey.trim();
        this.timeout = requirePositive(timeout);
        this.objectMapper = Objects.requireNonNull(
                objectMapper, "objectMapper must not be null");
        this.httpClient = Objects.requireNonNull(
                httpClient, "httpClient must not be null");
        this.endpoint = Objects.requireNonNull(endpoint, "endpoint must not be null");
    }

    @Override
    public EmbeddingModel model() {
        return MODEL;
    }

    @Override
    public List<EmbeddingVector> embed(List<String> texts) throws EmbeddingException {
        List<String> input = validateInput(texts);
        if (apiKey.isBlank()) {
            throw new EmbeddingException(
                    "Zhipu API key is not configured; set ZHIPU_API_KEY externally");
        }

        HttpRequest request;
        try {
            request = HttpRequest.newBuilder(endpoint)
                    .timeout(timeout)
                    .header("Authorization", "Bearer " + apiKey)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(requestBody(input)))
                    .build();
        } catch (RuntimeException failure) {
            throw new EmbeddingException("Zhipu embedding configuration is invalid", failure);
        }

        HttpResponse<String> response;
        try {
            response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (HttpTimeoutException failure) {
            throw new EmbeddingException("Zhipu embedding request timed out", failure);
        } catch (InterruptedException failure) {
            Thread.currentThread().interrupt();
            throw new EmbeddingException("Zhipu embedding request was interrupted", failure);
        } catch (IOException failure) {
            throw new EmbeddingException("Zhipu embedding request failed", failure);
        }

        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new EmbeddingException(
                    "Zhipu embedding request failed with HTTP status "
                            + response.statusCode());
        }
        return parseResponse(response.body(), input.size());
    }

    private List<String> validateInput(List<String> texts) {
        if (texts == null || texts.isEmpty()) {
            throw new EmbeddingException("Embedding input must not be empty");
        }
        if (texts.size() > MAX_BATCH_SIZE) {
            throw new EmbeddingException("Zhipu embedding batch must not exceed 64 texts");
        }
        if (texts.stream().anyMatch(value -> value == null || value.isBlank())) {
            throw new EmbeddingException("Embedding text must not be blank");
        }
        return List.copyOf(texts);
    }

    private String requestBody(List<String> input) {
        try {
            return objectMapper.writeValueAsString(
                    new ZhipuEmbeddingRequest(MODEL.model(), input, MODEL.dimension()));
        } catch (JsonProcessingException failure) {
            throw new EmbeddingException("Unable to create Zhipu embedding request", failure);
        }
    }

    private List<EmbeddingVector> parseResponse(String body, int expectedCount) {
        JsonNode root;
        try {
            root = objectMapper.readTree(body);
        } catch (JsonProcessingException failure) {
            throw new EmbeddingException("Zhipu embedding response is malformed", failure);
        }
        if (root != null && root.hasNonNull("error")) {
            throw new EmbeddingException("Zhipu embedding API returned an error");
        }
        JsonNode data = root == null ? null : root.get("data");
        if (data == null || !data.isArray()) {
            throw new EmbeddingException("Zhipu embedding response is malformed");
        }
        JsonNode responseModel = root.get("model");
        if (responseModel == null || !MODEL.model().equals(responseModel.textValue())) {
            throw new EmbeddingException("Zhipu embedding response model is incompatible");
        }
        if (data.size() != expectedCount) {
            throw new EmbeddingException("Zhipu embedding response count does not match input");
        }

        EmbeddingVector[] ordered = new EmbeddingVector[expectedCount];
        for (JsonNode item : data) {
            JsonNode indexNode = item.get("index");
            JsonNode embeddingNode = item.get("embedding");
            if (indexNode == null || !indexNode.isIntegralNumber()
                    || embeddingNode == null || !embeddingNode.isArray()) {
                throw new EmbeddingException("Zhipu embedding response is malformed");
            }
            int index = indexNode.intValue();
            if (index < 0 || index >= expectedCount || ordered[index] != null) {
                throw new EmbeddingException("Zhipu embedding response index is invalid");
            }
            if (embeddingNode.size() != MODEL.dimension()) {
                throw new EmbeddingException("Zhipu embedding vector dimension is invalid");
            }

            List<Float> values = new ArrayList<>(MODEL.dimension());
            for (JsonNode value : embeddingNode) {
                if (!value.isNumber()) {
                    throw new EmbeddingException("Zhipu embedding response is malformed");
                }
                values.add(value.floatValue());
            }
            ordered[index] = new EmbeddingVector(MODEL, values);
        }
        if (Arrays.stream(ordered).anyMatch(Objects::isNull)) {
            throw new EmbeddingException("Zhipu embedding response index is invalid");
        }
        return List.copyOf(Arrays.asList(ordered));
    }

    private static HttpClient client(Duration timeout) {
        return HttpClient.newBuilder()
                .connectTimeout(requirePositive(timeout))
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
    }

    private static Duration requirePositive(Duration value) {
        Objects.requireNonNull(value, "timeout must not be null");
        if (value.isZero() || value.isNegative()) {
            throw new IllegalArgumentException("timeout must be positive");
        }
        return value;
    }

    private record ZhipuEmbeddingRequest(
            String model, List<String> input, int dimensions) {
    }
}
