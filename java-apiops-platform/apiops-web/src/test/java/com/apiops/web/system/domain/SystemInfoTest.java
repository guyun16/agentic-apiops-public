package com.apiops.web.system.domain;

import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;

class SystemInfoTest {

    @Test
    void shouldExposeSystemInformation() {
        Instant generatedAt =
                Instant.parse("2026-07-24T08:00:00Z");

        SystemInfo systemInfo = new SystemInfo(
                "apiops-web",
                "0.1.0-SNAPSHOT",
                "UP",
                generatedAt
        );

        assertEquals(
                "apiops-web",
                systemInfo.serviceName()
        );

        assertEquals(
                "0.1.0-SNAPSHOT",
                systemInfo.version()
        );

        assertEquals(
                "UP",
                systemInfo.status()
        );

        assertEquals(
                generatedAt,
                systemInfo.generatedAt()
        );
    }
}
