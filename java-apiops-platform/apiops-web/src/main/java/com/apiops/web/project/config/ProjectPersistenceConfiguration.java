package com.apiops.web.project.config;

import com.apiops.web.project.repository.EmptyProjectRepository;
import com.apiops.web.project.repository.JdbcProjectRepository;
import com.apiops.web.project.repository.ProjectRepository;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import javax.sql.DataSource;

/** Binds project-space persistence to the platform auth database. */
@Configuration(proxyBeanMethods = false)
public class ProjectPersistenceConfiguration {

    @Bean
    @ConditionalOnMissingBean(ProjectRepository.class)
    public ProjectRepository projectRepository(
            @Qualifier("authDataSource") ObjectProvider<DataSource> dataSourceProvider
    ) {
        DataSource dataSource = dataSourceProvider.getIfAvailable();
        return dataSource == null
                ? new EmptyProjectRepository()
                : new JdbcProjectRepository(dataSource);
    }
}
