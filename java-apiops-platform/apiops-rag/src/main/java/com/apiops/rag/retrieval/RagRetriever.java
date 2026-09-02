package com.apiops.rag.retrieval;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.rag.domain.Document;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;
import com.apiops.rag.domain.EvidenceCitation;
import com.apiops.rag.embedding.EmbeddingService;
import com.apiops.rag.embedding.EmbeddingVector;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.repository.RagQueryRecordRepository;
import com.apiops.rag.vector.VectorSearchMatch;
import com.apiops.rag.vector.VectorStoreService;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** Orchestrates deterministic, project-scoped evidence retrieval. */
public class RagRetriever {

    private static final Comparator<VectorSearchMatch> MATCH_ORDER = Comparator
            .comparingDouble(VectorSearchMatch::relevanceScore).reversed()
            .thenComparing(VectorSearchMatch::documentId)
            .thenComparing(VectorSearchMatch::chunkId);

    private final ProjectAuthorizationService authorizationService;
    private final EmbeddingService embeddingService;
    private final VectorStoreService vectorStore;
    private final DocumentRepository documentRepository;
    private final RagQueryRecordRepository queryRecordRepository;
    private final Clock clock;
    private final Double minRelevanceScore;

    public RagRetriever(
            ProjectAuthorizationService authorizationService,
            EmbeddingService embeddingService,
            VectorStoreService vectorStore,
            DocumentRepository documentRepository,
            RagQueryRecordRepository queryRecordRepository,
            Clock clock
    ) {
        this(authorizationService, embeddingService, vectorStore, documentRepository,
                queryRecordRepository, clock, null);
    }

    public RagRetriever(
            ProjectAuthorizationService authorizationService,
            EmbeddingService embeddingService,
            VectorStoreService vectorStore,
            DocumentRepository documentRepository,
            RagQueryRecordRepository queryRecordRepository,
            Clock clock,
            Double minRelevanceScore
    ) {
        this.authorizationService = Objects.requireNonNull(
                authorizationService, "authorizationService must not be null");
        this.embeddingService = Objects.requireNonNull(
                embeddingService, "embeddingService must not be null");
        this.vectorStore = Objects.requireNonNull(vectorStore, "vectorStore must not be null");
        this.documentRepository = Objects.requireNonNull(
                documentRepository, "documentRepository must not be null");
        this.queryRecordRepository = Objects.requireNonNull(
                queryRecordRepository, "queryRecordRepository must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
        this.minRelevanceScore = validateMinRelevanceScore(minRelevanceScore);
    }

    @PreAuthorize("isAuthenticated()")
    public RagRetrieval retrieve(long projectId, String queryText, int topK) {
        validate(projectId, queryText, topK);
        authorizationService.requireProjectReadable(currentUserId(), projectId);

        String ragQueryId = "ragq_" + UUID.randomUUID().toString().replace("-", "");
        Instant startedAt = clock.instant();
        try {
            EmbeddingVector queryVector = embeddingService.embed(queryText);
            List<VectorSearchMatch> matches = vectorStore.search(
                    projectId, queryVector, topK);
            List<RagSearchResult> results = resolve(projectId, matches, topK);
            saveRecord(ragQueryId, projectId, queryText, topK, results,
                    results.isEmpty() ? RagQueryStatus.ZERO_HIT
                            : RagQueryStatus.SUCCESS_WITH_RESULTS,
                    startedAt, clock.instant());
            return new RagRetrieval(ragQueryId, results);
        } catch (RuntimeException failure) {
            Instant finishedAt = clock.instant();
            try {
                saveRecord(ragQueryId, projectId, queryText, topK, List.of(),
                        RagQueryStatus.FAILURE, startedAt, finishedAt);
            } catch (RuntimeException persistenceFailure) {
                failure.addSuppressed(persistenceFailure);
            }
            if (failure instanceof RagRetrievalException retrievalFailure) {
                throw retrievalFailure;
            }
            throw new RagRetrievalException("RAG retrieval failed", failure);
        }
    }

    private List<RagSearchResult> resolve(
            long projectId, List<VectorSearchMatch> rawMatches, int topK) {
        List<VectorSearchMatch> ordered = new ArrayList<>(List.copyOf(
                Objects.requireNonNull(rawMatches, "vector matches must not be null")));
        ordered.forEach(match -> {
            if (match == null || match.projectId() != projectId) {
                throw new RagRetrievalException(
                        "Vector result violates the requested project scope");
            }
        });
        if (minRelevanceScore != null) {
            ordered.removeIf(match -> match.relevanceScore() < minRelevanceScore);
        }
        ordered.sort(MATCH_ORDER);

        Map<String, VectorSearchMatch> unique = new LinkedHashMap<>();
        for (VectorSearchMatch match : ordered) {
            unique.putIfAbsent(match.chunkId(), match);
            if (unique.size() == topK) {
                break;
            }
        }

        Map<String, Document> documents = new HashMap<>();
        Map<String, Map<String, DocumentChunk>> chunks = new HashMap<>();
        List<RagSearchResult> results = new ArrayList<>(unique.size());
        for (VectorSearchMatch match : unique.values()) {
            Document document = documents.computeIfAbsent(match.documentId(), id ->
                    documentRepository.findById(projectId, id).orElseThrow(() ->
                            new RagRetrievalException(
                                    "Vector result references a missing document")));
            if (document.status() != DocumentStatus.INDEXED) {
                throw new RagRetrievalException(
                        "Vector result references a document that is not indexed");
            }
            Map<String, DocumentChunk> documentChunks = chunks.computeIfAbsent(
                    match.documentId(), id -> byChunkId(
                            documentRepository.findChunks(projectId, id)));
            DocumentChunk chunk = documentChunks.get(match.chunkId());
            if (chunk == null) {
                throw new RagRetrievalException(
                        "Vector result references a missing document chunk");
            }
            EvidenceCitation citation = new EvidenceCitation(
                    document.sourceType(), document.sourceKey(), projectId,
                    document.documentId(), chunk.chunkId(), match.relevanceScore(),
                    document.title(), "chunk:" + chunk.ordinal(), chunk.content());
            results.add(new RagSearchResult(
                    projectId, document.documentId(), chunk.chunkId(), chunk.content(),
                    match.relevanceScore(), citation));
        }
        return List.copyOf(results);
    }

    private Map<String, DocumentChunk> byChunkId(List<DocumentChunk> values) {
        Map<String, DocumentChunk> chunks = new HashMap<>();
        for (DocumentChunk chunk : values) {
            if (chunks.put(chunk.chunkId(), chunk) != null) {
                throw new RagRetrievalException("Formal knowledge has a duplicate chunk identity");
            }
        }
        return Map.copyOf(chunks);
    }

    private void saveRecord(
            String ragQueryId,
            long projectId,
            String queryText,
            int topK,
            List<RagSearchResult> results,
            RagQueryStatus status,
            Instant startedAt,
            Instant finishedAt
    ) {
        List<RagResultReference> references = results.stream()
                .map(result -> new RagResultReference(
                        result.documentId(), result.chunkId()))
                .toList();
        queryRecordRepository.save(new RagQueryRecord(
                ragQueryId, projectId, queryText, topK, references.size(), references,
                status, startedAt, finishedAt,
                Math.max(0, Duration.between(startedAt, finishedAt).toMillis())));
    }

    private void validate(long projectId, String queryText, int topK) {
        if (projectId <= 0) {
            throw new IllegalArgumentException("projectId must be positive");
        }
        if (queryText == null || queryText.isBlank()) {
            throw new IllegalArgumentException("queryText must not be blank");
        }
        if (topK <= 0) {
            throw new IllegalArgumentException("topK must be positive");
        }
    }

    private static Double validateMinRelevanceScore(Double value) {
        if (value != null && (!Double.isFinite(value) || value < 0.0 || value > 1.0)) {
            throw new IllegalArgumentException(
                    "minRelevanceScore must be finite and between 0.0 and 1.0");
        }
        return value;
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
