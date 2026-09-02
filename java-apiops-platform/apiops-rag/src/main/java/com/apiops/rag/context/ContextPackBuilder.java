package com.apiops.rag.context;

import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.rag.domain.EvidenceCitation;
import com.apiops.rag.retrieval.RagSearchResult;
import com.apiops.report.vo.TestReportVO;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

public class ContextPackBuilder {

    private final ObjectMapper objectMapper;
    private final SensitiveDataMasker masker;
    private final ContextDeduplicator deduplicator;
    private final ContextRanker ranker;
    private final ContextCompressor compressor;

    public ContextPackBuilder(
            ObjectMapper objectMapper,
            SensitiveDataMasker masker,
            ContextDeduplicator deduplicator,
            ContextRanker ranker,
            ContextCompressor compressor
    ) {
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper");
        this.masker = Objects.requireNonNull(masker, "masker");
        this.deduplicator = Objects.requireNonNull(deduplicator, "deduplicator");
        this.ranker = Objects.requireNonNull(ranker, "ranker");
        this.compressor = Objects.requireNonNull(compressor, "compressor");
    }

    public ContextPack build(
            long projectId,
            TestReportVO testReport,
            ApiMetadataDetailVO apiMetadata,
            List<RagSearchResult> ragResults
    ) {
        if (projectId <= 0) {
            throw new IllegalArgumentException("projectId must be positive");
        }
        Objects.requireNonNull(testReport, "testReport");
        Objects.requireNonNull(apiMetadata, "apiMetadata");
        Objects.requireNonNull(ragResults, "ragResults");
        if (testReport.projectId() != projectId) {
            throw new IllegalArgumentException("TestReport projectId does not match context projectId");
        }

        List<ContextItem> rawItems = new ArrayList<>();
        rawItems.add(new ContextItem(
                projectId,
                ContextSource.TEST_REPORT,
                "run:" + testReport.runId(),
                serializeReport(testReport),
                null,
                null,
                null
        ));
        rawItems.add(new ContextItem(
                projectId,
                ContextSource.OPENAPI_METADATA,
                "api:" + apiMetadata.apiId(),
                serialize(apiMetadata, "ApiMetadata"),
                null,
                null,
                null
        ));
        for (RagSearchResult result : ragResults) {
            if (result.projectId() != projectId) {
                throw new IllegalArgumentException("RAG result projectId does not match context projectId");
            }
            EvidenceCitation citation = result.citation();
            rawItems.add(new ContextItem(
                    projectId,
                    ContextSource.RAG_DOCUMENT,
                    "chunk:" + result.chunkId(),
                    result.content(),
                    null,
                    result.relevanceScore(),
                    citation
            ));
        }

        List<ContextItem> masked = masker.maskAll(rawItems);
        List<ContextItem> deduplicated = deduplicator.deduplicate(masked);
        List<ContextItem> ranked = ranker.rank(deduplicated);
        List<ContextItem> compressed = compressor.compress(ranked);
        int totalChars = compressed.stream().mapToInt(item -> item.content().length()).sum();
        return new ContextPack(
                projectId,
                compressed,
                totalChars,
                compressor.maxTotalChars()
        );
    }

    private String serialize(Object value, String sourceName) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Unable to build context from " + sourceName, exception);
        }
    }

    private String serializeReport(TestReportVO report) {
        ObjectNode fields = objectMapper.valueToTree(report);
        ObjectNode summaryFields = (ObjectNode) fields.remove("summary");
        ObjectNode orderedSummary = objectMapper.createObjectNode();
        orderedSummary.set("failureType", summaryFields.remove("failureType"));
        summaryFields.properties().forEach(entry ->
                orderedSummary.set(entry.getKey(), entry.getValue()));

        ObjectNode ordered = objectMapper.createObjectNode();
        ordered.set("status", fields.remove("status"));
        ordered.set("summary", orderedSummary);
        fields.properties().forEach(entry ->
                ordered.set(entry.getKey(), entry.getValue()));
        return serialize(ordered, "TestReport");
    }
}
