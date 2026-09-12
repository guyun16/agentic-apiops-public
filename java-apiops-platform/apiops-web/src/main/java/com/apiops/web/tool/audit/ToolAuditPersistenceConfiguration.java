package com.apiops.web.tool.audit;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.tool.gateway.audit.JdbcToolAuditRepository;
import com.apiops.tool.gateway.audit.ToolAuditRepository;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import javax.sql.DataSource;

/** Binds the Java Tool Gateway's durable audit repository to its owned database. */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "apiops.datasource.tool-gateway", name = "url")
public class ToolAuditPersistenceConfiguration {

    @Bean
    public ToolAuditRepository toolAuditRepository(
            @Qualifier("toolGatewayDataSource") DataSource dataSource
    ) {
        return new JdbcToolAuditRepository(dataSource);
    }

    @Bean
    public ToolAuditQueryApplicationService toolAuditQueryApplicationService(
            ProjectAuthorizationService authorization,
            ToolAuditRepository repository
    ) {
        return new ToolAuditQueryApplicationService(authorization, repository);
    }
}
