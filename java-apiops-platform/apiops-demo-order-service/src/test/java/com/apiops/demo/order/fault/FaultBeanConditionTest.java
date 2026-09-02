package com.apiops.demo.order.fault;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class FaultBeanConditionTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withUserConfiguration(FaultController.class, FaultService.class, Dependencies.class);

    @Test
    void localAndEnabledRegistersFaultComponents() {
        contextRunner.withInitializer(context -> context.getEnvironment().setActiveProfiles("local"))
                .withPropertyValues("apiops.fault.enabled=true")
                .run(context -> {
                    assertThat(context).hasSingleBean(FaultController.class);
                    assertThat(context).hasSingleBean(FaultService.class);
                });
    }

    @Test
    void localAndDisabledDoesNotRegisterFaultComponents() {
        contextRunner.withInitializer(context -> context.getEnvironment().setActiveProfiles("local"))
                .withPropertyValues("apiops.fault.enabled=false")
                .run(context -> assertThat(context)
                        .doesNotHaveBean(FaultController.class)
                        .doesNotHaveBean(FaultService.class));
    }

    @Test
    void nonFaultProfileAndEnabledDoesNotRegisterFaultComponents() {
        contextRunner.withInitializer(context -> context.getEnvironment().setActiveProfiles("prod"))
                .withPropertyValues("apiops.fault.enabled=true")
                .run(context -> assertThat(context)
                        .doesNotHaveBean(FaultController.class)
                        .doesNotHaveBean(FaultService.class));
    }

    @Configuration(proxyBeanMethods = false)
    static class Dependencies {

        @Bean
        FaultProperties faultProperties() {
            return new FaultProperties();
        }

        @Bean
        SlowSqlMapper slowSqlMapper() {
            return mock(SlowSqlMapper.class);
        }
    }
}
