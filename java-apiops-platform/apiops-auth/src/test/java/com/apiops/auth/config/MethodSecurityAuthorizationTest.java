package com.apiops.auth.config;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.security.access.prepost.PreAuthorize;

import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class MethodSecurityAuthorizationTest {

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void shouldEnableMethodSecurityOnProductionConfiguration() {
        assertTrue(ApiOpsSecurityConfiguration.class
                .isAnnotationPresent(EnableMethodSecurity.class));
    }

    @Test
    void adminWithCreateAuthorityCanInvokeProtectedMethod() {
        try (AnnotationConfigApplicationContext context = newContext()) {
            MethodSecurityProbe probe = context.getBean(MethodSecurityProbe.class);
            Authentication authentication = authenticatedWith("PLATFORM_PROJECT_CREATE");
            SecurityContextHolder.getContext().setAuthentication(authentication);

            assertEquals("created", probe.createProject());
            assertEquals(1, probe.invocationCount());
        }
    }

    @Test
    void userWithoutCreateAuthorityIsDenied() {
        try (AnnotationConfigApplicationContext context = newContext()) {
            MethodSecurityProbe probe = context.getBean(MethodSecurityProbe.class);
            SecurityContextHolder.getContext().setAuthentication(
                    authenticatedWith("PLATFORM_PROJECT_LIST")
            );

            assertThrows(AccessDeniedException.class, probe::createProject);
            assertEquals(0, probe.invocationCount());
        }
    }

    @Test
    void authenticatedUserWithNoAuthoritiesIsDenied() {
        try (AnnotationConfigApplicationContext context = newContext()) {
            MethodSecurityProbe probe = context.getBean(MethodSecurityProbe.class);
            SecurityContextHolder.getContext().setAuthentication(
                    UsernamePasswordAuthenticationToken.authenticated(
                            "no-permission-user",
                            null,
                            List.of()
                    )
            );

            assertThrows(AccessDeniedException.class, probe::createProject);
            assertEquals(0, probe.invocationCount());
        }
    }

    @Test
    void deniedInvocationDoesNotExecuteMethodBody() {
        try (AnnotationConfigApplicationContext context = newContext()) {
            MethodSecurityProbe probe = context.getBean(MethodSecurityProbe.class);
            SecurityContextHolder.getContext().setAuthentication(
                    authenticatedWith("PLATFORM_PROJECT_LIST")
            );

            assertThrows(AccessDeniedException.class, probe::createProject);
            assertEquals(0, probe.invocationCount());
        }
    }

    private AnnotationConfigApplicationContext newContext() {
        return new AnnotationConfigApplicationContext(MethodSecurityTestConfiguration.class);
    }

    private Authentication authenticatedWith(String authority) {
        return UsernamePasswordAuthenticationToken.authenticated(
                "test-user",
                null,
                List.of(new SimpleGrantedAuthority(authority))
        );
    }

    @Configuration(proxyBeanMethods = false)
    @EnableMethodSecurity
    static class MethodSecurityTestConfiguration {

        @Bean
        MethodSecurityProbe methodSecurityProbe() {
            return new MethodSecurityProbe();
        }
    }

    static class MethodSecurityProbe {

        private final AtomicInteger invocationCount = new AtomicInteger();

        @PreAuthorize("hasAuthority('PLATFORM_PROJECT_CREATE')")
        public String createProject() {
            invocationCount.incrementAndGet();
            return "created";
        }

        int invocationCount() {
            return invocationCount.get();
        }
    }
}
