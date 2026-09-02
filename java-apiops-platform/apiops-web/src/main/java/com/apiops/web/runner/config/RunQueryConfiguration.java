package com.apiops.web.runner.config;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.web.runner.application.RunQueryApplicationService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Registers the project-scoped Run read boundary when runner persistence is available. */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "apiops.datasource.runner", name = "url")
public class RunQueryConfiguration {

    @Bean
    public RunQueryApplicationService runQueryApplicationService(
            ProjectAuthorizationService authorization,
            ExecutionFactRepository repository
    ) {
        return new RunQueryApplicationService(authorization, repository);
    }
}
