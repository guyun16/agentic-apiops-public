package com.apiops.rag.vector;

import com.apiops.rag.embedding.EmbeddingModel;
import com.apiops.rag.embedding.EmbeddingVector;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class InMemoryVectorStoreServiceTest {

    private static final EmbeddingModel MODEL = new EmbeddingModel("fake", "test", 2);

    @Test
    void upsertPreservesProjectScopedIdentity() {
        InMemoryVectorStoreService store = new InMemoryVectorStoreService();

        store.upsert(41L, "doc-1", List.of(entry(41L, "doc-1", "chunk-1")));

        VectorEntry stored = store.entries(41L, "doc-1").getFirst();
        assertEquals(41L, stored.projectId());
        assertEquals("doc-1", stored.documentId());
        assertEquals("chunk-1", stored.chunkId());
    }

    @Test
    void deleteByDocumentDoesNotCrossProjectBoundary() {
        InMemoryVectorStoreService store = new InMemoryVectorStoreService();
        store.upsert(41L, "doc-1", List.of(entry(41L, "doc-1", "chunk-a")));
        store.upsert(42L, "doc-1", List.of(entry(42L, "doc-1", "chunk-b")));

        store.deleteByDocument(41L, "doc-1");

        assertEquals(List.of(), store.entries(41L, "doc-1"));
        assertEquals("chunk-b", store.entries(42L, "doc-1").getFirst().chunkId());
    }

    @Test
    void reindexAtomicallyReplacesOldDocumentVectors() {
        InMemoryVectorStoreService store = new InMemoryVectorStoreService();
        store.upsert(41L, "doc-1", List.of(
                entry(41L, "doc-1", "old-1"), entry(41L, "doc-1", "old-2")));

        store.upsert(41L, "doc-1", List.of(entry(41L, "doc-1", "new-1")));

        assertEquals(List.of("new-1"), store.entries(41L, "doc-1").stream()
                .map(VectorEntry::chunkId).toList());
    }

    @Test
    void rejectsEntriesOutsideDeclaredScopeAndSearchesOnlyRequestedProject() {
        InMemoryVectorStoreService store = new InMemoryVectorStoreService();

        assertThrows(VectorStoreException.class,
                () -> store.upsert(41L, "doc-1",
                        List.of(entry(42L, "doc-1", "chunk-1"))));
        store.upsert(41L, "doc-1", List.of(entry(41L, "doc-1", "chunk-a")));
        store.upsert(42L, "doc-2", List.of(entry(42L, "doc-2", "chunk-b")));
        assertEquals(List.of("chunk-a"), store.search(41L, vector(), 3).stream()
                .map(VectorSearchMatch::chunkId).toList());
    }

    private VectorEntry entry(long projectId, String documentId, String chunkId) {
        return new VectorEntry(
                projectId, documentId, chunkId, "a".repeat(64), vector(), Map.of());
    }

    private EmbeddingVector vector() {
        return new EmbeddingVector(MODEL, List.of(1.0F, 2.0F));
    }
}
