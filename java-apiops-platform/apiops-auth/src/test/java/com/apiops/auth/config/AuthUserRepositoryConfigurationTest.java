package com.apiops.auth.config;

import com.apiops.auth.repository.AuthUserRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import org.springframework.mock.env.MockEnvironment;

import javax.sql.DataSource;

import static org.junit.jupiter.api.Assertions.assertTrue;

class AuthUserRepositoryConfigurationTest {

    @Test
    void shouldUseEmptyRepositoryOutsideTestProfileWhenDataSourceIsMissing() {
        ApiOpsSecurityConfiguration configuration = new ApiOpsSecurityConfiguration();
        AuthUserRepository repository = configuration.authUserRepository(
                new DefaultListableBeanFactory().getBeanProvider(DataSource.class),
                new MockEnvironment()
        );

        assertTrue(repository.findByUsername("demo-user").isEmpty());
    }

    @Test
    void shouldEnableDemonstrationRepositoryOnlyForTestProfile() {
        ApiOpsSecurityConfiguration configuration = new ApiOpsSecurityConfiguration();
        MockEnvironment environment = new MockEnvironment();
        environment.setActiveProfiles("test");
        AuthUserRepository repository = configuration.authUserRepository(
                new DefaultListableBeanFactory().getBeanProvider(DataSource.class),
                environment
        );

        assertTrue(repository.findByUsername("demo-user").isPresent());
    }
}
