package com.apiops.rag.context;

import com.apiops.common.enums.FailureType;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.rag.domain.EvidenceCitation;
import com.apiops.rag.retrieval.RagSearchResult;
import com.apiops.report.vo.TestReportVO;
import com.apiops.runner.state.RunStatus;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ContextPackBuilderTest {

    private static final long PROJECT_ID = 41L;

    @Test
    void appliesAuthorityThenRagScoreWithStableIdentityTieBreak() {
        ContextPack pack = builder(defaultProperties()).build(
                PROJECT_ID,
                report(),
                metadata(),
                List.of(
                        rag("doc-b", "chunk-c", 0.90, "C"),
                        rag("doc-a", "chunk-b", 0.80, "B"),
                        rag("doc-a", "chunk-a", 0.80, "A")));

        assertEquals(List.of(
                        ContextSource.TEST_REPORT,
                        ContextSource.OPENAPI_METADATA,
                        ContextSource.RAG_DOCUMENT,
                        ContextSource.RAG_DOCUMENT,
                        ContextSource.RAG_DOCUMENT),
                pack.items().stream().map(ContextItem::source).toList());
        assertEquals(List.of("chunk-c", "chunk-a", "chunk-b"),
                ragItems(pack).stream().map(item -> item.citation().chunkId()).toList());
        assertEquals(List.of(0.90, 0.80, 0.80),
                ragItems(pack).stream().map(ContextItem::relevanceScore).toList());
    }

    @Test
    void deduplicatesRagByChunkKeepingHighestScore() {
        ContextPack pack = builder(defaultProperties()).build(
                PROJECT_ID,
                report(),
                metadata(),
                List.of(
                        rag("doc-a", "chunk-a", 0.40, "lower"),
                        rag("doc-a", "chunk-a", 0.95, "higher"),
                        rag("doc-a", "chunk-b", 0.70, "other")));

        assertEquals(List.of("chunk-a", "chunk-b"),
                ragItems(pack).stream().map(item -> item.citation().chunkId()).toList());
        assertEquals("higher", ragItems(pack).getFirst().content());
        assertEquals(0.95, ragItems(pack).getFirst().citation().score());
    }

    @Test
    void exactHashDedupNeverCrossesSourceBoundary() {
        ContextDeduplicator deduplicator = new ContextDeduplicator();
        ContextItem report = plainItem(ContextSource.TEST_REPORT, "report", "same-hash");
        ContextItem duplicateReport = plainItem(ContextSource.TEST_REPORT, "report-2", "same-hash");
        ContextItem metadata = plainItem(ContextSource.OPENAPI_METADATA, "api", "same-hash");

        List<ContextItem> deduplicated = deduplicator.deduplicate(
                List.of(report, duplicateReport, metadata));

        assertEquals(2, deduplicated.size());
        assertEquals(List.of(ContextSource.TEST_REPORT, ContextSource.OPENAPI_METADATA),
                deduplicated.stream().map(ContextItem::source).toList());
    }

    @Test
    void masksSensitiveDataOnlyInContextOutput() {
        String original = "Authorization: Bearer bearer-token\n"
                + "Cookie: session=cookie-value\n"
                + "Set-Cookie: refresh=set-cookie-value\n"
                + "password=db-password api_key=key-value secret=secret-value\n"
                + "jdbc:mysql://db-user:db-credential@localhost:3306/apiops";
        RagSearchResult result = rag("doc-a", "chunk-a", 0.90, original);

        ContextItem retained = ragItems(builder(defaultProperties()).build(
                PROJECT_ID, report(), metadata(), List.of(result))).getFirst();

        for (String secret : List.of(
                "bearer-token", "cookie-value", "set-cookie-value", "db-password",
                "key-value", "secret-value", "db-user", "db-credential")) {
            assertFalse(retained.content().contains(secret));
        }
        assertTrue(retained.content().contains("[REDACTED]"));
        assertEquals(original, result.content());
        assertEquals(retained.content(), retained.citation().excerpt());
    }

    @Test
    void masksCredentialValueRepeatedInOverlappingChunkWithoutItsHeader() {
        String value = "overlap-cookie-value";
        ContextPack pack = builder(defaultProperties()).build(
                PROJECT_ID,
                report(),
                metadata(),
                List.of(
                        rag("doc-a", "chunk-a", 0.90,
                                "Cookie: SESSION=" + value + "\nfirst chunk"),
                        rag("doc-a", "chunk-b", 0.80,
                                value + "\noverlapping continuation")));

        assertTrue(ragItems(pack).stream()
                .noneMatch(item -> item.content().contains(value)));
        assertTrue(ragItems(pack).stream()
                .allMatch(item -> item.content().contains("[REDACTED]")));
    }

    @Test
    void reservesAuthoritativeContextThenCutsLowerRagWithinBudget() {
        ContextPack baseline = builder(defaultProperties()).build(
                PROJECT_ID, report(), metadata(), List.of());
        ContextPackProperties constrained = new ContextPackProperties();
        constrained.setMaxTotalChars(baseline.totalChars() + 50);
        constrained.setMaxRagItemChars(2_000);

        ContextPack pack = builder(constrained).build(
                PROJECT_ID,
                report(),
                metadata(),
                List.of(
                        rag("doc-a", "chunk-high", 0.90, "H".repeat(100)),
                        rag("doc-a", "chunk-low", 0.10, "L".repeat(100))));

        assertEquals(constrained.getMaxTotalChars(), pack.totalChars());
        assertEquals(List.of(ContextSource.TEST_REPORT, ContextSource.OPENAPI_METADATA),
                pack.items().subList(0, 2).stream().map(ContextItem::source).toList());
        assertEquals(1, ragItems(pack).size());
        ContextItem retained = ragItems(pack).getFirst();
        assertEquals("chunk-high", retained.citation().chunkId());
        assertEquals(50, retained.content().length());
        assertEquals(retained.content(), retained.citation().excerpt());
    }

    @Test
    void deterministicallyKeepsCoreReportFailureFactsWhenAuthoritiesExceedBudget() {
        ContextPackProperties constrained = new ContextPackProperties();
        constrained.setMaxTotalChars(80);

        ContextPackBuilder builder = builder(constrained);
        ContextPack first = builder.build(PROJECT_ID, report(), metadata(), List.of());
        ContextPack second = builder.build(PROJECT_ID, report(), metadata(), List.of());

        assertEquals(first, second);
        assertEquals(80, first.totalChars());
        assertEquals(1, first.items().size());
        ContextItem retained = first.items().getFirst();
        assertEquals(ContextSource.TEST_REPORT, retained.source());
        assertTrue(retained.content().contains("\"status\":\"ASSERTION_FAILED\""));
        assertTrue(retained.content().contains("\"failureType\":\"ASSERTION_MISMATCH\""));
    }

    @Test
    void enforcesPerRagItemBudgetAndKeepsCitationIdentityAligned() {
        ContextPackProperties properties = defaultProperties();
        properties.setMaxRagItemChars(20);

        ContextItem item = ragItems(builder(properties).build(
                PROJECT_ID,
                report(),
                metadata(),
                List.of(rag("doc-a", "chunk-a", 0.77, "content-".repeat(10))))).getFirst();

        assertEquals(20, item.content().length());
        assertEquals(PROJECT_ID, item.projectId());
        assertEquals(PROJECT_ID, item.citation().projectId());
        assertEquals("doc-a", item.citation().documentId());
        assertEquals("chunk-a", item.citation().chunkId());
        assertEquals(item.relevanceScore(), item.citation().score());
        assertEquals(item.content(), item.citation().excerpt());
    }

    @Test
    void sameInputProducesDeterministicPackAndPreservesProjectScope() {
        ContextPackBuilder builder = builder(defaultProperties());
        List<RagSearchResult> evidence = List.of(
                rag("doc-b", "chunk-b", 0.60, "second"),
                rag("doc-a", "chunk-a", 0.70, "first"));

        ContextPack first = builder.build(PROJECT_ID, report(), metadata(), evidence);
        ContextPack second = builder.build(PROJECT_ID, report(), metadata(), evidence);

        assertEquals(first, second);
        assertEquals(PROJECT_ID, first.projectId());
        assertTrue(first.items().stream().allMatch(item -> item.projectId() == PROJECT_ID));
    }

    @Test
    void rejectsCrossProjectFactsAndEvidence() {
        assertThrows(IllegalArgumentException.class, () -> builder(defaultProperties()).build(
                PROJECT_ID + 1, report(), metadata(), List.of()));
        assertThrows(IllegalArgumentException.class, () -> builder(defaultProperties()).build(
                PROJECT_ID, report(), metadata(), List.of(
                        rag(PROJECT_ID + 1, "doc-a", "chunk-a", 0.5, "foreign"))));
    }

    private static ContextPackBuilder builder(ContextPackProperties properties) {
        return new ContextPackBuilder(
                new ObjectMapper().findAndRegisterModules(),
                new SensitiveDataMasker(),
                new ContextDeduplicator(),
                new ContextRanker(),
                new ContextCompressor(properties));
    }

    private static ContextPackProperties defaultProperties() {
        return new ContextPackProperties();
    }

    private static TestReportVO report() {
        return new TestReportVO(
                PROJECT_ID,
                12L,
                34L,
                RunStatus.ASSERTION_FAILED,
                Instant.parse("2026-08-13T01:00:00Z"),
                Instant.parse("2026-08-13T01:00:02Z"),
                new TestReportVO.Summary(
                        1, 1, 1, 0, 1, FailureType.ASSERTION_MISMATCH),
                List.of());
    }

    private static ApiMetadataDetailVO metadata() {
        return new ApiMetadataDetailVO(
                "api-1",
                "doc-1",
                "getOrder",
                "GET",
                "/orders/{id}",
                "Get order",
                "Returns one order",
                JsonNodeFactory.instance.arrayNode().add("orders"),
                JsonNodeFactory.instance.arrayNode(),
                JsonNodeFactory.instance.arrayNode(),
                false,
                List.of(),
                List.of(),
                List.of(),
                List.of());
    }

    private static RagSearchResult rag(
            String documentId, String chunkId, double score, String content) {
        return rag(PROJECT_ID, documentId, chunkId, score, content);
    }

    private static RagSearchResult rag(
            long projectId, String documentId, String chunkId, double score, String content) {
        EvidenceCitation citation = new EvidenceCitation(
                "DOCUMENT",
                "runbook/" + documentId,
                projectId,
                documentId,
                chunkId,
                score,
                "Runbook " + documentId,
                "chunk:" + chunkId,
                content);
        return new RagSearchResult(
                projectId, documentId, chunkId, content, score, citation);
    }

    private static ContextItem plainItem(
            ContextSource source, String itemId, String contentHash) {
        return new ContextItem(
                PROJECT_ID, source, itemId, "duplicate", contentHash, null, null);
    }

    private static List<ContextItem> ragItems(ContextPack pack) {
        return pack.items().stream()
                .filter(item -> item.source() == ContextSource.RAG_DOCUMENT)
                .toList();
    }
}
