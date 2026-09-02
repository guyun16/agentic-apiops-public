package com.apiops.rag.embedding.zhipu;

import com.apiops.rag.embedding.EmbeddingVector;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.time.Duration;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class ZhipuEmbeddingServiceIntegrationTest {

    @Test
    void callsRealEmbedding3WhenApiKeyIsProvided() {
        String apiKey = System.getenv("ZHIPU_API_KEY");
        assumeTrue(apiKey != null && !apiKey.isBlank(),
                "ZHIPU_API_KEY is absent; skipping real Zhipu integration test");

        ZhipuEmbeddingService service = new ZhipuEmbeddingService(
                apiKey, Duration.ofSeconds(30), new ObjectMapper());

        EmbeddingVector vector = service.embed("Agentic APIOps diagnostic evidence");

        assertEquals("zhipu", vector.model().provider());
        assertEquals("embedding-3", vector.model().model());
        assertEquals(1_024, vector.model().dimension());
        assertEquals(1_024, vector.values().size());
    }
}
