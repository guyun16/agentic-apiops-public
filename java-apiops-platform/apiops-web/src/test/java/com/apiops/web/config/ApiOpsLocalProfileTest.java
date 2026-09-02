package com.apiops.web.config;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import static org.junit.jupiter.api.Assertions.assertEquals;

@SpringBootTest(properties = "spring.ai.openai.api-key=stage13-test-placeholder")
@ActiveProfiles({"test", "local"})
class ApiOpsLocalProfileTest {

    @Autowired
    private ApiOpsProperties properties;

    @Test
    void shouldOverrideNameAndInheritVersionFromCommonConfiguration() {
        assertEquals(
                "Agentic APIOps Java Platform Local",
                properties.application().name()
        );
        assertEquals(
                "0.1.0-SNAPSHOT",
                properties.application().version()
        );
    }
}
