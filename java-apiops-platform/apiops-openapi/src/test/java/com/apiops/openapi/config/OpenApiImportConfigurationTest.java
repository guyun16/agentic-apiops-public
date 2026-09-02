package com.apiops.openapi.config;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.openapi.application.OpenApiImportApplicationService;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.controller.OpenApiDocumentController;
import com.apiops.openapi.controller.OpenApiMetadataQueryController;
import com.apiops.openapi.converter.OpenApiMetadataAssembler;
import com.apiops.openapi.normalizer.OpenApiMetadataNormalizer;
import com.apiops.openapi.parser.OpenApiDocumentParser;
import com.apiops.openapi.repository.JdbcOpenApiMetadataRepository;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.transaction.PlatformTransactionManager;

import javax.sql.DataSource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;

class OpenApiImportConfigurationTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withBean(ProjectAuthorizationService.class, () ->
                    new ProjectAuthorizationService((ProjectMembershipRepository)
                            (userId, projectId) -> java.util.Optional.empty()))
            .withUserConfiguration(OpenApiImportConfiguration.class);

    @Test
    void shouldNotCreatePersistenceBackedBeansWithoutDataSource() {
        contextRunner.withPropertyValues("apiops.openapi.import.max-file-size=12KB")
                .run(context -> {
            assertEquals(1, context.getBeansOfType(OpenApiDocumentParser.class).size());
            assertEquals(1, context.getBeansOfType(OpenApiMetadataNormalizer.class).size());
            assertTrue(context.getBeansOfType(OpenApiMetadataRepository.class).isEmpty());
            assertTrue(context.getBeansOfType(OpenApiImportApplicationService.class).isEmpty());
            assertTrue(context.getBeansOfType(OpenApiQueryApplicationService.class).isEmpty());
            assertTrue(context.getBeansOfType(OpenApiDocumentController.class).isEmpty());
            assertTrue(context.getBeansOfType(OpenApiMetadataQueryController.class).isEmpty());
            assertTrue(context.getBeansOfType(OpenApiMetadataAssembler.class).isEmpty());
            assertEquals(
                    12L * 1024,
                    context.getBean(OpenApiImportProperties.class).getMaxFileSize().toBytes()
            );
        });
    }

    @Test
    void shouldCreateCompletePersistenceBackedGraphWithDataSource() {
        contextRunner
                .withBean("openApiDataSource", DataSource.class,
                        () -> mock(DataSource.class))
                .withBean("openApiTransactionManager", PlatformTransactionManager.class,
                        () -> mock(PlatformTransactionManager.class))
                .run(context -> {
                    assertInstanceOf(JdbcOpenApiMetadataRepository.class,
                            context.getBean(OpenApiMetadataRepository.class));
                    assertEquals(1, context.getBeansOfType(
                            OpenApiImportApplicationService.class).size());
                    assertEquals(1, context.getBeansOfType(
                            OpenApiQueryApplicationService.class).size());
                    assertEquals(1, context.getBeansOfType(
                            OpenApiDocumentController.class).size());
                    assertEquals(1, context.getBeansOfType(
                            OpenApiMetadataQueryController.class).size());
                });
    }
}
