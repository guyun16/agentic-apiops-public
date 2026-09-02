package com.apiops.report.config;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.report.application.TestReportQueryService;
import com.apiops.report.assembler.TestReportAssembler;
import com.apiops.report.controller.TestReportController;
import com.apiops.report.exception.TestReportExceptionHandler;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;

@Configuration(proxyBeanMethods = false)
@Import({TestReportPersistenceConfiguration.class, TestReportExceptionHandler.class})
public class TestReportConfiguration {

    @Bean
    @ConditionalOnBean(ExecutionFactRepository.class)
    public TestReportAssembler testReportAssembler(ObjectMapper objectMapper) {
        return new TestReportAssembler(objectMapper);
    }

    @Bean
    @ConditionalOnBean(ExecutionFactRepository.class)
    public TestReportQueryService testReportQueryService(
            ProjectAuthorizationService authorizationService,
            ExecutionFactRepository repository,
            TestReportAssembler assembler
    ) {
        return new TestReportQueryService(authorizationService, repository, assembler);
    }

    @Bean
    @ConditionalOnBean(ExecutionFactRepository.class)
    public TestReportController testReportController(TestReportQueryService queryService) {
        return new TestReportController(queryService);
    }
}
