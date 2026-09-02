package com.apiops.rag.vector.qdrant;

import com.apiops.rag.embedding.EmbeddingVector;
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.VectorStoreException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class QdrantVectorStoreServiceIntegrationTest {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static String baseUrl;
    private static String collection;
    private static String incompatibleCollection;
    private static QdrantTestClient client;
    private static QdrantVectorStoreService service;

    @BeforeAll
    static void initialize() {
        baseUrl = System.getenv("APIOPS_RAG_QDRANT_BASE_URL");
        if (baseUrl == null || baseUrl.isBlank()) {
            return;
        }
        String suffix = UUID.randomUUID().toString().replace("-", "");
        collection = "apiops_rag_it_" + suffix;
        incompatibleCollection = "apiops_rag_bad_it_" + suffix;
        client = new QdrantTestClient(baseUrl, OBJECT_MAPPER);
        service = new QdrantVectorStoreService(
                baseUrl, collection, Duration.ofSeconds(10), "", OBJECT_MAPPER);
    }

    @BeforeEach
    void requireQdrantConfiguration() {
        assumeTrue(service != null,
                "Set APIOPS_RAG_QDRANT_BASE_URL to run Qdrant integration tests");
    }

    @AfterAll
    static void cleanup() {
        if (client == null) {
            return;
        }
        deleteIfPresent(collection);
        deleteIfPresent(incompatibleCollection);
    }

    @Test
    void bootstrapsIdempotentlyAndRejectsIncompatibleCollectionWithoutDeletingIt() {
        assertEquals("1.19.0", client.root().path("version").asText());
        service.initialize();
        service.initialize();

        JsonNode current = client.collection(collection).path("result");
        assertEquals(1_024, current.path("config").path("params")
                .path("vectors").path("size").asInt());
        assertEquals("Cosine", current.path("config").path("params")
                .path("vectors").path("distance").asText());
        assertEquals("integer", current.path("payload_schema")
                .path("projectId").path("data_type").asText());
        assertEquals("keyword", current.path("payload_schema")
                .path("documentId").path("data_type").asText());

        client.createCollection(incompatibleCollection, 3, "Dot");
        QdrantVectorStoreService incompatible = new QdrantVectorStoreService(
                baseUrl, incompatibleCollection, Duration.ofSeconds(10), "", OBJECT_MAPPER);
        assertThrows(VectorStoreException.class, incompatible::initialize);
        assertEquals(3, client.collection(incompatibleCollection).path("result")
                .path("config").path("params").path("vectors").path("size").asInt());
    }

    @Test
    void upsertDeleteAndReindexRemainProjectDocumentScoped() {
        service.initialize();
        long projectA = 91_001L;
        long projectB = 91_002L;
        String document1 = "document-1";
        String document2 = "document-2";

        service.upsert(projectA, document1,
                List.of(entry(projectA, document1, "old-1"),
                        entry(projectA, document1, "old-2")));
        service.upsert(projectA, document2,
                List.of(entry(projectA, document2, "keep-project-a")));
        service.upsert(projectB, document1,
                List.of(entry(projectB, document1, "keep-project-b")));

        assertEquals(2, client.count(collection, projectA, document1));
        assertEquals(1, client.count(collection, projectA, document2));
        assertEquals(1, client.count(collection, projectB, document1));
        List<com.apiops.rag.vector.VectorSearchMatch> projectAMatches = service.search(
                projectA, entry(projectA, document1, "query").embedding(), 10);
        assertEquals(3, projectAMatches.size());
        assertTrue(projectAMatches.stream().allMatch(
                match -> match.projectId() == projectA));
        assertTrue(projectAMatches.stream().noneMatch(
                match -> match.chunkId().equals("keep-project-b")));
        assertTrue(projectAMatches.stream().allMatch(
                match -> Double.isFinite(match.relevanceScore())));
        JsonNode payload = client.payloads(collection, projectA, document1).getFirst();
        assertEquals(projectA, payload.path("projectId").asLong());
        assertEquals(document1, payload.path("documentId").asText());
        assertEquals("zhipu", payload.path("embeddingProvider").asText());
        assertEquals("embedding-3", payload.path("embeddingModel").asText());
        assertEquals(1_024, payload.path("embeddingDimension").asInt());
        assertFalse(payload.has("content"));

        service.deleteByDocument(projectA, document1);
        assertEquals(0, client.count(collection, projectA, document1));
        assertEquals(1, client.count(collection, projectA, document2));
        assertEquals(1, client.count(collection, projectB, document1));

        service.upsert(projectA, document1,
                List.of(entry(projectA, document1, "new-1")));
        List<JsonNode> replacement = client.payloads(collection, projectA, document1);
        assertEquals(1, replacement.size());
        assertEquals("new-1", replacement.getFirst().path("chunkId").asText());
        assertTrue(replacement.stream().noneMatch(value ->
                value.path("chunkId").asText().startsWith("old-")));
    }

    private static VectorEntry entry(long projectId, String documentId, String chunkId) {
        EmbeddingVector embedding = new EmbeddingVector(
                QdrantVectorStoreService.INDEX_MODEL,
                new ArrayList<>(Collections.nCopies(1_024, 0.125F)));
        return new VectorEntry(projectId, documentId, chunkId,
                "a".repeat(64), embedding, Map.of());
    }

    private static void deleteIfPresent(String name) {
        if (name == null) {
            return;
        }
        try {
            client.deleteCollection(name);
        } catch (RuntimeException ignored) {
            // Best-effort cleanup after a real infrastructure test.
        }
    }
}
