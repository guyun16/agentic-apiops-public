package com.apiops.rag.vector.qdrant;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;

final class QdrantTestClient {

    private final URI baseUrl;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    QdrantTestClient(String baseUrl, ObjectMapper objectMapper) {
        this.baseUrl = URI.create(baseUrl.endsWith("/")
                ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl);
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(5)).build();
    }

    JsonNode root() {
        return exchange("GET", "/", null);
    }

    JsonNode collection(String name) {
        return exchange("GET", "/collections/" + name, null);
    }

    void createCollection(String name, int dimension, String distance) {
        ObjectNode body = objectMapper.createObjectNode();
        ObjectNode vectors = body.putObject("vectors");
        vectors.put("size", dimension);
        vectors.put("distance", distance);
        exchange("PUT", "/collections/" + name, body);
    }

    void deleteCollection(String name) {
        exchange("DELETE", "/collections/" + name, null);
    }

    long count(String collection, long projectId, String documentId) {
        ObjectNode body = objectMapper.createObjectNode();
        body.set("filter", filter(projectId, documentId));
        body.put("exact", true);
        return exchange("POST", "/collections/" + collection + "/points/count", body)
                .path("result").path("count").asLong(-1);
    }

    List<JsonNode> payloads(String collection, long projectId, String documentId) {
        ObjectNode body = objectMapper.createObjectNode();
        body.set("filter", filter(projectId, documentId));
        body.put("limit", 100);
        body.put("with_payload", true);
        body.put("with_vector", false);
        JsonNode points = exchange(
                "POST", "/collections/" + collection + "/points/scroll", body)
                .path("result").path("points");
        if (!points.isArray()) {
            throw new IllegalStateException("Qdrant test scroll response is malformed");
        }
        java.util.ArrayList<JsonNode> payloads = new java.util.ArrayList<>();
        points.forEach(point -> payloads.add(point.path("payload")));
        return List.copyOf(payloads);
    }

    private ObjectNode filter(long projectId, String documentId) {
        ObjectNode filter = objectMapper.createObjectNode();
        ArrayNode must = filter.putArray("must");
        ObjectNode project = must.addObject();
        project.put("key", "projectId");
        project.putObject("match").put("value", projectId);
        ObjectNode document = must.addObject();
        document.put("key", "documentId");
        document.putObject("match").put("value", documentId);
        return filter;
    }

    private JsonNode exchange(String method, String path, JsonNode body) {
        try {
            HttpRequest.Builder request = HttpRequest.newBuilder(baseUrl.resolve(path))
                    .timeout(Duration.ofSeconds(10))
                    .header("Accept", "application/json");
            if (body == null) {
                request.method(method, HttpRequest.BodyPublishers.noBody());
            } else {
                request.header("Content-Type", "application/json");
                request.method(method, HttpRequest.BodyPublishers.ofString(
                        objectMapper.writeValueAsString(body), StandardCharsets.UTF_8));
            }
            HttpResponse<String> response = httpClient.send(
                    request.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new IllegalStateException(
                        "Qdrant test request failed with HTTP " + response.statusCode());
            }
            return objectMapper.readTree(response.body());
        } catch (IOException exception) {
            throw new IllegalStateException("Qdrant test request failed", exception);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Qdrant test request interrupted", exception);
        }
    }
}
