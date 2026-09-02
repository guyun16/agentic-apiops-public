package com.apiops.web.config;

import com.zaxxer.hikari.HikariDataSource;
import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.autoconfigure.context.ConfigurationPropertiesAutoConfiguration;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;

import javax.sql.DataSource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertSame;

class ApiOpsDataSourceConfigurationTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withConfiguration(AutoConfigurations.of(
                    ConfigurationPropertiesAutoConfiguration.class))
            .withUserConfiguration(ApiOpsDataSourceConfiguration.class);

    @Test
    void shouldCreateNoPersistenceBeansWhenModuleUrlsAreAbsent() {
        contextRunner.run(context -> {
            assertFalse(context.containsBean("authDataSource"));
            assertFalse(context.containsBean("openApiDataSource"));
            assertFalse(context.containsBean("runnerDataSource"));
            assertFalse(context.containsBean("ragDataSource"));
            assertFalse(context.containsBean("openApiTransactionManager"));
        });
    }

    @Test
    void shouldCreateNamedDataSourcesAndBindOpenApiTransactionManager() {
        contextRunner
                .withPropertyValues(
                        "apiops.datasource.auth.url=jdbc:mysql://localhost:3306/apiops_auth",
                        "apiops.datasource.auth.username=root",
                        "apiops.datasource.openapi.url=jdbc:mysql://localhost:3306/apiops_openapi",
                        "apiops.datasource.openapi.username=root",
                        "apiops.datasource.runner.url=jdbc:mysql://localhost:3306/apiops_runner",
                        "apiops.datasource.runner.username=root",
                        "apiops.datasource.rag.url=jdbc:mysql://localhost:3306/apiops_rag",
                        "apiops.datasource.rag.username=root"
                )
                .run(context -> {
                    DataSource auth = context.getBean("authDataSource", DataSource.class);
                    DataSource openApi = context.getBean(
                            "openApiDataSource", DataSource.class);
                    DataSource runner = context.getBean(
                            "runnerDataSource", DataSource.class);
                    DataSource rag = context.getBean(
                            "ragDataSource", DataSource.class);

                    assertEquals("jdbc:mysql://localhost:3306/apiops_auth",
                            assertInstanceOf(HikariDataSource.class, auth).getJdbcUrl());
                    assertEquals("jdbc:mysql://localhost:3306/apiops_openapi",
                            assertInstanceOf(HikariDataSource.class, openApi).getJdbcUrl());
                    assertEquals("jdbc:mysql://localhost:3306/apiops_runner",
                            assertInstanceOf(HikariDataSource.class, runner).getJdbcUrl());
                    assertEquals("jdbc:mysql://localhost:3306/apiops_rag",
                            assertInstanceOf(HikariDataSource.class, rag).getJdbcUrl());

                    DataSourceTransactionManager transactionManager = assertInstanceOf(
                            DataSourceTransactionManager.class,
                            context.getBean("openApiTransactionManager")
                    );
                    assertSame(openApi, transactionManager.getDataSource());
                });
    }
}
