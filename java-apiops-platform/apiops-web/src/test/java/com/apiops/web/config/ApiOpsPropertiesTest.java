package com.apiops.web.config;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.junit.jupiter.api.Assertions.assertEquals;

@SpringBootTest(
        properties = {
                "apiops.auth.jwt.secret=dGVzdC1vbmx5LWp3dC1zZWNyZXQtbWF0ZXJpYWwtMjAyNi0wOC0wNw==",
                "spring.autoconfigure.exclude=org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration"
        }
)
class ApiOpsPropertiesTest {

    @Autowired
    private ApiOpsProperties properties;

    @Test
    void shouldBindDefaultApplicationProperties() {
        assertEquals(
                "Agentic APIOps Java Platform",
                properties.application().name()
        );
        assertEquals(
                "0.1.0-SNAPSHOT",
                properties.application().version()
        );
        assertEquals(
                "X-Trace-Id",
                properties.tracing().headerName()
        );
    }
}
