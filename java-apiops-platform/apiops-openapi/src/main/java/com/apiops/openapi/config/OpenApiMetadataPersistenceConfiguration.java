package com.apiops.openapi.config;

import com.apiops.openapi.repository.JdbcOpenApiMetadataRepository;
import com.apiops.openapi.repository.OpenApiMetadataRepository;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import javax.sql.DataSource;

/** Binds OpenAPI metadata persistence to the host's named OpenAPI DataSource. */
@Configuration(proxyBeanMethods = false)
public class OpenApiMetadataPersistenceConfiguration {

    @Bean
    @ConditionalOnBean(name = "openApiDataSource")
    @ConditionalOnMissingBean(OpenApiMetadataRepository.class)
    public OpenApiMetadataRepository openApiMetadataRepository(
            @Qualifier("openApiDataSource") DataSource dataSource
    ) {
        return new JdbcOpenApiMetadataRepository(dataSource);
    }
}
