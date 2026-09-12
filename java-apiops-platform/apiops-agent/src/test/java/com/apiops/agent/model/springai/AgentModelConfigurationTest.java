package com.apiops.agent.model.springai;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.ResourceGuard;
import com.apiops.tool.gateway.ToolAuth;
import com.apiops.tool.gateway.ToolGateway;
import com.apiops.tool.gateway.ToolRegistry;
import io.micrometer.core.instrument.MeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import org.springframework.core.env.Environment;

import java.time.Duration;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AgentModelConfigurationTest {

    @Test
    void toolGatewayUsesConfiguredExecutionTimeout() {
        ProjectAuthorizationService authorization =
                new ProjectAuthorizationService((userId, projectId) -> Optional.empty());
        ToolRegistry registry = new ToolRegistry(authorization);
        ToolAuth toolAuth = new ToolAuth(registry, authorization);
        Environment environment = mock(Environment.class);
        Duration configuredTimeout = Duration.ofMillis(2_750);
        when(environment.getProperty(
                "apiops.tool.gateway.execution-timeout",
                Duration.class,
                Duration.ofSeconds(4)))
                .thenReturn(configuredTimeout);

        StaticListableBeanFactory beans = new StaticListableBeanFactory();
        try (ToolGateway gateway = new AgentModelConfiguration().toolGateway(
                toolAuth,
                authorization,
                new Audit(),
                beans.getBeanProvider(MeterRegistry.class),
                beans.getBeanProvider(ResourceGuard.class),
                environment)) {
            assertEquals(configuredTimeout, gateway.executionTimeout());
        }
    }
}
