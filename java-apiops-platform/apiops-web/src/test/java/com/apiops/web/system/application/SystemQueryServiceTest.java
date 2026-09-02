package com.apiops.web.system.application;

import com.apiops.web.config.ApiOpsProperties;
import com.apiops.web.system.domain.SystemInfo;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;

import static org.junit.jupiter.api.Assertions.assertEquals;

class SystemQueryServiceTest {

    @Test
    void shouldReturnSystemInfoUsingInjectedClock() {
        Instant fixedTime =
                Instant.parse("2026-07-24T08:00:00Z");

        Clock fixedClock = Clock.fixed(
                fixedTime,
                ZoneOffset.UTC
        );

        ApiOpsProperties properties = new ApiOpsProperties(
                new ApiOpsProperties.Application(
                        "Agentic APIOps Java Platform Test",
                        "0.1.0-SNAPSHOT"
                ),
                new ApiOpsProperties.Tracing("X-Trace-Id")
        );

        SystemQueryService service =
                new SystemQueryService(properties, fixedClock);

        SystemInfo result = service.query();

        assertEquals(
                "Agentic APIOps Java Platform Test",
                result.serviceName()
        );

        assertEquals(
                "0.1.0-SNAPSHOT",
                result.version()
        );

        assertEquals(
                "UP",
                result.status()
        );

        assertEquals(
                fixedTime,
                result.generatedAt()
        );
    }
}
