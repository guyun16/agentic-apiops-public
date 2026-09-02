package com.apiops.rag.application;

import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.vo.ApiMetadataDetailVO;
import com.apiops.rag.context.ContextPack;
import com.apiops.rag.context.ContextPackBuilder;
import com.apiops.rag.retrieval.RagRetrieval;
import com.apiops.rag.retrieval.RagRetriever;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.vo.TestReportVO;

import java.util.Objects;

/** Coordinates the existing authoritative read boundaries into an immediate context read model. */
public class DiagnosticContextApplicationService {

    private final TestReportQueryService testReportQueryService;
    private final OpenApiQueryApplicationService openApiQueryService;
    private final RagRetriever ragRetriever;
    private final ContextPackBuilder contextPackBuilder;

    public DiagnosticContextApplicationService(
            TestReportQueryService testReportQueryService,
            OpenApiQueryApplicationService openApiQueryService,
            RagRetriever ragRetriever,
            ContextPackBuilder contextPackBuilder
    ) {
        this.testReportQueryService = Objects.requireNonNull(
                testReportQueryService, "testReportQueryService");
        this.openApiQueryService = Objects.requireNonNull(
                openApiQueryService, "openApiQueryService");
        this.ragRetriever = Objects.requireNonNull(ragRetriever, "ragRetriever");
        this.contextPackBuilder = Objects.requireNonNull(
                contextPackBuilder, "contextPackBuilder");
    }

    public ContextPack buildContext(
            long projectId,
            long runId,
            String apiId,
            String queryText,
            int topK
    ) {
        TestReportVO testReport = testReportQueryService.getReport(projectId, runId);
        ApiMetadataDetailVO apiMetadata = openApiQueryService.getApi(projectId, apiId);
        RagRetrieval retrieval = ragRetriever.retrieve(projectId, queryText, topK);
        return contextPackBuilder.build(
                projectId, testReport, apiMetadata, retrieval.results());
    }
}
