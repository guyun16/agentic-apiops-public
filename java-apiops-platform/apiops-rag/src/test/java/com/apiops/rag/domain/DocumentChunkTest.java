package com.apiops.rag.domain;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DocumentChunkTest {

    @Test
    void retainsOwningDocumentProjectAndStableOrdinal() {
        DocumentChunk chunk = new DocumentChunk(
                "chunk_orders_003",
                "doc_runbook_orders",
                41L,
                3,
                "Retry order creation only after checking the idempotency key.",
                "b".repeat(64),
                Map.of("heading", "Retries"));

        assertEquals("doc_runbook_orders", chunk.documentId());
        assertEquals(41L, chunk.projectId());
        assertEquals(3, chunk.ordinal());
    }

    @Test
    void textualRepresentationDoesNotExposeFullChunkContent() {
        String sensitiveContent = "internal recovery credential rotation procedure";
        DocumentChunk chunk = new DocumentChunk(
                "chunk_orders_004", "doc_runbook_orders", 41L, 4,
                sensitiveContent, "c".repeat(64), Map.of());

        assertFalse(chunk.toString().contains(sensitiveContent));
        assertTrue(chunk.toString().contains("contentLength=" + sensitiveContent.length()));
    }
}
