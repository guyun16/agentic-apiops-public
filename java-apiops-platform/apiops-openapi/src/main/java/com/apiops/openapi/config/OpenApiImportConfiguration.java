package com.apiops.openapi.config;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.openapi.application.OpenApiImportApplicationService;
import com.apiops.openapi.application.OpenApiQueryApplicationService;
import com.apiops.openapi.controller.OpenApiDocumentController;
import com.apiops.openapi.controller.OpenApiMetadataQueryController;
import com.apiops.openapi.converter.OpenApiMetadataAssembler;
import com.apiops.openapi.exception.OpenApiImportExceptionHandler;
import com.apiops.openapi.exception.OpenApiQueryExceptionHandler;
import com.apiops.openapi.normalizer.OpenApiMetadataNormalizer;
import com.apiops.openapi.parser.OpenApiDocumentParser;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.transaction.PlatformTransactionManager;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(OpenApiImportProperties.class)
@Import({
        OpenApiMetadataPersistenceConfiguration.class,
        OpenApiImportExceptionHandler.class,
        OpenApiQueryExceptionHandler.class
})
public class OpenApiImportConfiguration {

    @Bean
    public OpenApiDocumentParser openApiDocumentParser() {
        return new OpenApiDocumentParser();
    }

    @Bean
    public OpenApiMetadataNormalizer openApiMetadataNormalizer() {
        return new OpenApiMetadataNormalizer();
    }

    @Bean
    @ConditionalOnBean(
            value = OpenApiMetadataRepository.class,
            name = "openApiTransactionManager"
    )
    public OpenApiImportApplicationService openApiImportApplicationService(
            ProjectAuthorizationService authorizationService,
            OpenApiDocumentParser parser,
            OpenApiImportProperties properties,
            OpenApiMetadataNormalizer normalizer,
            OpenApiMetadataRepository repository,
            @Qualifier("openApiTransactionManager")
            PlatformTransactionManager transactionManager
    ) {
        return new OpenApiImportApplicationService(
                authorizationService, parser, properties, normalizer,
                repository, transactionManager);
    }

    @Bean
    @ConditionalOnBean(OpenApiMetadataRepository.class)
    public OpenApiMetadataAssembler openApiMetadataAssembler() {
        return new OpenApiMetadataAssembler();
    }

    @Bean
    @ConditionalOnBean(OpenApiMetadataRepository.class)
    public OpenApiQueryApplicationService openApiQueryApplicationService(
            ProjectAuthorizationService authorizationService,
            OpenApiMetadataRepository repository,
            OpenApiMetadataAssembler assembler
    ) {
        return new OpenApiQueryApplicationService(
                authorizationService, repository, assembler);
    }

    @Bean
    @ConditionalOnBean(
            value = OpenApiMetadataRepository.class,
            name = "openApiTransactionManager"
    )
    public OpenApiDocumentController openApiDocumentController(
            OpenApiImportApplicationService importService
    ) {
        return new OpenApiDocumentController(importService);
    }

    @Bean
    @ConditionalOnBean(OpenApiMetadataRepository.class)
    public OpenApiMetadataQueryController openApiMetadataQueryController(
            OpenApiQueryApplicationService queryService
    ) {
        return new OpenApiMetadataQueryController(queryService);
    }
}
