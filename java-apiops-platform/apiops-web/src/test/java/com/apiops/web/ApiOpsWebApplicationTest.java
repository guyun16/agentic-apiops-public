package com.apiops.web;

import com.apiops.openapi.application.OpenApiImportApplicationService;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.controller.OpenApiDocumentController;
import com.apiops.openapi.controller.OpenApiMetadataQueryController;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import com.apiops.rag.application.DocumentIngestionApplicationService;
import com.apiops.rag.embedding.EmbeddingService;
import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.vector.VectorStoreService;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.controller.TestReportController;
import com.apiops.runner.persistence.ExecutionFactRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;
import org.springframework.test.context.ActiveProfiles;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertEquals;

@SpringBootTest
@ActiveProfiles("test")
class ApiOpsWebApplicationTest {

    @Autowired
    private ApplicationContext applicationContext;

    @Test
    void contextLoadsWithoutOpenApiPersistenceGraphWhenDataSourceIsAbsent() {
        assertTrue(applicationContext.getBeansOfType(
                OpenApiMetadataRepository.class).isEmpty());
        assertTrue(applicationContext.getBeansOfType(
                OpenApiImportApplicationService.class).isEmpty());
        assertTrue(applicationContext.getBeansOfType(
                OpenApiQueryApplicationService.class).isEmpty());
        assertTrue(applicationContext.getBeansOfType(
                OpenApiDocumentController.class).isEmpty());
        assertTrue(applicationContext.getBeansOfType(
                OpenApiMetadataQueryController.class).isEmpty());
        assertTrue(applicationContext.getBeansOfType(
                ExecutionFactRepository.class).isEmpty());
        assertTrue(applicationContext.getBeansOfType(
                TestReportQueryService.class).isEmpty());
        assertTrue(applicationContext.getBeansOfType(
                TestReportController.class).isEmpty());
        assertTrue(applicationContext.getBeansOfType(
                DocumentRepository.class).isEmpty());
        EmbeddingService embeddingService = applicationContext.getBean(EmbeddingService.class);
        assertEquals("zhipu", embeddingService.model().provider());
        assertEquals("embedding-3", embeddingService.model().model());
        assertEquals(1_024, embeddingService.model().dimension());
        assertTrue(applicationContext.getBeansOfType(VectorStoreService.class).isEmpty());
        assertTrue(applicationContext.getBeansOfType(
                DocumentIngestionApplicationService.class).isEmpty());
    }
}
