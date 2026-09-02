package com.apiops.rag.application;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.rag.domain.Document;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;
import com.apiops.rag.embedding.EmbeddingException;
import com.apiops.rag.embedding.EmbeddingModel;
import com.apiops.rag.embedding.EmbeddingService;
import com.apiops.rag.embedding.EmbeddingVector;
import com.apiops.rag.parser.DocumentParseException;
import com.apiops.rag.parser.DocumentParser;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.splitter.TextSplitter;
import com.apiops.rag.vector.VectorEntry;
import com.apiops.rag.vector.VectorStoreException;
import com.apiops.rag.vector.VectorStoreService;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** Synchronous preparation of formal knowledge and its rebuildable vector index. */
public class DocumentIngestionApplicationService {

    private final ProjectAuthorizationService authorizationService;
    private final DocumentParser parser;
    private final TextSplitter splitter;
    private final DocumentRepository repository;
    private final EmbeddingService embeddingService;
    private final VectorStoreService vectorStore;
    private final Clock clock;

    public DocumentIngestionApplicationService(
            ProjectAuthorizationService authorizationService,
            DocumentParser parser,
            TextSplitter splitter,
            DocumentRepository repository,
            EmbeddingService embeddingService,
            VectorStoreService vectorStore,
            Clock clock
    ) {
        this.authorizationService = Objects.requireNonNull(
                authorizationService, "authorizationService must not be null");
        this.parser = Objects.requireNonNull(parser, "parser must not be null");
        this.splitter = Objects.requireNonNull(splitter, "splitter must not be null");
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.embeddingService = Objects.requireNonNull(
                embeddingService, "embeddingService must not be null");
        this.vectorStore = Objects.requireNonNull(vectorStore, "vectorStore must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
    }

    @PreAuthorize("isAuthenticated()")
    public DocumentIngestionResult ingest(
            long projectId, DocumentIngestionInput input) {
        long userId = currentUserId();
        authorizationService.requireProjectEditable(userId, projectId);
        validate(input);

        byte[] rawContent = input.content();
        String contentHash = sha256(rawContent);
        String normalizedText;
        try {
            normalizedText = parser.parse(input.fileName(), input.mediaType(), rawContent);
        } catch (DocumentParseException failure) {
            throw new DocumentIngestionException(
                    DocumentIngestionStage.PARSE, "Document parsing failed", failure);
        }

        List<String> texts = splitter.split(normalizedText);
        if (texts.isEmpty()) {
            throw new DocumentIngestionException(
                    DocumentIngestionStage.PARSE, "Document produced no chunks");
        }

        Document previous = repository.findBySourceKey(projectId, input.sourceKey()).orElse(null);
        String documentId = previous == null ? businessId("doc") : previous.documentId();
        Instant createdAt = previous == null ? clock.instant() : previous.createdAt();
        long createdBy = previous == null ? userId : previous.createdBy();
        Document stored = new Document(
                documentId, projectId, input.sourceKey(), input.sourceType(), input.title(),
                input.fileName(), input.mediaType(), contentHash, DocumentStatus.STORED,
                createdBy, createdAt);
        List<DocumentChunk> chunks = chunks(stored, texts);

        // Removing derived data first favors safe absence over stale evidence during re-index.
        try {
            vectorStore.deleteByDocument(projectId, documentId);
        } catch (RuntimeException failure) {
            // The delete port is atomic: on failure the old index remains authoritative.
            throw new DocumentIngestionException(
                    DocumentIngestionStage.VECTOR_INDEX,
                    "Unable to remove the previous document index", failure);
        }
        try {
            repository.saveKnowledge(stored, chunks);
        } catch (RuntimeException failure) {
            markIndexFailedAfterConfirmedVectorAbsence(projectId, documentId, failure);
            throw new DocumentIngestionException(
                    DocumentIngestionStage.PERSISTENCE,
                    "Unable to replace formal document knowledge", failure);
        }

        List<EmbeddingVector> embeddings;
        EmbeddingModel embeddingModel;
        try {
            embeddingModel = Objects.requireNonNull(
                    embeddingService.model(), "embedding model must not be null");
            embeddings = List.copyOf(embeddingService.embed(texts));
            validateEmbeddings(texts.size(), embeddingModel, embeddings);
        } catch (RuntimeException failure) {
            markIndexFailedAfterConfirmedVectorAbsence(projectId, documentId, failure);
            throw new DocumentIngestionException(
                    DocumentIngestionStage.EMBEDDING, "Document embedding failed", failure);
        }

        try {
            vectorStore.upsert(projectId, documentId, vectorEntries(chunks, embeddings));
        } catch (RuntimeException failure) {
            // Atomic upsert failure cannot publish a partial replacement.
            markIndexFailedAfterConfirmedVectorAbsence(projectId, documentId, failure);
            throw new DocumentIngestionException(
                    DocumentIngestionStage.VECTOR_INDEX,
                    "Document vector indexing failed", failure);
        }
        try {
            repository.updateStatus(projectId, documentId, DocumentStatus.INDEXED);
        } catch (RuntimeException failure) {
            rollbackPublishedIndex(projectId, documentId, failure);
            throw new DocumentIngestionException(
                    DocumentIngestionStage.PERSISTENCE,
                    "Vector index was rolled back because INDEXED could not be persisted",
                    failure);
        }

        return new DocumentIngestionResult(
                projectId, documentId, contentHash, chunks.size(),
                DocumentStatus.INDEXED, embeddingModel);
    }

    @PreAuthorize("isAuthenticated()")
    public void delete(long projectId, String documentId) {
        long userId = currentUserId();
        authorizationService.requireProjectEditable(userId, projectId);
        requireText(documentId, "documentId");

        // Derived data disappears first; a persistence failure can leave knowledge but not stale vectors.
        try {
            vectorStore.deleteByDocument(projectId, documentId);
        } catch (RuntimeException failure) {
            // Do not downgrade the formal status while the old vectors may still be live.
            throw new DocumentIngestionException(
                    DocumentIngestionStage.VECTOR_INDEX,
                    "Unable to delete document vectors", failure);
        }
        try {
            repository.markDeleted(projectId, documentId);
        } catch (RuntimeException failure) {
            markIndexFailedAfterConfirmedVectorAbsence(projectId, documentId, failure);
            throw new DocumentIngestionException(
                    DocumentIngestionStage.PERSISTENCE,
                    "Unable to delete formal document knowledge", failure);
        }
    }

    private void rollbackPublishedIndex(
            long projectId, String documentId, RuntimeException cause) {
        try {
            vectorStore.deleteByDocument(projectId, documentId);
        } catch (RuntimeException cleanupFailure) {
            cause.addSuppressed(cleanupFailure);
            // Atomic delete failure means the published vectors remain. A status retry keeps
            // the two stores aligned when the initial persistence failure was transient.
            try {
                repository.updateStatus(projectId, documentId, DocumentStatus.INDEXED);
            } catch (RuntimeException retryFailure) {
                cause.addSuppressed(retryFailure);
            }
            return;
        }
        markIndexFailedAfterConfirmedVectorAbsence(projectId, documentId, cause);
    }

    private void markIndexFailedAfterConfirmedVectorAbsence(
            long projectId, String documentId, RuntimeException cause) {
        try {
            repository.updateStatus(projectId, documentId, DocumentStatus.INDEX_FAILED);
        } catch (RuntimeException statusFailure) {
            cause.addSuppressed(statusFailure);
        }
    }

    private List<DocumentChunk> chunks(Document document, List<String> texts) {
        List<DocumentChunk> chunks = new ArrayList<>(texts.size());
        for (int ordinal = 0; ordinal < texts.size(); ordinal++) {
            String text = texts.get(ordinal);
            String hash = sha256(text.getBytes(StandardCharsets.UTF_8));
            String chunkId = document.documentId() + "_" + ordinal + "_" + hash.substring(0, 16);
            chunks.add(new DocumentChunk(
                    chunkId, document.documentId(), document.projectId(), ordinal,
                    text, hash, Map.of("sourceKey", document.sourceKey())));
        }
        return List.copyOf(chunks);
    }

    private List<VectorEntry> vectorEntries(
            List<DocumentChunk> chunks, List<EmbeddingVector> embeddings) {
        List<VectorEntry> entries = new ArrayList<>(chunks.size());
        for (int index = 0; index < chunks.size(); index++) {
            DocumentChunk chunk = chunks.get(index);
            entries.add(new VectorEntry(
                    chunk.projectId(), chunk.documentId(), chunk.chunkId(),
                    chunk.contentHash(), embeddings.get(index), chunk.metadata()));
        }
        return List.copyOf(entries);
    }

    private void validateEmbeddings(
            int expectedCount,
            EmbeddingModel expectedModel,
            List<EmbeddingVector> embeddings
    ) {
        if (embeddings.size() != expectedCount) {
            throw new EmbeddingException("Embedding result count does not match chunk count");
        }
        embeddings.forEach(value -> {
            if (!value.model().equals(expectedModel)) {
                throw new EmbeddingException("Embedding model compatibility changed within batch");
            }
        });
    }

    private void validate(DocumentIngestionInput input) {
        if (input == null) {
            throw invalid("input must not be null");
        }
        requireText(input.sourceKey(), "sourceKey");
        requireText(input.sourceType(), "sourceType");
        requireText(input.title(), "title");
        requireText(input.fileName(), "fileName");
        requireText(input.mediaType(), "mediaType");
        if (input.content() == null || input.content().length == 0) {
            throw invalid("content must not be empty");
        }
    }

    private void requireText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw invalid(name + " must not be blank");
        }
    }

    private DocumentIngestionException invalid(String message) {
        return new DocumentIngestionException(DocumentIngestionStage.VALIDATION, message);
    }

    private String sha256(byte[] content) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(content));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private String businessId(String prefix) {
        return prefix + "_" + UUID.randomUUID().toString().replace("-", "");
    }

    private long currentUserId() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null
                || !authentication.isAuthenticated()
                || !(authentication.getPrincipal() instanceof ApiOpsPrincipal principal)) {
            throw new AccessDeniedException("Authenticated ApiOpsPrincipal required");
        }
        return principal.getUserId();
    }
}
