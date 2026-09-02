package com.apiops.report.config;

import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.JdbcExecutionFactRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import javax.sql.DataSource;

/** Reads runner execution facts through the host's named runner DataSource. */
@Configuration(proxyBeanMethods = false)
public class TestReportPersistenceConfiguration {

    @Bean
    @ConditionalOnBean(name = "runnerDataSource")
    @ConditionalOnMissingBean(ExecutionFactRepository.class)
    public ExecutionFactRepository executionFactRepository(
            @Qualifier("runnerDataSource") DataSource dataSource,
            ObjectMapper objectMapper
    ) {
        return new JdbcExecutionFactRepository(dataSource, objectMapper);
    }
}
