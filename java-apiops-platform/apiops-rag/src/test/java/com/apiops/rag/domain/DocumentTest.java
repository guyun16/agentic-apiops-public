package com.apiops.rag.domain;

import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;

class DocumentTest {

    @Test
    void retainsProjectScopeAndSourceIdentity() {
        Instant createdAt = Instant.parse("2026-08-12T08:00:00Z");

        Document document = new Document(
                "doc_runbook_orders",
                41L,
                "runbooks/orders.md",
                "RUNBOOK",
                "Orders runbook",
                "orders.md",
                "text/markdown",
                "a".repeat(64),
                DocumentStatus.STORED,
                7L,
                createdAt);

        assertEquals(41L, document.projectId());
        assertEquals("runbooks/orders.md", document.sourceKey());
        assertEquals(createdAt, document.createdAt());
    }
}
