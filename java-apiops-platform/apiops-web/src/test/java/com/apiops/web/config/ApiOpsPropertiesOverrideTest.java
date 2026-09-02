package com.apiops.web.config;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import static org.junit.jupiter.api.Assertions.assertEquals;

@SpringBootTest(
        properties = "apiops.application.name=Agentic APIOps Java Platform Override"
)
@ActiveProfiles("test")
class ApiOpsPropertiesOverrideTest {

    @Autowired
    private ApiOpsProperties properties;

    @Test
    void shouldPreferTestPropertyOverProfileConfiguration() {
        assertEquals(
                "Agentic APIOps Java Platform Override",
                properties.application().name()
        );
        assertEquals(
                "0.1.0-SNAPSHOT",
                properties.application().version()
        );
    }
}
