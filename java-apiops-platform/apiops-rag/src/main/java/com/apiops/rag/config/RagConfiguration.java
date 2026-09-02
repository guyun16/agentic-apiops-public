package com.apiops.rag.config;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.rag.application.DiagnosticContextApplicationService;
import com.apiops.rag.application.DocumentIngestionApplicationService;
import com.apiops.rag.context.ContextCompressor;
import com.apiops.rag.context.ContextDeduplicator;
import com.apiops.rag.context.ContextPackBuilder;
import com.apiops.rag.context.ContextPackProperties;
import com.apiops.rag.context.ContextRanker;
import com.apiops.rag.context.SensitiveDataMasker;
import com.apiops.rag.embedding.EmbeddingService;
import com.apiops.rag.embedding.zhipu.ZhipuEmbeddingProperties;
import com.apiops.rag.embedding.zhipu.ZhipuEmbeddingService;
import com.apiops.rag.parser.DocumentParser;
import com.apiops.rag.parser.PlainTextDocumentParser;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.repository.RagQueryRecordRepository;
import com.apiops.rag.retrieval.RagRetriever;
import com.apiops.rag.splitter.FixedSizeTextSplitter;
import com.apiops.rag.splitter.TextSplitter;
import com.apiops.rag.splitter.TextSplitterConfig;
import com.apiops.rag.vector.VectorStoreService;
import com.apiops.rag.vector.qdrant.QdrantVectorStoreProperties;
import com.apiops.rag.vector.qdrant.QdrantVectorStoreService;
import com.apiops.report.application.TestReportQueryService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;

import java.time.Clock;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties({
        RagIngestionProperties.class,
        RagRetrievalProperties.class,
        ContextPackProperties.class,
        ZhipuEmbeddingProperties.class,
        QdrantVectorStoreProperties.class
})
@Import(RagPersistenceConfiguration.class)
public class RagConfiguration {

    @Bean
    @ConditionalOnMissingBean(SensitiveDataMasker.class)
    public SensitiveDataMasker sensitiveDataMasker() {
        return new SensitiveDataMasker();
    }

    @Bean
    @ConditionalOnMissingBean(ContextDeduplicator.class)
    public ContextDeduplicator contextDeduplicator() {
        return new ContextDeduplicator();
    }

    @Bean
    @ConditionalOnMissingBean(ContextRanker.class)
    public ContextRanker contextRanker() {
        return new ContextRanker();
    }

    @Bean
    @ConditionalOnMissingBean(ContextCompressor.class)
    public ContextCompressor contextCompressor(ContextPackProperties properties) {
        return new ContextCompressor(properties);
    }

    @Bean
    @ConditionalOnMissingBean(ContextPackBuilder.class)
    public ContextPackBuilder contextPackBuilder(
            ObjectMapper objectMapper,
            SensitiveDataMasker masker,
            ContextDeduplicator deduplicator,
            ContextRanker ranker,
            ContextCompressor compressor
    ) {
        return new ContextPackBuilder(
                objectMapper, masker, deduplicator, ranker, compressor);
    }

    @Bean
    @ConditionalOnBean({
            TestReportQueryService.class,
            OpenApiQueryApplicationService.class,
            RagRetriever.class,
            ContextPackBuilder.class
    })
    @ConditionalOnMissingBean(DiagnosticContextApplicationService.class)
    public DiagnosticContextApplicationService diagnosticContextApplicationService(
            TestReportQueryService testReportQueryService,
            OpenApiQueryApplicationService openApiQueryService,
            RagRetriever ragRetriever,
            ContextPackBuilder contextPackBuilder
    ) {
        return new DiagnosticContextApplicationService(
                testReportQueryService, openApiQueryService,
                ragRetriever, contextPackBuilder);
    }

    @Bean
    @ConditionalOnMissingBean(DocumentParser.class)
    public DocumentParser documentParser() {
        return new PlainTextDocumentParser();
    }

    @Bean
    @ConditionalOnMissingBean(TextSplitter.class)
    public TextSplitter textSplitter(RagIngestionProperties properties) {
        return new FixedSizeTextSplitter(new TextSplitterConfig(
                properties.getChunkSize(), properties.getChunkOverlap()));
    }

    @Bean
    @ConditionalOnMissingBean(Clock.class)
    public Clock ragClock() {
        return Clock.systemUTC();
    }

    @Bean
    @ConditionalOnMissingBean(EmbeddingService.class)
    public EmbeddingService zhipuEmbeddingService(
            ZhipuEmbeddingProperties properties, ObjectMapper objectMapper) {
        return new ZhipuEmbeddingService(
                properties.getApiKey(), properties.getTimeout(), objectMapper);
    }

    @Bean
    @ConditionalOnProperty(
            prefix = "apiops.rag.vector-store.qdrant",
            name = "enabled",
            havingValue = "true")
    @ConditionalOnMissingBean(VectorStoreService.class)
    public VectorStoreService qdrantVectorStoreService(
            QdrantVectorStoreProperties properties, ObjectMapper objectMapper) {
        QdrantVectorStoreService service = new QdrantVectorStoreService(
                properties.getBaseUrl(), properties.getCollection(),
                properties.getTimeout(), properties.getApiKey(), objectMapper);
        service.initialize();
        return service;
    }

    @Bean
    @ConditionalOnBean({
            DocumentRepository.class,
            EmbeddingService.class,
            VectorStoreService.class
    })
    @ConditionalOnMissingBean(DocumentIngestionApplicationService.class)
    public DocumentIngestionApplicationService documentIngestionApplicationService(
            ProjectAuthorizationService authorizationService,
            DocumentParser parser,
            TextSplitter splitter,
            DocumentRepository repository,
            EmbeddingService embeddingService,
            VectorStoreService vectorStoreService,
            Clock clock
    ) {
        return new DocumentIngestionApplicationService(
                authorizationService, parser, splitter, repository,
                embeddingService, vectorStoreService, clock);
    }

    @Bean
    @ConditionalOnBean({
            DocumentRepository.class,
            RagQueryRecordRepository.class,
            EmbeddingService.class,
            VectorStoreService.class
    })
    @ConditionalOnMissingBean(RagRetriever.class)
    public RagRetriever ragRetriever(
            ProjectAuthorizationService authorizationService,
            EmbeddingService embeddingService,
            VectorStoreService vectorStoreService,
            DocumentRepository documentRepository,
            RagQueryRecordRepository queryRecordRepository,
            Clock clock,
            RagRetrievalProperties retrievalProperties
    ) {
        return new RagRetriever(
                authorizationService, embeddingService, vectorStoreService,
                documentRepository, queryRecordRepository, clock,
                retrievalProperties.getMinRelevanceScore());
    }
}
