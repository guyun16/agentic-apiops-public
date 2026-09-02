package com.apiops.rag.config;

import com.apiops.rag.repository.DocumentRepository;
import com.apiops.rag.repository.JdbcDocumentRepository;
import com.apiops.rag.repository.JdbcRagQueryRecordRepository;
import com.apiops.rag.repository.RagQueryRecordRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import javax.sql.DataSource;

@Configuration(proxyBeanMethods = false)
public class RagPersistenceConfiguration {

    @Bean
    @ConditionalOnBean(name = "ragDataSource")
    @ConditionalOnMissingBean(DocumentRepository.class)
    public DocumentRepository documentRepository(
            @Qualifier("ragDataSource") DataSource dataSource,
            ObjectMapper objectMapper
    ) {
        return new JdbcDocumentRepository(dataSource, objectMapper);
    }

    @Bean
    @ConditionalOnBean(name = "ragDataSource")
    @ConditionalOnMissingBean(RagQueryRecordRepository.class)
    public RagQueryRecordRepository ragQueryRecordRepository(
            @Qualifier("ragDataSource") DataSource dataSource,
            ObjectMapper objectMapper
    ) {
        return new JdbcRagQueryRecordRepository(dataSource, objectMapper);
    }
}
