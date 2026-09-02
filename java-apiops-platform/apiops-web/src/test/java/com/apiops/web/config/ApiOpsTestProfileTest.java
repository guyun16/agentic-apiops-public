package com.apiops.web.config;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.core.env.Environment;
import org.springframework.test.context.ActiveProfiles;

import static org.junit.jupiter.api.Assertions.assertEquals;

@SpringBootTest
@ActiveProfiles("test")
class ApiOpsTestProfileTest {

    @Autowired
    private ApiOpsProperties properties;

    @Autowired
    private Environment environment;

    @Test
    void shouldOverrideNameAndPortAndInheritVersionFromCommonConfiguration() {
        assertEquals(
                "Agentic APIOps Java Platform Test",
                properties.application().name()
        );
        assertEquals(
                "0.1.0-SNAPSHOT",
                properties.application().version()
        );
        assertEquals(
                Integer.valueOf(0),
                environment.getProperty("server.port", Integer.class)
        );
    }
}
