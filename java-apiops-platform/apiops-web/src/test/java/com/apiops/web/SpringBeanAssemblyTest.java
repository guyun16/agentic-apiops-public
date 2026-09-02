package com.apiops.web;

import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.web.system.application.SystemQueryService;
import com.apiops.web.system.domain.SystemInfo;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;
import org.springframework.test.context.ActiveProfiles;

import java.time.Clock;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertEquals;

@SpringBootTest
@ActiveProfiles("test")
class SpringBeanAssemblyTest {

    @Autowired
    private ApplicationContext applicationContext;

    @Test
    void shouldRegisterOnlySpringManagedCollaborators() {
        assertNotNull(applicationContext.getBean(SystemQueryService.class));
        assertNotNull(applicationContext.getBean(JwtTokenService.class));
        assertNotNull(applicationContext.getBean(Clock.class));
        assertEquals(1, applicationContext.getBeansOfType(Clock.class).size());
        assertTrue(applicationContext.getBeansOfType(SystemInfo.class).isEmpty());
    }
    @Test
    void shouldReturnSameSystemQueryServiceBean() {
        SystemQueryService first =
                applicationContext.getBean(SystemQueryService.class);

        SystemQueryService second =
                applicationContext.getBean(SystemQueryService.class);

        assertSame(first, second);
    }

    @Test
    void shouldCreateNewSystemInfoForEachQuery() {
        SystemQueryService service =
                applicationContext.getBean(SystemQueryService.class);

        SystemInfo first = service.query();
        SystemInfo second = service.query();

        assertNotSame(first, second);
    }
}
