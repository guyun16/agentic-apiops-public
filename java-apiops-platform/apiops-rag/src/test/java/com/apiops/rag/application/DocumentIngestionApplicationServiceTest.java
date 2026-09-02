package com.apiops.rag.application;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.rag.domain.Document;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;
import com.apiops.rag.embedding.EmbeddingException;
import com.apiops.rag.embedding.EmbeddingModel;
import com.apiops.rag.embedding.EmbeddingService;
import com.apiops.rag.embedding.EmbeddingVector;
import com.apiops.rag.parser.DocumentParseError;
import com.apiops.rag.parser.DocumentParseException;
import com.apiops.rag.parser.DocumentParser;
import com.apiops.rag.parser.PlainTextDocumentParser;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.splitter.FixedSizeTextSplitter;
import com.apiops.rag.splitter.TextSplitter;
import com.apiops.rag.splitter.TextSplitterConfig;
import com.apiops.rag.vector.InMemoryVectorStoreService;
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.VectorStoreException;
import com.apiops.rag.vector.VectorStoreService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class DocumentIngestionApplicationServiceTest {

    private static final long PROJECT_ID = 41L;
    private static final long USER_ID = 7L;
    private static final EmbeddingModel MODEL =
            new EmbeddingModel("fake", "deterministic-test", 2);
    private static final Clock CLOCK = Clock.fixed(
            Instant.parse("2026-08-12T12:00:00Z"), ZoneOffset.UTC);

    private InMemoryDocumentRepository repository;
    private InMemoryVectorStoreService vectorStore;

    @BeforeEach
    void authenticate() {
        repository = new InMemoryDocumentRepository();
        vectorStore = new InMemoryVectorStoreService();
        ApiOpsPrincipal principal = new ApiOpsPrincipal(
                USER_ID, "ingestion-user", "not-used", true, List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities()));
    }

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void successfulIngestionPersistsFormalKnowledgeThenIndexesIt() {
        DocumentIngestionResult result = service(
                parser(), splitter(), embedding(false), vectorStore, ProjectRole.EDITOR)
                .ingest(PROJECT_ID, input("abcdefghij"));

        Document stored = repository.findById(PROJECT_ID, result.documentId()).orElseThrow();
        List<DocumentChunk> chunks = repository.findChunks(PROJECT_ID, result.documentId());
        assertEquals(DocumentStatus.INDEXED, result.status());
        assertEquals(DocumentStatus.INDEXED, stored.status());
        assertEquals(List.of(0, 1, 2), chunks.stream().map(DocumentChunk::ordinal).toList());
        assertEquals(chunks.size(), vectorStore.entries(PROJECT_ID, result.documentId()).size());
        assertEquals(PROJECT_ID, chunks.getFirst().projectId());
    }

    @Test
    void parserFailureCreatesNoFormalKnowledgeOrVectors() {
        DocumentParser failing = (fileName, mediaType, content) -> {
            throw new DocumentParseException(
                    DocumentParseError.INVALID_ENCODING, "parse failed");
        };

        DocumentIngestionException failure = assertThrows(
                DocumentIngestionException.class,
                () -> service(failing, splitter(), embedding(false), vectorStore,
                        ProjectRole.EDITOR).ingest(PROJECT_ID, input("content")));

        assertEquals(DocumentIngestionStage.PARSE, failure.stage());
        assertEquals(Optional.empty(), repository.findBySourceKey(PROJECT_ID, "runbook/orders"));
    }

    @Test
    void embeddingFailureLeavesFormalKnowledgeAsIndexFailedAndNoVectors() {
        DocumentIngestionException failure = assertThrows(
                DocumentIngestionException.class,
                () -> service(parser(), splitter(), embedding(true), vectorStore,
                        ProjectRole.EDITOR).ingest(PROJECT_ID, input("abcdefghij")));

        Document document = repository.findBySourceKey(
                PROJECT_ID, "runbook/orders").orElseThrow();
        assertEquals(DocumentIngestionStage.EMBEDDING, failure.stage());
        assertEquals(DocumentStatus.INDEX_FAILED, document.status());
        assertEquals(List.of(), vectorStore.entries(PROJECT_ID, document.documentId()));
    }

    @Test
    void missingEmbeddingCompatibilityMetadataIsAnEmbeddingFailure() {
        EmbeddingService invalid = new EmbeddingService() {
            @Override
            public EmbeddingModel model() {
                return null;
            }

            @Override
            public List<EmbeddingVector> embed(List<String> texts) {
                throw new AssertionError("embed must not run without model metadata");
            }
        };

        DocumentIngestionException failure = assertThrows(
                DocumentIngestionException.class,
                () -> service(parser(), splitter(), invalid, vectorStore,
                        ProjectRole.EDITOR).ingest(PROJECT_ID, input("abcdefghij")));

        Document document = repository.findBySourceKey(
                PROJECT_ID, "runbook/orders").orElseThrow();
        assertEquals(DocumentIngestionStage.EMBEDDING, failure.stage());
        assertEquals(DocumentStatus.INDEX_FAILED, document.status());
        assertEquals(List.of(), vectorStore.entries(PROJECT_ID, document.documentId()));
    }

    @Test
    void vectorUpsertFailureCannotProduceIndexedSuccess() {
        VectorStoreService failing = new DelegatingVectorStore(vectorStore) {
            @Override
            public void upsert(long projectId, String documentId, List<VectorEntry> entries) {
                throw new VectorStoreException("fake vector store failed");
            }
        };

        DocumentIngestionException failure = assertThrows(
                DocumentIngestionException.class,
                () -> service(parser(), splitter(), embedding(false), failing,
                        ProjectRole.EDITOR).ingest(PROJECT_ID, input("abcdefghij")));

        Document document = repository.findBySourceKey(
                PROJECT_ID, "runbook/orders").orElseThrow();
        assertEquals(DocumentIngestionStage.VECTOR_INDEX, failure.stage());
        assertEquals(DocumentStatus.INDEX_FAILED, document.status());
        assertNotEquals(DocumentStatus.INDEXED, document.status());
        assertEquals(List.of(), vectorStore.entries(PROJECT_ID, document.documentId()));
    }

    @Test
    void indexedStatusPersistenceFailureRollsBackPublishedVectors() {
        repository.failNextStatusUpdate(DocumentStatus.INDEXED);

        DocumentIngestionException failure = assertThrows(
                DocumentIngestionException.class,
                () -> service(parser(), splitter(), embedding(false), vectorStore,
                        ProjectRole.EDITOR).ingest(PROJECT_ID, input("abcdefghij")));

        Document document = repository.findBySourceKey(
                PROJECT_ID, "runbook/orders").orElseThrow();
        assertEquals(DocumentIngestionStage.PERSISTENCE, failure.stage());
        assertEquals(DocumentStatus.INDEX_FAILED, document.status());
        assertIndexFactMatchesVectors(document.documentId());
    }

    @Test
    void rollbackDeleteFailureRestoresIndexedFactForPublishedVectors() {
        repository.failNextStatusUpdate(DocumentStatus.INDEXED);
        VectorStoreService rollbackDeleteFails = new DelegatingVectorStore(vectorStore) {
            private int deleteCalls;

            @Override
            public void deleteByDocument(long projectId, String documentId) {
                deleteCalls++;
                if (deleteCalls == 2) {
                    throw new VectorStoreException("fake rollback delete failure");
                }
                super.deleteByDocument(projectId, documentId);
            }
        };

        DocumentIngestionException failure = assertThrows(
                DocumentIngestionException.class,
                () -> service(parser(), splitter(), embedding(false), rollbackDeleteFails,
                        ProjectRole.EDITOR).ingest(PROJECT_ID, input("abcdefghij")));

        Document document = repository.findBySourceKey(
                PROJECT_ID, "runbook/orders").orElseThrow();
        assertEquals(DocumentIngestionStage.PERSISTENCE, failure.stage());
        assertEquals(DocumentStatus.INDEXED, document.status());
        assertEquals(1, failure.getCause().getSuppressed().length);
        assertIndexFactMatchesVectors(document.documentId());
    }

    @Test
    void deniedProjectAccessStopsBeforeParserAndPersistence() {
        CountingParser parser = new CountingParser();

        assertThrows(AccessDeniedException.class,
                () -> service(parser, splitter(), embedding(false), vectorStore,
                        ProjectRole.VIEWER).ingest(PROJECT_ID, input("content")));

        assertEquals(0, parser.calls);
        assertEquals(Optional.empty(), repository.findBySourceKey(PROJECT_ID, "runbook/orders"));
    }

    @Test
    void reindexReusesDocumentIdentityAndLeavesNoStaleChunksOrVectors() {
        DocumentIngestionApplicationService service = service(
                parser(), splitter(), embedding(false), vectorStore, ProjectRole.EDITOR);
        DocumentIngestionResult first = service.ingest(PROJECT_ID, input("abcdefghij"));
        List<String> oldChunkIds = vectorStore.entries(PROJECT_ID, first.documentId()).stream()
                .map(VectorEntry::chunkId).toList();

        DocumentIngestionResult second = service.ingest(PROJECT_ID, input("xy"));

        assertEquals(first.documentId(), second.documentId());
        assertEquals(1, repository.findChunks(PROJECT_ID, second.documentId()).size());
        List<String> current = vectorStore.entries(PROJECT_ID, second.documentId()).stream()
                .map(VectorEntry::chunkId).toList();
        assertEquals(1, current.size());
        oldChunkIds.forEach(old -> assertNotEquals(old, current.getFirst()));
    }

    @Test
    void deleteRemovesChunksAndVectorsAndMarksDocumentDeleted() {
        DocumentIngestionApplicationService service = service(
                parser(), splitter(), embedding(false), vectorStore, ProjectRole.OWNER);
        DocumentIngestionResult indexed = service.ingest(PROJECT_ID, input("abcdefghij"));

        service.delete(PROJECT_ID, indexed.documentId());

        assertEquals(DocumentStatus.DELETED,
                repository.findById(PROJECT_ID, indexed.documentId()).orElseThrow().status());
        assertEquals(List.of(), repository.findChunks(PROJECT_ID, indexed.documentId()));
        assertEquals(List.of(), vectorStore.entries(PROJECT_ID, indexed.documentId()));
    }

    @Test
    void vectorDeleteFailureRetainsIndexedFactAndExistingVectors() {
        DocumentIngestionApplicationService indexingService = service(
                parser(), splitter(), embedding(false), vectorStore, ProjectRole.OWNER);
        DocumentIngestionResult indexed = indexingService.ingest(
                PROJECT_ID, input("abcdefghij"));
        VectorStoreService failing = new DelegatingVectorStore(vectorStore) {
            @Override
            public void deleteByDocument(long projectId, String documentId) {
                throw new VectorStoreException("fake delete failure");
            }
        };

        DocumentIngestionException failure = assertThrows(
                DocumentIngestionException.class,
                () -> service(parser(), splitter(), embedding(false), failing,
                        ProjectRole.OWNER).delete(PROJECT_ID, indexed.documentId()));

        assertEquals(DocumentIngestionStage.VECTOR_INDEX, failure.stage());
        assertEquals(DocumentStatus.INDEXED,
                repository.findById(PROJECT_ID, indexed.documentId()).orElseThrow().status());
        assertIndexFactMatchesVectors(indexed.documentId());
    }

    @Test
    void formalDeletePersistenceFailureMarksIndexFailedAfterVectorDeletion() {
        DocumentIngestionApplicationService service = service(
                parser(), splitter(), embedding(false), vectorStore, ProjectRole.OWNER);
        DocumentIngestionResult indexed = service.ingest(PROJECT_ID, input("abcdefghij"));
        repository.failNextMarkDeleted();

        DocumentIngestionException failure = assertThrows(
                DocumentIngestionException.class,
                () -> service.delete(PROJECT_ID, indexed.documentId()));

        assertEquals(DocumentIngestionStage.PERSISTENCE, failure.stage());
        assertEquals(DocumentStatus.INDEX_FAILED,
                repository.findById(PROJECT_ID, indexed.documentId()).orElseThrow().status());
        assertEquals(3, repository.findChunks(PROJECT_ID, indexed.documentId()).size());
        assertIndexFactMatchesVectors(indexed.documentId());
    }

    private DocumentIngestionApplicationService service(
            DocumentParser parser,
            TextSplitter splitter,
            EmbeddingService embedding,
            VectorStoreService vectorStore,
            ProjectRole role
    ) {
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> userId == USER_ID && projectId == PROJECT_ID
                        ? Optional.of(role) : Optional.empty());
        return new DocumentIngestionApplicationService(
                authorization, parser, splitter, repository,
                embedding, vectorStore, CLOCK);
    }

    private DocumentParser parser() {
        return new PlainTextDocumentParser();
    }

    private TextSplitter splitter() {
        return new FixedSizeTextSplitter(new TextSplitterConfig(4, 1));
    }

    private EmbeddingService embedding(boolean fail) {
        return new EmbeddingService() {
            @Override
            public EmbeddingModel model() {
                return MODEL;
            }

            @Override
            public List<EmbeddingVector> embed(List<String> texts) {
                if (fail) {
                    throw new EmbeddingException("fake embedding failure");
                }
                return texts.stream()
                        .map(text -> new EmbeddingVector(
                                MODEL, List.of((float) text.length(), 1.0F)))
                        .toList();
            }
        };
    }

    private DocumentIngestionInput input(String content) {
        return new DocumentIngestionInput(
                "runbook/orders", "RUNBOOK", "Orders runbook",
                "orders.md", "text/markdown", content.getBytes(StandardCharsets.UTF_8));
    }

    private void assertIndexFactMatchesVectors(String documentId) {
        boolean formallyIndexed = repository.findById(PROJECT_ID, documentId)
                .orElseThrow().status() == DocumentStatus.INDEXED;
        boolean hasVectors = !vectorStore.entries(PROJECT_ID, documentId).isEmpty();
        assertEquals(formallyIndexed, hasVectors,
                "INDEXED status and retrievable vector presence must agree");
    }

    private static final class CountingParser implements DocumentParser {
        private int calls;

        @Override
        public String parse(String fileName, String mediaType, byte[] content) {
            calls++;
            return "content";
        }
    }

    private static final class InMemoryDocumentRepository implements DocumentRepository {
        private final Map<Key, Document> documents = new LinkedHashMap<>();
        private final Map<Key, List<DocumentChunk>> chunks = new LinkedHashMap<>();
        private DocumentStatus statusUpdateToFail;
        private boolean failMarkDeleted;

        private void failNextStatusUpdate(DocumentStatus status) {
            statusUpdateToFail = status;
        }

        private void failNextMarkDeleted() {
            failMarkDeleted = true;
        }

        @Override
        public Optional<Document> findBySourceKey(long projectId, String sourceKey) {
            return documents.values().stream()
                    .filter(value -> value.projectId() == projectId)
                    .filter(value -> value.sourceKey().equals(sourceKey))
                    .findFirst();
        }

        @Override
        public Optional<Document> findById(long projectId, String documentId) {
            return Optional.ofNullable(documents.get(new Key(projectId, documentId)));
        }

        @Override
        public List<DocumentChunk> findChunks(long projectId, String documentId) {
            return chunks.getOrDefault(new Key(projectId, documentId), List.of());
        }

        @Override
        public void saveKnowledge(Document document, List<DocumentChunk> values) {
            Key key = new Key(document.projectId(), document.documentId());
            documents.put(key, document);
            chunks.put(key, List.copyOf(values));
        }

        @Override
        public void updateStatus(long projectId, String documentId, DocumentStatus status) {
            if (status == statusUpdateToFail) {
                statusUpdateToFail = null;
                throw new IllegalStateException("fake status persistence failure");
            }
            Key key = new Key(projectId, documentId);
            documents.compute(key, (ignored, existing) -> existing.withStatus(status));
        }

        @Override
        public void markDeleted(long projectId, String documentId) {
            if (failMarkDeleted) {
                failMarkDeleted = false;
                throw new IllegalStateException("fake delete persistence failure");
            }
            Key key = new Key(projectId, documentId);
            chunks.remove(key);
            documents.compute(key,
                    (ignored, existing) -> existing.withStatus(DocumentStatus.DELETED));
        }

        private record Key(long projectId, String documentId) {
        }
    }

    private static class DelegatingVectorStore implements VectorStoreService {
        private final VectorStoreService delegate;

        private DelegatingVectorStore(VectorStoreService delegate) {
            this.delegate = delegate;
        }

        @Override
        public void upsert(long projectId, String documentId, List<VectorEntry> entries) {
            delegate.upsert(projectId, documentId, entries);
        }

        @Override
        public List<com.apiops.rag.vector.VectorSearchMatch> search(
                long projectId, EmbeddingVector queryVector, int topK) {
            return delegate.search(projectId, queryVector, topK);
        }

        @Override
        public void deleteByDocument(long projectId, String documentId) {
            delegate.deleteByDocument(projectId, documentId);
        }
    }
}
