package com.apiops.rag.domain;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class EvidenceCitationTest {

    @Test
    void locatesProjectDocumentChunkAndOriginalSource() {
        EvidenceCitation citation = new EvidenceCitation(
                "RUNBOOK",
                "runbooks/orders.md",
                41L,
                "doc_runbook_orders",
                "chunk_orders_003",
                0.92,
                "Orders runbook",
                "Retries",
                "Retry order creation only after checking the idempotency key.");

        assertEquals(41L, citation.projectId());
        assertEquals("doc_runbook_orders", citation.documentId());
        assertEquals("chunk_orders_003", citation.chunkId());
        assertEquals("runbooks/orders.md", citation.sourceId());
        assertEquals(0.92, citation.score());
    }
}
