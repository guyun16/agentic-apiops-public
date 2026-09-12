package com.apiops.web.config;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.jdbc.DataSourceProperties;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;

import javax.sql.DataSource;

/** Database boundaries for the modules hosted by {@code apiops-web}. */
@Configuration(proxyBeanMethods = false)
public class ApiOpsDataSourceConfiguration {

    @Bean
    @ConfigurationProperties("apiops.datasource.auth")
    public DataSourceProperties authDataSourceProperties() {
        return new DataSourceProperties();
    }

    @Bean(name = "authDataSource")
    @ConditionalOnProperty(prefix = "apiops.datasource.auth", name = "url")
    @ConditionalOnMissingBean(name = "authDataSource")
    public DataSource authDataSource(
            @Qualifier("authDataSourceProperties") DataSourceProperties properties
    ) {
        return properties.initializeDataSourceBuilder().build();
    }

    @Bean
    @ConfigurationProperties("apiops.datasource.openapi")
    public DataSourceProperties openApiDataSourceProperties() {
        return new DataSourceProperties();
    }

    @Bean(name = "openApiDataSource")
    @ConditionalOnProperty(prefix = "apiops.datasource.openapi", name = "url")
    @ConditionalOnMissingBean(name = "openApiDataSource")
    public DataSource openApiDataSource(
            @Qualifier("openApiDataSourceProperties") DataSourceProperties properties
    ) {
        return properties.initializeDataSourceBuilder().build();
    }

    @Bean
    @ConfigurationProperties("apiops.datasource.runner")
    public DataSourceProperties runnerDataSourceProperties() {
        return new DataSourceProperties();
    }

    @Bean(name = "runnerDataSource")
    @ConditionalOnProperty(prefix = "apiops.datasource.runner", name = "url")
    @ConditionalOnMissingBean(name = "runnerDataSource")
    public DataSource runnerDataSource(
            @Qualifier("runnerDataSourceProperties") DataSourceProperties properties
    ) {
        return properties.initializeDataSourceBuilder().build();
    }

    @Bean
    @ConfigurationProperties("apiops.datasource.tool-gateway")
    public DataSourceProperties toolGatewayDataSourceProperties() {
        return new DataSourceProperties();
    }

    @Bean(name = "toolGatewayDataSource")
    @ConditionalOnProperty(prefix = "apiops.datasource.tool-gateway", name = "url")
    @ConditionalOnMissingBean(name = "toolGatewayDataSource")
    public DataSource toolGatewayDataSource(
            @Qualifier("toolGatewayDataSourceProperties") DataSourceProperties properties
    ) {
        return properties.initializeDataSourceBuilder().build();
    }

    @Bean
    @ConfigurationProperties("apiops.datasource.rag")
    public DataSourceProperties ragDataSourceProperties() {
        return new DataSourceProperties();
    }

    @Bean(name = "ragDataSource")
    @ConditionalOnProperty(prefix = "apiops.datasource.rag", name = "url")
    @ConditionalOnMissingBean(name = "ragDataSource")
    public DataSource ragDataSource(
            @Qualifier("ragDataSourceProperties") DataSourceProperties properties
    ) {
        return properties.initializeDataSourceBuilder().build();
    }

    @Bean(name = "openApiTransactionManager")
    @ConditionalOnBean(name = "openApiDataSource")
    @ConditionalOnMissingBean(name = "openApiTransactionManager")
    public DataSourceTransactionManager openApiTransactionManager(
            @Qualifier("openApiDataSource") DataSource dataSource
    ) {
        return new DataSourceTransactionManager(dataSource);
    }
}
